"""The keyword leg: it is a cache of the collection, so the tests are about it
following writes, surviving nonsense queries, and never failing a query."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ctxvault.core import indexer, keyword_index
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.storage import chroma_store


def _config(tmp_path: Path) -> dict:
    db_path = tmp_path / "vault" / "chroma"
    db_path.mkdir(parents=True, exist_ok=True)
    return {"vault_path": str(tmp_path / "vault"), "db_path": str(db_path)}


def _chunk(chunk_id: str, text: str, doc_id: str = "doc", chunk_index: int = 0) -> dict:
    return {"chunk_id": chunk_id, "doc_id": doc_id, "chunk_index": chunk_index,
            "source": f"{doc_id}.txt", "filetype": "txt"}


def test_a_written_chunk_is_found_by_its_identifier(tmp_path):
    config = _config(tmp_path)
    keyword_index.upsert(config, ["c1"], [_chunk("c1", "The service returns ERR_4021 on timeout")],
                         ["The service returns ERR_4021 on timeout"])

    assert keyword_index.count(config) == 1
    hits = keyword_index.search(config, "ERR_4021", limit=5)
    assert [hit["chunk_id"] for hit in hits] == ["c1"]
    assert hits[0]["metadata"]["doc_id"] == "doc"


def test_deleting_a_document_takes_its_chunks_with_it(tmp_path):
    config = _config(tmp_path)
    keyword_index.upsert(config, ["c1", "c2"], [_chunk("c1", "alpha"), _chunk("c2", "beta", chunk_index=1)],
                         ["alpha", "beta"])

    keyword_index.delete_document(config, "doc")

    assert keyword_index.count(config) == 0
    assert keyword_index.search(config, "alpha", limit=5) == []


def test_fts_operators_in_the_query_are_words_not_syntax(tmp_path):
    config = _config(tmp_path)
    keyword_index.upsert(config, ["c1"], [_chunk("c1", "ctxvault core keyword index")],
                         ["ctxvault core keyword index"])

    # A bare query like this is an FTS5 syntax error; the leg must not raise.
    assert keyword_index.search(config, "ctxvault.foo(bar)", limit=5) != []
    assert keyword_index.search(config, '"', limit=5) == []


def test_rebuild_reads_the_collection_and_marks_the_index(tmp_path, monkeypatch):
    config = _config(tmp_path)
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["c1", "c2"],
        "documents": ["alpha apple", "beta banana"],
        "metadatas": [_chunk("c1", "alpha apple"), _chunk("c2", "beta banana", chunk_index=1)],
    }
    monkeypatch.setattr(chroma_store, "get_collection", MagicMock(return_value=collection))

    assert keyword_index.rebuild(config) == 2
    assert keyword_index.count(config) == 2


def test_index_and_delete_keep_the_cache_in_step(tmp_path):
    config = _config(tmp_path)
    doc = tmp_path / "vault" / "note.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("The retry limit is RETRY_MAX_7 in the worker")

    indexer.index_file(str(doc), config)
    assert keyword_index.search(config, "RETRY_MAX_7", limit=5)

    indexer.delete_file(str(doc), config)
    assert keyword_index.search(config, "RETRY_MAX_7", limit=5) == []


def test_hybrid_ranks_a_chunk_both_legs_agree_on_above_the_vector_leader(tmp_path, monkeypatch):
    config = _config(tmp_path)
    keyword_index.upsert(config, ["c2"], [_chunk("c2", "see ERR_4021", doc_id="doc2")], ["see ERR_4021"])
    keyword_index.mark_built(config, "2026-01-01T00:00:00+00:00")   # an already-built vault

    def fake_query(query_embedding, config, n_results=5, filters=None):
        # The vector leg leads with c1, which is not what the query asks for.
        return {
            "documents": [["alpha apple", "see ERR_4021"]],
            "metadatas": [[_chunk("c1", "alpha apple"), _chunk("c2", "see ERR_4021", doc_id="doc2")]],
            "distances": [[0.10, 0.90]],
        }

    monkeypatch.setattr(chroma_store, "query", fake_query)

    vault = SemanticVault("v", config)
    result = vault.query("ERR_4021", n_results=2, hybrid=True)

    assert result.mode == "hybrid"
    assert result.results[0].chunk_id == "c2"
    assert result.results[0].rank_score == pytest.approx(1 / 61 + 1 / 62)
    # (a): the field still means the distance the vector leg gave it.
    assert result.results[0].score == 0.90
    assert result.results[1].rank_score == pytest.approx(1 / 61)


def test_hybrid_without_fts5_answers_vector_only(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(keyword_index, "available", lambda config: False)

    def fake_query(query_embedding, config, n_results=5, filters=None):
        return {"documents": [["alpha"]], "metadatas": [[_chunk("c1", "alpha")]], "distances": [[0.2]]}

    monkeypatch.setattr(chroma_store, "query", fake_query)

    vault = SemanticVault("v", config)
    result = vault.query("alpha", n_results=1, hybrid=True)

    assert result.mode == "vector"
    assert result.results[0].rank_score is None
    assert result.results[0].score == 0.2


def test_hybrid_is_off_by_default(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = {}

    def fake_query(query_embedding, config, n_results=5, filters=None):
        calls["n_results"] = n_results
        return {"documents": [["alpha"]], "metadatas": [[_chunk("c1", "alpha")]], "distances": [[0.2]]}

    monkeypatch.setattr(chroma_store, "query", fake_query)
    # Nothing to index: a default query must not even look at the keyword file.
    keyword_index.upsert(config, ["c1"], [_chunk("c1", "ERR_4021")], ["ERR_4021"])

    vault = SemanticVault("v", config)
    result = vault.query("alpha", n_results=3)

    assert result.mode == "vector"
    assert calls["n_results"] == 3          # not the deeper hybrid depth
    assert result.results[0].rank_score is None
