from pathlib import Path
import pytest
from ctxvault.core import vault_router
from ctxvault.models.vaults import SkillInput
from ctxvault.core.exceptions import UnsupportedVaultOperationError

# ── Semantic vault ──────────────────────────────────────────────────────────

def test_init_vault_creates_dirs(mock_vault_not_initialized):
    vault_path, config_path = vault_router.init_vault(
        vault_name="test_vault",
        path=str(mock_vault_not_initialized.parent)
    )
    assert Path(vault_path).exists()
    assert Path(config_path).exists()

def test_query_returns_result(mock_vault_config):
    result = vault_router.query(text="test query", vault_name="test_vault")
    assert len(result.results) == 1
    assert hasattr(result, "results")

def test_index_files_returns_lists(mock_vault_config, temp_docs):
    indexed, skipped = vault_router.index_files(vault_name="test_vault", path=str(temp_docs))
    assert isinstance(indexed, list)
    assert isinstance(skipped, list)

def test_list_documents_returns_list(mock_vault_config):
    docs = vault_router.list_documents(vault_name="test_vault")
    assert isinstance(docs, list)

def test_list_documents_has_doc_info_fields(mock_vault_config):
    docs = vault_router.list_documents(vault_name="test_vault")
    for doc in docs:
        assert hasattr(doc, "doc_id")
        assert hasattr(doc, "source")

def test_get_document_content_reconstructs_chunks(mock_vault_config):
    doc = vault_router.get_document_content(vault_name="test_vault", doc_id="1")
    assert doc.doc_id == "1"
    assert doc.content == "alpha\n\nbeta"
    assert doc.chunks_count == 2
    assert doc.reconstructed is True
    assert doc.warning

def test_get_document_content_missing_raises(mock_vault_config):
    from ctxvault.core.exceptions import DocumentNotFoundError
    with pytest.raises(DocumentNotFoundError):
        vault_router.get_document_content(vault_name="test_vault", doc_id="missing")

def test_write_doc_creates_and_indexes(mock_vault_config):
    vault_router.write_doc(vault_name="test_vault", file_path="notes/test.txt", content="hello world")
    assert (mock_vault_config / "notes" / "test.txt").exists()

def test_write_doc_no_overwrite_raises(mock_vault_config):
    vault_router.write_doc(vault_name="test_vault", file_path="dup.txt", content="first")
    with pytest.raises(Exception):
        vault_router.write_doc(vault_name="test_vault", file_path="dup.txt", content="second", overwrite=False)

def test_write_doc_unsupported_type_raises(mock_vault_config):
    with pytest.raises(Exception):
        vault_router.write_doc(vault_name="test_vault", file_path="file.xyz", content="content")

def test_query_empty_text_raises(mock_vault_config):
    with pytest.raises(Exception):
        vault_router.query(text="  ", vault_name="test_vault")

def test_init_vault_already_exists_raises(mock_vault_config):
    with pytest.raises(Exception):
        vault_router.init_vault(vault_name="test_vault")

# ── Skill vault ─────────────────────────────────────────────────────────────

def test_init_skill_vault_creates_dirs(mock_global_config):
    vault_path, config_path = vault_router.init_vault(
        vault_name="new_skill_vault",
        vault_type="skill"
    )
    assert Path(vault_path).exists()
    assert Path(config_path).exists()

def test_list_skills_returns_list(mock_skill_vault_config, temp_skills):
    vault_router.index_files(vault_name="test_skill_vault")
    skills = vault_router.list_skills(vault_name="test_skill_vault")
    assert isinstance(skills, list)

def test_list_skills_has_expected_fields(mock_skill_vault_config, temp_skills):
    vault_router.index_files(vault_name="test_skill_vault")
    skills = vault_router.list_skills(vault_name="test_skill_vault")
    assert len(skills) == 2
    for skill in skills:
        assert hasattr(skill, "skill_name")
        assert hasattr(skill, "description")

def test_write_skill_creates_file(mock_skill_vault_config, sample_skill_input):
    filename = vault_router.write_skill(vault_name="test_skill_vault", skill=sample_skill_input)
    assert (mock_skill_vault_config / filename).exists()

def test_write_skill_registers_in_index(mock_skill_vault_config, sample_skill_input):
    vault_router.write_skill(vault_name="test_skill_vault", skill=sample_skill_input)
    skills = vault_router.list_skills(vault_name="test_skill_vault")
    assert any(s.skill_name == sample_skill_input.name for s in skills)

def test_read_skill_returns_correct_content(mock_skill_vault_config, temp_skills):
    vault_router.index_files(vault_name="test_skill_vault")
    skill = vault_router.read_skill(vault_name="test_skill_vault", skill_name="Write Tests")
    assert skill.name == "Write Tests"
    assert "pytest" in skill.instructions

def test_read_skill_not_found_raises(mock_skill_vault_config):
    with pytest.raises(Exception):
        vault_router.read_skill(vault_name="test_skill_vault", skill_name="Nonexistent")

# ── Cross-type operation guards ─────────────────────────────────────────────

def test_query_on_skill_vault_raises(mock_skill_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.query(text="something", vault_name="test_skill_vault")

def test_read_skill_on_semantic_vault_raises(mock_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.read_skill(vault_name="test_vault", skill_name="anything")

def test_list_skills_on_semantic_vault_raises(mock_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.list_skills(vault_name="test_vault")

def test_list_documents_on_skill_vault_raises(mock_skill_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.list_documents(vault_name="test_skill_vault")

def test_write_doc_on_skill_vault_raises(mock_skill_vault_config):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.write_doc(vault_name="test_skill_vault", file_path="test.txt", content="hello")

def test_write_skill_on_semantic_vault_raises(mock_vault_config, sample_skill_input):
    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.write_skill(vault_name="test_vault", skill=sample_skill_input)

# ── Shared behaviors ─────────────────────────────────────────────────────────

def test_list_vaults_returns_list(mock_global_config):
    result = vault_router.list_vaults()
    assert isinstance(result, list)

def test_list_vaults_contains_both_vault_types(mock_vault_config, mock_skill_vault_config):
    result = vault_router.list_vaults()
    types = {v["type"] for v in result}
    assert "semantic" in types
    assert "skill" in types

def test_list_vaults_scope(mock_vault_config):
    result = vault_router.list_vaults()
    for v in result:
        assert v.get("scope") in ("local", "global")

# ── Chunking strategies ────────────────────────────────────────────────────

def test_chunking_default_uses_recursive():
    from ctxvault.utils.chuncking import chunking
    text = " ".join(["word"] * 500)
    chunks = chunking(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.split()) <= 400

def test_chunking_markdown_splits_on_headers():
    from ctxvault.utils.chuncking import chunking
    md_text = "# Title\n\nIntro paragraph.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
    chunks = chunking(md_text, file_type=".md")
    assert len(chunks) >= 2

def test_chunking_backward_compatible():
    from ctxvault.utils.chuncking import chunking
    text = "hello world " * 100
    chunks = chunking(text)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)

def test_fixed_chunks_keep_the_text_as_written_and_say_what_they_repeat():
    from ctxvault.utils.chuncking import _chunk_fixed
    text = "w0 w1\nw2 w3 w4 w5 w6 w7 w8 w9"
    chunks = _chunk_fixed(text, chunk_size=4, overlap=1, measure=lambda s: len(s.split()))

    assert [c.text for c in chunks] == ["w0 w1\nw2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]   # the newline survives
    assert [c.repeated_words for c in chunks] == [0, 1, 1]

def test_chunks_are_cut_by_the_given_measure():
    from ctxvault.utils.chuncking import chunk_text
    # every word costs two, so a chunk of six holds three words
    chunks = chunk_text(" ".join(f"w{i}" for i in range(9)), chunk_size=6, overlap=0, measure=lambda s: 2 * len(s.split()))

    assert [c.text for c in chunks] == ["w0 w1 w2", "w3 w4 w5", "w6 w7 w8"]

def test_markdown_is_extracted_as_written_so_the_chunker_sees_its_headings(tmp_path):
    from ctxvault.utils.text_extraction import extract_text
    from ctxvault.utils.chuncking import chunk_text
    md = tmp_path / "guide.md"
    md.write_text("# Guide\n\nIntro.\n\n## Audit log\n\nEvery write is logged.\n")

    text, filetype = extract_text(str(md))
    chunks = chunk_text(text, file_type=filetype)

    assert text.startswith("# Guide")
    assert chunks[1].text == "Guide > Audit log\nEvery write is logged."

def test_a_markdown_continuation_repeats_its_heading_path_and_its_overlap():
    from ctxvault.utils.chuncking import chunk_text
    body = " ".join(f"w{i}" for i in range(10))
    chunks = chunk_text(f"# T\n\n## A\n\n{body}", chunk_size=6, overlap=1, file_type=".md")

    assert chunks[0].text == "T"                                                      # the title section, empty body
    assert chunks[1].text.startswith("T > A\nw0") and chunks[1].repeated_words == 0
    assert chunks[2].text.startswith("T > A\n") and chunks[2].repeated_words == 3 + 1   # "T > A" and one word of overlap

def test_a_document_is_rebuilt_without_the_repeats(mock_vault_config, monkeypatch):
    from ctxvault.storage import chroma_store
    from ctxvault.core.indexer import index_file
    from ctxvault.core import querying
    source = mock_vault_config / "long.txt"
    words = [f"w{i}" for i in range(1000)]
    source.write_text(" ".join(words))
    stored = {}
    monkeypatch.setattr(chroma_store, "add_document", lambda ids, embeddings, metadatas, chunks, config: stored.update(metadatas=metadatas, documents=chunks))
    config = vault_router.open_vault("test_vault").config
    index_file(str(source), config)
    assert len(stored["documents"]) > 1 and stored["metadatas"][1]["chunk_repeated_words"] == 100
    monkeypatch.setattr(chroma_store, "get_document_records", lambda doc_id, config: stored)

    doc = querying.get_document_content("whatever", config)

    assert doc.content.split() == words
    assert doc.warning is None

def test_a_document_indexed_by_an_earlier_version_still_warns(mock_vault_config):
    doc = vault_router.get_document_content(vault_name="test_vault", doc_id="1")   # the mock chunks carry no repeat count
    assert "earlier version" in doc.warning

def test_query_results_carry_the_agent_metadata_and_a_similarity(mock_vault_config):
    hit = vault_router.query(text="anything", vault_name="test_vault").results[0]
    assert hit.metadata == {}
    assert abs(hit.similarity - 0.01) < 1e-9        # the mocked cosine distance is 0.99

def test_index_status_and_sync(mock_vault_config, monkeypatch):
    import os
    from ctxvault.storage import chroma_store
    from ctxvault.core.vaults.semantic import SemanticVault
    fresh, stale, never = mock_vault_config / "fresh.txt", mock_vault_config / "stale.txt", mock_vault_config / "never.txt"
    fresh.write_text("a"); stale.write_text("b"); never.write_text("c")
    os.utime(fresh, (1_700_000_000, 1_700_000_000))
    os.utime(stale, (1_800_000_000, 1_800_000_000))
    at = "2026-01-01T00:00:00+00:00"
    gone = str(mock_vault_config / "gone.txt")
    monkeypatch.setattr(chroma_store, "get_all_metadatas", lambda config: [
        {"doc_id": "f", "source": str(fresh), "filetype": ".txt", "indexed_at": at},
        {"doc_id": "s", "source": str(stale), "filetype": ".txt", "indexed_at": at},
        {"doc_id": "m", "source": gone, "filetype": ".txt", "indexed_at": at},
    ])
    calls = []
    monkeypatch.setattr(SemanticVault, "reindex_file", lambda self, file_path: calls.append(("reindex", str(file_path))))
    monkeypatch.setattr(SemanticVault, "index_file", lambda self, file_path, agent_metadata=None: calls.append(("index", str(file_path))))
    monkeypatch.setattr("ctxvault.core.indexer.delete_file", lambda file_path, config: calls.append(("drop", file_path)))

    status = vault_router.index_status("test_vault")
    assert {d.doc_id: d.state for d in status.documents} == {"f": "in_sync", "s": "changed", "m": "missing"}
    assert status.unindexed == [str(never)]

    assert vault_router.sync_index("test_vault") == ([str(stale)], [str(never)], [gone])
    assert calls == [("reindex", str(stale)), ("drop", gone), ("index", str(never))]

def test_a_whole_reindex_moves_an_old_collection_to_cosine(mock_vault_config, temp_docs):
    from ctxvault.storage import chroma_store
    config = vault_router.open_vault("test_vault").config
    collection = chroma_store.get_collection(config)
    collection.metadata = {"hnsw:space": "l2"}            # made by an earlier version
    client = chroma_store._clients[config["db_path"]]

    indexed, skipped = vault_router.reindex_files("test_vault")

    client.delete_collection.assert_called_once_with("ctxvault")
    assert sorted(indexed) == sorted(str(p) for p in temp_docs.iterdir()) and skipped == []

def test_chunking_new_defaults():
    from ctxvault.utils.chuncking import chunking
    import inspect
    sig = inspect.signature(chunking)
    assert sig.parameters["chunk_size"].default == 400
    assert sig.parameters["overlap"].default == 100

# ── Per-vault embedding model (#18) ─────────────────────────────────────────

def test_init_vault_stores_embedding_model(mock_global_config):
    from ctxvault.utils.config import get_vaults
    vault_router.init_vault(
        vault_name="custom_model_vault", global_vault=True,
        embedding_model="all-mpnet-base-v2"
    )
    vault = next(v for v in get_vaults() if v["name"] == "custom_model_vault")
    assert vault["embedding_model"] == "all-mpnet-base-v2"

def test_init_vault_default_has_no_embedding_model(mock_vault_config):
    from ctxvault.utils.config import get_vaults
    vault = next(v for v in get_vaults() if v["name"] == "test_vault")
    assert vault["embedding_model"] is None

def test_init_vault_rejects_embedding_model_for_skill(mock_global_config):
    with pytest.raises(ValueError):
        vault_router.init_vault(
            vault_name="skill_with_model", vault_type="skill",
            global_vault=True, embedding_model="all-mpnet-base-v2"
        )

def test_index_threads_vault_embedding_model(mock_global_config, monkeypatch):
    vault_path, _ = vault_router.init_vault(
        vault_name="idx_vault", global_vault=True,
        embedding_model="all-mpnet-base-v2"
    )
    (Path(vault_path) / "doc.txt").write_text("hello world")

    seen = []
    def recording_embed(chunks, model_name=None):
        seen.append(model_name)
        return [[0.1] * 384] * len(chunks)
    monkeypatch.setattr("ctxvault.core.embedding.embed_list", recording_embed)

    vault_router.index_files(vault_name="idx_vault")
    assert seen and all(model == "all-mpnet-base-v2" for model in seen)

def test_query_threads_vault_embedding_model(mock_global_config, monkeypatch):
    vault_router.init_vault(
        vault_name="qry_vault", global_vault=True,
        embedding_model="all-mpnet-base-v2"
    )

    seen = []
    def recording_embed(chunks, model_name=None):
        seen.append(model_name)
        return [[0.1] * 384] * len(chunks)
    # querying.py binds embed_list at import, so patch it where it is looked up.
    monkeypatch.setattr("ctxvault.core.querying.embed_list", recording_embed)

    vault_router.query(text="anything", vault_name="qry_vault")
    assert seen == ["all-mpnet-base-v2"]

def test_get_model_caches_per_name_and_defaults(monkeypatch):
    import ctxvault.core.embedding as embedding

    created = []
    class FakeSentenceTransformer:
        def __init__(self, name):
            self.name = name
            created.append(name)
    monkeypatch.setattr(embedding, "SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr(embedding, "_MODELS", {})

    first = embedding.get_model("model-a")
    again = embedding.get_model("model-a")
    default = embedding.get_model()

    assert first is again  # same name -> cached instance reused
    assert default is not first  # default model is a distinct instance
    assert created == ["model-a", embedding.DEFAULT_EMBEDDING_MODEL]

def test_the_global_registry_is_not_also_a_local_one(tmp_path, monkeypatch):
    from ctxvault.utils import config

    home = tmp_path / "home"
    (home / ".ctxvault").mkdir(parents=True)
    (home / ".ctxvault" / "config.json").write_text('{"vaults": {}}')
    (home / "project" / "sub").mkdir(parents=True)
    monkeypatch.setattr(config, "GLOBAL_DIR", home / ".ctxvault")

    monkeypatch.chdir(home / "project" / "sub")
    assert config.find_local_root() is None           # walking up hits only the global one

    (home / "project" / ".ctxvault").mkdir()
    (home / "project" / ".ctxvault" / "config.json").write_text('{"vaults": {}}')
    assert config.find_local_root() == home / "project" / ".ctxvault"

def test_a_vault_whose_folder_is_gone_does_not_reopen_empty(mock_episodic_vault_config):
    import shutil
    from ctxvault.core import vault_router
    from ctxvault.core.exceptions import VaultNotFoundError, VaultPathMissingError
    from ctxvault.storage import sqlite_store

    vault_router.write_episode("test_episodic_vault", "Giuseppe lives in Mestre")
    sqlite_store.close_connections()
    shutil.rmtree(mock_episodic_vault_config)

    with pytest.raises(VaultPathMissingError) as error:
        vault_router.open_vault("test_episodic_vault")
    assert isinstance(error.value, VaultNotFoundError)    # every existing handler still catches it
    assert not mock_episodic_vault_config.exists()        # opening did not recreate it

def test_attaching_an_agent_keeps_a_project_vault_path_relative(tmp_path, monkeypatch):
    import json
    from ctxvault.utils import config
    from ctxvault.models.vaults import VaultType
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(config, "GLOBAL_DIR", tmp_path / "home" / ".ctxvault")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    config.create_vault("notes", VaultType.SKILL, False, None, global_vault=False)

    config.attach_agent_to_vault("notes", "writer")
    config.detach_agent_from_vault("notes", "writer")
    config.make_public("notes")

    saved = json.loads((project / ".ctxvault" / "config.json").read_text())["vaults"]["notes"]
    assert saved["vault_path"] == ".ctxvault/vaults/notes"          # as created: the project can move
    assert Path(config.get_vault_config("notes")["vault_path"]).is_absolute()   # readers still get it resolved

def test_a_skill_whose_file_is_gone_is_skipped_and_said(mock_skill_vault_config, temp_skills):
    import warnings
    from ctxvault.core.exceptions import SkillNotFoundError
    vault_router.index_files("test_skill_vault")
    (mock_skill_vault_config / "code-review.md").unlink()

    with warnings.catch_warnings(record=True) as said:
        warnings.simplefilter("always")
        skills = vault_router.list_skills("test_skill_vault")

    assert [s.skill_name for s in skills] == ["Write Tests"]
    assert any("code-review.md" in str(w.message) for w in said)
    with pytest.raises(SkillNotFoundError):
        vault_router.read_skill("test_skill_vault", "Code Review")

def test_a_vault_whose_folder_is_gone_can_still_be_purged(mock_vault_config):
    import shutil
    from ctxvault.core import vault_router
    from ctxvault.utils import config

    shutil.rmtree(mock_vault_config)

    vault_router.purge_vault("test_vault")

    assert all(v["name"] != "test_vault" for v in config.get_vaults())
