from chromadb import PersistentClient, Settings

_clients: dict[str, PersistentClient] = {}
_collections: dict[str, object] = {}

COLLECTION = "ctxvault"
# New collections compare vectors by cosine distance, so a score reads the
# same for every embedding model, normalised or not: 1 - cosine similarity.
# Collections made by earlier versions use Chroma's default, squared L2,
# which only maps to a similarity on unit vectors; `space` tells which one a
# vault has, and `reset_collection` (a full reindex) moves it over.
SPACE = "cosine"

def _client(db_path: str) -> PersistentClient:
    if db_path not in _clients:
        _clients[db_path] = PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))
    return _clients[db_path]

def _get_collection(db_path: str):
    if db_path not in _collections:
        client = _client(db_path)
        try:
            collection = client.get_collection(COLLECTION)
        except Exception:
            collection = client.create_collection(COLLECTION, metadata={"hnsw:space": SPACE})
        _collections[db_path] = collection
    return _collections[db_path]

def get_collection(config: dict):
    return _get_collection(config["db_path"])

def space(config: dict) -> str:
    """How the vault's collection measures distance: "cosine" for collections
    made by this version, "l2" for older ones (Chroma's default)."""
    metadata = get_collection(config=config).metadata or {}
    return metadata.get("hnsw:space") or "l2"

def reset_collection(config: dict) -> None:
    """Drop the collection and make it again with this version's distance.
    Everything indexed is gone with it: the caller reindexes."""
    db_path = config["db_path"]
    client = _client(db_path)
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    _collections.pop(db_path, None)
    _get_collection(db_path)

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
