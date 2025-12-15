from ctxvault.utils.text_extraction import extract_text, get_doc_id
from ctxvault.utils.chuncking import chunking
from ctxvault.core.embedding import embed_list
from ctxvault.storage.chroma_store import add_document, delete_document, query
from ctxvault.utils.metadata_builder import build_chunks_metadatas

if __name__ == "__main__":
    file_path = "./data/test.md"
    query_text = "When was proposed ORION-LENS?"

    print("Extracting text...")
    text, file_type = extract_text(path=file_path)
    doc_id = get_doc_id(path=file_path)

    print("Chunking...")
    chunks = chunking(text, chunk_size=50)

    print("Calculating Embeddings...")
    embeddings = embed_list(chunks=chunks)

    print("Building metadatas...")
    chunk_ids, metadatas = build_chunks_metadatas(doc_id=doc_id, chunks_size=len(chunks), source=file_path, filetype=file_type)

    query_embedding = embed_list(chunks=[query_text])
    add_document(ids=chunk_ids, embeddings=embeddings, metadatas=metadatas, chunks=chunks)

    result = query(query_embedding=query_embedding)

    delete_document(ids=chunk_ids)
    
    print(result)