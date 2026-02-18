from ctxvault.models.documents import DocumentInfo
from ctxvault.models.query_result import ChunkMatch
from pydantic import BaseModel

class InitRequest(BaseModel):
    vault_name: str

class InitResponse(BaseModel):
    vault_path: str
    config_path: str

class IndexRequest(BaseModel):
    vault_name: str
    file_path: str | None = None

class IndexResponse(BaseModel):
    indexed_files: list[str]
    skipped_files: list[str]

class QueryRequest(BaseModel):
    vault_name: str
    query: str
    filters: dict | None = None

class QueryResponse(BaseModel):
    results: list[ChunkMatch]

class DeleteRequest(BaseModel):
    vault_name: str
    file_path: str | None = None

class DeleteResponse(BaseModel):
    deleted_files: list[str]
    skipped_files: list[str]

class ReindexRequest(BaseModel):
    vault_name: str
    file_path: str | None = None

class ReindexResponse(BaseModel):
    reindexed_files: list[str]
    skipped_files: list[str]

class ListRequest(BaseModel):
    vault_name: str

class ListResponse(BaseModel):
    vault_name: str
    documents: list[DocumentInfo]

class AgentMetadata(BaseModel):
    generated_by: str
    artifact_type: str
    topic: str

class WriteRequest(BaseModel):
    vault_name: str
    file_path: str
    content: str
    overwrite: bool
    agent_metadata: AgentMetadata | None = None

class WriteResponse(BaseModel):
    file_path: str