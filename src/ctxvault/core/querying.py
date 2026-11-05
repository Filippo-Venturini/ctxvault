import hashlib
import re

from ctxvault.core.embedding import embed_list
from ctxvault.core.exceptions import DocumentNotFoundError
from ctxvault.models.documents import DocumentContent, SemanticDocumentInfo
from ctxvault.storage import chroma_store
from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS

# Chunks indexed by an earlier version carry no repeat count, so the text
# they rebuild still duplicates what the chunker carried over.
_LEGACY_WARNING = (
    "Text is reconstructed by concatenating indexed chunks in order. "
    "Indexed by an earlier version, so overlapping chunk windows may duplicate "
    "text at boundaries; reindex the vault to fix."
)
_MARKDOWN_WARNING = (
    "Text is reconstructed from indexed chunks: markdown headings appear as "
    "their heading path (A > B), not as written."
)

def _without_repeats(text: str, repeated: int) -> str:
    """The chunk minus its leading words that repeat earlier chunks."""
    if repeated <= 0:
        return text
    for n, word in enumerate(re.finditer(r"\S+", text)):
        if n == repeated:
            return text[word.start():]
    return ""

def build_documents_from_metadatas(metadatas)-> list[SemanticDocumentInfo]:
    """One entry per document from its chunks' metadata. Every chunk of a
    document carries the same indexed_at and the same caller metadata, so the
    first chunk met speaks for the document."""
    acc = {}

    for row in metadatas:
        if not row:
            continue
        doc_id = row["doc_id"]

        if doc_id not in acc:
            acc[doc_id] = {
                "source": row["source"],
                "filetype": row["filetype"],
                "chunks_count": 1,
                "indexed_at": row.get("indexed_at"),
                "metadata": {k: v for k, v in row.items() if k not in BUILT_IN_METADATA_KEYS},
            }
        else:
            acc[doc_id]["chunks_count"] += 1

    return [SemanticDocumentInfo(doc_id=doc_id, **fields) for doc_id, fields in acc.items()]

def query(query_txt: str, config: dict, n_results: int = 5, filters: dict | None = None)-> dict:
    # Query must embed with the same model used to index this vault, or the
    # vectors are not comparable; both read it from the vault config.
    query_embedding = embed_list(chunks=[query_txt], model_name=config.get("embedding_model"))
    return chroma_store.query(query_embedding=query_embedding, config=config, n_results=n_results, filters=filters)

def list_documents(config: dict)-> list[SemanticDocumentInfo]:
    metadatas = chroma_store.get_all_metadatas(config=config)
    return build_documents_from_metadatas(metadatas=metadatas)

def _document_pairs(doc_id: str, config: dict) -> list[tuple[dict, str]]:
    """The document's chunks as (metadata, text), in index order."""
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
    return pairs

def get_document_chunks(doc_id: str, config: dict) -> list[str]:
    """The document as the agent meets it: its chunks, in index order."""
    return [text for _, text in _document_pairs(doc_id=doc_id, config=config)]

def get_document_content(doc_id: str, config: dict) -> DocumentContent:
    """The document as its chunks give it back: each chunk minus the words
    it repeats from the ones before, a continuation joined to its passage,
    a new passage on its own paragraph."""
    pairs = _document_pairs(doc_id=doc_id, config=config)
    first_metadata = pairs[0][0]
    legacy = any("chunk_repeated_words" not in metadata for metadata, _ in pairs)
    content = ""
    for n, (metadata, text) in enumerate(pairs):
        repeated = int(metadata.get("chunk_repeated_words") or 0) if n else 0
        part = _without_repeats(text, repeated)
        if not content:
            content = part
        elif repeated:
            content += " " + part
        else:
            content += "\n\n" + part
    chunks_count = len(pairs)
    if chunks_count > 1 and legacy:
        warning = _LEGACY_WARNING
    elif first_metadata.get("filetype") == ".md":
        warning = _MARKDOWN_WARNING
    else:
        warning = None

    return DocumentContent(
        doc_id=doc_id,
        source=first_metadata.get("source", ""),
        filetype=first_metadata.get("filetype", ""),
        chunks_count=chunks_count,
        content=content,
        reconstructed_text_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        indexed_at=first_metadata.get("indexed_at"),
        reconstructed=True,
        warning=warning,
    )
