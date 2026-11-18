import chromadb
import pytest

from ctxvault.core import querying, vault_router
from ctxvault.core.exceptions import DocumentNotFoundError, UnsupportedFileTypeError, UnsupportedVaultOperationError
from ctxvault.core.identifiers import get_doc_id
from ctxvault.core.references import chunk_hash, chunk_reference, resolve_chunk
from ctxvault.core.transcripts import SESSION_METADATA_KEYS, Turn, write_session
from ctxvault.models.vaults import VaultType
from ctxvault.storage import chroma_store
from ctxvault.utils.config import create_vault

@pytest.fixture
def real_chroma(monkeypatch):
    """A real Chroma store, with the conftest's fake embeddings: what is
    tested here is what upserts, deletes and filters actually do."""
    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)
    # small chunks, so a short session spans several: 30 words, 8 of overlap
    monkeypatch.setattr(
        "ctxvault.core.embedding.token_budget",
        lambda model_name=None: (lambda text: len(text.split()), 30, 8),
    )

@pytest.fixture
def vault(mock_vault_config, real_chroma):
    return vault_router.open_vault("test_vault")

def turns(n, start_hour=9, words=6):
    """n turns with words unique to each, so a turn is found by its words."""
    return [
        Turn(speaker="user" if i % 2 == 0 else "assistant",
             text=" ".join(f"t{i}w{j}" for j in range(words)),
             at=f"2026-03-01T{start_hour + i // 60:02d}:{i % 60:02d}:00")
        for i in range(n)
    ]

def records(vault, doc_id):
    return chroma_store.get_document_records(doc_id=doc_id, config=vault.config)

# ── write_session ───────────────────────────────────────────────────────────

def test_a_session_is_one_line_per_turn_with_its_time_in_utc(vault, mock_vault_config):
    write_session(vault, "s/one.txt", [
        Turn(speaker="user", text="I moved\nto Lisbon", at="2026-03-01T09:05:00"),
        Turn(speaker="assistant", text="Noted.", at="2026-03-01T10:30:00+01:00"),
        Turn(speaker="user", text="Undated aside"),
        Turn(speaker="assistant", text="Late reply", at="2026-03-01T09:40:00Z"),
    ])
    assert (mock_vault_config / "s" / "one.txt").read_text() == (
        "2026-03-01 09:05  user: I moved to Lisbon\n"
        "2026-03-01 09:30  assistant: Noted.\n"
        "user: Undated aside\n"
        "2026-03-01 09:40  assistant: Late reply\n"
    )

def test_the_session_dates_come_from_its_turns_and_filter_as_numbers(vault):
    written = write_session(vault, "a.txt", turns(3), session_id="s-1", agent_metadata={"generated_by": "harness"})
    assert written.session_started == "2026-03-01T09:00:00+00:00"
    assert written.session_ended == "2026-03-01T09:02:00+00:00"

    metadata = records(vault, written.doc_id)["metadatas"][0]
    assert metadata["session_id"] == "s-1" and metadata["generated_by"] == "harness"
    assert metadata["session_dated"] is True
    assert metadata["session_started"] == written.session_started

    write_session(vault, "b.txt", turns(3, start_hour=15), session_id="s-2")
    cutoff = metadata["session_ended_ts"] + 60
    before = chroma_store.get_collection(vault.config).get(where={"session_ended_ts": {"$lt": cutoff}}, include=["metadatas"])
    assert {m["session_id"] for m in before["metadatas"]} == {"s-1"}

def test_a_session_without_a_dated_turn_is_undated_never_the_files_time(vault, mock_vault_config):
    written = write_session(vault, "u.txt", [Turn(speaker="user", text="hello"), {"speaker": "bot", "text": "hi"}])
    assert written.session_started is None and written.session_ended is None
    metadata = records(vault, written.doc_id)["metadatas"][0]
    assert metadata["session_dated"] is False
    assert not {"session_started", "session_ended", "session_started_ts", "session_ended_ts", "session_id"} & set(metadata)
    assert (mock_vault_config / "u.txt").read_text() == "user: hello\nbot: hi\n"

def test_each_turn_maps_to_the_first_chunk_it_appears_in(vault):
    session = turns(12)
    # one turn longer than a chunk: the word split carries overlap through it
    session[5] = Turn(speaker="user", text=" ".join(f"t5w{j}" for j in range(70)), at="2026-03-01T09:05:00")
    written = write_session(vault, "long.txt", session)

    chunks = querying.get_document_chunks(written.doc_id, vault.config)
    assert written.chunks == len(chunks) > 3
    assert len(written.turn_chunks) == len(session)
    assert written.turn_chunks == sorted(written.turn_chunks)
    for i, k in enumerate(written.turn_chunks):
        first_word = f"t{i}w0"
        assert first_word in chunks[k].split()
        assert all(first_word not in chunks[j].split() for j in range(k))
    # the long turn spans several chunks and is mapped to where it starts
    assert sum("t5w40" in c.split() for c in chunks) >= 1
    assert "t5w40" not in chunks[written.turn_chunks[5]].split()

def test_writing_the_same_session_again_replaces_it(vault):
    first = write_session(vault, "same.txt", turns(30), session_id="s")
    assert first.chunks > 3
    second = write_session(vault, "same.txt", turns(2), session_id="s")

    assert second.doc_id == first.doc_id
    assert [d.doc_id for d in vault.list_documents()] == [first.doc_id]
    assert len(records(vault, first.doc_id)["ids"]) == second.chunks == 1
    assert second.session_ended == "2026-03-01T09:01:00+00:00"

def test_rewriting_any_document_shorter_leaves_no_old_chunks(vault):
    vault.write_doc("doc.md", " ".join(f"w{i}" for i in range(200)))
    doc_id = vault.list_documents()[0].doc_id
    assert len(querying.get_document_chunks(doc_id, vault.config)) > 1

    vault.write_doc("doc.md", "short now")
    assert querying.get_document_chunks(doc_id, vault.config) == ["short now"]

@pytest.mark.parametrize("call, error", [
    (lambda v: write_session(v, "s.md", turns(1)), UnsupportedFileTypeError),
    (lambda v: write_session(v, "s.txt", []), ValueError),
    (lambda v: write_session(v, "s.txt", [Turn(speaker="u", text="x", at="last tuesday")]), ValueError),
    (lambda v: write_session(v, "s.txt", turns(1), agent_metadata={"session_started": "x"}), ValueError),
    (lambda v: write_session(v, "s.txt", [{"speaker": "u", "text": "  "}]), ValueError),
])
def test_what_write_session_refuses(vault, call, error):
    with pytest.raises(error):
        call(vault)
    assert vault.list_documents() == []

def test_write_session_needs_a_semantic_vault(mock_episodic_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        write_session(vault_router.open_vault("test_episodic_vault"), "s.txt", turns(1))

def test_the_core_turn_has_the_layers_fields():
    from ctxvault.consolidation.model import Turn as LayerTurn
    assert set(Turn.model_fields) == set(LayerTurn.model_fields)
    assert {k: v.is_required() for k, v in Turn.model_fields.items()} == \
        {k: v.is_required() for k, v in LayerTurn.model_fields.items()}

def test_session_keys_are_not_built_in():
    from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS
    # they are the caller's metadata: a reindex carries them over
    assert not SESSION_METADATA_KEYS & BUILT_IN_METADATA_KEYS

# ── chunk_reference ─────────────────────────────────────────────────────────

def test_a_reference_names_the_chunk_as_it_is_now(vault):
    written = write_session(vault, "refs/s.txt", turns(12))
    k = written.turn_chunks[-1]
    ref = chunk_reference("test_vault", written.doc_id, k)
    chunks = querying.get_document_chunks(written.doc_id, vault.config)
    assert ref == {"vault": "test_vault", "doc_id": written.doc_id, "chunk_index": k,
                   "chunk_hash": chunk_hash(chunks[k]), "path": "refs/s.txt"}

def test_a_reference_to_nothing_raises(vault):
    written = write_session(vault, "s.txt", turns(1))
    with pytest.raises(IndexError):
        chunk_reference("test_vault", written.doc_id, 5)
    with pytest.raises(DocumentNotFoundError):
        chunk_reference("test_vault", "0" * 64, 0)

# ── resolve_chunk ───────────────────────────────────────────────────────────

@pytest.fixture
def ref(vault):
    written = write_session(vault, "r/s.txt", turns(12))
    return chunk_reference("test_vault", written.doc_id, 1)

def test_holds(vault, ref):
    found = resolve_chunk(ref)
    assert found.state == "holds" and found.doc_id == ref["doc_id"] and found.chunk_index == 1
    assert chunk_hash(found.text) == ref["chunk_hash"]

def test_changed_never_carries_text(vault, ref):
    session = turns(12)
    written = write_session(vault, "r/s.txt", session)
    # an edit in chunk 0 leaves a reference to chunk 1 holding
    session[0] = Turn(speaker="user", text="something else entirely", at=session[0].at)
    write_session(vault, "r/s.txt", session)
    assert resolve_chunk(ref).state == "holds"

    inside = written.turn_chunks.index(1)
    session[inside] = Turn(speaker="user", text="something else entirely", at=session[inside].at)
    write_session(vault, "r/s.txt", session)
    found = resolve_chunk(ref)
    assert found.state == "changed" and found.text is None and found.doc_id == ref["doc_id"]

def test_past_the_end_is_changed(vault, ref):
    write_session(vault, "r/s.txt", turns(1))
    found = resolve_chunk(ref)
    assert found.state == "changed" and found.text is None and "past its end" in found.said

def test_moved_when_the_doc_id_is_gone_but_the_path_has_the_chunk(vault, ref):
    # what a vault moved to another directory looks like: same relative path,
    # every doc_id derived from the old absolute path
    old = {**ref, "doc_id": get_doc_id("/old/home/r/s.txt")}
    found = resolve_chunk(old)
    assert found.state == "moved" and found.doc_id == ref["doc_id"] and found.text

    changed = {**old, "chunk_hash": "0" * 64}
    assert resolve_chunk(changed).state == "changed"

def test_missing(vault, ref, mock_vault_config):
    vault.delete_file(mock_vault_config / "r" / "s.txt")
    chroma_store.delete_document(ref["doc_id"], vault.config)
    assert resolve_chunk(ref).state == "missing"
    assert resolve_chunk({**ref, "path": None}).state == "missing"

def test_unreachable_is_never_missing(vault, ref, mock_episodic_vault_config):
    assert resolve_chunk({**ref, "vault": "registered_elsewhere"}).state == "unreachable"
    assert resolve_chunk({**ref, "vault": "test_episodic_vault"}).state == "unreachable"

@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "\\\\server\\share.txt", "C:s.txt", "r/../../x.txt"])
def test_a_path_that_leaves_the_vault_is_refused(vault, ref, path):
    found = resolve_chunk({**ref, "path": path, "doc_id": "0" * 64})
    assert found.state == "refused" and found.text is None and found.doc_id is None

def test_refused_comes_first_and_leaks_nothing(mock_global_config, real_chroma):
    create_vault("locked", VaultType.SEMANTIC, True, None, global_vault=True)
    vault_router.attach_agent("locked", "reader")
    locked = vault_router.open_vault("locked")
    written = write_session(locked, "s.txt", turns(3))
    real = chunk_reference("locked", written.doc_id, 0)
    absent = {**real, "doc_id": "0" * 64, "path": "nope.txt"}

    for agent in (None, "stranger"):
        answers = [resolve_chunk(r, agent=agent) for r in (real, absent)]
        assert {a.state for a in answers} == {"refused"}
        assert answers[0] == answers[1]
    assert resolve_chunk(real, agent="reader").state == "holds"

@pytest.mark.parametrize("broken", [
    {},
    {"vault": "v", "doc_id": "d", "chunk_index": -1, "chunk_hash": "0" * 64},
    {"vault": "v", "doc_id": "d", "chunk_index": True, "chunk_hash": "0" * 64},
    {"vault": "v", "doc_id": "d", "chunk_index": 0, "chunk_hash": "not-a-hash"},
    {"vault": "v", "doc_id": "d", "chunk_index": 0, "chunk_hash": "0" * 64, "path": 3},
])
def test_a_malformed_reference_raises(broken):
    with pytest.raises(ValueError):
        resolve_chunk(broken)
