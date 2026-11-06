from typing import Literal, Union
from pydantic import BaseModel, Field

class BaseDocumentInfo(BaseModel):
    source: str      
    filetype: str

class SemanticDocumentInfo(BaseDocumentInfo):
    doc_id: str
    chunks_count: int
    indexed_at: str | None = None
    # what the writing agent attached to the document, beyond the indexer's own keys
    metadata: dict = Field(default_factory=dict)

class DocumentContent(BaseDocumentInfo):
    doc_id: str
    chunks_count: int
    content: str
    reconstructed_text_hash: str = Field(
        description="SHA-256 of reconstructed chunk text, not the original source file."
    )
    indexed_at: str | None = None
    reconstructed: bool = True
    warning: str | None = None

class DocumentStatus(BaseModel):
    """Whether a document's index still matches its file: in_sync, changed
    (the file was modified after indexing) or missing (the file is gone). A
    stale document still answers queries, from the old text."""
    doc_id: str
    source: str
    state: Literal["in_sync", "changed", "missing"]
    indexed_at: str | None = None
    modified_at: str | None = None

class VaultStatus(BaseModel):
    documents: list[DocumentStatus]
    # files in the vault folder, of a supported type, never indexed
    unindexed: list[str]

class SkillDocumentInfo(BaseDocumentInfo):
    skill_name: str
    description: str | None = None
    last_modified: str
    size_bytes: int | None = None