"""SQLite-backed storage for episodic vaults.

Episodic memory is bi-temporal. Every episode carries the window in which the
statement holds in the world (`valid_from` / `valid_to`) and the window in which
this vault believed it (`recorded_at` / `invalidated_at`). The two move
independently: learning today that something stopped being true last month
closes the valid window in the past while the transaction window closes now.

Nothing is ever deleted. Superseding an episode closes it and links it to its
successor, so what the vault believed, and when, stays reconstructable.

Structured filtering lives here; ranking (similarity, recency, salience) lives
in the vault layer, which is the only place that knows about embeddings.

Timestamps are stored and compared as ISO-8601 strings, which only orders
correctly when they share an offset: everything written by this module is UTC,
and callers passing their own timestamps should be too.
"""

import array
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ctxvault.core.exceptions import EpisodeAlreadyClosedError, EpisodeNotFoundError, SchemaVersionError

SCHEMA_VERSION = 1

# A connection is reused per database file: SQLite serialises writers itself,
# and the vault is a single-process store. check_same_thread is off because the
# HTTP and MCP servers hand requests to worker threads; _write_lock keeps the
# multi-statement operations (supersede) atomic across those threads.
_connections: dict[str, sqlite3.Connection] = {}
_write_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    source          TEXT,
    confidence      REAL NOT NULL DEFAULT 1.0,
    salience        REAL NOT NULL DEFAULT 0.5,
    occurred_at     TEXT,
    valid_from      TEXT NOT NULL,
    valid_to        TEXT,
    recorded_at     TEXT NOT NULL,
    invalidated_at  TEXT,
    superseded_by   TEXT REFERENCES episodes(id),
    recall_count    INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    embedding       BLOB
);

CREATE INDEX IF NOT EXISTS idx_episodes_valid      ON episodes(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_episodes_recorded   ON episodes(recorded_at, invalidated_at);
CREATE INDEX IF NOT EXISTS idx_episodes_supersedes ON episodes(superseded_by);
CREATE INDEX IF NOT EXISTS idx_episodes_source     ON episodes(source);

CREATE TABLE IF NOT EXISTS episode_entities (
    episode_id  TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    entity      TEXT NOT NULL,
    entity_norm TEXT NOT NULL,
    PRIMARY KEY (episode_id, entity_norm)
);

CREATE INDEX IF NOT EXISTS idx_entities_norm ON episode_entities(entity_norm);
"""

# from_version -> list of statements taking the file to from_version + 1.
# Empty while the schema is at its first version; every future change appends
# one entry here instead of editing _SCHEMA.
_MIGRATIONS: dict[int, list[str]] = {}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def new_episode_id() -> str:
    return uuid.uuid4().hex

def encode_embedding(vector: list[float] | None) -> bytes | None:
    if vector is None:
        return None
    return array.array("f", vector).tobytes()

def decode_embedding(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    vector = array.array("f")
    vector.frombytes(blob)
    return vector.tolist()

def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        return

    version = int(row["value"])

    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"This episodic vault was written by a newer ctxvault (schema v{version}, "
            f"this version understands up to v{SCHEMA_VERSION}). Upgrade ctxvault to open it."
        )

    while version < SCHEMA_VERSION:
        for statement in _MIGRATIONS.get(version, []):
            conn.execute(statement)
        version += 1
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))

    conn.commit()

def get_connection(config: dict) -> sqlite3.Connection:
    db_path = config.get("db_path")
    if not db_path:
        raise ValueError("Episodic vault config has no db_path.")

    key = str(db_path)
    conn = _connections.get(key)
    if conn is not None:
        return conn

    with _write_lock:
        conn = _connections.get(key)
        if conn is not None:
            return conn

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            _apply_schema(conn)
        except Exception:
            # A store this version cannot open must not leave a handle behind,
            # or the next attempt inherits a half-open connection.
            conn.close()
            raise

        _connections[key] = conn
        return conn

def close_connections() -> None:
    """Close every cached connection. Used by tests and by vault deletion."""
    with _write_lock:
        for conn in _connections.values():
            conn.close()
        _connections.clear()

def _row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row, with_embedding: bool = False) -> dict:
    data = {
        "id": row["id"],
        "content": row["content"],
        "source": row["source"],
        "confidence": row["confidence"],
        "salience": row["salience"],
        "occurred_at": row["occurred_at"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "recorded_at": row["recorded_at"],
        "invalidated_at": row["invalidated_at"],
        "superseded_by": row["superseded_by"],
        "recall_count": row["recall_count"],
        "last_recalled_at": row["last_recalled_at"],
        "metadata": json.loads(row["metadata"] or "{}"),
        "entities": _get_entities(conn, row["id"]),
    }
    if with_embedding:
        data["embedding"] = decode_embedding(row["embedding"])
    return data

def _get_entities(conn: sqlite3.Connection, episode_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT entity FROM episode_entities WHERE episode_id = ? ORDER BY entity",
        (episode_id,),
    ).fetchall()
    return [r["entity"] for r in rows]

def _insert(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    content: str,
    entities: list[str],
    source: str | None,
    confidence: float,
    salience: float,
    occurred_at: str | None,
    valid_from: str,
    valid_to: str | None,
    recorded_at: str,
    metadata: dict,
    embedding: list[float] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO episodes (
            id, content, source, confidence, salience, occurred_at,
            valid_from, valid_to, recorded_at, metadata, embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            episode_id, content, source, confidence, salience, occurred_at,
            valid_from, valid_to, recorded_at, json.dumps(metadata), encode_embedding(embedding),
        ),
    )

    for entity in dict.fromkeys(e.strip() for e in entities if e and e.strip()):
        conn.execute(
            "INSERT OR IGNORE INTO episode_entities (episode_id, entity, entity_norm) VALUES (?, ?, ?)",
            (episode_id, entity, entity.casefold()),
        )

def write_episode(
    config: dict,
    *,
    content: str,
    entities: list[str] | None = None,
    source: str | None = None,
    confidence: float = 1.0,
    salience: float = 0.5,
    occurred_at: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    metadata: dict | None = None,
    embedding: list[float] | None = None,
) -> dict:
    conn = get_connection(config)
    recorded_at = now_iso()
    episode_id = new_episode_id()

    with _write_lock, conn:
        _insert(
            conn,
            episode_id=episode_id,
            content=content,
            entities=entities or [],
            source=source,
            confidence=confidence,
            salience=salience,
            occurred_at=occurred_at,
            # An episode is valid from when it happened unless told otherwise;
            # falling back to ingestion time keeps the column non-null.
            valid_from=valid_from or occurred_at or recorded_at,
            valid_to=valid_to,
            recorded_at=recorded_at,
            metadata=metadata or {},
            embedding=embedding,
        )

    return get_episode(config, episode_id)

def get_episode(config: dict, episode_id: str, with_embedding: bool = False) -> dict:
    conn = get_connection(config)
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
    return _row_to_dict(conn, row, with_embedding=with_embedding)

def _check_boundary(row: sqlite3.Row, boundary: str, field: str) -> None:
    """An episode cannot stop holding before it starts.

    Closing an episode at an instant earlier than its own valid_from would leave
    a window that is true at no point in time: the episode would simply vanish
    from every query without any error ever being raised.
    """
    if boundary < row["valid_from"]:
        raise ValueError(
            f"{field} {boundary!r} is before the episode's valid_from {row['valid_from']!r}: "
            "an episode cannot stop holding before it starts."
        )

def invalidate_episode(
    config: dict,
    episode_id: str,
    *,
    valid_to: str | None = None,
    reason: str | None = None,
) -> dict:
    conn = get_connection(config)

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is not None:
            raise EpisodeAlreadyClosedError(
                f"Episode '{episode_id}' was already closed at {row['invalidated_at']}."
            )

        now = now_iso()
        _check_boundary(row, valid_to or now, "valid_to")

        metadata = json.loads(row["metadata"] or "{}")
        if reason:
            metadata["invalidation_reason"] = reason

        conn.execute(
            "UPDATE episodes SET valid_to = ?, invalidated_at = ?, metadata = ? WHERE id = ?",
            (valid_to or now, now, json.dumps(metadata), episode_id),
        )

    return get_episode(config, episode_id)

def supersede_episode(
    config: dict,
    episode_id: str,
    *,
    content: str,
    entities: list[str] | None = None,
    source: str | None = None,
    confidence: float = 1.0,
    salience: float | None = None,
    occurred_at: str | None = None,
    valid_from: str | None = None,
    metadata: dict | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Close an episode and open its successor in one transaction.

    The old episode's validity ends exactly where the new one begins, so a query
    at any instant sees one of the two and never both or neither.

    `entities` and `salience` are inherited from the predecessor when the caller
    leaves them out: a correction is usually about the same thing, and dropping
    the entity links would make the current version unreachable by the lookup
    that found the old one. Pass an explicit empty list to clear them.
    """
    conn = get_connection(config)
    new_id = new_episode_id()
    recorded_at = now_iso()

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is not None:
            raise EpisodeAlreadyClosedError(
                f"Episode '{episode_id}' was already closed at {row['invalidated_at']}; "
                "supersede its successor instead."
            )

        boundary = valid_from or occurred_at or recorded_at
        _check_boundary(row, boundary, "valid_from")

        _insert(
            conn,
            episode_id=new_id,
            content=content,
            entities=_get_entities(conn, episode_id) if entities is None else entities,
            source=source,
            confidence=confidence,
            # Carry the predecessor's salience unless the caller sets one: a
            # correction is usually about the same thing, and as important.
            salience=row["salience"] if salience is None else salience,
            occurred_at=occurred_at,
            valid_from=boundary,
            valid_to=None,
            recorded_at=recorded_at,
            metadata=metadata or {},
            embedding=embedding,
        )

        conn.execute(
            "UPDATE episodes SET valid_to = ?, invalidated_at = ?, superseded_by = ? WHERE id = ?",
            (boundary, recorded_at, new_id, episode_id),
        )

    return get_episode(config, new_id)

def mark_recalled(config: dict, episode_ids: list[str]) -> None:
    """Reinforce episodes that were actually used, so decay can favour them."""
    if not episode_ids:
        return

    conn = get_connection(config)
    now = now_iso()

    with _write_lock, conn:
        conn.executemany(
            "UPDATE episodes SET recall_count = recall_count + 1, last_recalled_at = ? WHERE id = ?",
            [(now, episode_id) for episode_id in episode_ids],
        )

def history(config: dict, episode_id: str) -> list[dict]:
    """Return the whole supersession chain the episode belongs to, oldest first."""
    conn = get_connection(config)

    if conn.execute("SELECT 1 FROM episodes WHERE id = ?", (episode_id,)).fetchone() is None:
        raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")

    # Walk back to the head of the chain, then forward from it. The `seen` set
    # is belt and braces: the writers never build a cycle, but a hand-edited
    # database should not hang the process.
    head = episode_id
    seen = {head}
    while True:
        row = conn.execute("SELECT id FROM episodes WHERE superseded_by = ?", (head,)).fetchone()
        if row is None or row["id"] in seen:
            break
        head = row["id"]
        seen.add(head)

    chain: list[dict] = []
    visited: set[str] = set()
    current: str | None = head
    while current is not None and current not in visited:
        visited.add(current)
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (current,)).fetchone()
        if row is None:
            break
        chain.append(_row_to_dict(conn, row))
        current = row["superseded_by"]

    return chain

def select_episodes(
    config: dict,
    *,
    entities: list[str] | None = None,
    source: str | None = None,
    min_confidence: float | None = None,
    valid_at: str | None = None,
    known_at: str | None = None,
    include_closed: bool = False,
    metadata_filters: dict | None = None,
    scan_limit: int = 5000,
) -> list[dict]:
    """Structured retrieval: the primary path into an episodic vault.

    `valid_at` filters on what is true in the world at that instant, `known_at`
    on what the vault had already recorded then. Passing both reconstructs the
    belief state of a past moment. With `include_closed` the time filters are
    dropped and the full history comes back.
    """
    conn = get_connection(config)

    clauses = []
    params: list = []

    if not include_closed:
        instant = valid_at or now_iso()
        clauses.append("valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)")
        params.extend([instant, instant])
    elif valid_at:
        clauses.append("valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)")
        params.extend([valid_at, valid_at])

    if known_at:
        clauses.append("recorded_at <= ? AND (invalidated_at IS NULL OR invalidated_at > ?)")
        params.extend([known_at, known_at])

    if source:
        clauses.append("source = ?")
        params.append(source)

    if min_confidence is not None:
        clauses.append("confidence >= ?")
        params.append(min_confidence)

    if entities:
        normalised = [e.casefold() for e in entities if e and e.strip()]
        if normalised:
            placeholders = ", ".join("?" for _ in normalised)
            clauses.append(
                f"id IN (SELECT episode_id FROM episode_entities WHERE entity_norm IN ({placeholders}))"
            )
            params.extend(normalised)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM episodes {where} ORDER BY valid_from DESC LIMIT ?",
        (*params, scan_limit),
    ).fetchall()

    episodes = [_row_to_dict(conn, row, with_embedding=True) for row in rows]

    # Metadata lives in a JSON blob rather than columns, so it is filtered here
    # instead of in SQL: the structured clauses above have already cut the set
    # down to something small.
    if metadata_filters:
        episodes = [
            episode for episode in episodes
            if all(episode["metadata"].get(key) == value for key, value in metadata_filters.items())
        ]

    return episodes

def count_episodes(config: dict) -> dict:
    conn = get_connection(config)
    total = conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()["n"]
    open_now = conn.execute(
        "SELECT COUNT(*) AS n FROM episodes WHERE valid_to IS NULL AND invalidated_at IS NULL"
    ).fetchone()["n"]
    return {"total": total, "open": open_now, "closed": total - open_now}
