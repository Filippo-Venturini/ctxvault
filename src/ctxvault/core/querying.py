import hashlib

from ctxvault.core.embedding import embed_list
from ctxvault.core.exceptions import DocumentNotFoundError
from ctxvault.models.documents import DocumentContent, SemanticDocumentInfo
from ctxvault.storage import chroma_store

_RECONSTRUCTION_WARNING = (
    "Text is reconstructed by concatenating indexed chunks in order. "
    "Overlapping chunk windows may duplicate text at boundaries."
)

def build_documents_from_metadatas(metadatas)-> list[SemanticDocumentInfo]:
    acc = {}

    for row in metadatas:
        doc_id = row["doc_id"]

        if doc_id not in acc:
            acc[doc_id] = (
                row["source"],
                row["filetype"],
                1
            )
        else:
            source, filetype, count = acc[doc_id]
            acc[doc_id] = (source, filetype, count + 1)

    return [
        SemanticDocumentInfo(
            doc_id=doc_id,
            source=source,
            filetype=filetype,
            chunks_count=count
        )
        for doc_id, (source, filetype, count) in acc.items()
    ]

def query(query_txt: str, config: dict, n_results: int = 5, filters: dict | None = None)-> dict:
    query_embedding = embed_list(chunks=[query_txt])
    return chroma_store.query(query_embedding=query_embedding, config=config, n_results=n_results, filters=filters)

def list_documents(config: dict)-> list[SemanticDocumentInfo]:
    metadatas = chroma_store.get_all_metadatas(config=config)
    return build_documents_from_metadatas(metadatas=metadatas)

def get_document_content(doc_id: str, config: dict) -> DocumentContent:
    records = chroma_store.get_document_records(doc_id=doc_id, config=config)
    metadatas = records.get("metadatas") or []
    documents = records.get("documents") or []

    if not metadatas:
        raise DocumentNotFoundError(f"Document '{doc_id}' not found in vault.")

    pairs = [
        (metadata, text)
        for metadata, text in zip(metadatas, documents)
        if metadata is not None and text is not None
    ]
    if not pairs:
        raise DocumentNotFoundError(f"Document '{doc_id}' has no retrievable chunk text.")

    pairs.sort(key=lambda item: item[0].get("chunk_index", 0))
    first_metadata = pairs[0][0]
    content = "".join(text for _, text in pairs)
    chunks_count = len(pairs)

    return DocumentContent(
        doc_id=doc_id,
        source=first_metadata.get("source", ""),
        filetype=first_metadata.get("filetype", ""),
        chunks_count=chunks_count,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        indexed_at=first_metadata.get("indexed_at"),
        reconstructed=True,
        warning=_RECONSTRUCTION_WARNING if chunks_count > 0 else None,
    )
