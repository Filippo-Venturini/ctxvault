from ctxvault.utils.text_extraction import get_doc_id, extract_text
from ctxvault.utils.chuncking import chunking
from ctxvault.core.embedding import embed_list
from ctxvault.storage.chroma_store import add_document
from ctxvault.utils.metadata_builder import build_chunks_metadatas

def index_file(file_path: str)-> dict:
    print("Extracting text...")
    text, file_type = extract_text(path=file_path)
    doc_id = get_doc_id(path=file_path)

    print("Chunking...")
    chunks = chunking(text, chunk_size=50)

    print("Calculating Embeddings...")
    embeddings = embed_list(chunks=chunks)

    print("Building metadatas...")
    chunk_ids, metadatas = build_chunks_metadatas(doc_id=doc_id, chunks_size=len(chunks), source=file_path, filetype=file_type)

    add_document(ids=chunk_ids, embeddings=embeddings, metadatas=metadatas, chunks=chunks)

    print("Document added succesfully!")
    None