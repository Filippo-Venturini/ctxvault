from fastapi.testclient import TestClient
from ctxvault.api.app import app, ctxvault_router
import pytest
from pathlib import Path

app.include_router(ctxvault_router)

client = TestClient(app)

class TestInitEndpoint:
    def test_init_success(self, mock_vault_not_initialized):
        response = client.post(
            "/ctxvault/init",
            json={"vault_path": str(mock_vault_not_initialized.parent)}
        )
        assert response.status_code == 200
        data = response.json()
        assert "vault_path" in data
        assert "config_path" in data
        assert Path(data["vault_path"]).exists()

    def test_init_already_exists(self, mock_vault_config):
        response = client.post(
            "/ctxvault/init",
            json={"vault_path": str(mock_vault_config)}
        )
        assert response.status_code == 400
        assert "already initialized" in response.json()["detail"]

    def test_init_invalid_json(self):
        response = client.post(
            "/ctxvault/init",
            json={}
        )
        assert response.status_code == 422


class TestIndexEndpoint:
    @pytest.mark.usefixtures("mock_chroma")
    def test_index_success(self, mock_vault_config, temp_docs):
        response = client.put(
            "/ctxvault/index",
            json={"file_path": str(temp_docs)}
        )
        assert response.status_code == 200
        data = response.json()
        assert "indexed_files" in data
        assert "skipped_files" in data
        assert isinstance(data["indexed_files"], list)
        assert isinstance(data["skipped_files"], list)

    @pytest.mark.usefixtures("mock_chroma")
    def test_index_nonexistent_path(self, mock_vault_config):
        response = client.put(
            "/ctxvault/index",
            json={"file_path": "/nonexistent/path"}
        )
        assert response.status_code in [200, 404, 400]


class TestQueryEndpoint:
    @pytest.mark.usefixtures("mock_chroma")
    def test_query_success(self, mock_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"query": "test query"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) > 0

    def test_query_empty_string(self, mock_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"query": ""}
        )
        assert response.status_code == 400
        assert "Empty query" in response.json()["detail"]

    def test_query_whitespace_only(self, mock_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"query": "   "}
        )
        assert response.status_code in [200, 400]

    def test_query_null_value(self):
        response = client.post(
            "/ctxvault/query",
            json={"query": None}
        )
        assert response.status_code == 422

    @pytest.mark.usefixtures("mock_chroma")
    def test_query_no_results(self, mock_vault_config, monkeypatch):
        from ctxvault.core import vault
        from unittest.mock import MagicMock
        
        mock_result = MagicMock()
        mock_result.results = []
        monkeypatch.setattr(vault, "query", lambda text: mock_result)
        
        response = client.post(
            "/ctxvault/query",
            json={"query": "nonexistent"}
        )
        assert response.status_code == 404
        assert "No results found" in response.json()["detail"]

    def test_query_missing_field(self):
        response = client.post(
            "/ctxvault/query",
            json={}
        )
        assert response.status_code == 422


class TestDeleteEndpoint:
    @pytest.mark.usefixtures("mock_chroma")
    def test_delete_success(self, mock_vault_config, temp_docs):
        response = client.delete(
            f"/ctxvault/delete?file_path={temp_docs}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "deleted_files" in data
        assert "skipped_files" in data
        assert isinstance(data["deleted_files"], list)
        assert isinstance(data["skipped_files"], list)

    @pytest.mark.usefixtures("mock_chroma")
    def test_delete_missing_param(self, mock_vault_config):
        response = client.delete("/ctxvault/delete")
        assert response.status_code == 422

    @pytest.mark.usefixtures("mock_chroma")
    def test_delete_nonexistent_path(self, mock_vault_config):
        response = client.delete(
            "/ctxvault/delete?file_path=/nonexistent/path"
        )
        assert response.status_code in [200, 404, 400]


class TestReindexEndpoint:
    @pytest.mark.usefixtures("mock_chroma")
    def test_reindex_success(self, mock_vault_config, temp_docs):
        response = client.put(
            "/ctxvault/reindex",
            json={"file_path": str(temp_docs)}
        )
        assert response.status_code == 200
        data = response.json()
        assert "reindexed_files" in data
        assert "skipped_files" in data
        assert isinstance(data["reindexed_files"], list)
        assert isinstance(data["skipped_files"], list)

    @pytest.mark.usefixtures("mock_chroma")
    def test_reindex_missing_field(self):
        response = client.put(
            "/ctxvault/reindex",
            json={}
        )
        assert response.status_code == 422

    @pytest.mark.usefixtures("mock_chroma")
    def test_reindex_nonexistent_path(self, mock_vault_config):
        response = client.put(
            "/ctxvault/reindex",
            json={"file_path": "/nonexistent/path"}
        )
        assert response.status_code in [200, 404, 400]


class TestListEndpoint:
    @pytest.mark.usefixtures("mock_chroma")
    def test_list_success(self, mock_vault_config):
        response = client.get("/ctxvault/list")
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    @pytest.mark.usefixtures("mock_chroma")
    def test_list_returns_documents(self, mock_vault_config):
        response = client.get("/ctxvault/list")
        assert response.status_code == 200
        data = response.json()
        if data["documents"]:
            assert "doc_id" in data["documents"][0]


class TestEndToEndFlow:
    @pytest.mark.usefixtures("mock_chroma")
    def test_full_workflow(self, mock_vault_not_initialized, tmp_path):
        init_response = client.post(
            "/ctxvault/init",
            json={"vault_path": str(mock_vault_not_initialized.parent)}
        )
        assert init_response.status_code == 200
        
        docs = mock_vault_not_initialized / "docs"
        docs.mkdir()
        (docs / "test.txt").write_text("test content")
        
        index_response = client.put(
            "/ctxvault/index",
            json={"file_path": str(docs)}
        )
        assert index_response.status_code == 200
        
        list_response = client.get("/ctxvault/list")
        assert list_response.status_code == 200
        
        query_response = client.post(
            "/ctxvault/query",
            json={"query": "test"}
        )
        assert query_response.status_code == 200
        
        delete_response = client.delete(
            f"/ctxvault/delete?file_path={docs}"
        )
        assert delete_response.status_code == 200