from chromadb import PersistentClient

chroma_client = PersistentClient(path="./data/chroma")
collection = chroma_client.get_or_create_collection(name="ctxvault")

def add_document(ids: list[str], embeddings: list[list[float]], metadatas, chunks: list[str]):
    collection.add(
        ids=ids, 
        embeddings=embeddings, 
        metadatas=metadatas, 
        documents=chunks
    )

def query(query_embedding: list[float],  n_results: int = 5):
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results
    )
    return results

def delete_document(ids: list[str]):
    collection.delete(ids=ids)
