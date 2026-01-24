import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

@pytest.fixture(autouse=True)
def mock_chroma(monkeypatch):
    monkeypatch.setattr("ctxvault.core.embedding.embed_list", lambda chunks: [[0.1]*384]*len(chunks))

    mock_collection = MagicMock()
    mock_collection.add = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.query = MagicMock(return_value={
        "documents": [["mock_doc"]], 
        "metadatas": [[{"chunk_id": "1", "chunk_index": 0}]], 
        "distances": [[0.99]]
    })
    mock_collection.get = MagicMock(return_value={
        "metadatas": [{"doc_id": "1", "source": "mock_doc", "filetype": "txt"}]
    })

    mock_client = MagicMock()
    mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

    monkeypatch.setattr("ctxvault.storage.chroma_store.PersistentClient", lambda path: mock_client)
    monkeypatch.setattr("ctxvault.storage.chroma_store._collection", None)

@pytest.fixture
def mock_vault_not_initialized(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    config_path = tmp_path / "config.json"
    
    def _load_config():
        return None  

    def _save_config(*args, **kwargs):
        config_path.write_text('{"vault_path": "test", "db_path": "test"}')
        return str(config_path)

    with patch("ctxvault.core.vault.load_config", side_effect=_load_config):
        with patch("ctxvault.core.vault.save_config", side_effect=_save_config):
            yield vault_path

@pytest.fixture
def mock_vault_config(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    config_path = tmp_path / "config.json"
    
    fake_config = {
        "vault_path": str(vault_path),
        "db_path": str(tmp_path / "chroma")
    }

    def _load_config():
        return fake_config

    def _save_config(*args, **kwargs):
        if kwargs:
            vault_path_str = kwargs.get('vault_path')
            db_path = kwargs.get('db_path')
        else:
            vault_path_str = args[0] if len(args) > 0 else None
            db_path = args[1] if len(args) > 1 else None
        
        if vault_path_str and db_path:
            fake_config.update({"vault_path": vault_path_str, "db_path": db_path})
        return str(config_path)

    with patch("ctxvault.core.vault.load_config", side_effect=_load_config):
        with patch("ctxvault.core.vault.save_config", side_effect=_save_config):
            yield vault_path

@pytest.fixture
def temp_docs(mock_vault_config):
    vault_path = mock_vault_config
    docs = vault_path / "docs"
    docs.mkdir()
    (docs / "file1.txt").write_text("Content of file 1")
    (docs / "file2.txt").write_text("Content of file 2")
    return docs

@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "vault.db"