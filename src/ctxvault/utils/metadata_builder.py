from ctxvault.core.identifiers import get_chunk_id

def build_chunks_metadatas(doc_id: str, chunks_size: int, source: str, filetype: str, agent_metadata: dict | None = None)-> tuple[list[str], list[dict]]:
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
            })
        if agent_metadata:
            metadatas[-1].update(agent_metadata)
    
    return chunk_ids, metadatas