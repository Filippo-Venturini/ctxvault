"""Pruning through HTTP, MCP and the Python client (#17, part 3).

Reading follows the usual access rules on every door. Changing anything,
applying, the policy, a restore, is a person's decision: HTTP refuses a
request that names an agent, and MCP has no tool for it at all.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import chromadb
import pytest
from fastapi.testclient import TestClient

from ctxvault import Client
from ctxvault.api.app import app
from ctxvault.core import prune_log, vault_router
from ctxvault.core.vaults.base import ARCHIVE_DIR
from ctxvault.mcp import server
from ctxvault.storage import chroma_store
from ctxvault.utils.config import get_vault_config

http = TestClient(app)
AGENT = {"X-CtxVault-Agent": "bot"}
NOW = datetime.now(timezone.utc)

@pytest.fixture
def vault_dir(mock_vault_config, monkeypatch):
    """A real Chroma store with the conftest's fake embeddings."""
    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)
    return mock_vault_config

def agent_metadata():
    return {"generated_by": "agent-x", "timestamp": (NOW + timedelta(minutes=1)).isoformat()}

def put(rel, text, *, agent=False, age_days=1):
    v = vault_router.open_vault("test_vault")
    path = (v.vault_path / rel).resolve()
    if agent:
        v.write_doc(rel, text, agent_metadata=agent_metadata())
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        v.index_file(path)
    stamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path

def two_copies():
    put("a.md", "same words", age_days=1)
    return put("b.md", "same words", age_days=5)

# ── HTTP: reading ───────────────────────────────────────────────────────────

def test_an_agent_reads_the_report_and_nothing_changes(vault_dir):
    copy = two_copies()
    response = http.post("/ctxvault/prune", json={"vault_name": "test_vault"}, headers=AGENT)
    assert response.status_code == 200
    report = response.json()
    assert report["vault_name"] == "test_vault" and report["policy_enabled"] is False
    assert {c["reason"] for c in report["candidates"]} >= {"duplicate"}
    assert copy.exists() and not (vault_dir / ARCHIVE_DIR).exists()

def test_a_report_takes_a_one_off_threshold_and_age(vault_dir):
    put("old.md", "old words", age_days=40)
    response = http.post("/ctxvault/prune", json={"vault_name": "test_vault", "reasons": ["stale"],
                                                  "older_than_days": 30})
    assert [c["signals"]["modified"] for c in response.json()["candidates"]]
    assert "prune" not in get_vault_config("test_vault")   # for this call only

@pytest.mark.parametrize("body", [{"reasons": ["nonsense"]}, {"threshold": 1.5}, {"older_than_days": 0}])
def test_a_report_refuses_what_cannot_hold(vault_dir, body):
    assert http.post("/ctxvault/prune", json={"vault_name": "test_vault", **body}).status_code in (400, 422)

def test_the_policy_reads_as_the_defaults_until_set(vault_dir):
    response = http.get("/ctxvault/prune/policy", params={"vault_name": "test_vault"}, headers=AGENT)
    assert response.status_code == 200
    policy = response.json()["policy"]
    assert policy["enabled"] is False and policy["rules"]["duplicate"]["mode"] == "auto"

def test_a_report_on_a_vault_that_cannot_prune_is_400(mock_skill_vault_config):
    assert http.post("/ctxvault/prune", json={"vault_name": "test_skill_vault"}).status_code == 400

# ── HTTP: changing is a person's ───────────────────────────────────────────

def test_an_agent_cannot_apply_and_a_person_can(vault_dir):
    copy = two_copies()
    body = {"vault_name": "test_vault", "targets": ["b.md"], "apply": True}

    refused = http.post("/ctxvault/prune", json=body, headers=AGENT)
    assert refused.status_code == 403 and "person" in refused.json()["detail"]
    assert copy.exists()

    applied = http.post("/ctxvault/prune", json=body).json()["applied"]
    assert [(e["target"], e["who"]) for e in applied] == [("b.md", "human")] and not copy.exists()

def test_an_agent_cannot_change_the_policy_and_a_person_can(vault_dir):
    body = {"vault_name": "test_vault", "enabled": True, "rules": {"stale": {"mode": "auto", "older_than_days": 365}}}
    assert http.put("/ctxvault/prune/policy", json=body, headers=AGENT).status_code == 403
    assert "prune" not in get_vault_config("test_vault")

    response = http.put("/ctxvault/prune/policy", json=body)
    assert response.status_code == 200
    assert get_vault_config("test_vault")["prune"]["rules"]["stale"] == {"mode": "auto", "older_than_days": 365}

@pytest.mark.parametrize("body", [{"retention_days": 0}, {"rules": {"duplicate_partial": {"mode": "auto"}}},
                                  {"rules": {"nonsense": {"mode": "report"}}}])
def test_a_policy_that_cannot_hold_is_400(vault_dir, body):
    assert http.put("/ctxvault/prune/policy", json={"vault_name": "test_vault", **body}).status_code == 400
    assert "prune" not in get_vault_config("test_vault")

def test_the_log_and_restore(vault_dir):
    copy = two_copies()
    http.post("/ctxvault/prune", json={"vault_name": "test_vault", "targets": ["b.md"], "apply": True})

    entries = http.get("/ctxvault/prune/log", params={"vault_name": "test_vault"}, headers=AGENT).json()["entries"]
    assert [(e["target"], e["reason"]) for e in entries] == [("b.md", "duplicate")]

    body = {"vault_name": "test_vault", "target": "b.md"}
    assert http.post("/ctxvault/prune/restore", json=body, headers=AGENT).status_code == 403
    assert not copy.exists()

    restored = http.post("/ctxvault/prune/restore", json=body)
    assert restored.status_code == 200 and restored.json()["entry"]["restored_at"] and copy.exists()
    assert http.post("/ctxvault/prune/restore", json=body).status_code == 404   # nothing archived there now

def test_restoring_onto_a_taken_path_is_409_unless_overwrite(vault_dir):
    copy = two_copies()
    http.post("/ctxvault/prune", json={"vault_name": "test_vault", "targets": ["b.md"], "apply": True})
    put("b.md", "a new b")
    body = {"vault_name": "test_vault", "target": "b.md"}
    assert http.post("/ctxvault/prune/restore", json=body).status_code == 409
    assert http.post("/ctxvault/prune/restore", json={**body, "overwrite": True}).status_code == 200
    assert copy.read_text() == "same words"

def test_a_log_that_does_not_chain_is_409(vault_dir):
    two_copies()
    http.post("/ctxvault/prune", json={"vault_name": "test_vault", "targets": ["b.md"], "apply": True})
    path = vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME
    path.write_text(path.read_text().replace('"who":"human"', '"who":"policy"'))
    response = http.post("/ctxvault/prune/restore", json={"vault_name": "test_vault", "target": "b.md"})
    assert response.status_code == 409 and "does not chain" in response.json()["detail"]

def test_a_restricted_vault_changes_only_through_the_cli_or_the_client(vault_dir):
    """Over HTTP a restricted vault needs the header, and the header names an
    agent: so the policy of a restricted vault is not changed over HTTP."""
    vault_router.attach_agent("test_vault", "bot")
    body = {"vault_name": "test_vault", "enabled": True}
    assert http.put("/ctxvault/prune/policy", json=body).status_code == 400
    assert http.put("/ctxvault/prune/policy", json=body, headers=AGENT).status_code == 403
    assert http.post("/ctxvault/prune", json={"vault_name": "test_vault"}, headers=AGENT).status_code == 200

    Client().set_prune_policy("test_vault", enabled=True)
    assert get_vault_config("test_vault")["prune"]["enabled"] is True

# ── write_doc says what it pruned ──────────────────────────────────────────

def test_write_doc_over_http_says_what_its_pass_archived(vault_dir):
    old = put("old.md", "same words", agent=True, age_days=5)
    body = {"vault_name": "test_vault", "file_path": "new.md", "content": "same words", "overwrite": True,
            "agent_metadata": agent_metadata()}

    assert http.post("/ctxvault/docs/write", json=body).json()["pruned"] == []   # policy off
    vault_router.set_prune_policy("test_vault", enabled=True)
    os.utime(old, ((NOW - timedelta(days=5)).timestamp(),) * 2)
    body["file_path"] = "newer.md"

    pruned = http.post("/ctxvault/docs/write", json=body).json()["pruned"]
    assert {(e["target"], e["who"], e["trigger"]) for e in pruned} >= {("old.md", "policy", "write_doc")}
    assert not old.exists()

def test_write_doc_through_the_client_returns_the_same(vault_dir):
    put("old.md", "same words", agent=True, age_days=5)
    vault_router.set_prune_policy("test_vault", enabled=True)
    pruned = Client().semantic("test_vault").write_doc("new.md", "same words", agent_metadata=agent_metadata())
    assert [e.target for e in pruned] == ["old.md"]

# ── MCP: read-only ─────────────────────────────────────────────────────────

def test_mcp_has_a_report_and_nothing_that_changes_pruning():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    prune_tools = {name for name in tools if "prune" in name or "restore" in name}
    assert prune_tools == {"prune_report"}
    assert set(tools["prune_report"].inputSchema["properties"]) == {"vault_name", "reasons"}

def test_mcp_prune_report_reads_and_changes_nothing(vault_dir):
    """Even what the policy would archive on its own stays put: the report is
    the policy's preview, never its trigger."""
    put("a.md", "same words", agent=True, age_days=1)
    copy = put("b.md", "same words", agent=True, age_days=5)
    vault_router.set_prune_policy("test_vault", enabled=True)
    report = server.prune_report("test_vault")
    assert any(c.reason == "duplicate" and c.auto_allowed for c in report.candidates)
    assert copy.exists() and not (vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME).exists()

def test_mcp_write_doc_says_what_its_pass_archived(vault_dir):
    old = put("old.md", "same words", agent=True, age_days=5)
    vault_router.set_prune_policy("test_vault", enabled=True)
    was_set = server.warmup_complete.is_set()
    server.warmup_complete.set()
    try:
        response = asyncio.run(server.write_doc("test_vault", "new.md", "same words", generated_by="agent-y"))
    finally:
        if not was_set:
            server.warmup_complete.clear()
    assert [(e.target, e.trigger) for e in response.pruned] == [("old.md", "write_doc")] and not old.exists()
