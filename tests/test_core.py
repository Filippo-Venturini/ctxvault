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
