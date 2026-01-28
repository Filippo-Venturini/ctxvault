from pydantic import BaseModel

class ChunkMatch(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    score: float
    doc_id: str
    source: str

class QueryResult(BaseModel):
    query: str
    results: list[ChunkMatch]