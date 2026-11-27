import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from ctxvault.core import indexer
import os
import warnings
from ctxvault.core import prune_log as log
from ctxvault.core.pruning import DUPLICATE, SEMANTIC_REASONS, find_semantic_candidates, text_hash
from ctxvault.core.vaults.base import ARCHIVE_DIR, BaseVault
from ctxvault.models.pruning import Candidate, PruneLogEntry, PruneMode, PrunePolicy, PruneReport, PruneTrigger
from ctxvault.models.documents import DocumentStatus, SemanticDocumentInfo, DocumentContent, VaultStatus
from ctxvault.models.query_result import ChunkMatch, QueryResult, SyncReport
from ctxvault.core.exceptions import EmptyQueryError, FileAlreadyExistError, FileOutsideVaultError, UnsupportedFileTypeError
from ctxvault.models.vaults import VaultOperation
from ctxvault.storage import chroma_store
from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS
from ctxvault.utils.text_extraction import SUPPORTED_EXT

# a file's mtime and indexed_at come from different clocks' roundings
_SYNC_SLACK = timedelta(seconds=1)

# What the files looked like when the index last matched them: a hash of
# path + mtime for every supported file. It sits beside the collection, so the
# vault's own file scan never sees it.
_SYNC_STATE_NAME = ".sync_on_query.json"

# One lock per vault folder: two queries arriving together in this process
# must not reindex the same file twice. Cross-process is not covered, but
# reindexing a file is idempotent, so a second process at worst repeats work.
_SYNC_LOCKS: dict[str, Lock] = {}
_SYNC_LOCKS_GUARD = Lock()

def _sync_lock(vault_path: Path) -> Lock:
    key = vault_path.resolve().as_posix()
    with _SYNC_LOCKS_GUARD:
        return _SYNC_LOCKS.setdefault(key, Lock())

def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

class SemanticVault(BaseVault):
    supported_operations = frozenset({
        VaultOperation.INDEX,
        VaultOperation.QUERY,
        VaultOperation.REINDEX,
        VaultOperation.DELETE,
        VaultOperation.WRITE_DOC,
        VaultOperation.LIST_DOCUMENTS,
        VaultOperation.READ_DOC_CONTENT,
        VaultOperation.PRUNE,
    })
    prune_reasons = SEMANTIC_REASONS

    def index_file(self, file_path:Path, agent_metadata: dict | None = None, *, new_write: bool = False)-> None:
        from ctxvault.core import indexer

        if file_path.suffix not in SUPPORTED_EXT:
            raise UnsupportedFileTypeError("File type not supported.")

        if not file_path.resolve().is_relative_to(self.vault_path):
            raise FileOutsideVaultError("The file to index is outside the Context Vault.")

        if file_path.resolve().is_relative_to(self.archive_path):
            raise FileOutsideVaultError(f"The file is inside {ARCHIVE_DIR}/: archived files are not indexed.")

        indexer.index_file(file_path=str(file_path), config=self.config, agent_metadata=agent_metadata,
                           new_write=new_write)

    def index_files(self, path: str | None = None)-> tuple[list[str], list[str]]:
        base_path = self._get_base_path(path=path)
        
        indexed_files = []
        skipped_files = []
        
        for file in self.iter_files(path=base_path, exclude_dirs=self._excluded_dirs()):
            try:
                self.index_file(file_path=file)
                indexed_files.append(str(file))
            except Exception as e:
                skipped_files.append(f"{str(file)} ({e})")

        self._evaluate_quietly("index")
        return indexed_files, skipped_files
    
    def reindex_files(self, path: str | None = None)-> tuple[list[str], list[str]]:
        if path is None and chroma_store.space(self.config) != chroma_store.SPACE:
            # a collection from an earlier version measures distance
            # differently; a whole-vault reindex is the moment to move it over
            return self._rebuild_collection()

        base_path = self._get_base_path(path=path)

        reindexed_files = []
        skipped_files = []

        for file in self.iter_files(path=base_path, exclude_dirs=self._excluded_dirs()):
            try:
                self.reindex_file(file_path=file)
                reindexed_files.append(str(file))
            except Exception as e:
                skipped_files.append(f"{str(file)} ({e})")

        return reindexed_files, skipped_files

    def reindex_file(self, file_path: Path)-> None:
        from ctxvault.core import indexer

        if file_path.suffix not in SUPPORTED_EXT:
            raise UnsupportedFileTypeError("File type not supported.")

        if not file_path.resolve().is_relative_to(self.vault_path):
            raise FileOutsideVaultError("The file to reindex is outside the Context Vault.")

        indexer.reindex_file(file_path=str(file_path), config=self.config)

    def _rebuild_collection(self) -> tuple[list[str], list[str]]:
        """Make the collection again in this version's distance space and
        index every file into it, carrying each document's agent metadata."""
        # Everything indexed is about to be dropped, so the record of what the
        # index matched must go with it or the next query would trust it.
        state = self._sync_state_path()
        if state is not None:
            state.unlink(missing_ok=True)
        kept = {doc.source: doc.metadata or None for doc in self.list_documents()}
        chroma_store.reset_collection(self.config)
        indexed, skipped = [], []
        for file in self.iter_files(path=self.vault_path, exclude_dirs=self._excluded_dirs()):
            try:
                self.index_file(file_path=file, agent_metadata=kept.get(str(file)))
                indexed.append(str(file))
            except Exception as e:
                skipped.append(f"{str(file)} ({e})")
        return indexed, skipped

    def status(self) -> VaultStatus:
        """The index against the files: per document whether its file is
        unchanged, changed since indexing or gone, and the files in the vault
        never indexed. A stale document still answers queries, from the old
        text; `sync_index` brings the index back."""
        documents, indexed = [], set()
        for doc in self.list_documents():
            source = Path(doc.source)
            indexed.add(source.resolve())
            modified = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc) if source.is_file() else None
            indexed_at = _instant(doc.indexed_at)
            if modified is None:
                state = "missing"
            elif indexed_at is not None and modified > indexed_at + _SYNC_SLACK:
                state = "changed"
            else:
                state = "in_sync"
            documents.append(DocumentStatus(doc_id=doc.doc_id, source=doc.source, state=state, indexed_at=doc.indexed_at,
                                            modified_at=modified.isoformat() if modified else None))
        unindexed = [str(f) for f in self.iter_files(path=self.vault_path, exclude_dirs=self._excluded_dirs())
                     if f.suffix in SUPPORTED_EXT and f.resolve() not in indexed]
        return VaultStatus(documents=documents, unindexed=unindexed)

    def sync_index(self) -> tuple[list[str], list[str], list[str]]:
        """Bring the index back to the files: reindex the changed documents,
        index the files never indexed, drop the documents whose file is gone.
        Returns (reindexed, indexed, dropped).

        When a sync record exists, the files are compared to it by `mtime_ns`
        rather than through `status()`: a save that lands in the same second
        the file was indexed moves the nanosecond mtime but not the second
        one, and `status()` would call that file in sync. A stale answer is
        what the option promises never to return, so the exact comparison
        wins here; `status()` keeps its slack because it also has to answer
        for files indexed by an earlier version."""
        snapshot = self._files_snapshot()
        recorded = (self._read_sync_state().get("files") or {})
        if recorded:
            reindexed, indexed, dropped = [], [], []
            for path, mtime in sorted(snapshot.items()):
                if recorded.get(path) == mtime:
                    continue
                if path in recorded:
                    self.reindex_file(file_path=Path(path))
                    reindexed.append(path)
                else:
                    self.index_file(file_path=Path(path))
                    indexed.append(path)
            for path in sorted(set(recorded) - set(snapshot)):
                indexer.delete_file(file_path=path, config=self.config)
                dropped.append(path)
            self._evaluate_quietly("sync")
            return reindexed, indexed, dropped

        status = self.status()
        reindexed, indexed, dropped = [], [], []
        for doc in status.documents:
            if doc.state == "changed":
                self.reindex_file(file_path=Path(doc.source))
                reindexed.append(doc.source)
            elif doc.state == "missing":
                indexer.delete_file(file_path=doc.source, config=self.config)
                dropped.append(doc.source)
        for file in status.unindexed:
            self.index_file(file_path=Path(file))
            indexed.append(file)
        self._evaluate_quietly("sync")
        return reindexed, indexed, dropped

    def _find_candidates(self, policy: PrunePolicy, reasons: set[str]) -> PruneReport:
        return find_semantic_candidates(vault_name=self.vault_name, config=self.config, policy=policy, reasons=reasons)

    def _prune_target(self, target: str) -> str:
        path = Path(target)
        return str(path if path.is_absolute() else (self.vault_path / path).resolve())

    def _log_target(self, target: str) -> str:
        """The path relative to the vault, with "/": how the log names a document on every platform."""
        path = Path(self._prune_target(target)).resolve()
        try:
            return path.relative_to(self.vault_path.resolve()).as_posix()
        except ValueError:
            raise FileOutsideVaultError(f"{target} is not inside the vault.") from None

    def _display(self, target: str) -> str:
        try:
            return self._log_target(target)
        except FileOutsideVaultError:
            return target

    # ── pruning: archive, restore, purge ─────────────────────────────────────

    def _why_not_apply(self, candidate: Candidate) -> str | None:
        """Approved bytes are proposed bytes: a file is archived only while it
        still has the text it was found with, and a duplicate only while the
        copy that stays still has it too."""
        expected = candidate.signals.get("text_hash")
        try:
            if not Path(candidate.target).is_file():
                return "the file is gone"
            if not expected or text_hash(candidate.target) != expected:
                return "changed since it was found"
            kept = candidate.signals.get("kept")
            if kept and (not Path(str(kept)).is_file() or text_hash(str(kept)) != expected):
                return "the copy that stays is gone or changed, so this one is no longer a duplicate"
        except Exception as e:
            return f"could not be read ({e})"
        return None

    def _apply_candidate(self, candidate: Candidate, *, who: str, trigger: PruneTrigger,
                         policy: PrunePolicy) -> PruneLogEntry:
        """Archive = move the file into the archive, log it, drop it from the
        index. The log row is written before the index changes, so whatever
        happens next the log knows where the file went."""
        from ctxvault.core.identifiers import get_doc_id
        source = Path(candidate.target)
        relative = self._log_target(candidate.target)
        doc_id = get_doc_id(candidate.target)
        records = chroma_store.get_document_records(doc_id=doc_id, config=self.config)
        agent_metadata = indexer._extract_agent_metadata(records.get("metadatas") or [])

        stamp = log.now().replace(":", "").replace("-", "").replace("+", "_").replace(".", "_")
        archived = f"{stamp}-{doc_id[:12]}/{relative}"
        destination = self.archive_path / archived
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        try:
            row = log.append(self.prune_log_path, "archive", who, trigger=trigger, target=relative,
                             reason=candidate.reason, action=candidate.suggested_action.value,
                             signals=candidate.signals, archived=archived, doc_id=doc_id,
                             text_hash=candidate.signals.get("text_hash"), agent_metadata=agent_metadata)
        except Exception:
            os.replace(destination, source)
            self._sweep_archive(destination.parent)
            raise
        indexer.delete_file(file_path=candidate.target, config=self.config)
        return next(e for e in self.prune_log(policy) if e.n == row["n"])

    def _restore_entry(self, entry: PruneLogEntry, *, overwrite: bool) -> None:
        archived = self.archive_path / entry.archived_path
        destination = (self.vault_path / entry.target).resolve()
        if not archived.is_file():
            raise FileNotFoundError(f"The archived file for {entry.target} is gone from {ARCHIVE_DIR}/{entry.archived_path}.")
        if entry.text_hash and text_hash(str(archived)) != entry.text_hash:
            raise ValueError(f"{ARCHIVE_DIR}/{entry.archived_path} changed after it was archived; "
                             "look at it before restoring it by hand.")
        if destination.exists():
            if not overwrite:
                raise FileAlreadyExistError(f"{entry.target} exists again in the vault. "
                                            "Restore with overwrite to replace it.")
            indexer.delete_file(file_path=str(destination), config=self.config)
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(archived, destination)
        self._sweep_archive(archived.parent)

    def _after_restore(self, entry: PruneLogEntry) -> None:
        # the file keeps its mtime through the move, so a restored agent
        # document is still agent-written
        self.index_file(file_path=(self.vault_path / entry.target).resolve(), agent_metadata=entry.agent_metadata)

    def _purge_entry(self, entry: PruneLogEntry) -> None:
        archived = self.archive_path / entry.archived_path
        archived.unlink(missing_ok=True)
        self._sweep_archive(archived.parent)

    def _evaluate_quietly(self, trigger: PruneTrigger) -> PruneReport | None:
        """The policy's own pass after an index or a sync. It never fails the
        operation it follows: what went wrong is a warning, and nothing that
        was not logged was moved."""
        try:
            return self._evaluate(trigger)
        except Exception as e:
            warnings.warn(f"Pruning after {trigger} did not run: {e}")
            return None

    def _evaluate_write(self, abs_path: Path) -> PruneReport | None:
        """After write_doc, only what one write can do: copy a document that is
        already there. One filtered read on the new document's text hash, not
        a scan of the vault; then purge what has expired."""
        try:
            policy = self.prune_policy()
            if not policy.enabled:
                return None
            report = None
            if SEMANTIC_REASONS[DUPLICATE].auto_eligible and policy.mode(DUPLICATE) == PruneMode.AUTO:
                from ctxvault.core.identifiers import get_doc_id
                records = chroma_store.get_document_records(doc_id=get_doc_id(str(abs_path)), config=self.config)
                digest = next((m.get("text_hash") for m in records.get("metadatas") or [] if m and m.get("text_hash")), None)
                if digest:
                    report = find_semantic_candidates(vault_name=self.vault_name, config=self.config, policy=policy,
                                                      reasons={DUPLICATE}, same_text_as=digest)
                    self._hold_restored(report)
                    self._apply(report, policy=policy, named=False, trigger="write_doc")
            self.purge_expired(policy)
            return report
        except Exception as e:
            warnings.warn(f"Pruning after write_doc did not run: {e}")
            return None

    def delete_file(self, file_path: Path)-> None:
        indexer.delete_file(file_path=str(file_path), config=self.config)
        super().delete_file(file_path=file_path)
        
    def _sync_state_path(self) -> Path | None:
        return self.db_path / _SYNC_STATE_NAME if self.db_path else None

    def _files_snapshot(self) -> dict[str, int]:
        """Every supported file's path and `mtime_ns`: one stat per file, and
        no vector-store read, so it is cheap enough to run per query.

        Keeping the per-file value, not just a hash of them, is what lets a
        sync reindex the files whose entry moved instead of comparing their
        mtimes to `indexed_at`, which is stored to the second.

        Deliberately not `iter_files`: that resolves every path to check it is
        inside the vault, which cost about a millisecond a file here. Walking
        the tree with `os.walk` keeps the scan to the stats themselves."""
        root = str(self.vault_path)
        excluded = [os.path.normcase(str(path)) for path in self._excluded_dirs()]
        files = {}
        for directory, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames
                           if os.path.normcase(os.path.join(directory, name)) not in excluded]
            for name in filenames:
                if os.path.splitext(name)[1].lower() not in SUPPORTED_EXT:
                    continue
                path = os.path.join(directory, name)
                try:
                    files[path] = os.stat(path).st_mtime_ns
                except OSError:      # gone between the listing and the stat
                    continue
        return files

    def _read_sync_state(self) -> dict:
        path = self._sync_state_path()
        if path is None or not path.is_file():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    def _write_sync_state(self, files: dict[str, int]) -> None:
        path = self._sync_state_path()
        if path is None:
            return
        try:
            path.write_text(json.dumps({
                "files": files,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }))
        except OSError:
            pass    # a vault that cannot record it will check the files instead

    def _seconds_since(self, state: dict) -> float:
        try:
            return (datetime.now(timezone.utc) - _instant(state.get("synced_at"))).total_seconds()
        except (TypeError, ValueError):
            return float("inf")

    def _sync_before_query(self) -> SyncReport | None:
        """Bring the index to the files before answering, but only when the
        files moved since the last sync: an unchanged vault pays the snapshot
        and nothing else, and an interval can spare even that."""
        lock = _sync_lock(self.vault_path)
        with lock:
            state = self._read_sync_state()
            interval = float(self.config.get("sync_on_query_interval") or 0)
            if state and interval > 0 and self._seconds_since(state) < interval:
                return None
            snapshot = self._files_snapshot()
            if state.get("files") == snapshot:
                # restart the interval: the files were checked, nothing was done
                if interval > 0:
                    self._write_sync_state(snapshot)
                return None
            started = time.monotonic()
            reindexed, indexed, dropped = self.sync_index()
            self._write_sync_state(snapshot)
        report = SyncReport(
            reindexed=reindexed,
            indexed=indexed,
            dropped=dropped,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return report if report.changed() else None

    def query(self, text: str, filters: dict | None = None, n_results: int = 5) -> QueryResult:
        from ctxvault.core import querying
        if not text.strip():
            raise EmptyQueryError("Query text cannot be empty.")

        # Opt-in: when the vault says so, a query first brings the index in
        # line with the files, so a stale answer is impossible without a
        # watcher. Off by default, and then this costs nothing.
        sync = self._sync_before_query() if self.config.get("sync_on_query") else None

        result_dict = querying.query(query_txt=text, config=self.config, n_results=n_results, filters=filters)

        raw_triples = list(zip(
            result_dict["documents"][0],
            result_dict["metadatas"][0],
            result_dict["distances"][0]
        ))

        valid_triples = [(d, m, dist) for d, m, dist in raw_triples if d is not None and m is not None]
        skipped = len(raw_triples) - len(valid_triples)

        if skipped > 0:
            import warnings
            warnings.warn(f"Skipped {skipped} stale hit(s) with missing backing records.")

        cosine = chroma_store.space(self.config) == "cosine"
        chunks_match = [
            ChunkMatch(
                chunk_id=m["chunk_id"],
                chunk_index=m["chunk_index"],
                text=d,
                score=dist,
                similarity=max(0.0, min(1.0, 1.0 - dist)) if cosine else None,
                doc_id=m["doc_id"],
                source=m["source"],
                metadata={k: v for k, v in m.items() if k not in BUILT_IN_METADATA_KEYS},
            )
            for d, m, dist in valid_triples
        ]
        return QueryResult(query=text, results=chunks_match, sync=sync)

    def list_documents(self) -> list[SemanticDocumentInfo]:
        from ctxvault.core import querying
        return querying.list_documents(config=self.config)

    def get_document_content(self, doc_id: str) -> DocumentContent:
        from ctxvault.core import querying
        return querying.get_document_content(doc_id=doc_id, config=self.config)

    def get_document_chunks(self, doc_id: str) -> list[str]:
        """The document's chunks in index order: the units retrieval returns."""
        from ctxvault.core import querying
        return querying.get_document_chunks(doc_id=doc_id, config=self.config)
    
    def write_doc(self, file_path: str, content: str, overwrite: bool = True,
                  agent_metadata: dict | None = None)-> list[PruneLogEntry]:
        """Write the file and index it. Returns what the policy's own pass
        after the write archived: an older agent-written copy of the same
        text, when the policy is on and duplicates are in auto. Usually empty."""
        self.write_file(file_path=file_path, content=content, overwrite=overwrite, agent_metadata=agent_metadata)

        abs_path = (self.vault_path / file_path).resolve()
        self.index_file(file_path=abs_path, agent_metadata=agent_metadata, new_write=True)
        report = self._evaluate_write(abs_path)
        return report.applied if report else []
