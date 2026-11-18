import hashlib
import unicodedata

def get_doc_id(path: str)-> str:
    return hashlib.sha256(path.encode()).hexdigest()

def get_chunk_id(chunk_id: int):
    return hashlib.sha256(chunk_id.to_bytes(8, 'big')).hexdigest()

def get_text_hash(text: str) -> str:
    """A document's extracted text, normalised (Unicode NFC, whitespace
    collapsed), hashed. Equal hashes are the same document whatever the
    vault's model or chunking."""
    normalised = " ".join(unicodedata.normalize("NFC", text).split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
