"""The memory viewer: what its JSON says, and what the exported page carries."""

import re

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ctxvault.cli.app import app as cli
from ctxvault.core import vault_router
from ctxvault.ui import server

client = TestClient(server.create_app())
EPISODIC = "test_episodic_vault"

# ── Overview ────────────────────────────────────────────────────────────────

def test_overview_lists_every_vault_with_its_counts(mock_vault_config, mock_skill_vault_config, mock_episodic_vault_config, temp_skills):
    vault_router.write_episode(EPISODIC, "Giuseppe lives in Mestre", entities=["Giuseppe"])
    vault_router.index_files("test_skill_vault")

    data = client.get("/ui/api/overview").json()
    by_name = {v["name"]: v for v in data["vaults"]}

    assert by_name[EPISODIC]["type"] == "episodic"
    assert by_name[EPISODIC]["counts"] == {"total": 1, "open": 1, "closed": 0, "holding": 1, "disputes": 0, "entities": 1}
    assert by_name[EPISODIC]["last_activity"]
    assert by_name["test_skill_vault"]["counts"] == {"skills": 2}
    assert by_name["test_vault"]["counts"]["documents"] == 1   # the mocked chroma holds one document

def test_overview_counts_what_holds_now_as_a_query_sees_it(mock_episodic_vault_config):
    past = "2026-01-01T00:00:00+00:00"
    morning = vault_router.write_episode(EPISODIC, "Takes the pill at 8", valid_from=past)
    evening = vault_router.write_episode(EPISODIC, "Takes the pill in the evening", valid_from=past)
    vault_router.write_episode(EPISODIC, "Starts physio next year", valid_from="2099-01-01T00:00:00+00:00")
    ended = vault_router.write_episode(EPISODIC, "Lives in Mestre", valid_from=past)
    vault_router.invalidate_episode(EPISODIC, ended.id)
    vault_router.dispute_episodes(EPISODIC, morning.id, evening.id)

    counts = client.get("/ui/api/overview").json()["vaults"][0]["counts"]

    assert counts["open"] == 3              # the row's own state: the future one has no end set
    assert counts["holding"] == 2           # not the future one, not the ended one
    assert counts["disputes"] == 1          # one pair, both sides still true

def test_overview_says_where_it_looked(mock_global_config):
    data = client.get("/ui/api/overview").json()

    assert data["vaults"] == []
    assert data["registry"]["local"] is None
    assert data["registry"]["global"] == str(mock_global_config)

def test_a_vault_that_cannot_open_is_listed_with_its_error(mock_global_config, monkeypatch):
    monkeypatch.setattr("ctxvault.ui.server.registry.get_vaults", lambda: [{"name": "ghost", "type": "episodic", "scope": "global"}])

    data = client.get("/ui/api/overview").json()

    assert data["vaults"][0]["name"] == "ghost"
    assert "VaultNotFoundError" in data["vaults"][0]["error"]

def test_overview_says_how_much_each_vault_takes_and_how_it_changed(mock_episodic_vault_config):
    vault_router.write_episode(EPISODIC, "Giuseppe lives in Mestre")

    data = client.get("/ui/api/overview").json()
    vault = data["vaults"][0]

    assert data["activity_days"] == len(vault["activity"]) == 30
    assert vault["activity"][-1] == 1                  # the write, today
    assert vault["disk_bytes"] > 0
    assert vault["last_activity"]

def test_a_vault_whose_folder_is_gone_is_a_problem_not_an_empty_vault(mock_episodic_vault_config):
    import shutil
    from ctxvault.storage import sqlite_store
    sqlite_store.close_connections()
    shutil.rmtree(mock_episodic_vault_config)

    vault = client.get("/ui/api/overview").json()["vaults"][0]

    assert vault["problem"] == "folder missing" and "counts" not in vault
    assert not mock_episodic_vault_config.exists()     # looking did not recreate it

def test_restriction_shows_but_does_not_gate(mock_episodic_vault_config):
    vault_router.attach_agent(EPISODIC, "keeper")

    vault = client.get("/ui/api/overview").json()["vaults"][0]
    assert vault["restricted"] and vault["allowed_agents"] == ["keeper"]
    assert client.get(f"/ui/api/vaults/{EPISODIC}").status_code == 200

# ── Vault payloads ──────────────────────────────────────────────────────────

def test_episodic_payload_carries_the_whole_history(mock_episodic_vault_config):
    first = vault_router.write_episode(EPISODIC, "Sarah is the contact", entities=["Sarah"])
    vault_router.supersede_episode(EPISODIC, first.id, "Marco is the contact", entities=["Marco"])

    payload = client.get(f"/ui/api/vaults/{EPISODIC}").json()

    assert payload["type"] == "episodic"
    assert {e["content"] for e in payload["episodes"]} == {"Sarah is the contact", "Marco is the contact"}
    closed = next(e for e in payload["episodes"] if e["content"].startswith("Sarah"))
    assert closed["superseded_by"] and closed["valid_to"]
    assert {e["entity"] for e in payload["entities"]} == {"Sarah", "Marco"}
    assert payload["stats"] == {"total": 2, "open": 1, "closed": 1, "holding": 1, "disputes": 0}

def test_episodic_payload_says_who_confirmed_and_when_a_dispute_was_noticed(mock_episodic_vault_config):
    morning = vault_router.write_episode(EPISODIC, "Takes the pill at 8", valid_from="2026-09-01T00:00:00+00:00")
    evening = vault_router.write_episode(EPISODIC, "Takes the pill in the evening", valid_from="2026-09-01T00:00:00+00:00")
    vault_router.confirm_episode(EPISODIC, morning.id, at="2026-10-02T09:00:00+00:00", source="carer")
    vault_router.dispute_episodes(EPISODIC, morning.id, evening.id, at="2026-11-01T10:00:00+00:00", note="different times")

    episodes = {e["id"]: e for e in client.get(f"/ui/api/vaults/{EPISODIC}").json()["episodes"]}

    assert [(a["at"][:10], a["source"]) for a in episodes[morning.id]["attestations"]] == [("2026-10-02", "carer")]
    assert episodes[evening.id]["attestations"] == []
    for one, other in ((morning, evening), (evening, morning)):
        (dispute,) = episodes[one.id]["disputes"]
        assert dispute["with"] == other.id and dispute["noticed_at"].startswith("2026-11-01") and dispute["note"] == "different times"

def test_reading_the_payload_leaves_no_trace(mock_episodic_vault_config):
    episode = vault_router.write_episode(EPISODIC, "Giuseppe lives in Mestre")

    client.get(f"/ui/api/vaults/{EPISODIC}")

    assert vault_router.get_episode(EPISODIC, episode.id).recall_count == 0

def test_skill_payload_includes_the_instructions(mock_skill_vault_config, temp_skills):
    vault_router.index_files("test_skill_vault")

    payload = client.get("/ui/api/vaults/test_skill_vault").json()

    by_name = {s["skill_name"]: s for s in payload["skills"]}
    assert by_name["Write Tests"]["instructions"] == "Always use pytest."

def test_skill_payload_carries_the_extra_frontmatter_as_the_skill_metadata(mock_skill_vault_config):
    (mock_skill_vault_config / "deploy.md").write_text(
        "---\nname: Deploy\ndescription: Ship it\nversion: 3\nreviewed: 2026-10-20\ntags: [ops, ci]\n---\nRun the pipeline.")
    vault_router.index_files("test_skill_vault")

    skill = client.get("/ui/api/vaults/test_skill_vault").json()["skills"][0]

    assert skill["metadata"] == {"version": 3, "reviewed": "2026-10-20", "tags": ["ops", "ci"]}
    assert skill["size_bytes"] > 0 and skill["last_modified"]
    assert skill["metadata"] == vault_router.read_skill("test_skill_vault", "Deploy").model_dump(mode="json")["metadata"]

def test_semantic_payload_lists_documents(mock_vault_config):
    payload = client.get("/ui/api/vaults/test_vault").json()

    assert payload["type"] == "semantic"
    assert payload["documents"][0]["doc_id"] == "1"

def test_document_text_and_search_are_for_semantic_vaults_only(mock_vault_config, mock_episodic_vault_config):
    assert client.get("/ui/api/vaults/test_vault/documents/1").json()["content"] == "alpha\n\nbeta"
    assert client.get("/ui/api/vaults/test_vault/search?q=anything").json()["results"]
    assert client.get(f"/ui/api/vaults/{EPISODIC}/documents/1").status_code == 400
    assert client.get(f"/ui/api/vaults/{EPISODIC}/search?q=anything").status_code == 400

def test_on_the_api_server_the_viewer_answers_only_the_machine_itself(mock_episodic_vault_config, monkeypatch):
    # The API may listen beyond localhost for agents; the viewer shows every
    # vault without any agent gating, so there it is loopback only.
    from ctxvault.api.app import app as api
    api_client = TestClient(api)                                   # TestClient is not loopback

    assert api_client.get("/ui/api/overview").status_code == 403
    assert api_client.get(f"/ui/api/vaults/{EPISODIC}").status_code == 403
    assert api_client.get("/ui/").status_code == 403

    monkeypatch.setattr(server, "_is_local", lambda request: True)
    assert api_client.get("/ui/api/overview").status_code == 200

    # `ctxvault ui` serves whatever host was chosen on purpose
    assert client.get("/ui/api/overview").status_code == 200

def test_reveal_opens_the_registered_folder_and_only_for_local_requests(mock_skill_vault_config, monkeypatch):
    opened = []
    monkeypatch.setattr(server, "_reveal", opened.append)

    assert client.post("/ui/api/vaults/test_skill_vault/reveal").status_code == 403   # TestClient is not loopback
    assert opened == []

    monkeypatch.setattr(server, "_is_local", lambda request: True)
    assert client.post("/ui/api/vaults/test_skill_vault/reveal").json()["opened"] == str(mock_skill_vault_config)
    assert opened == [str(mock_skill_vault_config)]
    assert client.post("/ui/api/vaults/nowhere/reveal").status_code == 404

def test_unknown_vault_is_404(mock_global_config):
    assert client.get("/ui/api/vaults/nowhere").status_code == 404

def test_the_page_and_its_assets_are_served(mock_global_config):
    assert "<div id=\"app\">" in client.get("/ui/").text
    assert client.get("/ui/static/app.js").status_code == 200
    assert client.get("/ui/static/vendor/preact.umd.js").status_code == 200
    assert client.get("/").status_code == 200   # redirected to the page

# ── Export ──────────────────────────────────────────────────────────────────

def test_export_is_one_self_contained_file(mock_episodic_vault_config, tmp_path):
    vault_router.write_episode(EPISODIC, "Content with </script> inside", entities=["Giuseppe"])

    html = server.export(tmp_path / "memory.html").read_text(encoding="utf-8")

    assert "window.CTXVAULT_SNAPSHOT = " in html
    assert "Content with <\\/script> inside" in html          # cannot close the script tag early
    assert "const CV = " in html and "liveSource" in html       # the app, inlined
    assert "const MD = " in html                                # the markdown reader, inlined
    assert "data:font/woff2;base64," in html                    # the fonts, inlined
    assert "window.CTXVAULT_ASSETS = " in html and "data:image/svg+xml;base64," in html  # the logos, inlined
    assert not re.search(r'(?:src|href)="(?!#)[^"]+"', html)   # nothing left to fetch
    assert "preload" not in html

def test_export_can_carry_a_note_for_whoever_opens_it(mock_episodic_vault_config, tmp_path):
    html = server.export(tmp_path / "memory.html", note="A demo: three agents, six vaults. Hover a vault, drag the time cursor.").read_text(encoding="utf-8")
    assert 'window.CTXVAULT_NOTE = "A demo: three agents, six vaults. Hover a vault, drag the time cursor."' in html
    assert "\nwindow.CTXVAULT_NOTE = \"" not in server.export(tmp_path / "plain.html").read_text(encoding="utf-8")

def test_export_carries_every_vault_payload(mock_skill_vault_config, mock_episodic_vault_config, temp_skills):
    vault_router.index_files("test_skill_vault")

    data = server.snapshot()

    by_name = {v["name"]: v for v in data["vaults"]}
    assert "episodes" in by_name[EPISODIC]["payload"]
    assert len(by_name["test_skill_vault"]["payload"]["skills"]) == 2

def test_cli_ui_export(mock_episodic_vault_config, tmp_path):
    out = tmp_path / "memory.html"

    result = CliRunner().invoke(cli, ["ui", "--export", str(out)])

    assert result.exit_code == 0, result.output
    assert "Snapshot written" in result.output
    assert out.exists() and "CTXVAULT_SNAPSHOT" in out.read_text(encoding="utf-8")

def test_snapshot_carries_document_text(mock_vault_config):
    data = server.snapshot()

    payload = next(v for v in data["vaults"] if v["name"] == "test_vault")["payload"]
    assert payload["contents"]["1"]["content"] == "alpha\n\nbeta"

def test_document_comes_with_its_chunks_in_index_order(mock_vault_config):
    doc = client.get("/ui/api/vaults/test_vault/documents/1").json()

    assert [(c["index"], c["text"], c["words"]) for c in doc["chunks"]] == [(0, "alpha", 1), (1, "beta", 1)]
    assert doc["chunks"] == [{"index": i, "text": t, "words": 1} for i, t in enumerate(vault_router.open_vault("test_vault").get_document_chunks("1"))]

def test_the_page_shows_the_index_state_the_vault_reports(mock_vault_config, monkeypatch):
    import os
    from ctxvault.storage import chroma_store
    fresh, stale, never = mock_vault_config / "fresh.md", mock_vault_config / "stale.md", mock_vault_config / "never.md"
    fresh.write_text("a"); stale.write_text("b"); never.write_text("c")
    os.utime(fresh, (1_700_000_000, 1_700_000_000))   # 2023, before indexing
    os.utime(stale, (1_800_000_000, 1_800_000_000))   # 2027, after indexing
    at = "2026-01-01T00:00:00+00:00"
    monkeypatch.setattr(chroma_store, "get_all_metadatas", lambda config: [
        {"doc_id": "f", "source": str(fresh), "filetype": ".md", "indexed_at": at, "topic": "x"},
        {"doc_id": "s", "source": str(stale), "filetype": ".md", "indexed_at": at},
        {"doc_id": "m", "source": str(mock_vault_config / "gone.md"), "filetype": ".md", "indexed_at": at},
    ])

    payload = client.get("/ui/api/vaults/test_vault").json()
    counts = client.get("/ui/api/overview").json()["vaults"][0]["counts"]

    assert {d["doc_id"]: d["state"] for d in payload["documents"]} == {"f": "in_sync", "s": "changed", "m": "missing"}
    assert payload["unindexed"] == [str(never)]
    assert counts["out_of_sync"] == 2 and counts["unindexed"] == 1
    assert next(d for d in payload["documents"] if d["doc_id"] == "f")["metadata"] == {"topic": "x"}

def test_static_files_are_revalidated_so_an_upgrade_is_never_served_stale():
    response = client.get("/ui/static/app.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
