from ctxvault.utils.text_extraction import extract_text
from ctxvault.utils.chuncking import chunking
from ctxvault.core.embedding import embed_list
from ctxvault.storage.chroma_store import add_document, query

if __name__ == "__main__":
    query_text = "Cosa devo fare al punto 4.3?"

    text = extract_text(path='./data/test.md') 
    chunks = chunking(text, chunk_size=50)
    embeddings = embed_list(chunks=chunks)

    query_embedding = embed_list(chunks=[query_text])

    add_document(ids=[], embeddings=embeddings, metadatas=[], chunks=chunks)

    result = query(query_embedding=query_embedding)
    
    print(result)