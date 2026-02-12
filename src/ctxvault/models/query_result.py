from pydantic import BaseModel

class ChunkMatch(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    score: float
    doc_id: str
    source: str
    generated_by: str | None = None
    artifact_type: str | None = None
    topic: str | None = None

class QueryResult(BaseModel):
    query: str
    results: list[ChunkMatch]