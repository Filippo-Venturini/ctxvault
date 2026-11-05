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
        indexed, skipped = [], []
        for file in self.iter_files(path=self.vault_path, exclude_dirs=[self.db_path]):
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
        
    def query(self, text: str, filters: dict | None = None, n_results: int = 5) -> QueryResult:
        from ctxvault.core import querying
        if not text.strip():
            raise EmptyQueryError("Query text cannot be empty.")

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