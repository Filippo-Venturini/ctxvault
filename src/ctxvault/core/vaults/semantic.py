from pathlib import Path
from ctxvault.core import indexer
from ctxvault.core.vaults.base import BaseVault
from ctxvault.models.documents import SemanticDocumentInfo, DocumentContent
from ctxvault.models.query_result import ChunkMatch, QueryResult
from ctxvault.core.exceptions import EmptyQueryError, FileOutsideVaultError, UnsupportedFileTypeError
from ctxvault.models.vaults import VaultOperation
from ctxvault.utils.text_extraction import SUPPORTED_EXT

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

    def delete_file(self, file_path: Path)-> None:
        indexer.delete_file(file_path=str(file_path), config=self.config)
        super().delete_file(file_path=file_path)
        
    def query(self, text: str, filters: dict | None = None) -> QueryResult:
        from ctxvault.core import querying
        if not text.strip():
            raise EmptyQueryError("Query text cannot be empty.")

        result_dict = querying.query(query_txt=text, config=self.config, filters=filters)

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

        chunks_match = [
            ChunkMatch(
                chunk_id=m["chunk_id"],
                chunk_index=m["chunk_index"],
                text=d,
                score=dist,
                doc_id=m["doc_id"],
                source=m["source"],
                generated_by=m.get("generated_by"),
                artifact_type=m.get("artifact_type"),
                topic=m.get("topic")
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
    
    def write_doc(self, file_path: str, content: str, overwrite: bool = True, agent_metadata: dict | None = None)-> None:
        self.write_file(file_path=file_path, content=content, overwrite=overwrite, agent_metadata=agent_metadata)

        abs_path = (self.vault_path / file_path).resolve()
        self.index_file(file_path=abs_path, agent_metadata=agent_metadata)