from sentence_transformers import SentenceTransformer

MODEL: SentenceTransformer = None

def get_model():
    global MODEL
    if MODEL is None:
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return MODEL

def embed_list(chunks: list[str]):
    embeddings = get_model().encode(sentences=chunks)
    print(embeddings.shape)
    return embeddings