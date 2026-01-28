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

class QueryResponse(BaseModel):
    results: list[ChunkMatch]