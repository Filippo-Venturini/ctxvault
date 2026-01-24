from typer.testing import CliRunner
from ctxvault.cli.app import app
from pathlib import Path

import pytest

runner = CliRunner()

def test_cli_init(mock_vault_not_initialized):
    result = runner.invoke(app, ["init", "--path", str(mock_vault_not_initialized)])
    assert result.exit_code == 0
    assert "Context Vault initialized" in result.stdout

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_index(mock_vault_config, temp_docs):
    result = runner.invoke(app, ["index", "--path", str(temp_docs)])
    assert result.exit_code == 0
    assert "Indexed:" in result.stdout or "Skipped:" in result.stdout

@pytest.mark.usefixtures("mock_chroma")
def test_cli_query(mock_vault_config):
    result = runner.invoke(app, ["query", "--text", "test query"])
    assert result.exit_code == 0
    assert "mock_doc" in result.stdout

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_delete(mock_vault_config,temp_docs):
    result = runner.invoke(app, ["delete", "--path", str(temp_docs)])
    assert result.exit_code == 0
    assert "Deleted:" in result.stdout or "Skipped:" in result.stdout

@pytest.mark.usefixtures("mock_chroma", "temp_docs")
def test_cli_reindex(mock_vault_config, temp_docs):
    result = runner.invoke(app, ["reindex", "--path", str(temp_docs)])
    assert result.exit_code == 0
    assert "Reindexed:" in result.stdout or "Skipped:" in result.stdout

@pytest.mark.usefixtures("mock_chroma")
def test_cli_list(mock_vault_config):
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Found" in result.stdout
