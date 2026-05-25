from fastapi.testclient import TestClient
from ctxvault.api.app import app, ctxvault_router
from pathlib import Path

app.include_router(ctxvault_router)
client = TestClient(app)


class TestIndexEndpoint:
    def test_index_success(self, mock_vault_config, temp_docs):
        response = client.put(
            "/ctxvault/index",
            json={"vault_name": "test_vault", "file_path": str(temp_docs)}
        )
        assert response.status_code == 200
        data = response.json()
        assert "indexed_files" in data
        assert "skipped_files" in data

    def test_index_missing_file_path(self, mock_vault_config):
        response = client.put("/ctxvault/index", json={"vault_name": "test_vault"})
        assert response.status_code == 200
        assert isinstance(response.json()["indexed_files"], list)


class TestQueryEndpoint:
    def test_query_success(self, mock_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"vault_name": "test_vault", "query": "test query"}
        )
        assert response.status_code == 200
        assert len(response.json()["results"]) > 0

    def test_query_empty_string(self, mock_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"vault_name": "test_vault", "query": ""}
        )
        assert response.status_code == 400
        assert "Query text cannot be empty." in response.json()["detail"]

    def test_query_no_results(self, mock_vault_config, monkeypatch):
        from ctxvault.core import vault_router
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.results = []
        monkeypatch.setattr(vault_router, "query", lambda vault_name, text, filters=None: mock_result)
        response = client.post(
            "/ctxvault/query",
            json={"vault_name": "test_vault", "query": "nonexistent"}
        )
        assert response.status_code == 404

    def test_query_on_skill_vault_returns_400(self, mock_skill_vault_config):
        response = client.post(
            "/ctxvault/query",
            json={"vault_name": "test_skill_vault", "query": "something"}
        )
        assert response.status_code == 400


class TestDeleteEndpoint:
    def test_delete_success(self, mock_vault_config, temp_docs):
        response = client.delete(
            "/ctxvault/delete",
            params={"vault_name": "test_vault", "file_path": str(temp_docs)}
        )
        assert response.status_code == 200
        data = response.json()
        assert "deleted_files" in data
        assert "skipped_files" in data

    def test_delete_missing_param(self, mock_vault_config):
        response = client.delete("/ctxvault/delete", params={"vault_name": "test_vault"})
        assert response.status_code == 200


class TestReindexEndpoint:
    def test_reindex_success(self, mock_vault_config, temp_docs):
        response = client.put(
            "/ctxvault/reindex",
            json={"vault_name": "test_vault", "file_path": str(temp_docs)}
        )
        assert response.status_code == 200
        assert "reindexed_files" in response.json()

    def test_reindex_missing_field(self, mock_vault_config):
        response = client.put("/ctxvault/reindex", json={"vault_name": "test_vault"})
        assert response.status_code == 200


class TestListVaultsEndpoint:
    def test_list_vaults(self, mock_global_config):
        response = client.get("/ctxvault/vaults")
        assert response.status_code == 200
        assert isinstance(response.json()["vaults"], list)

    def test_list_vaults_contains_both_types(self, mock_vault_config, mock_skill_vault_config):
        response = client.get("/ctxvault/vaults")
        assert response.status_code == 200
        data = response.json()
        types = {vault["type"] for vault in data["vaults"]}
        assert "semantic" in types
        assert "skill" in types


class TestListDocsEndpoint:
    def test_list_docs_success(self, mock_vault_config):
        response = client.get("/ctxvault/docs", params={"vault_name": "test_vault"})
        assert response.status_code == 200
        data = response.json()
        assert "vault_name" in data
        assert "documents" in data

    def test_list_docs_on_skill_vault_returns_400(self, mock_skill_vault_config):
        response = client.get("/ctxvault/docs", params={"vault_name": "test_skill_vault"})
        assert response.status_code == 400


class TestDocContentEndpoint:
    def test_doc_content_success(self, mock_vault_config):
        response = client.get(
            "/ctxvault/docs/1/content",
            params={"vault_name": "test_vault"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["vault_name"] == "test_vault"
        assert data["document"]["doc_id"] == "1"
        assert data["document"]["content"] == "alpha beta"
        assert data["document"]["content_hash"]
        assert data["document"]["warning"]

    def test_doc_content_not_found(self, mock_vault_config):
        response = client.get(
            "/ctxvault/docs/missing/content",
            params={"vault_name": "test_vault"},
        )
        assert response.status_code == 404

    def test_doc_content_on_skill_vault_returns_400(self, mock_skill_vault_config):
        response = client.get(
            "/ctxvault/docs/1/content",
            params={"vault_name": "test_skill_vault"},
        )
        assert response.status_code == 400


class TestListSkillsEndpoint:
    def test_list_skills_success(self, mock_skill_vault_config, temp_skills):
        client.put("/ctxvault/index", json={"vault_name": "test_skill_vault"})
        response = client.get("/ctxvault/skills", params={"vault_name": "test_skill_vault"})
        assert response.status_code == 200
        data = response.json()
        assert "vault_name" in data
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_list_skills_on_semantic_vault_returns_400(self, mock_vault_config):
        response = client.get("/ctxvault/skills", params={"vault_name": "test_vault"})
        assert response.status_code == 400


class TestReadSkillEndpoint:
    def test_read_skill_success(self, mock_skill_vault_config, temp_skills):
        client.put("/ctxvault/index", json={"vault_name": "test_skill_vault"})
        response = client.get(
            "/ctxvault/skill",
            params={"vault_name": "test_skill_vault", "skill_name": "Write Tests"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["skill"]["name"] == "Write Tests"
        assert "pytest" in data["skill"]["instructions"]

    def test_read_skill_not_found_returns_500(self, mock_skill_vault_config):
        response = client.get(
            "/ctxvault/skill",
            params={"vault_name": "test_skill_vault", "skill_name": "Nonexistent"}
        )
        assert response.status_code == 500

    def test_read_skill_on_semantic_vault_returns_400(self, mock_vault_config):
        response = client.get(
            "/ctxvault/skill",
            params={"vault_name": "test_vault", "skill_name": "anything"}
        )
        assert response.status_code == 400


class TestWriteDocEndpoint:
    def test_write_doc_success(self, mock_vault_config):
        response = client.post("/ctxvault/docs/write", json={
            "vault_name": "test_vault",
            "file_path": "test.md",
            "content": "Hello world",
            "overwrite": True
        })
        assert response.status_code == 200
        assert response.json()["file_path"] == "test.md"
        assert (mock_vault_config / "test.md").exists()

    def test_write_doc_no_overwrite_conflict(self, mock_vault_config):
        client.post("/ctxvault/docs/write", json={
            "vault_name": "test_vault",
            "file_path": "dup.md",
            "content": "first",
            "overwrite": True
        })
        response = client.post("/ctxvault/docs/write", json={
            "vault_name": "test_vault",
            "file_path": "dup.md",
            "content": "second",
            "overwrite": False
        })
        assert response.status_code == 409

    def test_write_doc_on_skill_vault_returns_400(self, mock_skill_vault_config):
        response = client.post("/ctxvault/docs/write", json={
            "vault_name": "test_skill_vault",
            "file_path": "test.md",
            "content": "hello",
            "overwrite": True
        })
        assert response.status_code == 400


class TestWriteSkillEndpoint:
    def test_write_skill_success(self, mock_skill_vault_config):
        response = client.post("/ctxvault/skills/write", json={
            "vault_name": "test_skill_vault",
            "skill_name": "Deploy Service",
            "description": "How to deploy",
            "instructions": "Run docker build.",
            "overwrite": True
        })
        assert response.status_code == 200
        assert "filename" in response.json()
        assert (mock_skill_vault_config / response.json()["filename"]).exists()

    def test_write_skill_no_overwrite_conflict(self, mock_skill_vault_config):
        payload = {
            "vault_name": "test_skill_vault",
            "skill_name": "Deploy Service",
            "description": "How to deploy",
            "instructions": "Run docker build.",
            "overwrite": True
        }
        client.post("/ctxvault/skills/write", json=payload)
        response = client.post("/ctxvault/skills/write", json={**payload, "overwrite": False})
        assert response.status_code == 409

    def test_write_skill_on_semantic_vault_returns_400(self, mock_vault_config):
        response = client.post("/ctxvault/skills/write", json={
            "vault_name": "test_vault",
            "skill_name": "My Skill",
            "description": "desc",
            "instructions": "do stuff",
            "overwrite": True
        })
        assert response.status_code == 400