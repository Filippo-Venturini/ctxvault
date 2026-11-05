"""Chunking strategies for text splitting.

Three strategies are available:
- Markdown chunking: splits on markdown headers, preserving header hierarchy.
- Recursive character splitting: tries paragraph -> line -> word splits.
- Fixed-size splitting: windowed chunks over word boundaries, with overlap.

Sizes are counted by a `measure`: a function from text to a number. The
default counts words. The indexer passes the embedding model's own token
count, with the model's input limit as `chunk_size`, so that no chunk is
longer than what the model can actually read. `overlap` is in the same unit.

Each chunk comes back with how many of its leading words repeat the end of
the chunk before it (the fixed strategy carries words over so a split does
not cut a thought; a markdown continuation repeats its heading path). That
is what lets a document be reconstructed from its chunks without the repeats.
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

Measure = Callable[[str], int]

class Chunk(NamedTuple):
    text: str
    # leading words of `text` that repeat earlier chunks: carried-over overlap,
    # and a heading path repeated on a continuation
    repeated_words: int = 0

def _words(text: str) -> int:
    return len(text.split())

def chunking(
    text: str,
    chunk_size: int = 400,
    overlap: int = 100,
    file_type: str | None = None,
    measure: Measure | None = None,
) -> list[str]:
    """Split text into chunks using a strategy based on file_type.

    Args:
        text: The input text to chunk.
        chunk_size: Maximum size of a chunk, as `measure` counts it.
        overlap: Overlap between consecutive fixed-size chunks, as `measure` counts it.
        file_type: File extension (e.g. ".md", ".txt"). When None, uses recursive strategy.
        measure: How size is counted; words when not given.

    Returns:
        A list of non-empty text chunks.
    """
    return [c.text for c in chunk_text(text, chunk_size, overlap, file_type, measure)]

def chunk_text(
    text: str,
    chunk_size: int = 400,
    overlap: int = 100,
    file_type: str | None = None,
    measure: Measure | None = None,
) -> list[Chunk]:
    """Like `chunking`, with each chunk's repeated leading words."""
    if not text or not text.strip():
        return []
    measure = measure or _words

    if file_type == ".md":
        return _chunk_markdown(text, chunk_size, overlap, measure)

    # .txt, .pdf, .docx, None, and anything else -> recursive
    return _chunk_recursive(text, chunk_size, overlap, measure)


def _chunk_markdown(text: str, chunk_size: int, overlap: int, measure: Measure) -> list[Chunk]:
    """Split markdown text on headers, preserving header hierarchy as context prefixes.

    Each section becomes a chunk prefixed with its full header hierarchy.
    Sections exceeding chunk_size are further split using the recursive
    strategy, every piece carrying the prefix. Falls back to recursive
    splitting if no markdown headers are found.
    """
    # Match lines that start with one or more '#' characters followed by a space
    header_pattern = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)

    headers = list(header_pattern.finditer(text))

    if not headers:
        return _chunk_recursive(text, chunk_size, overlap, measure)

    # Build sections: each section is (header_hierarchy_prefix, body_text)
    sections: list[tuple[str, str]] = []

    # Track the current header stack for hierarchy context
    # Each entry is (level, header_text)
    header_stack: list[tuple[int, str]] = []

    # Collect any text before the first header as a preamble
    preamble = text[: headers[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(headers):
        level = len(match.group(1))
        header_text = match.group(2).strip()

        # Pop headers from the stack that are at the same level or deeper
        header_stack = [(lvl, txt) for lvl, txt in header_stack if lvl < level]
        header_stack.append((level, header_text))

        # Build the hierarchy prefix from the stack
        hierarchy_prefix = " > ".join(txt for _, txt in header_stack)

        # Extract body text between this header and the next header (or end of text)
        body_start = match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end].strip()

        sections.append((hierarchy_prefix, body))

    chunks: list[Chunk] = []

    for prefix, body in sections:
        if prefix:
            section_text = f"{prefix}\n{body}" if body else prefix
        else:
            section_text = body

        if measure(section_text) <= chunk_size:
            if section_text.strip():
                chunks.append(Chunk(section_text.strip()))
            continue

        # Section too large; split body with recursive strategy and prepend
        # prefix. The prefix counts against the size of every piece.
        room = max(1, chunk_size - (measure(prefix) if prefix else 0))
        sub_chunks = _chunk_recursive(body if body else section_text, room, overlap, measure)
        for n, sub in enumerate(sub_chunks):
            piece = f"{prefix}\n{sub.text}" if prefix else sub.text
            if not piece.strip():
                continue
            # a continuation repeats the heading path on top of its own overlap
            repeated = sub.repeated_words + (_words(prefix) if prefix and n else 0)
            chunks.append(Chunk(piece.strip(), repeated))

    return chunks


def _chunk_recursive(text: str, chunk_size: int, overlap: int, measure: Measure) -> list[Chunk]:
    """Recursively split text by paragraphs, then lines, then words.

    Tries splitting by double newlines (paragraphs) first. If any resulting piece
    exceeds chunk_size, splits those pieces by single newlines (lines).
    If still too large, falls back to fixed-size splitting with overlap.
    """
    if not text or not text.strip():
        return []

    # If the entire text fits, return it as a single chunk
    if measure(text) <= chunk_size:
        return [Chunk(text.strip())]

    # Step 1: split by paragraphs
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    pieces = _merge_pieces(paragraphs, chunk_size, measure)

    # Step 2: any piece still too large -> split by lines
    refined: list[str] = []
    for piece in pieces:
        if measure(piece) <= chunk_size:
            refined.append(piece)
        else:
            lines = [ln.strip() for ln in piece.split("\n") if ln.strip()]
            refined.extend(_merge_pieces(lines, chunk_size, measure))

    # Step 3: any piece still too large -> fixed-size split
    final: list[Chunk] = []
    for piece in refined:
        if measure(piece) <= chunk_size:
            final.append(Chunk(piece))
        else:
            final.extend(_chunk_fixed(piece, chunk_size, overlap, measure))

    return [c for c in final if c.text.strip()]


def _merge_pieces(pieces: list[str], chunk_size: int, measure: Measure) -> list[str]:
    """Merge small consecutive pieces together up to chunk_size.

    Greedily combines pieces so that each merged chunk stays within the limit.
    """
    merged: list[str] = []
    current: list[str] = []
    current_size = 0

    for piece in pieces:
        piece_size = measure(piece)
        if current and current_size + piece_size > chunk_size:
            merged.append("\n\n".join(current))
            current = [piece]
            current_size = piece_size
        else:
            current.append(piece)
            current_size += piece_size

    if current:
        merged.append("\n\n".join(current))

    return merged


def _chunk_fixed(text: str, chunk_size: int = 400, overlap: int = 100, measure: Measure = _words) -> list[Chunk]:
    """Fixed-size splitting over word boundaries, with overlap.

    Windows are cut between words and keep the text between them as it was,
    newlines included. Each word is measured once; a window grows while the
    sum stays within chunk_size, and the next one starts back by `overlap`.
    A single word larger than the limit still gets a window of its own.
    """
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    cost = [measure(text[a:b]) for a, b in words]

    chunks: list[Chunk] = []
    start, repeated = 0, 0
    while start < len(words):
        end, size = start, 0
        while end < len(words) and (end == start or size + cost[end] <= chunk_size):
            size += cost[end]
            end += 1
        chunks.append(Chunk(text[words[start][0]:words[end - 1][1]], repeated))
        if end >= len(words):
            break
        # step back by `overlap`, never to the window's own first word
        back, carried = end, 0
        while back > start + 1 and carried + cost[back - 1] <= overlap:
            carried += cost[back - 1]
            back -= 1
        repeated = end - back
        start = back
    return chunks
