from pydantic import BaseModel, Field

class ChunkMatch(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    # The distance the vector store ranked by: lower is closer. Its scale
    # depends on the collection's distance space (see chroma_store.space).
    score: float
    # 1 - cosine distance, in [0, 1], when the collection compares by cosine;
    # None on a collection made by an earlier version, until it is reindexed.
    similarity: float | None = None
    doc_id: str
    source: str
    # What the writing agent attached to the document: every chunk metadata
    # key beyond the indexer's own.
    metadata: dict = Field(default_factory=dict)
    # The reciprocal-rank-fusion value when the query also used the keyword leg:
    # higher is better, and it is what hybrid results are ordered by. None on
    # a vector-only result, where `score` still ranks.
    rank_score: float | None = None

class QueryResult(BaseModel):
    query: str
    results: list[ChunkMatch]
    # "hybrid" when the keyword leg was consulted and contributed to the
    # ranking, "vector" otherwise. `score` keeps its meaning either way; a
    # hybrid result carries `rank_score` and its order follows it.
    mode: str = "vector"
