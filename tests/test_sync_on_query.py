"""The reviewer's same-second repro, end to end.

The suite's Chroma mock returns a fixed document, so it cannot tell whether an
answer came from the old or the new file. This small collection stores what was
upserted and answers from it, which is what the freshness assertion needs.
"""
from ctxvault.core import vault_router
from ctxvault.utils.config import set_sync_on_query


class Collection:
    metadata = {"hnsw:space": "cosine"}

    def __init__(self):
        self.rows = {}

    def upsert(self, ids, embeddings, metadatas, documents):
        for id_, text, meta in zip(ids, documents, metadatas):
            self.rows[id_] = (text, meta)

    def delete(self, where=None):
        doc_id = (where or {}).get("doc_id")
        if doc_id:
            for id_ in [i for i in self.rows if self.rows[i][1].get("doc_id") == doc_id]:
                del self.rows[id_]

    def get(self, where=None, include=None):
        rows = [(text, meta) for text, meta in self.rows.values()
                if not where or where.get("doc_id") == meta.get("doc_id")]
        return {"documents": [text for text, _ in rows], "metadatas": [meta for _, meta in rows]}

    def query(self, query_embeddings, n_results=5, where=None):
        rows = list(self.rows.values())[:n_results]
        return {
            "documents": [[text for text, _ in rows]],
            "metadatas": [[meta for _, meta in rows]],
            "distances": [[0.0 for _ in rows]],
        }


def _install(monkeypatch):
    from ctxvault.storage import chroma_store

    collection = Collection()
    client = type("Client", (), {
        "get_collection": lambda self, name: collection,
        "create_collection": lambda self, name, metadata=None: collection,
        "delete_collection": lambda self, name: None,
    })()
    monkeypatch.setattr(chroma_store, "PersistentClient", lambda path, settings=None: client)
    monkeypatch.setattr(chroma_store, "_clients", {})
    monkeypatch.setattr(chroma_store, "_collections", {})


def test_the_first_query_catches_an_edit_made_right_after_index(mock_vault_config, monkeypatch):
    """The review repro: index, rewrite immediately, query once. There is no
    file record yet, so only `status()` can see the change, and its slack hides
    it; the query must still answer from the new text."""
    _install(monkeypatch)
    set_sync_on_query("test_vault", True)
    note = mock_vault_config / "b.txt"
    note.write_text("gamma grape")
    vault_router.index_files(vault_name="test_vault")

    note.write_text("delta durian")
    result = vault_router.query(text="delta durian", vault_name="test_vault")

    assert result.sync is not None and str(note) in result.sync.reindexed
    assert "delta durian" in result.results[0].text


def test_an_edit_after_a_recorded_query_is_reindexed(mock_vault_config, monkeypatch):
    _install(monkeypatch)
    set_sync_on_query("test_vault", True)
    note = mock_vault_config / "note.txt"
    note.write_text("the first version")
    vault_router.query(text="version", vault_name="test_vault")

    note.write_text("the second version")
    result = vault_router.query(text="version", vault_name="test_vault")

    assert result.sync is not None and result.sync.reindexed == [str(note)]
    assert "the second version" in result.results[0].text
