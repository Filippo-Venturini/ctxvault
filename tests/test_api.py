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
        monkeypatch.setattr(vault, "query", lambda text, filters=None: mock_result)
        
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
    def test_full_workflow(self, mock_vault_config, temp_docs):
        
        list_response = client.get("/ctxvault/list")
        assert list_response.status_code == 200
        
        index_response = client.put(
            "/ctxvault/index",
            json={"file_path": str(temp_docs)}
        )
        assert index_response.status_code == 200
        assert "indexed_files" in index_response.json()
        
        list_response = client.get("/ctxvault/list")
        assert list_response.status_code == 200
        
        query_response = client.post(
            "/ctxvault/query",
            json={"query": "test"}
        )
        assert query_response.status_code == 200
        assert "results" in query_response.json()
        
        reindex_response = client.put(
            "/ctxvault/reindex",
            json={"file_path": str(temp_docs)}
        )
        assert reindex_response.status_code == 200
        
        delete_response = client.delete(
            f"/ctxvault/delete?file_path={temp_docs}"
        )
        assert delete_response.status_code == 200
        assert "deleted_files" in delete_response.json()


class TestWriteEndpoint:

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_success_new_file(self, mock_vault_config):
        file_path = mock_vault_config / "test.md"
        content = "Hello world"

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": content,
            "overwrite": True
        })

        assert response.status_code == 200
        data = response.json()
        assert data["file_path"] == str(file_path)
        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == content

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_success_overwrite(self, mock_vault_config):
        file_path = mock_vault_config / "test.md"
        file_path.write_text("Old content", encoding="utf-8")
        content = "New content"

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": content,
            "overwrite": True
        })

        assert response.status_code == 200
        assert file_path.read_text(encoding="utf-8") == content

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_fail_no_overwrite(self, mock_vault_config):
        file_path = mock_vault_config / "test.md"
        file_path.write_text("Existing content", encoding="utf-8")

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": "New content",
            "overwrite": False
        })

        assert response.status_code == 409
        assert "already exist" in response.json()["detail"]

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_fail_unsupported_extension(self, tmp_path):
        file_path = tmp_path / "test.exe"
        content = "Should fail"

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": content,
            "overwrite": True
        })

        assert response.status_code == 400
        assert "File type not supported" in response.json()["detail"]

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_fail_missing_extension(self, tmp_path):
        file_path = tmp_path / "test"  
        content = "No ext"

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": content,
            "overwrite": True
        })

        assert response.status_code == 400
        assert "File type not present" in response.json()["detail"]

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_fail_file_outside_vault(self, tmp_path):

        vault_root = Path("/tmp/ctxvault")  
        file_path = tmp_path / "outside.md"
        content = "Hello"

        response = client.post("/ctxvault/write", json={
            "file_path": str(file_path),
            "content": content,
            "overwrite": True
        })

        assert response.status_code == 400
        assert "must have a path inside the Context Vault" in response.json()["detail"]

    @pytest.mark.usefixtures("mock_vault_config")
    def test_write_missing_field(self, tmp_path):
        response = client.post("/ctxvault/write", json={})
        assert response.status_code == 422 
