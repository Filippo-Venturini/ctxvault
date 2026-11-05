def index_file(file_path: str, config: dict, agent_metadata: dict | None = None)-> dict:
    from ctxvault.utils.text_extraction import extract_text
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.utils.chuncking import chunk_text
    from ctxvault.core import embedding
    from ctxvault.storage.chroma_store import add_document
    from ctxvault.utils.metadata_builder import build_chunks_metadatas

    text, file_type = extract_text(path=file_path)
    doc_id = get_doc_id(path=file_path)

    # The model pinned to this vault (config["embedding_model"], else the
    # default) decides both the vectors and how long a chunk may be: it is
    # cut in its tokens, to its input limit, so every chunk is embedded whole.
    model_name = config.get("embedding_model")
    measure, chunk_size, overlap = embedding.token_budget(model_name)
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap, file_type=file_type, measure=measure)

    embeddings = embedding.embed_list(chunks=[c.text for c in chunks], model_name=model_name)

    chunk_ids, metadatas = build_chunks_metadatas(doc_id=doc_id, chunks_size=len(chunks), source=file_path, filetype=file_type,
                                                  agent_metadata=agent_metadata, repeated_words=[c.repeated_words for c in chunks])

    add_document(ids=chunk_ids, embeddings=embeddings, metadatas=metadatas, chunks=[c.text for c in chunks], config=config)

def delete_file(file_path: str, config: dict)-> None:
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.storage.chroma_store import delete_document

    doc_id = get_doc_id(path=file_path)
    delete_document(doc_id=doc_id, config=config)

def reindex_file(file_path: str, config: dict)->None:
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.storage.chroma_store import get_document_records
    from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS

    # Chunks carry whatever metadata the writing agent attached; rebuilding them
    # from the file alone would silently drop it, so it is read back from the
    # existing chunks and carried over.
    doc_id = get_doc_id(path=file_path)
    existing = get_document_records(doc_id=doc_id, config=config)
    agent_metadata = _extract_agent_metadata(existing.get("metadatas") or [])

    delete_file(file_path=file_path, config=config)
    index_file(file_path=file_path, config=config, agent_metadata=agent_metadata)

def _extract_agent_metadata(metadatas: list[dict | None]) -> dict | None:
    from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS

    for metadata in metadatas:
        if not metadata:
            continue
        custom = {k: v for k, v in metadata.items() if k not in BUILT_IN_METADATA_KEYS}
        if custom:
            return custom
    return None
