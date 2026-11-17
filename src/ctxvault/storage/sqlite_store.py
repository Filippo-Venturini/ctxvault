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

Closes are stored as intervals in `episode_closures`, and the `episodes` row
is a cache of the current state. A query as of a past `known_at` filters on
those intervals in SQL so a `scan_limit` cannot drop rows that only fail a
later Python check. Metadata is always read from the row, never reconstructed.

A vault migrated from schema v3 gets one closure per already-closed row.
The valid window that was on the row before that close was overwritten and
is not recoverable, so `prior_valid_to` is stored as NULL. Reopening such
a legacy close therefore cannot restore a written-in `valid_to`.

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

from ctxvault.core.exceptions import EpisodeAlreadyClosedError, EpisodeAlreadyOpenError, EpisodeNotFoundError, EpisodeSuccessorStillOpenError, EpisodeWasRevisedError, SchemaVersionError

SCHEMA_VERSION = 4

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
    revised_by      TEXT REFERENCES episodes(id),
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

-- One row per time a statement was asserted again. Kept as events rather
-- than a counter so that how well a statement was attested at any past
-- instant stays reconstructable, like everything else here.
CREATE TABLE IF NOT EXISTS episode_attestations (
    episode_id  TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    source      TEXT
);

CREATE INDEX IF NOT EXISTS idx_attestations_episode ON episode_attestations(episode_id, at);

-- Two open statements that cannot both hold, noticed but not settled. A
-- dispute has no state of its own: it is open while both episodes are, and
-- closing either one (invalidate, supersede) is what resolves it.
CREATE TABLE IF NOT EXISTS episode_disputes (
    episode_a   TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    episode_b   TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    noticed_at  TEXT NOT NULL,
    note        TEXT,
    PRIMARY KEY (episode_a, episode_b)
);

CREATE INDEX IF NOT EXISTS idx_disputes_b ON episode_disputes(episode_b);

-- One row per close. The episodes table is a cache of the current state;
-- a query as of a past instant uses these intervals to see whether the
-- statement was closed then. Reopening sets reopened_at on the latest
-- closure and restores prior_valid_to on the row, so the close stays
-- reconstructable. reason is why it was closed; reopen_reason is why
-- it was later reopened, when it was.
--
-- Vaults migrated from v3 backfill one closure per already-closed row
-- with prior_valid_to NULL: that earlier end was overwritten on the
-- row and is not recoverable.
CREATE TABLE IF NOT EXISTS episode_closures (
    episode_id     TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    closed_at      TEXT NOT NULL,
    valid_to       TEXT,
    prior_valid_to TEXT,
    superseded_by  TEXT REFERENCES episodes(id),
    revised_by     TEXT REFERENCES episodes(id),
    reason         TEXT,
    reopened_at    TEXT,
    reopen_reason  TEXT,
    PRIMARY KEY (episode_id, closed_at)
);

CREATE INDEX IF NOT EXISTS idx_closures_episode ON episode_closures(episode_id, closed_at);
"""

# from_version -> list of statements taking the file to from_version + 1.
# Every schema change appends one entry here as well as editing _SCHEMA: the
# latter is what a new file gets, the former is what an existing file needs.
# A change that only adds tables needs no statements of its own, because
# _SCHEMA runs on every open with IF NOT EXISTS; the version still moves so an
# older ctxvault refuses the file instead of ignoring what it cannot see.
_MIGRATIONS: dict[int, list[str]] = {
    1: [],   # v2: episode_attestations and episode_disputes, created by _SCHEMA
    2: [     # v3: a statement can be revised, not only superseded
        "ALTER TABLE episodes ADD COLUMN revised_by TEXT REFERENCES episodes(id)",
    ],
    3: [   # v4: episode_closures is created by _SCHEMA; backfill one row per already-closed episode
        """
        INSERT INTO episode_closures (
            episode_id, closed_at, valid_to, prior_valid_to,
            superseded_by, revised_by, reason, reopened_at, reopen_reason
        )
        SELECT
            id, invalidated_at, valid_to, NULL,
            superseded_by, revised_by,
            json_extract(metadata, '$.invalidation_reason'),
            NULL, NULL
        FROM episodes
        WHERE invalidated_at IS NOT NULL
        """,
    ]
}

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

# Indexes on columns added by a migration cannot sit in _SCHEMA: on an old
# file the CREATE TABLE IF NOT EXISTS leaves the table as it was, and the
# index would name a column that is not there yet. Created after migrating.
_LATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_episodes_revised ON episodes(revised_by)",
]

def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        for statement in _LATE_INDEXES:
            conn.execute(statement)
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

    for statement in _LATE_INDEXES:
        conn.execute(statement)
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

def _attestation_summary(conn: sqlite3.Connection, episode_id: str,
                         known_at: str | None = None) -> tuple[int, str | None]:
    """How many times, and when last, the statement was asserted again.

    With `known_at` only the attestations recorded by then count, so a
    belief's standing at a past instant reads the way it stood then.
    """
    clause, params = "", [episode_id]
    if known_at:
        clause, params = " AND at <= ?", [episode_id, known_at]
    row = conn.execute(
        f"SELECT COUNT(*) AS n, MAX(at) AS last FROM episode_attestations "
        f"WHERE episode_id = ?{clause}",
        params,
    ).fetchone()
    return row["n"], row["last"]

def _covering_closure(
    conn: sqlite3.Connection, episode_id: str, known_at: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM episode_closures
        WHERE episode_id = ?
          AND closed_at <= ?
          AND (reopened_at IS NULL OR reopened_at > ?)
        ORDER BY closed_at DESC
        LIMIT 1
        """,
        (episode_id, known_at, known_at),
    ).fetchone()

def _next_closure(
    conn: sqlite3.Connection, episode_id: str, known_at: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM episode_closures
        WHERE episode_id = ? AND closed_at > ?
        ORDER BY closed_at ASC
        LIMIT 1
        """,
        (episode_id, known_at),
    ).fetchone()

def _last_reopen(
    conn: sqlite3.Connection, episode_id: str, known_at: str | None = None
) -> sqlite3.Row | None:
    if known_at:
        return conn.execute(
            """
            SELECT reopened_at, reopen_reason FROM episode_closures
            WHERE episode_id = ?
              AND reopened_at IS NOT NULL
              AND reopened_at <= ?
            ORDER BY reopened_at DESC
            LIMIT 1
            """,
            (episode_id, known_at),
        ).fetchone()
    return conn.execute(
        """
        SELECT reopened_at, reopen_reason FROM episode_closures
        WHERE episode_id = ? AND reopened_at IS NOT NULL
        ORDER BY reopened_at DESC
        LIMIT 1
        """,
        (episode_id,),
    ).fetchone()

def _insert_closure(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    closed_at: str,
    valid_to: str | None,
    superseded_by: str | None = None,
    revised_by: str | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO episode_closures (
            episode_id, closed_at, valid_to, prior_valid_to,
            superseded_by, revised_by, reason, reopened_at, reopen_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            row["id"],
            closed_at,
            valid_to,
            row["valid_to"],
            superseded_by,
            revised_by,
            reason,
        ),
    )

def _covering_clause(alias: str, known_at: str) -> tuple[str, list]:
    sql = (
        f"EXISTS (SELECT 1 FROM episode_closures c "
        f"WHERE c.episode_id = {alias}.id AND c.closed_at <= ? "
        f"AND (c.reopened_at IS NULL OR c.reopened_at > ?))"
    )
    return sql, [known_at, known_at]

def _retracted_clause(alias: str, known_at: str) -> tuple[str, list]:
    sql = (
        f"EXISTS (SELECT 1 FROM episode_closures c "
        f"WHERE c.episode_id = {alias}.id AND c.revised_by IS NOT NULL "
        f"AND c.closed_at <= ? AND (c.reopened_at IS NULL OR c.reopened_at > ?))"
    )
    return sql, [known_at, known_at]

def _as_of_valid_to_sql(alias: str, known_at: str) -> tuple[str, list]:
    """Valid_to as of known_at: the covering close's end, else the
    prior_valid_to of the next later close, else the current row."""
    sql = f"""(
      CASE
        WHEN EXISTS (
          SELECT 1 FROM episode_closures c
          WHERE c.episode_id = {alias}.id
            AND c.closed_at <= ?
            AND (c.reopened_at IS NULL OR c.reopened_at > ?)
        ) THEN (
          SELECT c.valid_to FROM episode_closures c
          WHERE c.episode_id = {alias}.id
            AND c.closed_at <= ?
            AND (c.reopened_at IS NULL OR c.reopened_at > ?)
          ORDER BY c.closed_at DESC LIMIT 1
        )
        WHEN EXISTS (
          SELECT 1 FROM episode_closures c
          WHERE c.episode_id = {alias}.id AND c.closed_at > ?
        ) THEN (
          SELECT c.prior_valid_to FROM episode_closures c
          WHERE c.episode_id = {alias}.id AND c.closed_at > ?
          ORDER BY c.closed_at ASC LIMIT 1
        )
        ELSE {alias}.valid_to
      END
    )"""
    return sql, [known_at] * 6

def _lifecycle_as_of(
    conn: sqlite3.Connection, row: sqlite3.Row, known_at: str | None = None
) -> dict:
    """Transaction-time fields as they stood at `known_at`, or now.

    Metadata always comes from the current row: it is not reconstructed
    from a past close. When `known_at` is covered by a closure, the
    close's valid_to and successor links are the ones that held then;
    otherwise the statement was open and valid_to is the prior end
    (or the row, if no later close is on file).
    """
    metadata = json.loads(row["metadata"] or "{}")
    last = _last_reopen(conn, row["id"], known_at)
    reopened_at = last["reopened_at"] if last else None
    reopen_reason = last["reopen_reason"] if last else None

    if known_at is None:
        return {
            "valid_to": row["valid_to"],
            "invalidated_at": row["invalidated_at"],
            "superseded_by": row["superseded_by"],
            "revised_by": row["revised_by"],
            "metadata": metadata,
            "reopened_at": reopened_at,
            "reopen_reason": reopen_reason,
        }

    covering = _covering_closure(conn, row["id"], known_at)
    if covering is not None:
        return {
            "valid_to": covering["valid_to"],
            "invalidated_at": covering["closed_at"],
            "superseded_by": covering["superseded_by"],
            "revised_by": covering["revised_by"],
            "metadata": metadata,
            "reopened_at": reopened_at,
            "reopen_reason": reopen_reason,
        }

    nxt = _next_closure(conn, row["id"], known_at)
    return {
        "valid_to": nxt["prior_valid_to"] if nxt is not None else row["valid_to"],
        "invalidated_at": None,
        "superseded_by": None,
        "revised_by": None,
        "metadata": metadata,
        "reopened_at": reopened_at,
        "reopen_reason": reopen_reason,
    }


def _successor_id(conn: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    if row["superseded_by"] or row["revised_by"]:
        return row["superseded_by"] or row["revised_by"]
    event = conn.execute(
        """
        SELECT superseded_by, revised_by FROM episode_closures
        WHERE episode_id = ?
          AND (superseded_by IS NOT NULL OR revised_by IS NOT NULL)
        ORDER BY closed_at DESC
        LIMIT 1
        """,
        (row["id"],),
    ).fetchone()
    if event is None:
        return None
    return event["superseded_by"] or event["revised_by"]


def _predecessor_id(conn: sqlite3.Connection, episode_id: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM episodes WHERE superseded_by = ? OR revised_by = ?",
        (episode_id, episode_id),
    ).fetchone()
    if row is not None:
        return row["id"]
    event = conn.execute(
        """
        SELECT episode_id FROM episode_closures
        WHERE superseded_by = ? OR revised_by = ?
        ORDER BY closed_at DESC
        LIMIT 1
        """,
        (episode_id, episode_id),
    ).fetchone()
    return event["episode_id"] if event is not None else None


def _open_successor_id(conn: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    """The first still-current successor in the chain, if any."""
    seen: set[str] = set()
    current = _successor_id(conn, row)
    while current is not None and current not in seen:
        seen.add(current)
        successor = conn.execute("SELECT * FROM episodes WHERE id = ?", (current,)).fetchone()
        if successor is None:
            return None
        if successor["invalidated_at"] is None:
            return current
        current = _successor_id(conn, successor)
    return None


def _open_disputes(
    conn: sqlite3.Connection, episode_id: str, known_at: str | None = None
) -> list[str]:
    """The open episodes this one is in dispute with.

    A dispute counts only while its other side is still open: once that
    episode is closed the question is settled and the flag goes with it. With
    `known_at` both the noticing and the other side's state are read as of
    that instant: recorded, not revised away, and not ended as far as the
    vault knew by then. A later reopen of the other side is ignored when
    reading an instant before it happened.
    """
    instant = known_at or now_iso()
    retracted, retracted_params = _retracted_clause("o", instant)
    covering, covering_params = _covering_clause("o", instant)
    as_of_to, as_of_params = _as_of_valid_to_sql("o", instant)
    rows = conn.execute(
        f"""
        SELECT CASE WHEN d.episode_a = ? THEN d.episode_b ELSE d.episode_a END AS other
        FROM episode_disputes d
        JOIN episodes o
          ON o.id = CASE WHEN d.episode_a = ? THEN d.episode_b ELSE d.episode_a END
        WHERE (d.episode_a = ? OR d.episode_b = ?)
          AND d.noticed_at <= ?
          AND o.recorded_at <= ?
          AND NOT ({retracted})
          AND NOT ({covering})
          AND ({as_of_to} IS NULL OR {as_of_to} > ?)
        ORDER BY d.noticed_at
        """,
        (
            episode_id, episode_id, episode_id, episode_id, instant, instant,
            *retracted_params,
            *covering_params,
            *as_of_params, *as_of_params,
            instant,
        ),
    ).fetchall()
    return [item["other"] for item in rows]


def _row_to_dict(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    with_embedding: bool = False,
    known_at: str | None = None,
) -> dict:
    confirmed_count, last_confirmed_at = _attestation_summary(conn, row["id"], known_at)
    state = _lifecycle_as_of(conn, row, known_at=known_at)
    data = {
        "id": row["id"],
        "content": row["content"],
        "source": row["source"],
        "confidence": row["confidence"],
        "salience": row["salience"],
        "occurred_at": row["occurred_at"],
        "valid_from": row["valid_from"],
        "valid_to": state["valid_to"],
        "recorded_at": row["recorded_at"],
        "invalidated_at": state["invalidated_at"],
        "superseded_by": state["superseded_by"],
        "revised_by": state["revised_by"],
        "reopened_at": state["reopened_at"],
        "reopen_reason": state["reopen_reason"],
        "recall_count": row["recall_count"],
        "last_recalled_at": row["last_recalled_at"],
        "confirmed_count": confirmed_count,
        "last_confirmed_at": last_confirmed_at,
        "disputed_with": _open_disputes(conn, row["id"], known_at),
        "metadata": state["metadata"],
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
    recorded_at: str | None = None,
) -> dict:
    """`recorded_at` is when the vault learned this, for callers replaying
    the past (an import, a demo); it defaults to now."""
    conn = get_connection(config)
    recorded_at = recorded_at or now_iso()
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

def _check_close_after_reopen(conn: sqlite3.Connection, episode_id: str, closed_at: str) -> None:
    """A close recorded before the latest reopen would overlap intervals."""
    latest = conn.execute(
        """
        SELECT reopened_at FROM episode_closures
        WHERE episode_id = ? AND reopened_at IS NOT NULL
        ORDER BY reopened_at DESC
        LIMIT 1
        """,
        (episode_id,),
    ).fetchone()
    if latest is not None and closed_at < latest["reopened_at"]:
        raise ValueError(
            f"at {closed_at!r} is before the episode's latest reopen at {latest['reopened_at']!r}: "
            "an episode cannot be closed before it was reopened."
        )

def invalidate_episode(
    config: dict,
    episode_id: str,
    *,
    valid_to: str | None = None,
    reason: str | None = None,
    at: str | None = None,
) -> dict:
    """`at` is when the closing was recorded, for callers replaying the
    past; it defaults to now. `valid_to` is when the statement stopped
    holding in the world and defaults to the same instant."""
    conn = get_connection(config)

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is not None:
            raise EpisodeAlreadyClosedError(
                f"Episode '{episode_id}' was already closed at {row['invalidated_at']}."
            )

        now = at or now_iso()
        _check_close_after_reopen(conn, episode_id, now)
        _check_boundary(row, valid_to or now, "valid_to")

        metadata = json.loads(row["metadata"] or "{}")
        if reason:
            metadata["invalidation_reason"] = reason

        end = valid_to or now
        # The closure is the source of truth for this close; invalidation_reason
        # stays on the row so older readers still see it.
        _insert_closure(conn, row, closed_at=now, valid_to=end, reason=reason)
        conn.execute(
            "UPDATE episodes SET valid_to = ?, invalidated_at = ?, metadata = ? WHERE id = ?",
            (end, now, json.dumps(metadata), episode_id),
        )

    return get_episode(config, episode_id)

def reopen_episode(
    config: dict,
    episode_id: str,
    *,
    at: str | None = None,
    reason: str | None = None,
) -> dict:
    """Make a closed episode current again, without erasing the close.

    The close stays in `episode_closures`: reopening sets `reopened_at` on
    the latest closure and restores `prior_valid_to` on the current row, so
    a query as of an instant between the close and the reopen still sees
    the episode as closed. `at` is when the reopen was recorded, for
    callers replaying the past; it defaults to now and cannot precede the
    close.

    A revised original cannot be reopened: attestations and disputes
    already moved to the revision, and that is the statement to reopen
    (or close) instead. If the episode was superseded, the successor (or a
    later still-current one in the same chain) must already be closed.
    The reopen does not close a successor by itself: two current
    statements in one chain would leave a query at "now" seeing both.
    """
    conn = get_connection(config)

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is None:
            raise EpisodeAlreadyOpenError(
                f"Episode '{episode_id}' is already current; there is nothing to reopen."
            )

        latest = conn.execute(
            """
            SELECT * FROM episode_closures
            WHERE episode_id = ?
            ORDER BY closed_at DESC
            LIMIT 1
            """,
            (episode_id,),
        ).fetchone()
        revision_id = (latest["revised_by"] if latest is not None else None) or row["revised_by"]
        if revision_id:
            raise EpisodeWasRevisedError(episode_id, revision_id)

        moment = at or now_iso()
        closed_at = latest["closed_at"] if latest is not None else row["invalidated_at"]
        if moment < closed_at:
            raise ValueError(
                f"at {moment!r} is before the episode's close at {closed_at!r}: "
                "an episode cannot be reopened before it was closed."
            )

        open_successor = _open_successor_id(conn, row)
        if open_successor is not None:
            raise EpisodeSuccessorStillOpenError(episode_id, open_successor)

        closed_metadata = json.loads(row["metadata"] or "{}")
        open_metadata = {
            key: value for key, value in closed_metadata.items() if key != "invalidation_reason"
        }
        # Restore the valid window that was on the row before this close.
        # A legacy backfilled closure has prior_valid_to NULL because that
        # earlier end was not kept.
        prior_valid_to = latest["prior_valid_to"] if latest is not None else None

        if latest is not None:
            conn.execute(
                """
                UPDATE episode_closures
                SET reopened_at = ?, reopen_reason = ?
                WHERE episode_id = ? AND closed_at = ?
                """,
                (moment, reason, episode_id, latest["closed_at"]),
            )
        # Clear the close on the current cache so default queries see it as
        # open. Successor links go with it: history() follows them through
        # episode_closures instead, and current queries must not hide a
        # reopened original behind a cleared revised_by.
        conn.execute(
            """
            UPDATE episodes
            SET valid_to = ?, invalidated_at = NULL, superseded_by = NULL,
                revised_by = NULL, metadata = ?
            WHERE id = ?
            """,
            (prior_valid_to, json.dumps(open_metadata), episode_id),
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
    at: str | None = None,
) -> dict:
    """Close an episode and open its successor in one transaction.

    The old episode's validity ends exactly where the new one begins, so a query
    at any instant sees one of the two and never both or neither.

    `entities` and `salience` are inherited from the predecessor when the caller
    leaves them out: a correction is usually about the same thing, and dropping
    the entity links would make the current version unreachable by the lookup
    that found the old one. Pass an explicit empty list to clear them.

    `at` is when the change was recorded, for callers replaying the past; it
    defaults to now.
    """
    conn = get_connection(config)
    new_id = new_episode_id()
    recorded_at = at or now_iso()

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is not None:
            raise EpisodeAlreadyClosedError(
                f"Episode '{episode_id}' was already closed at {row['invalidated_at']}; "
                "supersede its successor instead."
            )

        _check_close_after_reopen(conn, episode_id, recorded_at)
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

        _insert_closure(
            conn, row, closed_at=recorded_at, valid_to=boundary, superseded_by=new_id,
        )
        conn.execute(
            "UPDATE episodes SET valid_to = ?, invalidated_at = ?, superseded_by = ? WHERE id = ?",
            (boundary, recorded_at, new_id, episode_id),
        )

    return get_episode(config, new_id)

def revise_episode(
    config: dict,
    episode_id: str,
    *,
    content: str,
    entities: list[str] | None = None,
    source: str | None = None,
    confidence: float | None = None,
    salience: float | None = None,
    metadata: dict | None = None,
    embedding: list[float] | None = None,
    at: str | None = None,
) -> dict:
    """Restate an episode more precisely, keeping its identity in the world.

    A supersession says the world changed: the old statement stops holding
    where the new one starts. A revision says the statement was right and is
    now said better ("lives in Padova" -> "lives in Padova, in the Arcella"):
    nothing changes in valid time. So the revision opens where the original
    did, inherits what attested the original (those attestations attest the
    fact, not its wording) and the disputes still open against it, and the
    original is closed in transaction time only: it stays reconstructable
    at any `known_at` before the revision, and is never returned as what
    the vault states today.

    Entities, salience, confidence and metadata carry over unless given;
    metadata given is merged over the inherited one. `at` is when the
    revision was recorded, for callers replaying the past; it defaults to now.
    """
    conn = get_connection(config)
    new_id = new_episode_id()
    recorded_at = at or now_iso()

    with _write_lock, conn:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
        if row["invalidated_at"] is not None:
            raise EpisodeAlreadyClosedError(
                f"Episode '{episode_id}' was already closed at {row['invalidated_at']}; "
                "revise its successor instead."
            )
        _check_close_after_reopen(conn, episode_id, recorded_at)

        inherited = json.loads(row["metadata"] or "{}")
        inherited.update(metadata or {})
        inherited["revision_of"] = episode_id

        _insert(
            conn,
            episode_id=new_id,
            content=content,
            entities=_get_entities(conn, episode_id) if entities is None else entities,
            source=source if source is not None else row["source"],
            confidence=row["confidence"] if confidence is None else confidence,
            salience=row["salience"] if salience is None else salience,
            occurred_at=row["occurred_at"],
            valid_from=row["valid_from"],
            valid_to=None,
            recorded_at=recorded_at,
            metadata=inherited,
            embedding=embedding,
        )
        conn.execute(
            "INSERT INTO episode_attestations (episode_id, at, source) "
            "SELECT ?, at, source FROM episode_attestations WHERE episode_id = ?",
            (new_id, episode_id),
        )
        conn.execute("UPDATE episode_disputes SET episode_a = ? WHERE episode_a = ?", (new_id, episode_id))
        conn.execute("UPDATE episode_disputes SET episode_b = ? WHERE episode_b = ?", (new_id, episode_id))

        closed_meta = json.loads(row["metadata"] or "{}")
        closed_meta["invalidation_reason"] = "revised"
        # A revision does not change valid time; the closure records the
        # same valid_to the row already had (often None).
        _insert_closure(
            conn, row, closed_at=recorded_at, valid_to=row["valid_to"],
            revised_by=new_id, reason="revised",
        )
        conn.execute(
            "UPDATE episodes SET invalidated_at = ?, revised_by = ?, metadata = ? WHERE id = ?",
            (recorded_at, new_id, json.dumps(closed_meta), episode_id),
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

def _open_row(conn: sqlite3.Connection, episode_id: str, verb: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")
    if row["invalidated_at"] is not None:
        raise EpisodeAlreadyClosedError(
            f"Episode '{episode_id}' was closed at {row['invalidated_at']}; "
            f"a statement that no longer holds cannot be {verb}."
        )
    return row

def confirm_episode(
    config: dict,
    episode_id: str,
    *,
    at: str | None = None,
    source: str | None = None,
) -> dict:
    """Record that an open statement was asserted again.

    A fact someone keeps repeating is not a new fact and not a correction: it
    is the same statement, better attested. Writing it again would duplicate
    it, and superseding it would pretend something changed. This leaves the
    episode as it is and adds one attestation, so a caller can tell a claim
    heard once from one heard fifty times, and `known_at` can tell how well
    attested it was at any instant.

    `at` is when it was reasserted, for callers replaying the past; it
    defaults to now and cannot precede the statement's own start.
    """
    conn = get_connection(config)

    with _write_lock, conn:
        row = _open_row(conn, episode_id, "confirmed")

        moment = at or now_iso()
        if moment < row["valid_from"]:
            raise ValueError(
                f"at {moment!r} is before the episode's valid_from {row['valid_from']!r}: "
                "a statement cannot be confirmed before it starts holding."
            )

        conn.execute(
            "INSERT INTO episode_attestations (episode_id, at, source) VALUES (?, ?, ?)",
            (episode_id, moment, source),
        )

    return get_episode(config, episode_id)

def dispute_episodes(
    config: dict,
    episode_id: str,
    other_id: str,
    *,
    at: str | None = None,
    note: str | None = None,
) -> dict:
    """Record that two open statements cannot both hold, without picking one.

    Supersession says "this replaced that". A dispute says "one of these two
    is wrong and I do not know which": both stay open, both come back from
    queries, each flagged with the other in `disputed_with`. The flag is not
    stored, it is read: a dispute is open exactly while both episodes are, so
    resolving it is done with the primitives that already exist, by closing
    or superseding one side. Nothing here needs undoing.

    The pair is unordered and recording it twice is harmless.
    """
    if episode_id == other_id:
        raise ValueError("An episode cannot be in dispute with itself.")

    conn = get_connection(config)
    first, second = sorted((episode_id, other_id))

    with _write_lock, conn:
        _open_row(conn, episode_id, "disputed")
        _open_row(conn, other_id, "disputed")

        conn.execute(
            "INSERT OR IGNORE INTO episode_disputes (episode_a, episode_b, noticed_at, note) "
            "VALUES (?, ?, ?, ?)",
            (first, second, at or now_iso(), note),
        )

    return get_episode(config, episode_id)

def history(config: dict, episode_id: str) -> list[dict]:
    """Return the whole chain the episode belongs to, supersessions and
    revisions alike, oldest first."""
    conn = get_connection(config)

    if conn.execute("SELECT 1 FROM episodes WHERE id = ?", (episode_id,)).fetchone() is None:
        raise EpisodeNotFoundError(f"Episode '{episode_id}' not found.")

    # Walk back to the head of the chain, then forward from it. The `seen` set
    # is belt and braces: the writers never build a cycle, but a hand-edited
    # database should not hang the process. A reopen clears successor links
    # on the current row, so the walk also follows episode_closures.
    head = episode_id
    seen = {head}
    while True:
        predecessor = _predecessor_id(conn, head)
        if predecessor is None or predecessor in seen:
            break
        head = predecessor
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
        current = _successor_id(conn, row)

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
    disputed: bool | None = None,
    scan_limit: int | None = 5000,
) -> list[dict]:
    """Structured retrieval: the primary path into an episodic vault.

    `valid_at` filters on what is true in the world at that instant, `known_at`
    on what the vault had already recorded then. Passing both reconstructs the
    belief state of a past moment. With `include_closed` the time filters are
    dropped and the full history comes back. `disputed` keeps only the
    episodes that are (True) or are not (False) in an open dispute.
    `scan_limit` caps the rows read before ranking; None reads them all, for
    a caller that wants the whole vault rather than the best of it.
    """
    conn = get_connection(config)

    clauses = []
    params: list = []

    # The valid window at an instant, against the current row. As-of
    # queries use closure intervals instead, so a later close cannot hide
    # a row the vault still believed at known_at.
    def valid_window(instant: str) -> None:
        clauses.append("valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)")
        params.extend([instant, instant])

    if known_at:
        # recorded_at is immutable. Closed-or-open at this instant, and the
        # valid window as it stood then, are expressed as interval
        # predicates so scan_limit applies after the time filters.
        clauses.append("recorded_at <= ?")
        params.append(known_at)
        retracted, retracted_params = _retracted_clause("episodes", known_at)
        clauses.append(f"NOT ({retracted})")
        params.extend(retracted_params)
        if not include_closed or valid_at:
            # known_at alone is "recorded by then, that holds now";
            # pass valid_at to move the valid instant.
            instant = valid_at or now_iso()
            as_of_to, as_of_params = _as_of_valid_to_sql("episodes", known_at)
            clauses.append(
                f"valid_from <= ? AND ({as_of_to} IS NULL OR {as_of_to} > ?)"
            )
            params.append(instant)
            params.extend(as_of_params)
            params.extend(as_of_params)
            params.append(instant)
    elif not include_closed:
        valid_window(valid_at or now_iso())
        # A revised wording is still valid in the world, it is just no longer
        # how the vault states it: the revision is. Hidden unless the caller
        # asks for the full history or reconstructs a past belief state.
        clauses.append("revised_by IS NULL")
    elif valid_at:
        valid_window(valid_at)

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
    limit = "" if scan_limit is None else " LIMIT ?"
    rows = conn.execute(
        f"SELECT * FROM episodes {where} ORDER BY valid_from DESC{limit}",
        (*params, *([] if scan_limit is None else [scan_limit])),
    ).fetchall()

    episodes = [_row_to_dict(conn, row, with_embedding=True, known_at=known_at) for row in rows]

    # Metadata lives in a JSON blob rather than columns, so it is filtered here
    # instead of in SQL: the structured clauses above have already cut the set
    # down to something small. The dispute flag is derived per row for the
    # same reason.
    if metadata_filters:
        episodes = [
            episode for episode in episodes
            if all(episode["metadata"].get(key) == value for key, value in metadata_filters.items())
        ]

    if disputed is not None:
        episodes = [episode for episode in episodes if bool(episode["disputed_with"]) == disputed]

    return episodes

def list_entities(
    config: dict,
    *,
    include_closed: bool = False,
    valid_at: str | None = None,
    min_episodes: int = 1,
) -> list[dict]:
    """The vault's vocabulary: every entity it knows, with how often it occurs.

    This is the inventory counterpart of `select_episodes`. That one answers
    "which episodes mention X"; this one answers "which X exist at all", which
    a retrieval query cannot: retrieval ranks and truncates, so enumerating
    through it silently loses whatever falls past the limit. The entity index
    is read directly instead, so the answer stays complete however large the
    vault grows.

    Validity filtering mirrors `select_episodes`: by default only episodes that
    hold now are counted, `valid_at` moves that instant, and `include_closed`
    counts the whole history. An entity therefore disappears from the default
    listing once every episode naming it has been closed.

    Entities are grouped by normalised form. `entity` reports the first surface
    spelling in sort order, so repeated calls return the same answer.
    """
    conn = get_connection(config)

    clauses = []
    params: list = []

    if not include_closed:
        instant = valid_at or now_iso()
        clauses.append("ep.valid_from <= ? AND (ep.valid_to IS NULL OR ep.valid_to > ?)")
        params.extend([instant, instant])
    elif valid_at:
        clauses.append("ep.valid_from <= ? AND (ep.valid_to IS NULL OR ep.valid_to > ?)")
        params.extend([valid_at, valid_at])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT MIN(ee.entity)       AS entity,
               ee.entity_norm       AS entity_norm,
               COUNT(*)             AS episode_count,
               MAX(ep.recorded_at)  AS last_recorded_at
        FROM episode_entities ee
        JOIN episodes ep ON ep.id = ee.episode_id
        {where}
        GROUP BY ee.entity_norm
        HAVING COUNT(*) >= ?
        ORDER BY episode_count DESC, ee.entity_norm ASC
        """,
        (*params, max(1, min_episodes)),
    ).fetchall()

    return [dict(row) for row in rows]

# What the vault states as true at an instant: the default filter of
# `select_episodes`, as one SQL condition over the `episodes` table (aliased
# `e`). Started, not ended, and not restated by a revision.
_HOLDS_AT = "e.valid_from <= ? AND (e.valid_to IS NULL OR e.valid_to > ?) AND e.revised_by IS NULL"

def list_metadata_values(config: dict, key: str, *, include_closed: bool = False,
                         valid_at: str | None = None) -> list[dict]:
    """The distinct values one metadata key takes across the vault, most
    used first, with how many episodes carry each.

    The metadata counterpart of `list_entities`: whoever needs to enumerate a
    set the writers encoded as metadata (a category, a card, a channel) asks
    here instead of paging through a ranked query, or of bending `entities`
    to hold it. Validity filtering is the same: what holds now by default,
    `valid_at` moves the instant, `include_closed` counts the whole history.
    A value that is a list or an object comes back as its JSON text.
    """
    if '"' in key:
        raise ValueError("A metadata key cannot contain a double quote.")
    conn = get_connection(config)

    if not include_closed or valid_at:
        instant = valid_at or now_iso()
        where, params = f"WHERE {_HOLDS_AT}", [instant, instant]
    else:
        where, params = "", []

    rows = conn.execute(
        f"""
        SELECT value, COUNT(*) AS episode_count FROM (
            SELECT json_extract(e.metadata, ?) AS value FROM episodes e {where}
        )
        WHERE value IS NOT NULL
        GROUP BY value
        ORDER BY episode_count DESC, value ASC
        """,
        (f'$."{key}"', *params),
    ).fetchall()
    return [dict(row) for row in rows]

def count_episodes(config: dict) -> dict:
    """How much the vault holds, in the terms the rest of the store uses.

    `open` is the row's own state (no end set, never invalidated) and `closed`
    its complement. `holding` is what a default query returns now: started,
    not ended, not revised, so an episode dated in the future or ended ahead
    of time is open but not yet, or no longer, holding. `disputes` counts the
    pairs whose two sides both hold now, which is exactly how long a dispute
    lasts.
    """
    conn = get_connection(config)
    now = now_iso()
    total = conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()["n"]
    open_now = conn.execute(
        "SELECT COUNT(*) AS n FROM episodes WHERE valid_to IS NULL AND invalidated_at IS NULL"
    ).fetchone()["n"]
    holding = conn.execute(
        f"SELECT COUNT(*) AS n FROM episodes e WHERE {_HOLDS_AT}", (now, now)
    ).fetchone()["n"]
    disputes = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM episode_disputes d
        WHERE EXISTS (SELECT 1 FROM episodes e WHERE e.id = d.episode_a AND {_HOLDS_AT})
          AND EXISTS (SELECT 1 FROM episodes e WHERE e.id = d.episode_b AND {_HOLDS_AT})
        """,
        (now, now, now, now),
    ).fetchone()["n"]
    return {"total": total, "open": open_now, "closed": total - open_now, "holding": holding, "disputes": disputes}

def list_attestations(config: dict) -> list[dict]:
    """Every attestation in the vault, oldest first: which episode, when, by whom.

    The episode row carries only their count and the last one; whoever wants
    to show each reassertion reads them here.
    """
    conn = get_connection(config)
    rows = conn.execute("SELECT episode_id, at, source FROM episode_attestations ORDER BY at").fetchall()
    return [dict(row) for row in rows]

def list_disputes(config: dict) -> list[dict]:
    """Every dispute ever noticed, oldest first, settled or not: the two
    episodes, when it was noticed and the note. The episode row only carries
    the ones still open."""
    conn = get_connection(config)
    rows = conn.execute(
        "SELECT episode_a, episode_b, noticed_at, note FROM episode_disputes ORDER BY noticed_at"
    ).fetchall()
    return [dict(row) for row in rows]

def change_moments(config: dict) -> list[str]:
    """Every instant the vault changed, as it recorded them: a statement
    recorded, one closed (invalidated, superseded or revised), one confirmed,
    two put in dispute, one reopened. Unordered; whoever reads it buckets or sorts."""
    conn = get_connection(config)
    rows = conn.execute(
        "SELECT recorded_at AS at FROM episodes UNION ALL "
        "SELECT closed_at FROM episode_closures UNION ALL "
        "SELECT reopened_at FROM episode_closures WHERE reopened_at IS NOT NULL UNION ALL "
        "SELECT at FROM episode_attestations UNION ALL "
        "SELECT noticed_at FROM episode_disputes"
    ).fetchall()
    return [row["at"] for row in rows]


def episodes_without_embedding(config: dict) -> list[dict]:
    """The id and content of every episode that has no vector yet: what a
    vault given an embedding model after the fact has to catch up on."""
    conn = get_connection(config)
    rows = conn.execute("SELECT id, content FROM episodes WHERE embedding IS NULL ORDER BY recorded_at").fetchall()
    return [{"id": row["id"], "content": row["content"]} for row in rows]


def set_embedding(config: dict, episode_id: str, embedding: list[float] | None) -> None:
    conn = get_connection(config)
    with _write_lock, conn:
        conn.execute("UPDATE episodes SET embedding = ? WHERE id = ?", (encode_embedding(embedding), episode_id))

