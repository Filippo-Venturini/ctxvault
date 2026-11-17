import json
import math
import os
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from ctxvault.cli.app import app
from ctxvault.core import vault_router
from ctxvault.core.exceptions import UnsupportedVaultOperationError
from ctxvault.models.pruning import PruneAction, PrunePolicy
from ctxvault.storage import chroma_store

runner = CliRunner()

class FakeCollection:
    """Enough of a Chroma collection for pruning: chunks with metadata, text
    and embeddings; `get` and a brute-force `query` that honours
    `{"doc_id": {"$ne": ...}}` and ranks by the collection's own space."""

    def __init__(self, space="cosine"):
        self.metadata = {"hnsw:space": space}
        self.rows = []

    def add(self, doc_id, source, chunks, extra=None):
        for i, (text, vector) in enumerate(chunks):
            meta = {"doc_id": doc_id, "chunk_id": f"{doc_id}::{i}", "chunk_index": i, "source": str(source),
                    "filetype": ".txt", "indexed_at": "2026-01-01T00:00:00+00:00", "chunk_repeated_words": 0}
            meta.update(extra or {})
            self.rows.append((meta, text, vector))

    def get(self, include=None, where=None):
        rows = [r for r in self.rows if not where or r[0]["doc_id"] == where.get("doc_id")]
        out = {"metadatas": [r[0] for r in rows], "documents": [r[1] for r in rows]}
        if include and "embeddings" in include:
            out["embeddings"] = [r[2] for r in rows]
        return out

    def _distance(self, a, b):
        if self.metadata["hnsw:space"] == "l2":
            return sum((x - y) ** 2 for x, y in zip(a, b))
        dot = sum(x * y for x, y in zip(a, b))
        return 1 - dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    def query(self, query_embeddings, n_results, where=None, include=None):
        excluded = (where or {}).get("doc_id", {}).get("$ne")
        pool = [r for r in self.rows if r[0]["doc_id"] != excluded]
        out = {"metadatas": [], "embeddings": [], "documents": [], "distances": []}
        for q in query_embeddings:
            ranked = sorted(pool, key=lambda r: self._distance(q, r[2]))[:n_results]
            out["metadatas"].append([r[0] for r in ranked])
            out["embeddings"].append([r[2] for r in ranked])
            out["documents"].append([r[1] for r in ranked])
            out["distances"].append([self._distance(q, r[2]) for r in ranked])
        return out

@pytest.fixture
def collection(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(chroma_store, "get_collection", lambda config: fake)
    return fake

def write(path, text, days_old=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    moment = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    os.utime(path, (moment, moment))
    return path

def agent(path, after_seconds=60):
    """Metadata of an agent write that happened after the file's mtime."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) + timedelta(seconds=after_seconds)
    return {"generated_by": "test-agent", "timestamp": stamp.isoformat()}

A, B, C = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]

def by_reason(report, reason):
    return [c for c in report.candidates if c.reason == reason]

# ── Identical documents ─────────────────────────────────────────────────────

def test_identical_documents_keep_the_newer_and_hold_a_human_written_copy(mock_vault_config, collection):
    new = write(mock_vault_config / "notes" / "setup.md", "Setup:  run it.\n", days_old=1)
    old = write(mock_vault_config / "archive" / "setup-old.md", "Setup: run it.", days_old=30)
    collection.add("n", new, [("Setup: run it.", A)])
    collection.add("o", old, [("Setup: run it.", A)])

    report = vault_router.prune("test_vault", reasons=["duplicate"])

    dupes = by_reason(report, "duplicate")
    assert {c.target: c.suggested_action for c in dupes} == {str(new): PruneAction.NONE, str(old): PruneAction.ARCHIVE}
    assert dupes[0].group == dupes[1].group
    assert [c.target for c in report.held] == [str(old)]
    assert not any(c.auto_allowed for c in dupes)

def test_an_agent_written_copy_is_auto_allowed_only_when_the_policy_is_on(mock_vault_config, collection):
    new = write(mock_vault_config / "a.txt", "same text", days_old=1)
    old = write(mock_vault_config / "b.txt", "same text", days_old=5)
    collection.add("a", new, [("same text", A)])
    collection.add("b", old, [("same text", A)], extra=agent(old))
    vault = vault_router.open_vault("test_vault")

    off = vault.prune(reasons={"duplicate"})
    assert off.held == [] and not any(c.auto_allowed for c in off.candidates)

    on = vault.prune(reasons={"duplicate"}, policy=PrunePolicy.for_vault({"prune": {"enabled": True}}, vault.prune_reasons))
    assert [c.target for c in on.candidates if c.auto_allowed] == [str(old)]

def test_an_agent_written_file_edited_since_counts_as_human_written(mock_vault_config, collection):
    new = write(mock_vault_config / "a.txt", "same text", days_old=1)
    old = write(mock_vault_config / "b.txt", "same text", days_old=5)
    collection.add("a", new, [("same text", A)])
    collection.add("b", old, [("same text", A)], extra=agent(old, after_seconds=-3600))  # edited after the agent

    report = vault_router.prune("test_vault", reasons=["duplicate"])

    assert [c.target for c in report.held] == [str(old)]
    assert by_reason(report, "duplicate")[1].signals["agent_written"] is False

def test_generated_by_without_a_timestamp_counts_as_human_written(mock_vault_config, collection):
    new = write(mock_vault_config / "a.txt", "same text", days_old=1)
    old = write(mock_vault_config / "b.txt", "same text", days_old=5)
    collection.add("a", new, [("same text", A)])
    collection.add("b", old, [("same text", A)], extra={"generated_by": "client-script"})

    report = vault_router.prune("test_vault", reasons=["duplicate"])

    assert [c.target for c in report.held] == [str(old)]

# ── Partial overlap ─────────────────────────────────────────────────────────

def test_chunks_of_one_document_never_match_each_other(mock_vault_config, collection):
    doc = write(mock_vault_config / "long.txt", "one long document")
    collection.add("l", doc, [("overlap", A), ("overlap", A)])

    assert by_reason(vault_router.prune("test_vault", reasons=["duplicate_partial"]), "duplicate_partial") == []

def test_a_shared_passage_is_reported_on_both_sides_and_never_suggested_for_removal(mock_vault_config, collection):
    install = write(mock_vault_config / "docs" / "install.md", "install doc")
    readme = write(mock_vault_config / "README.md", "readme doc")
    collection.add("i", install, [("Installation requires Python 3.10+", A), ("Other things", B)], extra=agent(install))
    collection.add("r", readme, [("Python 3.10 or higher is required", A), ("Unrelated", C)])

    report = vault_router.prune("test_vault", reasons=["duplicate_partial"])

    partial = by_reason(report, "duplicate_partial")
    assert sorted(c.target for c in partial) == sorted([str(install), str(readme)])
    assert all(c.suggested_action == PruneAction.NONE and not c.auto_allowed for c in partial)
    assert report.held == []
    assert {c.signals["matched_chunks"] for c in partial} == {1}
    assert {c.signals["total_chunks"] for c in partial} == {2}
    assert partial[0].signals["cosine_sim"] == 1.0

def test_similarity_is_cosine_from_the_stored_embeddings_on_an_l2_collection(mock_vault_config, collection):
    collection.metadata = {"hnsw:space": "l2"}   # made before the cosine switch
    x = write(mock_vault_config / "x.txt", "x")
    y = write(mock_vault_config / "y.txt", "y")
    collection.add("x", x, [("passage", [1.0, 2.0, 0.0])])
    collection.add("y", y, [("passage", [3.0, 6.0, 0.0])])   # same direction, far away in l2

    partial = by_reason(vault_router.prune("test_vault", reasons=["duplicate_partial"]), "duplicate_partial")

    assert len(partial) == 2 and partial[0].signals["cosine_sim"] == 1.0

def test_identical_documents_are_not_also_reported_as_partial_overlap(mock_vault_config, collection):
    a = write(mock_vault_config / "a.txt", "same", days_old=1)
    b = write(mock_vault_config / "b.txt", "same", days_old=2)
    collection.add("a", a, [("same", A)])
    collection.add("b", b, [("same", A)])

    report = vault_router.prune("test_vault", reasons=["duplicate", "duplicate_partial"])

    assert len(by_reason(report, "duplicate")) == 2
    assert by_reason(report, "duplicate_partial") == []

def test_a_model_with_no_known_threshold_skips_partial_overlap_unless_one_is_given(mock_vault_config, collection):
    from ctxvault.utils.config import set_embedding_model
    set_embedding_model("test_vault", "some-other-model")
    x = write(mock_vault_config / "x.txt", "x")
    y = write(mock_vault_config / "y.txt", "y")
    collection.add("x", x, [("p", A)])
    collection.add("y", y, [("p", A)])

    skipped = vault_router.prune("test_vault", reasons=["duplicate_partial"])
    assert by_reason(skipped, "duplicate_partial") == []
    assert any("no known threshold" in note for note in skipped.notes)

    given = vault_router.prune("test_vault", reasons=["duplicate_partial"], threshold=0.9)
    assert len(by_reason(given, "duplicate_partial")) == 2
    assert given.signals["model"] == "some-other-model"

# ── Stale ───────────────────────────────────────────────────────────────────

def test_stale_reads_the_files_age_not_indexed_at(mock_vault_config, collection):
    old = write(mock_vault_config / "drafts" / "v1-api.md", "old", days_old=279)
    fresh = write(mock_vault_config / "current.md", "new", days_old=3)
    collection.add("o", old, [("old", A)])      # indexed_at is recent for both
    collection.add("f", fresh, [("new", B)])

    stale = by_reason(vault_router.prune("test_vault", reasons=["stale"]), "stale")
    assert [c.target for c in stale] == [str(old)]
    assert stale[0].signals["age_days"] == 279

    assert by_reason(vault_router.prune("test_vault", reasons=["stale"], older_than_days=300), "stale") == []

def test_an_indexed_document_with_no_file_is_skipped_and_noted(mock_vault_config, collection):
    collection.add("g", mock_vault_config / "gone.txt", [("gone", A)])

    report = vault_router.prune("test_vault")

    assert report.candidates == []
    assert any("no file on disk" in note for note in report.notes)

# ── The base flow ───────────────────────────────────────────────────────────

def test_the_stored_policy_sets_the_modes(mock_vault_config, collection):
    old = write(mock_vault_config / "old.md", "old", days_old=400)
    collection.add("o", old, [("old", A)], extra=agent(old))
    vault = vault_router.open_vault("test_vault")
    vault.config["prune"] = {"enabled": True, "rules": {"stale": {"mode": "auto", "older_than_days": 90}}}

    report = vault.prune(reasons={"stale"})

    assert report.policy_enabled is True
    assert [c.auto_allowed for c in report.candidates] == [True]

    vault.config["prune"] = {"enabled": True, "rules": {"stale": {"mode": "off"}}}
    assert vault.prune(reasons={"stale"}).candidates == []

def test_targets_and_reasons_narrow_the_report(mock_vault_config, collection):
    a = write(mock_vault_config / "a.txt", "same", days_old=400)
    b = write(mock_vault_config / "b.txt", "same", days_old=500)
    collection.add("a", a, [("same", A)])
    collection.add("b", b, [("same", A)])

    only_b = vault_router.prune("test_vault", targets=["b.txt"])
    assert {c.target for c in only_b.candidates} == {str(b)}
    assert {c.reason for c in only_b.candidates} == {"duplicate", "stale"}

    with pytest.raises(ValueError, match="Unknown prune reason"):
        vault_router.prune("test_vault", reasons=["everything"])

def test_prune_does_not_change_the_vault(mock_vault_config, collection):
    a = write(mock_vault_config / "a.txt", "same", days_old=400)
    b = write(mock_vault_config / "b.txt", "same", days_old=500)
    collection.add("a", a, [("same", A)], extra=agent(a))
    collection.add("b", b, [("same", A)], extra=agent(b))
    before = list(collection.rows)
    vault = vault_router.open_vault("test_vault")

    vault.prune(policy=PrunePolicy.for_vault({"prune": {"enabled": True, "rules": {"stale": {"mode": "auto"}}}},
                                             vault.prune_reasons))

    assert collection.rows == before and a.exists() and b.exists()
    assert not vault.archive_path.exists()

@pytest.mark.parametrize("fixture", ["mock_episodic_vault_config", "mock_skill_vault_config"])
def test_other_vault_types_do_not_prune_yet(fixture, request):
    request.getfixturevalue(fixture)
    name = "test_episodic_vault" if "episodic" in fixture else "test_skill_vault"

    with pytest.raises(UnsupportedVaultOperationError):
        vault_router.prune(name)

# ── Archive directory and delete_file ───────────────────────────────────────

def test_the_archive_is_outside_every_walk_of_the_vault(mock_vault_config, monkeypatch):
    from ctxvault.core.vaults.semantic import SemanticVault
    kept = write(mock_vault_config / "kept.txt", "kept")
    archived = write(mock_vault_config / ".archive" / "old.txt", "archived")
    monkeypatch.setattr(chroma_store, "get_all_metadatas", lambda config: [])
    indexed = []
    monkeypatch.setattr(SemanticVault, "index_file", lambda self, file_path, agent_metadata=None: indexed.append(str(file_path)))

    vault_router.index_files("test_vault")
    assert indexed == [str(kept)]
    assert vault_router.index_status("test_vault").unindexed == [str(kept)]

    monkeypatch.setattr("ctxvault.core.indexer.delete_file", lambda file_path, config: None)
    vault_router.delete_files("test_vault")
    assert archived.exists() and not kept.exists()

def test_delete_file_on_a_file_already_gone_does_not_raise(mock_vault_config):
    vault = vault_router.open_vault("test_vault")
    from ctxvault.core.vaults.base import BaseVault
    BaseVault.delete_file(vault, mock_vault_config / "never-there.txt")

# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_prune_groups_by_reason_and_changes_nothing(mock_vault_config, collection):
    new = write(mock_vault_config / "notes" / "setup.md", "same", days_old=1)
    old = write(mock_vault_config / "archive" / "setup-old.md", "same", days_old=200)
    collection.add("n", new, [("same", A)])
    collection.add("o", old, [("same", A)])

    result = runner.invoke(app, ["prune", "test_vault"])

    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "── DUPLICATE" in out and "identical document" in out and "── STALE" in out
    assert "notes/setup.md" in out and "keep" in out
    assert "needs a human, use --doc" in out
    assert "Nothing was changed." in out

def test_cli_prune_json_and_older_than(mock_vault_config, collection):
    old = write(mock_vault_config / "old.md", "old", days_old=100)
    collection.add("o", old, [("old", A)])

    result = runner.invoke(app, ["prune", "test_vault", "--older-than", "90d", "--json"])

    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert [c["reason"] for c in data["candidates"]] == ["stale"]

def test_cli_prune_rejects_a_bad_duration(mock_vault_config, collection):
    result = runner.invoke(app, ["prune", "test_vault", "--older-than", "soon"])
    assert result.exit_code != 0
