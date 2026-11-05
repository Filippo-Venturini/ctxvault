from datetime import datetime, timezone

from ctxvault.core.identifiers import get_chunk_id

# Metadata the indexer writes on every chunk. Everything else on a chunk came
# from the caller: it survives a reindex and is shown as the document's own.
BUILT_IN_METADATA_KEYS = {"doc_id", "chunk_id", "chunk_index", "source", "filetype", "indexed_at", "chunk_repeated_words"}

def build_chunks_metadatas(doc_id: str, chunks_size: int, source: str, filetype: str, agent_metadata: dict | None = None,
                           repeated_words: list[int] | None = None)-> tuple[list[str], list[dict]]:
    """`repeated_words`, one per chunk, is how many of its leading words repeat
    earlier chunks (overlap, heading path): what reconstruction drops."""
    indexed_at = datetime.now(timezone.utc).isoformat()
    chunk_ids = []
    metadatas = []

    for i in range(chunks_size):
        chunk_id = f"{doc_id}::{get_chunk_id(i)}"
        chunk_ids.append(chunk_id)
        metadatas.append(
            {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_index": i,
                "source": source,
                "filetype": filetype,
                "indexed_at": indexed_at,
                "chunk_repeated_words": repeated_words[i] if repeated_words else 0,
            })
        if agent_metadata:
            metadatas[-1].update(agent_metadata)
    
    return chunk_ids, metadatas