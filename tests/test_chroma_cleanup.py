"""Exercise per-vault release with real Chroma, without embedding downloads."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import chromadb
from chromadb.api.shared_system_client import SharedSystemClient
import pytest

from ctxvault.storage import chroma_store

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def real_chroma(monkeypatch):
    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)
    yield
    for path, client in list(chroma_store._clients.items()):
        chroma_store._collections.pop(path, None)
        chroma_store._clients.pop(path)
        if hasattr(client, "close"):
            client.close()
        else:
            client._system.stop()
            SharedSystemClient._identifier_to_system.pop(client._identifier, None)


def test_close_client_releases_only_its_vault_and_can_reopen(tmp_path, real_chroma):
    first = {"db_path": (tmp_path / "first").as_posix()}
    second = {"db_path": (tmp_path / "second").as_posix()}
    for config in (first, second):
        chroma_store.add_document(["one"], [[1.0, 0.0]], [{"source": "local"}], ["stored"], config)
    chroma_store.close_client(first)
    chroma_store.close_client(first)
    assert first["db_path"] not in chroma_store._clients
    assert first["db_path"] not in chroma_store._collections
    assert first["db_path"] not in SharedSystemClient._identifier_to_system
    assert chroma_store.get_all_records(second, ["documents"])["documents"] == ["stored"]
    assert chroma_store.get_all_records(first, ["documents"])["documents"] == ["stored"]


@pytest.mark.parametrize("failure", [None, "ingestion", "retrieval"])
def test_semantic_replay_releases_real_chroma_before_directory_cleanup(tmp_path, monkeypatch, real_chroma, failure):
    from benchmarks.longmemeval.data import parse_record
    from benchmarks.longmemeval.replay import memory_for

    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)
    question = parse_record({
        "question_id": "cleanup", "question_type": "single-session-user",
        "question": "Where do I live?", "answer": "Venezia",
        "question_date": "2026-06-10", "haystack_session_ids": ["session"],
        "haystack_dates": ["2026-01-10"],
        "haystack_sessions": [[{"role": "user", "content": "I live in Venezia."}]],
    })
    original = chroma_store.add_document
    created = []

    def add_then_maybe_fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "ingestion":
            raise RuntimeError("interrupted ingestion")
        return result

    query = chroma_store.query

    def query_then_maybe_fail(*args, **kwargs):
        result = query(*args, **kwargs)
        if failure == "retrieval":
            raise RuntimeError("interrupted retrieval")
        return result

    monkeypatch.setattr(chroma_store, "add_document", add_then_maybe_fail)
    monkeypatch.setattr(chroma_store, "query", query_then_maybe_fail)
    for _ in range(3):
        with TemporaryDirectory(dir=tmp_path) as directory:
            workdir = Path(directory)
            created.append(workdir)
            if failure:
                with pytest.raises(RuntimeError, match="interrupted"):
                    memory_for("semantic-only", question, workdir=workdir)
            else:
                assert "Venezia" in memory_for("semantic-only", question, workdir=workdir)
            assert not chroma_store._clients
            assert not chroma_store._collections
            assert not any(workdir.as_posix() in key for key in SharedSystemClient._identifier_to_system)
        assert not workdir.exists()
    assert all(not path.exists() for path in created)
