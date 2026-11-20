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

class SyncReport(BaseModel):
    """What a query-time sync did to the index, so the caller can see it move.

    Only the files that changed are named: a query on an unchanged vault
    reports nothing, because nothing was done."""
    reindexed: list[str] = Field(default_factory=list)
    indexed: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    duration_ms: float

    def changed(self) -> bool:
        return bool(self.reindexed or self.indexed or self.dropped)

class QueryResult(BaseModel):
    query: str
    results: list[ChunkMatch]
    # Set only when the vault synced its index before answering, and only if
    # that sync changed something; None means the query read the index as-is.
    sync: SyncReport | None = None
