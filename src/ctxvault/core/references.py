"""Chunk references: a span of a semantic vault, named so it can be checked later.

A reference is plain data: the vault, the document, the chunk's position, the
hash of the text it pointed at, and the document's path inside the vault. It
means nothing until `resolve_chunk` looks at the vault as it is now, and that
answer is always exactly one state, never a blend: text comes back only when
the hash still matches, so a caller can never read a span that changed.
"""

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ctxvault.core.exceptions import DocumentNotFoundError, MissingAgentNameError, VaultNotFoundError
from ctxvault.core.identifiers import get_doc_id

def chunk_hash(text: str) -> str:
    """SHA-256 hex of the chunk text exactly as `get_document_chunks()` returns
    it: overlap words included, nothing normalised."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _relative_path(source: str, vault_path: Path) -> str | None:
    try:
        return Path(source).resolve().relative_to(vault_path.resolve()).as_posix()
    except ValueError:
        return None

def _semantic_vault(vault_name: str):
    from ctxvault.core import vault_router
    from ctxvault.core.vaults.semantic import SemanticVault

    vault = vault_router.open_vault(vault_name)
    if not isinstance(vault, SemanticVault):
        raise ValueError(f"Vault '{vault_name}' is not a semantic vault: chunk references point into semantic vaults.")
    return vault

def chunk_reference(vault_name: str, doc_id: str, chunk_index: int) -> dict:
    """{vault, doc_id, chunk_index, chunk_hash, path} for one chunk as it is now.

    `path` is the document's path relative to the vault, so a vault moved to
    another directory (which changes every doc_id) can still be followed.
    Raises DocumentNotFoundError for a document that is not indexed, and
    IndexError for a chunk past its end.
    """
    vault = _semantic_vault(vault_name)
    chunks = vault.get_document_chunks(doc_id)
    if not 0 <= chunk_index < len(chunks):
        raise IndexError(f"Document '{doc_id}' has {len(chunks)} chunks; there is no chunk {chunk_index}.")

    from ctxvault.storage import chroma_store
    records = chroma_store.get_document_records(doc_id=doc_id, config=vault.config)
    source = next((m.get("source") for m in records.get("metadatas") or [] if m and m.get("source")), None)
    return {
        "vault": vault_name,
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "chunk_hash": chunk_hash(chunks[chunk_index]),
        "path": _relative_path(source, vault.vault_path) if source else None,
    }

ResolutionState = Literal["holds", "changed", "moved", "missing", "unreachable", "refused"]

class ChunkResolution(BaseModel):
    """What a reference points at now. `text` is set only for holds and moved."""

    state: ResolutionState
    said: str                  # why, in one line
    text: str | None = None
    doc_id: str | None = None  # the current doc_id, when the document was found
    chunk_index: int | None = None

_DRIVE = re.compile(r"^[A-Za-z]:")

def _plain_relative(path: str) -> bool:
    """A path inside a vault: not absolute, no drive, nothing climbing out."""
    if not path or path.startswith(("/", "\\")) or _DRIVE.match(path):
        return False
    return ".." not in re.split(r"[/\\]", path)

def _parse(reference: Mapping) -> tuple[str, str, int, str, str | None]:
    try:
        vault, doc_id = reference["vault"], reference["doc_id"]
        index, expected = reference["chunk_index"], reference["chunk_hash"]
    except KeyError as missing:
        raise ValueError(f"A chunk reference needs {missing}.") from None
    path = reference.get("path")
    if not (isinstance(vault, str) and vault and isinstance(doc_id, str) and doc_id):
        raise ValueError("A chunk reference needs a vault and a doc_id.")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("A chunk reference's chunk_index is a non-negative integer.")
    if not (isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected)):
        raise ValueError("A chunk reference's chunk_hash is a SHA-256 hex digest.")
    if path is not None and not isinstance(path, str):
        raise ValueError("A chunk reference's path is a string.")
    return vault, doc_id, index, expected, path

def resolve_chunk(reference: Mapping, *, agent: str | None = None) -> ChunkResolution:
    """Check a chunk reference against the vault as it is now.

    Exactly one state comes back. `unreachable` and `refused` are never
    `missing`: a vault registered elsewhere, or one this agent may not read,
    says nothing about whether the source is gone. Access is checked before
    anything is read, and a refused caller learns nothing about the document.
    A malformed reference is the caller's bug, and raises ValueError.
    """
    from ctxvault.core import vault_router
    from ctxvault.core.vaults.semantic import SemanticVault

    vault_name, doc_id, index, expected, path = _parse(reference)

    if path is not None and not _plain_relative(path):
        return ChunkResolution(state="refused", said="the reference's path is not a plain relative path inside a vault")

    try:
        authorized = vault_router.is_agent_authorized(vault_name, agent)
    except MissingAgentNameError:
        return ChunkResolution(state="refused", said=f"vault '{vault_name}' is restricted, and no agent name was given")
    except VaultNotFoundError as e:
        return ChunkResolution(state="unreachable", said=str(e))
    if not authorized:
        return ChunkResolution(state="refused", said=f"agent '{agent}' may not read vault '{vault_name}'")

    try:
        vault = vault_router.open_vault(vault_name)
    except Exception as e:
        return ChunkResolution(state="unreachable", said=f"vault '{vault_name}' could not be opened: {e}")
    if not isinstance(vault, SemanticVault):
        return ChunkResolution(state="unreachable", said=f"vault '{vault_name}' is not a semantic vault")

    def chunks_of(candidate: str) -> list[str] | None:
        try:
            return vault.get_document_chunks(candidate)
        except DocumentNotFoundError:
            return None

    try:
        chunks = chunks_of(doc_id)
        found_id = doc_id
        if chunks is None and path is not None:
            target = (vault.vault_path / path).resolve()
            if not target.is_relative_to(vault.vault_path.resolve()):
                return ChunkResolution(state="refused", said="the reference's path leads outside the vault")
            found_id = get_doc_id(str(target))
            chunks = chunks_of(found_id) if found_id != doc_id else None
    except Exception as e:
        return ChunkResolution(state="unreachable", said=f"vault '{vault_name}' could not be read: {e}")

    if chunks is None:
        where = f"under its doc_id or at '{path}'" if path is not None else "under its doc_id, and the reference has no path"
        return ChunkResolution(state="missing", said=f"the document is not in vault '{vault_name}' {where}")

    moved = found_id != doc_id
    if index >= len(chunks):
        return ChunkResolution(state="changed", doc_id=found_id,
                               said=f"the document has {len(chunks)} chunks now; chunk {index} is past its end")
    if chunk_hash(chunks[index]) != expected:
        return ChunkResolution(state="changed", doc_id=found_id, chunk_index=index,
                               said=f"chunk {index} no longer has the text the reference was made from")
    if moved:
        return ChunkResolution(state="moved", text=chunks[index], doc_id=found_id, chunk_index=index,
                               said=f"the document is at '{path}' under a new doc_id, with the same text")
    return ChunkResolution(state="holds", text=chunks[index], doc_id=doc_id, chunk_index=index,
                           said="the chunk is where the reference says, with the same text")
