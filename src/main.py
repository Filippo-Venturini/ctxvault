from ctxvault.utils.text_extraction import extract_text
from ctxvault.utils.chuncking import chunking
from ctxvault.core.embedding import embed_list

if __name__ == "__main__":
    text = extract_text(path='./data/test.md') 
    chunks = chunking(text, chunk_size=50)
    embeddings = embed_list(chunks=chunks)
    
    print(embeddings)