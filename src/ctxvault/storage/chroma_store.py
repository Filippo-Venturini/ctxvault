from chromadb import PersistentClient, Settings

_clients: dict[str, PersistentClient] = {}
_collections: dict[str, object] = {}

def _get_collection(db_path: str):
    if db_path not in _collections:
        client = PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False)
        )
        _clients[db_path] = client
        _collections[db_path] = client.get_or_create_collection("ctxvault")
    return _collections[db_path]

def get_collection(config: dict):
    return _get_collection(config["db_path"])

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

def get_document_records(doc_id: str, config: dict) -> dict:
    collection = get_collection(config=config)
    return collection.get(
        where={"doc_id": doc_id},
        include=["documents", "metadatas"],
    )