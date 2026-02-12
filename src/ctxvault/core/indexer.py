from ctxvault.utils.text_extraction import extract_text
from ctxvault.core.identifiers import get_doc_id
from ctxvault.utils.chuncking import chunking
from ctxvault.core.embedding import embed_list
from ctxvault.storage.chroma_store import add_document, delete_document
from ctxvault.utils.metadata_builder import build_chunks_metadatas

def index_file(file_path: str, agent_metadata: dict | None = None)-> dict:
    text, file_type = extract_text(path=file_path)
    doc_id = get_doc_id(path=file_path)

    chunks = chunking(text, chunk_size=50)

    embeddings = embed_list(chunks=chunks)

    chunk_ids, metadatas = build_chunks_metadatas(doc_id=doc_id, chunks_size=len(chunks), source=file_path, filetype=file_type, agent_metadata=agent_metadata)

    add_document(ids=chunk_ids, embeddings=embeddings, metadatas=metadatas, chunks=chunks)

def delete_file(file_path: str)-> None:
    doc_id = get_doc_id(path=file_path)
    delete_document(doc_id=doc_id)

def reindex_file(file_path: str)->None:
    delete_file(file_path=file_path)
    index_file(file_path=file_path)