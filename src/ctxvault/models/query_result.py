from pydantic import BaseModel

class ChunkMatch(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    score: float

class DocumentMatch(BaseModel):
    doc_id: str
    source: str
    filetype: str
    score: float
    chunks: list[ChunkMatch]

class QueryResult(BaseModel):
    query: str
    results: list[DocumentMatch]