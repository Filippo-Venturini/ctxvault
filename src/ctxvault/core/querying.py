from ctxvault.core.embedding import embed_list
from ctxvault.models.documents import DocumentInfo
from ctxvault.storage import chroma_store

def build_documents_from_metadatas(metadatas)-> list[DocumentInfo]:
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
        DocumentInfo(
            doc_id=doc_id,
            source=source,
            filetype=filetype,
            chunks_count=count
        )
        for doc_id, (source, filetype, count) in acc.items()
    ]

def query(query_txt: str, config: dict, filters: dict | None = None)-> dict:
    query_embedding = embed_list(chunks=[query_txt])
    return chroma_store.query(query_embedding=query_embedding, config=config, filters=filters)

def list_documents(config: dict)-> list[DocumentInfo]:
    metadatas = chroma_store.get_all_metadatas(config=config)
    return build_documents_from_metadatas(metadatas=metadatas)
    