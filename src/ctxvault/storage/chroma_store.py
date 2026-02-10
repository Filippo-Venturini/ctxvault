from chromadb import PersistentClient
from pathlib import Path
from ctxvault.models.documents import DocumentInfo
from ctxvault.utils.config import get_db_path

_chroma_client = None
_collection = None

def get_collection():
    global _chroma_client, _collection
    if _collection is None:
        path = get_db_path()
        _chroma_client = PersistentClient(path=path)
        _collection = _chroma_client.get_or_create_collection("ctxvault")
    return _collection

def add_document(ids: list[str], embeddings: list[list[float]], metadatas: list[dict], chunks: list[str]):
    collection = get_collection()
    collection.upsert(
        ids=ids, 
        embeddings=embeddings, 
        metadatas=metadatas, 
        documents=chunks
    )

def query(query_embedding: list[float],  n_results: int = 5)-> dict:
    collection = get_collection()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results
    )
    return results

def delete_document(doc_id: str):
    collection = get_collection()
    collection.delete(
        where={"doc_id": doc_id}
    )

def get_all_metadatas():
    collection = get_collection()
    results = collection.get(include=["metadatas"])
    return results["metadatas"]