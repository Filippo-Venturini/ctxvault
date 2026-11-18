"""The prune log: an append-only record of what pruning archived, restored and purged.

Rows are never rewritten. An entry's state (archived, restored, purged) is
read from the rows that follow it, so the log is also the history of every
document pruning touched. Each row carries the hash of the one before it: a
log that was edited, cut short or reordered no longer chains, and pruning
refuses to act on it until a person has looked. Repairing it is never this
code's job.
"""

import hashlib
import json
import os
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
    data = path.read_bytes().decode("utf-8")
    if data and not data.endswith("\n"):
        return [], ["torn tail: the last line is unterminated"]
    rows, breaks, prev = [], [], GENESIS
    # "\n" only: str.splitlines() would also cut at U+2028 inside a file name
    lines = data.split("\n")[:-1] if data else []
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
    return rows, breaks

def rows_or_refuse(path: Path) -> list[dict]:
    rows, breaks = read(path)
    if breaks:
        raise PruneLogBroken(f"The prune log at {path} does not chain ({'; '.join(breaks)}). "
                             "Nothing was changed; look at the file before pruning again.")
    return rows

def _lock(f) -> None:
    """One writer at a time: flock where there is one; on Windows, msvcrt's
    lock on the log's first byte, tried until it is free."""
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)
    elif msvcrt is not None:
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                continue

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def append(path: Path, kind: str, who: str, **fields) -> dict:
    """One row on the log, under a lock, fsynced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8", newline="") as f:
        _lock(f)
        rows, breaks = read(path)  # the true tail, read under the lock
        if breaks:
            raise PruneLogBroken(f"The prune log at {path} does not chain ({'; '.join(breaks)}).")
        row = {"n": len(rows), "kind": kind, "who": who, "at": fields.pop("at", None) or now(), **fields}
        row["prev"] = rows[-1]["hash"] if rows else GENESIS
        row["hash"] = _h256(canon(row))
        f.write(canon(row) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return row
