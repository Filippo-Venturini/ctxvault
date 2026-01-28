from pathlib import Path
import pytest
from ctxvault.core import vault

def test_init_vault_creates_dirs(mock_vault_not_initialized):
    vault_path, config_path = vault.init_vault(path=str(mock_vault_not_initialized.parent))
    assert Path(vault_path).exists()
    assert Path(config_path).exists()

def test_iter_files(temp_docs):
    files = list(vault.iter_files(temp_docs))
    assert len(files) == 2
    assert all(f.suffix == ".txt" for f in files)

def test_index_file_calls_indexer(temp_docs):
    file_path = temp_docs / "file1.txt"
    vault.index_file(file_path=file_path)

@pytest.mark.usefixtures("mock_vault_config")
def test_query_returns_result():
    result = vault.query("test query")
    assert len(result.results) == 1
    assert hasattr(result, "results")

def test_delete_file_does_not_fail(temp_docs):
    file_path = temp_docs / "file1.txt"
    vault.delete_file(file_path=file_path)

def test_reindex_file_does_not_fail(temp_docs):
    file_path = temp_docs / "file1.txt"
    vault.reindex_file(file_path=file_path)

@pytest.mark.usefixtures("mock_vault_config")
def test_list_documents_returns_list():
    docs = vault.list_documents()
    assert len(docs) > 0
    assert hasattr(docs[0], "doc_id")
