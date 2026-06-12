from typer.testing import CliRunner
from ctxvault.cli.app import app
import pytest

runner = CliRunner()

# ── Init ────────────────────────────────────────────────────────────────────

def test_cli_init_semantic(mock_vault_not_initialized):
    result = runner.invoke(app, ["init", "test_vault", "--path", str(mock_vault_not_initialized)])
    assert result.exit_code == 0
    assert "Context Vault initialized" in result.stdout

def test_cli_init_skill_vault(mock_global_config):
    result = runner.invoke(app, ["init", "my_skill_vault", "--type", "skill"])
    assert result.exit_code == 0
    assert "Context Vault initialized" in result.stdout

def test_cli_init_already_exists(mock_vault_config):
    result = runner.invoke(app, ["init", "test_vault"])
    assert result.exit_code == 1
    assert "already" in result.stdout.lower()

def test_cli_init_invalid_type(mock_global_config):
    result = runner.invoke(app, ["init", "bad_vault", "--type", "invalid"])
    assert result.exit_code == 1

# ── Semantic vault operations ────────────────────────────────────────────────

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_index_semantic(mock_vault_config):
    result = runner.invoke(app, ["index", "test_vault"])
    assert result.exit_code == 0
    assert "Indexed:" in result.stdout or "Skipped:" in result.stdout

@pytest.mark.usefixtures("mock_chroma")
def test_cli_query_semantic(mock_vault_config):
    result = runner.invoke(app, ["query", "test_vault", "test query"])
    assert result.exit_code == 0
    assert "mock_doc" in result.stdout

def test_cli_query_empty_text(mock_vault_config):
    result = runner.invoke(app, ["query", "test_vault", "   "])
    assert result.exit_code == 1

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_delete_semantic(mock_vault_config, temp_docs):
    result = runner.invoke(app, ["delete", "test_vault"])
    assert result.exit_code == 0
    assert "Deleted:" in result.stdout or "Skipped:" in result.stdout

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_reindex_semantic(mock_vault_config):
    result = runner.invoke(app, ["reindex", "test_vault"])
    assert result.exit_code == 0
    assert "Reindexed: 2" in result.stdout
    assert "Skipped: 0" in result.stdout
    assert "unexpected keyword argument 'vault_config'" not in result.stdout

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_docs_semantic(mock_vault_config):
    result = runner.invoke(app, ["docs", "test_vault"])
    assert result.exit_code == 0
    assert "Found" in result.stdout

@pytest.mark.usefixtures("mock_chroma")
def test_cli_docs_show_semantic(mock_vault_config):
    result = runner.invoke(app, ["docs", "test_vault", "--show", "1"])
    assert result.exit_code == 0
    assert "alpha\n\nbeta" in result.stdout
    assert "Warning:" in result.stdout

@pytest.mark.usefixtures("mock_chroma")
def test_cli_docs_export_semantic(mock_vault_config, tmp_path):
    out = tmp_path / "recovered.txt"
    result = runner.invoke(app, ["docs", "test_vault", "--export", "1", "--output", str(out)])
    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8") == "alpha\n\nbeta"

# ── Skill vault operations ───────────────────────────────────────────────────

def test_cli_index_skill_vault(mock_skill_vault_config, temp_skills):
    result = runner.invoke(app, ["index", "test_skill_vault"])
    assert result.exit_code == 0
    assert "Indexed:" in result.stdout or "Skipped:" in result.stdout

def test_cli_skills_lists_skills(mock_skill_vault_config, temp_skills):
    runner.invoke(app, ["index", "test_skill_vault"])
    result = runner.invoke(app, ["skills", "test_skill_vault"])
    assert result.exit_code == 0
    assert "Found" in result.stdout
    assert "Write Tests" in result.stdout

def test_cli_skill_reads_single_skill(mock_skill_vault_config, temp_skills):
    runner.invoke(app, ["index", "test_skill_vault"])
    result = runner.invoke(app, ["skill", "test_skill_vault", "Write Tests"])
    assert result.exit_code == 0
    assert "Write Tests" in result.stdout
    assert "pytest" in result.stdout

def test_cli_skill_not_found(mock_skill_vault_config):
    result = runner.invoke(app, ["skill", "test_skill_vault", "Nonexistent"])
    assert result.exit_code == 1
    assert "Error" in result.stdout

# ── Cross-type guards ────────────────────────────────────────────────────────

def test_cli_query_on_skill_vault_fails(mock_skill_vault_config):
    result = runner.invoke(app, ["query", "test_skill_vault", "something"])
    assert result.exit_code == 1

def test_cli_skills_on_semantic_vault_fails(mock_vault_config):
    result = runner.invoke(app, ["skills", "test_vault"])
    assert result.exit_code == 1

def test_cli_docs_on_skill_vault_fails(mock_skill_vault_config):
    result = runner.invoke(app, ["docs", "test_skill_vault"])
    assert result.exit_code == 1

def test_cli_skill_on_semantic_vault_fails(mock_vault_config):
    result = runner.invoke(app, ["skill", "test_vault", "anything"])
    assert result.exit_code == 1

# ── Shared behaviors ─────────────────────────────────────────────────────────

@pytest.mark.usefixtures("mock_chroma")
def test_cli_vaults_shows_both_types(mock_vault_config, mock_skill_vault_config):
    result = runner.invoke(app, ["vaults"])
    assert result.exit_code == 0
    assert "SEMANTIC" in result.stdout
    assert "SKILL" in result.stdout

def test_cli_vaults_shows_scope(mock_vault_config):
    result = runner.invoke(app, ["vaults"])
    assert "global" in result.stdout or "local" in result.stdout

def test_cli_delete_purge(mock_vault_config):
    result = runner.invoke(app, ["delete", "test_vault", "--purge"])
    assert result.exit_code == 0
    assert "permanently deleted" in result.stdout