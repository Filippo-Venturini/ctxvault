from ctxvault.models.vaults import VaultType, SkillInput
from ctxvault.utils.config import create_vault
import pytest
from pathlib import Path
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def mock_chroma(monkeypatch):
    monkeypatch.setattr(
        "ctxvault.core.embedding.embed_list",
        lambda chunks: [[0.1] * 384] * len(chunks),
    )

    mock_collection = MagicMock()
    mock_collection.upsert = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.query = MagicMock(
        return_value={
            "documents": [["mock_doc"]],
            "metadatas": [[{
                "chunk_id": "1",
                "chunk_index": 0,
                "doc_id": "1",
                "source": "mock_doc"
            }]],
            "distances": [[0.99]],
        }
    )
    mock_collection.get = MagicMock(
        side_effect=lambda where=None, include=None: (
            {
                "metadatas": [
                    {
                        "doc_id": "1",
                        "chunk_index": 0,
                        "source": "mock_doc",
                        "filetype": "txt",
                        "indexed_at": "2026-01-01T00:00:00+00:00",
                    },
                    {
                        "doc_id": "1",
                        "chunk_index": 1,
                        "source": "mock_doc",
                        "filetype": "txt",
                        "indexed_at": "2026-01-01T00:00:00+00:00",
                    },
                ],
                "documents": ["alpha", "beta"],
            }
            if where and where.get("doc_id") == "1"
            else {
                "metadatas": [{
                    "doc_id": "1",
                    "source": "mock_doc",
                    "filetype": "txt",
                }]
            }
        )
    )

    mock_client = MagicMock()
    mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

    monkeypatch.setattr(
        "ctxvault.storage.chroma_store.PersistentClient",
        lambda path, settings=None: mock_client,
    )
    monkeypatch.setattr("ctxvault.storage.chroma_store._clients", {})
    monkeypatch.setattr("ctxvault.storage.chroma_store._collections", {})

@pytest.fixture
def mock_global_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".ctxvault"
    monkeypatch.setattr("ctxvault.utils.config.GLOBAL_DIR", config_dir)
    monkeypatch.setattr("ctxvault.utils.config._find_local_root", lambda: None)
    monkeypatch.chdir(tmp_path)
    return config_dir

@pytest.fixture
def mock_vault_not_initialized(mock_global_config, tmp_path):
    vault_path = tmp_path / "orphan_vault"
    vault_path.mkdir()
    return vault_path

@pytest.fixture
def mock_vault_config(mock_global_config):
    vault_path, config_path = create_vault("test_vault", VaultType.SEMANTIC, False, None, global_vault=True)
    return Path(vault_path)

@pytest.fixture
def mock_skill_vault_config(mock_global_config):
    vault_path, _ = create_vault("test_skill_vault", VaultType.SKILL, False, None, global_vault=True)
    return Path(vault_path)

@pytest.fixture
def temp_docs(mock_vault_config):
    docs = mock_vault_config / "docs"
    docs.mkdir()
    (docs / "file1.txt").write_text("Content of file 1")
    (docs / "file2.txt").write_text("Content of file 2")
    return docs

@pytest.fixture
def temp_skills(mock_skill_vault_config):
    skill_1 = mock_skill_vault_config / "write-tests.md"
    skill_1.write_text("---\nname: Write Tests\ndescription: How to write unit tests\n---\nAlways use pytest.")
    skill_2 = mock_skill_vault_config / "code-review.md"
    skill_2.write_text("---\nname: Code Review\ndescription: How to review code\n---\nCheck for clarity first.")
    return mock_skill_vault_config

@pytest.fixture
def sample_skill_input():
    return SkillInput(
        name="Deploy Service",
        description="How to deploy a service",
        instructions="Run docker build then docker push."
    )
