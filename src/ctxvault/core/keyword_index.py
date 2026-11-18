"""The keyword leg of a semantic vault: an FTS5 index of its chunks.

It is a cache, never a source of truth. The vector store holds the documents;
this file holds only what is needed to rank them by exact words, so it can be
dropped and rebuilt from the collection at any time. A vault without it (or
one whose interpreter lacks FTS5) answers vector-only queries exactly as
before; `available` and `search` say so instead of raising into a query.
"""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

DB_NAME = "keywords.sqlite3"
SCHEMA_VERSION = "1"

_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
    "chunk_id UNINDEXED, doc_id UNINDEXED, chunk_index UNINDEXED, "
    "source UNINDEXED, metadata UNINDEXED, text, tokenize='unicode61')"
)


def path(config: dict) -> Path | None:
    """Where the index lives: beside the collection, inside `db_path`, which
    the vault scan already excludes."""
    db_path = config.get("db_path")
    return Path(db_path) / DB_NAME if db_path else None


def _connect(config: dict):
    index_path = path(config)
    if index_path is None:
        return None
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path, timeout=10)
    connection.execute(_SCHEMA)
    connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return connection


def available(config: dict) -> bool:
    """Whether this interpreter can build and read the index at all. False
    means SQLite without FTS5; callers then stay on the vector leg."""
    if path(config) is None:
        return False
    try:
        with closing(_connect(config)) as connection:
            return True
    except sqlite3.Error:
        return False


def _metadata_json(metadata: dict | None) -> str:
    return json.dumps(metadata or {}, sort_keys=True, ensure_ascii=False)


def upsert(config: dict, chunk_ids: list[str], metadatas: list[dict], texts: list[str],
           replace: bool = True) -> None:
    """One document's chunks, replacing any earlier copy of that document.

    Deleting per chunk would scan the table once per chunk — quadratic, and it
    showed: a document has one row per chunk but only one `doc_id`. `replace`
    is off in `rebuild`, where the table was just cleared and there is nothing
    to remove."""
    if not chunk_ids or path(config) is None:
        return
    with closing(_connect(config)) as connection, connection:
        if replace:
            for doc_id in {metadata["doc_id"] for metadata in metadatas}:
                connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        for chunk_id, metadata, text in zip(chunk_ids, metadatas, texts):
            connection.execute(
                "INSERT INTO chunks (chunk_id, doc_id, chunk_index, source, metadata, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, metadata["doc_id"], metadata["chunk_index"], metadata["source"],
                 _metadata_json(metadata), text),
            )


def delete_document(config: dict, doc_id: str) -> None:
    if path(config) is None:
        return
    with closing(_connect(config)) as connection, connection:
        connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))


def clear(config: dict) -> None:
    if path(config) is None:
        return
    """Forget everything, meta included: the next hybrid query rebuilds."""
    with closing(_connect(config)) as connection, connection:
        connection.execute("DELETE FROM chunks")
        connection.execute("DELETE FROM meta")


def count(config: dict) -> int:
    if path(config) is None:
        return 0
    with closing(_connect(config)) as connection:
        return connection.execute("SELECT count(*) FROM chunks").fetchone()[0]


def built_at(config: dict) -> str | None:
    if path(config) is None:
        return None
    with closing(_connect(config)) as connection:
        row = connection.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    return row[0] if row else None


def mark_built(config: dict, when: str) -> None:
    if path(config) is None:
        return
    with closing(_connect(config)) as connection, connection:
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', ?)", (when,))
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))


def _match_expression(query: str) -> str:
    """The query as an OR of quoted words.

    FTS5 has its own grammar: a bare `ctxvault.foo(bar)` is a syntax error, and
    an identifier is what this leg exists for. Quoting every word keeps the
    user's text from being parsed as operators."""
    words = re.findall(r"\w+", query, flags=re.UNICODE)
    return " OR ".join(f'"{word}"' for word in words)


def search(config: dict, query: str, limit: int) -> list[dict]:
    """The best chunks for the query's words, best first. Empty on any reason
    to have no keyword leg, never an exception: a query must still answer."""
    match = _match_expression(query)
    if not match or not available(config):
        return []
    try:
        with closing(_connect(config)) as connection:
            rows = connection.execute(
                "SELECT chunk_id, doc_id, chunk_index, source, metadata, text "
                "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
                (match, limit),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {"chunk_id": row[0], "doc_id": row[1], "chunk_index": row[2], "source": row[3],
         "metadata": json.loads(row[4]), "text": row[5]}
        for row in rows
    ]


def rebuild(config: dict) -> int:
    if path(config) is None:
        return 0
    """Fill the index from the vector store, which stays the source of truth.
    Returns how many chunks were written."""
    from ctxvault.storage import chroma_store

    collection = chroma_store.get_collection(config)
    records = collection.get(include=["documents", "metadatas"])
    ids = records.get("ids") or []
    metadatas = records.get("metadatas") or []
    documents = records.get("documents") or []
    clear(config)
    pairs = [(chunk_id, metadata, text) for chunk_id, metadata, text
             in zip(ids, metadatas, documents) if metadata is not None and text is not None]
    if pairs:
        upsert(config, [p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs], replace=False)
    return len(pairs)

