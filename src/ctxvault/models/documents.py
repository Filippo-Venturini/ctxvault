from typing import Union
from pydantic import BaseModel, Field

class BaseDocumentInfo(BaseModel):
    source: str      
    filetype: str

class SemanticDocumentInfo(BaseDocumentInfo):
    doc_id: str
    chunks_count: int

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

class SkillDocumentInfo(BaseDocumentInfo):
    skill_name: str
    description: str | None = None
    last_modified: str