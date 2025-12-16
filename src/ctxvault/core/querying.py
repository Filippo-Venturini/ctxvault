from ctxvault.core.embedding import embed_list
from ctxvault.storage import chroma_store

def query(query_txt: str)-> dict:
    query_embedding = embed_list(chunks=[query_txt])
    return chroma_store.query(query_embedding=query_embedding)