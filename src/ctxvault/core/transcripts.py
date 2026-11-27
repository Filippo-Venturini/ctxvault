"""Sessions: a conversation written into a semantic vault as one document.

A session's dates come from its turns, never from the file: a file's
modification time says when it was written, not when the conversation took
place. Each turn is one line, its time in front when it has one, so a chunk
that starts in the middle of a session still says when its turns were said.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ctxvault.core.exceptions import UnsupportedFileTypeError, UnsupportedVaultOperationError

class Turn(BaseModel):
    """One thing said in a conversation: by whom, and when if known."""

    model_config = ConfigDict(str_strip_whitespace=True)

    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)
    at: str | None = None      # ISO 8601; a time without an offset is read as UTC

# The metadata write_session sets on every chunk of a session. Flat, so it
# filters; the *_ts copies are epoch seconds because Chroma's $gt and $lt
# compare numbers only.
SESSION_METADATA_KEYS = frozenset({
    "session_id", "session_started", "session_ended",
    "session_started_ts", "session_ended_ts", "session_dated",
})

class SessionWrite(BaseModel):
    """Where a session landed: its document, and the chunk each turn starts in."""

    doc_id: str
    path: str                     # relative to the vault
    chunks: int
    # turn_chunks[i] is the chunk turn i starts in: the first one, when the
    # overlap between chunks puts the turn in two
    turn_chunks: list[int]
    session_started: str | None = None
    session_ended: str | None = None

def _utc(value: str, n: int) -> datetime:
    try:
        # Python 3.10's fromisoformat does not accept a trailing "Z".
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise ValueError(f"Turn {n}: '{value}' is not an ISO 8601 date or time.") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def _one_line(text: str) -> str:
    return " ".join(text.split())

def session_lines(turns: list[Turn]) -> tuple[list[str], list[datetime | None]]:
    """The session's lines, one per turn, and each turn's time in UTC.

    `YYYY-MM-DD HH:MM  speaker: text` for a dated turn, `speaker: text` for an
    undated one. Line breaks inside a turn become spaces, so every line is a
    turn and the format reads back.
    """
    times = [_utc(turn.at, n) if turn.at else None for n, turn in enumerate(turns)]
    lines = [
        (f"{at:%Y-%m-%d %H:%M}  " if at else "") + f"{_one_line(turn.speaker)}: {_one_line(turn.text)}"
        for turn, at in zip(turns, times)
    ]
    return lines, times

def _turn_chunks(lines: list[str], pairs: list[tuple[dict, str]]) -> list[int]:
    """The chunk each line starts in, by word position.

    Chunking a .txt keeps every word in order and only repeats the words it
    carries over as overlap, which each chunk records as
    `chunk_repeated_words`. Counting the new words of each chunk gives the
    word range it adds to the document; a turn falls in the chunk whose range
    holds its first word.
    """
    starts, position = [], 0
    for line in lines:
        starts.append(position)
        position += len(line.split())
    total = position

    ends, position = [], 0
    for metadata, text in pairs:
        position += len(text.split()) - int(metadata.get("chunk_repeated_words") or 0)
        ends.append(position)
    if position != total:
        raise RuntimeError(f"The session's chunks hold {position} new words, its text {total}: they do not line up.")

    result, chunk = [], 0
    for start in starts:
        while ends[chunk] <= start:
            chunk += 1
        result.append(chunk)
    return result

def write_session(vault, file_path: str, turns: Iterable[Turn | dict], *,
                  session_id: str | None = None, agent_metadata: dict | None = None) -> SessionWrite:
    """Write a session to a semantic vault as one .txt document, and index it.

    Writing the same `file_path` again replaces the session: the same doc_id,
    never a second copy. The session's start and end are its earliest and
    latest dated turns; with no dated turn it is written as undated, and
    nothing falls back to the file's time. Built on `write_doc`, so
    `agent_metadata` (generated_by, timestamp) is stored as for any document.
    """
    from ctxvault.core import querying
    from ctxvault.core.identifiers import get_doc_id
    from ctxvault.core.vaults.semantic import SemanticVault
    from ctxvault.models.vaults import VaultOperation

    if not isinstance(vault, SemanticVault):
        raise UnsupportedVaultOperationError("A session is written to a semantic vault.")
    vault._require_operation(VaultOperation.WRITE_DOC)
    # .txt is chunked by paragraphs, lines and words, all of which keep the
    # text's words in order; that is what lets each turn be found in its chunk.
    if Path(file_path).suffix != ".txt":
        raise UnsupportedFileTypeError("A session is written as a .txt file.")

    turns = [Turn.model_validate(turn) for turn in turns]
    if not turns:
        raise ValueError("A session needs at least one turn.")
    overlap = SESSION_METADATA_KEYS & set(agent_metadata or {})
    if overlap:
        raise ValueError(f"agent_metadata may not set {', '.join(sorted(overlap))}: write_session sets them.")

    lines, times = session_lines(turns)
    dated = [at for at in times if at is not None]
    metadata = dict(agent_metadata or {})
    metadata["session_dated"] = bool(dated)
    if session_id is not None:
        metadata["session_id"] = session_id
    started = ended = None
    if dated:
        started, ended = min(dated).isoformat(), max(dated).isoformat()
        metadata.update({
            "session_started": started, "session_ended": ended,
            "session_started_ts": min(dated).timestamp(), "session_ended_ts": max(dated).timestamp(),
        })

    vault.write_doc(file_path=file_path, content="\n".join(lines) + "\n", overwrite=True, agent_metadata=metadata)

    abs_path = (vault.vault_path / file_path).resolve()
    doc_id = get_doc_id(str(abs_path))
    pairs = querying._document_pairs(doc_id=doc_id, config=vault.config)
    return SessionWrite(
        doc_id=doc_id,
        path=abs_path.relative_to(vault.vault_path.resolve()).as_posix(),
        chunks=len(pairs),
        turn_chunks=_turn_chunks(lines, pairs),
        session_started=started,
        session_ended=ended,
    )
