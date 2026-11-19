import math
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ctxvault.core import indexer
from ctxvault.core.vaults.base import BaseVault
from ctxvault.models.documents import DocumentStatus, SemanticDocumentInfo, DocumentContent, VaultStatus
from ctxvault.models.query_result import ChunkMatch, QueryResult
from ctxvault.core.exceptions import EmptyQueryError, FileOutsideVaultError, UnsupportedFileTypeError
from ctxvault.models.vaults import VaultOperation
from ctxvault.storage import chroma_store
from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS
from ctxvault.utils.text_extraction import SUPPORTED_EXT

# a file's mtime and indexed_at come from different clocks' roundings
_SYNC_SLACK = timedelta(seconds=1)

def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

def _distance(query_embedding: list[float], chunk_embedding: list[float], space: str) -> float:
    """The same measure the collection uses, so a keyword-only hit's `score`
    means what every other hit's `score` means."""
    if space == "cosine":
        norm = math.sqrt(sum(x * x for x in query_embedding)) * math.sqrt(sum(x * x for x in chunk_embedding))
        if norm == 0.0:
            return 1.0
        return 1.0 - sum(a * b for a, b in zip(query_embedding, chunk_embedding)) / norm
    # Chroma's "l2" is squared Euclidean, the same number its own hits carry.
    return sum((a - b) ** 2 for a, b in zip(query_embedding, chunk_embedding))

def _matches_filters(metadata: dict, filters: dict | None) -> bool:
    """Equality only: the keyword leg has no query planner, so a filter the
    caller expressed as an operator is not applied there rather than guessed.
    The vector leg still applies it in full."""
    if not filters:
        return True
    return all(not isinstance(value, dict) and metadata.get(key) == value
               for key, value in filters.items())


class SemanticVault(BaseVault):
    supported_operations = frozenset({
        VaultOperation.INDEX,
        VaultOperation.QUERY,
        VaultOperation.REINDEX,
        VaultOperation.DELETE,
        VaultOperation.WRITE_DOC,
        VaultOperation.LIST_DOCUMENTS,
        VaultOperation.READ_DOC_CONTENT,
    })

    def index_file(self, file_path:Path, agent_metadata: dict | None = None)-> None:
        from ctxvault.core import indexer

        if file_path.suffix not in SUPPORTED_EXT:
            raise UnsupportedFileTypeError("File type not supported.")

        if not file_path.resolve().is_relative_to(self.vault_path):
            raise FileOutsideVaultError("The file to index is outside the Context Vault.")

        indexer.index_file(file_path=str(file_path), config=self.config, agent_metadata=agent_metadata)

    def index_files(self, path: str | None = None)-> tuple[list[str], list[str]]:
        base_path = self._get_base_path(path=path)
        
        indexed_files = []
        skipped_files = []
        
        for file in self.iter_files(path=base_path, exclude_dirs=[self.db_path]):
            try:
                self.index_file(file_path=file)
                indexed_files.append(str(file))
            except Exception as e:
                skipped_files.append(f"{str(file)} ({e})")

        return indexed_files, skipped_files
    
    def reindex_files(self, path: str | None = None)-> tuple[list[str], list[str]]:
        if path is None and chroma_store.space(self.config) != chroma_store.SPACE:
            # a collection from an earlier version measures distance
            # differently; a whole-vault reindex is the moment to move it over
            return self._rebuild_collection()

        base_path = self._get_base_path(path=path)

        reindexed_files = []
        skipped_files = []

        for file in self.iter_files(path=base_path, exclude_dirs=[self.db_path]):
            try:
                self.reindex_file(file_path=file)
                reindexed_files.append(str(file))
            except Exception as e:
                skipped_files.append(f"{str(file)} ({e})")

        # A vault prepared ahead of time: `reindex` also builds the keyword
        # cache, so the first hybrid query does not pay for it (an MCP call can
        # time out on that build even after it got faster). Indexing hooks keep
        # it current afterwards.
        from ctxvault.core import keyword_index
        if keyword_index.available(self.config) and keyword_index.built_at(self.config) is None:
            self._build_keyword_index()

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
        kept = {doc.source: doc.metadata or None for doc in self.list_documents()}
        chroma_store.reset_collection(self.config)
        from ctxvault.core import keyword_index
        keyword_index.clear(self.config)      # it described the collection just dropped
        indexed, skipped = [], []
        for file in self.iter_files(path=self.vault_path, exclude_dirs=[self.db_path]):
            try:
                self.index_file(file_path=file, agent_metadata=kept.get(str(file)))
                indexed.append(str(file))
            except Exception as e:
                skipped.append(f"{str(file)} ({e})")
        if indexed:
            keyword_index.mark_built(self.config, datetime.now(timezone.utc).isoformat())
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
        unindexed = [str(f) for f in self.iter_files(path=self.vault_path, exclude_dirs=[self.db_path])
                     if f.suffix in SUPPORTED_EXT and f.resolve() not in indexed]
        return VaultStatus(documents=documents, unindexed=unindexed)

    def sync_index(self) -> tuple[list[str], list[str], list[str]]:
        """Bring the index back to the files: reindex the changed documents,
        index the files never indexed, drop the documents whose file is gone.
        Returns (reindexed, indexed, dropped)."""
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
        return reindexed, indexed, dropped

    def delete_file(self, file_path: Path)-> None:
        indexer.delete_file(file_path=str(file_path), config=self.config)
        super().delete_file(file_path=file_path)
        
    def query(self, text: str, filters: dict | None = None, n_results: int = 5,
              hybrid: bool | None = None) -> QueryResult:
        from ctxvault.core import querying
        if not text.strip():
            raise EmptyQueryError("Query text cannot be empty.")

        # None means "whatever the vault says": an agent calling over MCP does
        # not know whether its vault wants exact words, its owner does. The
        # per-query flag is the override.
        use_hybrid = bool(self.config.get("hybrid_search")) if hybrid is None else hybrid
        if use_hybrid:
            return self._query_hybrid(text=text, filters=filters, n_results=n_results)

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
        return QueryResult(query=text, results=chunks_match)

    def _build_keyword_index(self) -> bool:
        """(Re)build the keyword cache from the collection, the source of truth.
        Returns whether it can be used now."""
        from ctxvault.core import keyword_index

        try:
            keyword_index.rebuild(self.config)
            keyword_index.mark_built(self.config, datetime.now(timezone.utc).isoformat())
            return True
        except Exception as exc:
            import warnings
            warnings.warn(f"keyword index could not be built ({exc}); answering vector-only")
            return False

    def _keyword_index_ready(self, connection=None) -> bool:
        """An index that exists and still describes the collection. A crash
        between a vector write and its keyword row leaves the two counts apart;
        comparing them costs one number per side and catches that."""
        from ctxvault.core import keyword_index

        try:
            if keyword_index.built_at(self.config, connection) is not None:
                if keyword_index.count(self.config, connection) == chroma_store.count(self.config):
                    return True
            return self._build_keyword_index()
        except Exception as exc:
            import warnings
            warnings.warn(f"keyword index could not be checked ({exc}); answering vector-only")
            return False

    def _query_hybrid(self, text: str, filters: dict | None, n_results: int) -> QueryResult:
        """Rank by both legs: the vector store and the keyword index.

        Reciprocal rank fusion, k=60: a chunk is worth what both legs say about
        it, and neither leg's score scale has to be comparable. Deeper than the
        requested depth on each side, because a chunk the vector leg ranks 30th
        can still be the exact identifier the keyword leg ranks first.

        A chunk only the keyword leg found still has an embedding, so it gets
        its real distance from a lookup by id: `score` never invents a number
        that reads as a perfect match."""
        from ctxvault.core import keyword_index

        try:
            connection = keyword_index.connect(self.config)
        except Exception:
            connection = None
        try:
            if (connection is None or not keyword_index.available(self.config, connection)
                    or not self._keyword_index_ready(connection)):
                # No usable keyword leg: answer exactly as before rather than fail
                # a query over an optional one.
                return self.query(text=text, filters=filters, n_results=n_results, hybrid=False)
            return self._fuse_hybrid(text, filters, n_results, keyword_index, connection)
        finally:
            if connection is not None:
                connection.close()

    def _fuse_hybrid(self, text: str, filters: dict | None, n_results: int,
                     keyword_index, connection) -> QueryResult:
        """The two-leg ranking, on the one keyword connection opened for it."""
        from ctxvault.core import embedding, querying

        depth = max(20, n_results * 4)
        query_embedding = embedding.embed_list(chunks=[text], model_name=self.config.get("embedding_model"))[0]
        result_dict = querying.query(query_txt=text, config=self.config, n_results=depth,
                                     filters=filters, query_embedding=query_embedding)
        cosine = chroma_store.space(self.config) == "cosine"

        fused: dict[str, dict] = {}
        for rank, (document, metadata, distance) in enumerate(zip(
                result_dict["documents"][0], result_dict["metadatas"][0], result_dict["distances"][0]), start=1):
            if document is None or metadata is None:
                continue          # a stale hit with no backing record
            fused[metadata["chunk_id"]] = {
                "text": document, "metadata": metadata, "distance": distance,
                "rank_score": 1.0 / (60 + rank),
            }

        keyword_hits = keyword_index.search(self.config, text, depth, connection)
        missing = [hit for hit in keyword_hits
                   if hit["chunk_id"] not in fused and _matches_filters(hit["metadata"], filters)]
        records = chroma_store.records_by_ids([hit["chunk_id"] for hit in missing], self.config) if missing else {}
        record_ids = records.get("ids") or []
        record_texts = records.get("documents") or []
        record_metadatas = records.get("metadatas") or []
        record_embeddings = records.get("embeddings")
        if record_embeddings is None:
            record_embeddings = [None] * len(record_ids)
        by_id = {chunk_id: (text_value, metadata_value, vector)
                 for chunk_id, text_value, metadata_value, vector
                 in zip(record_ids, record_texts, record_metadatas, record_embeddings)}

        for rank, hit in enumerate(keyword_hits, start=1):
            entry = fused.get(hit["chunk_id"])
            if entry is not None:
                entry["rank_score"] += 1.0 / (60 + rank)
                continue
            record = by_id.get(hit["chunk_id"])
            if record is None or record[2] is None:
                continue      # the collection cannot give it a real score
            document, metadata, vector = record
            fused[hit["chunk_id"]] = {
                "text": document, "metadata": metadata,
                "distance": _distance(query_embedding, vector, "cosine" if cosine else "l2"),
                "rank_score": 1.0 / (60 + rank),
            }

        ordered = sorted(fused.items(),
                         key=lambda item: (-item[1]["rank_score"], item[1]["distance"]))
        chunks_match = [
            ChunkMatch(
                chunk_id=chunk_id,
                chunk_index=entry["metadata"]["chunk_index"],
                text=entry["text"],
                score=entry["distance"],
                similarity=max(0.0, min(1.0, 1.0 - entry["distance"])) if cosine else None,
                doc_id=entry["metadata"]["doc_id"],
                source=entry["metadata"]["source"],
                metadata={k: v for k, v in entry["metadata"].items() if k not in BUILT_IN_METADATA_KEYS},
                rank_score=entry["rank_score"],
            )
            for chunk_id, entry in ordered[:n_results]
        ]
        return QueryResult(query=text, results=chunks_match, mode="hybrid")

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
    
    def write_doc(self, file_path: str, content: str, overwrite: bool = True, agent_metadata: dict | None = None)-> None:
        self.write_file(file_path=file_path, content=content, overwrite=overwrite, agent_metadata=agent_metadata)

        abs_path = (self.vault_path / file_path).resolve()
        self.index_file(file_path=abs_path, agent_metadata=agent_metadata)