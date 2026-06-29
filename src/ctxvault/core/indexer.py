def index_file(file_path: str, config: dict, agent_metadata: dict | None = None)-> dict:
    from ctxvault.utils.text_extraction import extract_text
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.utils.chuncking import chunking
    from ctxvault.core.embedding import embed_list
    from ctxvault.storage.chroma_store import add_document
    from ctxvault.utils.metadata_builder import build_chunks_metadatas

    text, file_type = extract_text(path=file_path)
    doc_id = get_doc_id(path=file_path)

    chunks = chunking(text, file_type=file_type)

    # Use the model pinned to this vault (config["embedding_model"]); falls back
    # to the default model when the vault was created without an override.
    embeddings = embed_list(chunks=chunks, model_name=config.get("embedding_model"))

    chunk_ids, metadatas = build_chunks_metadatas(doc_id=doc_id, chunks_size=len(chunks), source=file_path, filetype=file_type, agent_metadata=agent_metadata)

    add_document(ids=chunk_ids, embeddings=embeddings, metadatas=metadatas, chunks=chunks, config=config)

def delete_file(file_path: str, config: dict)-> None:
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.storage.chroma_store import delete_document

    doc_id = get_doc_id(path=file_path)
    delete_document(doc_id=doc_id, config=config)

def reindex_file(file_path: str, config: dict)->None:
    delete_file(file_path=file_path, config=config)
    index_file(file_path=file_path, config=config)
