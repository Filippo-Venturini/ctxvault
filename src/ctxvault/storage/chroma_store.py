from chromadb import PersistentClient

_chroma_client = None
_collection = None

def get_collection(config: dict):
    global _chroma_client, _collection
    if _collection is None:
        path = config["db_path"]
        _chroma_client = PersistentClient(path=path)
        _collection = _chroma_client.get_or_create_collection("ctxvault")
    return _collection

def add_document(ids: list[str], embeddings: list[list[float]], metadatas: list[dict], chunks: list[str], config: dict):
    collection = get_collection(config=config)
    collection.upsert(
        ids=ids, 
        embeddings=embeddings, 
        metadatas=metadatas, 
        documents=chunks
    )

def query(query_embedding: list[float], config: dict, n_results: int = 5, filters: dict | None = None)-> dict:
    collection = get_collection(config=config)
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results,
        where=filters
    )
    return results

def delete_document(doc_id: str, config: dict):
    collection = get_collection(config=config)
    collection.delete(
        where={"doc_id": doc_id}
    )

def get_all_metadatas(config: dict):
    collection = get_collection(config=config)
    results = collection.get(include=["metadatas"])
    return results["metadatas"]