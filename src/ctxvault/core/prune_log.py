"""The prune log: an append-only record of what pruning archived, restored and purged.

Rows are never rewritten. An entry's state (archived, restored, purged) is
read from the rows that follow it, so the log is also the history of every
document pruning touched. Each row carries the hash of the one before it: a
log that was edited, cut short or reordered no longer chains, and pruning
refuses to act on it until a person has looked. Repairing it is never this
code's job.

One thing is not a break: an unterminated last line. Every row is written
with its newline in one write, so a line without one is a write that never
finished (a crash mid-append) and was never committed. It is ignored with a
warning, and the next append drops it.
"""

import hashlib
import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: msvcrt locks a byte of the log instead
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]

LOG_NAME = "prune-log.jsonl"
GENESIS = "0" * 64
ROW_KEYS = {"n", "kind", "who", "at", "prev", "hash"}

class PruneLogBroken(RuntimeError):
    """The log does not chain. Nothing is pruned, restored or purged until a person looks."""

def canon(row: dict) -> str:
    """Canonical JSON: keys sorted, no spaces, UTF-8 kept as is."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _h256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def read(path: Path) -> tuple[list[dict], list[str]]:
    """(rows, breaks). Every break is said; an empty list means the log holds."""
    if not path.exists():
        return [], []
    rows, breaks, _ = _parse(path.read_bytes(), path)
    return rows, breaks

def _parse(data: bytes, path: Path) -> tuple[list[dict], list[str], int]:
    """(rows, breaks, committed): `committed` is how many bytes of `data` are
    whole rows; past it is an unfinished write."""
    committed = data.rfind(b"\n") + 1
    if committed < len(data):
        warnings.warn(f"The last line of {path} is unterminated: a write that never finished. It is ignored, "
                      f"and the next append drops it. If it was an archive, the file is in {path.parent} "
                      "in a folder no row names; move it back by hand.", stacklevel=3)
    rows, breaks, prev = [], [], GENESIS
    # "\n" only: str.splitlines() would also cut at U+2028 inside a file name
    lines = data[:committed].decode("utf-8").split("\n")[:-1]
    for i, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if not isinstance(row, dict) or not ROW_KEYS <= row.keys():
            breaks.append(f"line {i}: garbled, not a log row")
            continue
        body = {k: v for k, v in row.items() if k != "hash"}
        if row["prev"] != prev or _h256(canon(body)) != row["hash"]:
            breaks.append(f"row {row['n']}: chain broken")
        if isinstance(row["n"], bool) or row["n"] != len(rows):
            breaks.append(f"row {row['n']!r}: out of place, it is row {len(rows)}")
        rows.append(row)
        prev = row["hash"]
    return rows, breaks, committed

def rows_or_refuse(path: Path) -> list[dict]:
    rows, breaks = read(path)
    if breaks:
        raise PruneLogBroken(f"The prune log at {path} does not chain ({'; '.join(breaks)}). "
                             "Nothing was changed; look at the file before pruning again. Archived files are "
                             f"still in {path.parent}, each at its path in the vault; to move them back by hand or "
                             "start a new log, see 'When the prune log does not chain' in the CLI reference.")
    return rows

class PruneLogBusy(TimeoutError):
    """Another writer held the log for longer than a lock waits."""

def _lock(f) -> None:
    """One writer at a time: flock where there is one; on Windows, msvcrt's
    lock on the log's first byte. LK_LOCK itself retries for about ten
    seconds; past that, the log is busy and nothing is written."""
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)
    elif msvcrt is not None:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except OSError as e:
            raise PruneLogBusy(f"The prune log at {f.name} is held by another writer; nothing was written.") from e

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def append(path: Path, kind: str, who: str, **fields) -> dict:
    """One row on the log, under a lock, fsynced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        _lock(f)
        # The true tail, read under the lock and through the handle that holds
        # it: a Windows lock is mandatory, and a second handle may not read
        # the locked byte. Writes in append mode still go to the end.
        f.seek(0)
        rows, breaks, committed = _parse(f.read(), path)
        if breaks:
            raise PruneLogBroken(f"The prune log at {path} does not chain ({'; '.join(breaks)}).")
        if committed < f.tell():
            f.truncate(committed)   # an unfinished write, dropped
        row = {"n": len(rows), "kind": kind, "who": who, "at": fields.pop("at", None) or now(), **fields}
        row["prev"] = rows[-1]["hash"] if rows else GENESIS
        row["hash"] = _h256(canon(row))
        f.write((canon(row) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    return row
