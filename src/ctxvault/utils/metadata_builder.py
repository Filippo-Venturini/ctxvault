import hashlib

def get_chunk_id(chunk_id: int):
    return hashlib.sha256(chunk_id.to_bytes(8, 'big')).hexdigest()

def build_chunks_metadatas(doc_id: str, chunks_size: int, source: str, filetype: str)-> tuple[list[str], list[dict]]:
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
                "filetype": filetype
            })
    
    return chunk_ids, metadatas