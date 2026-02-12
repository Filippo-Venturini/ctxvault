from ctxvault.models.documents import DocumentInfo
from ctxvault.models.query_result import ChunkMatch
from pydantic import BaseModel

class InitRequest(BaseModel):
    vault_path: str

class InitResponse(BaseModel):
    vault_path: str
    config_path: str

class IndexRequest(BaseModel):
    file_path: str

class IndexResponse(BaseModel):
    indexed_files: list[str]
    skipped_files: list[str]

class QueryRequest(BaseModel):
    query: str
    filters: dict | None = None

class QueryResponse(BaseModel):
    results: list[ChunkMatch]

class DeleteResponse(BaseModel):
    deleted_files: list[str]
    skipped_files: list[str]

class ReindexRequest(BaseModel):
    file_path: str

class ReindexResponse(BaseModel):
    reindexed_files: list[str]
    skipped_files: list[str]

class ListResponse(BaseModel):
    documents: list[DocumentInfo]

class AgentMetadata(BaseModel):
    generated_by: str
    artifact_type: str
    topic: str

class WriteRequest(BaseModel):
    file_path: str
    content: str
    overwrite: bool
    agent_metadata: AgentMetadata | None = None

class WriteResponse(BaseModel):
    file_path: str