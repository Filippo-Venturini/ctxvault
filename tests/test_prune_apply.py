import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chromadb
import pytest
from typer.testing import CliRunner

from ctxvault.cli.app import app
from ctxvault.core import prune_log, vault_router
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError
from ctxvault.core.identifiers import get_doc_id, get_text_hash
from ctxvault.core.vaults.base import ARCHIVE_DIR
from ctxvault.storage import chroma_store
from ctxvault.utils.config import get_vault_config

NOW = datetime.now(timezone.utc)

@pytest.fixture
def real_chroma(monkeypatch):
    """A real Chroma store with the conftest's fake embeddings: archive and
    restore are about what deletes and reindexes actually do."""
    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)

@pytest.fixture
def vault_dir(mock_vault_config, real_chroma):
    return mock_vault_config

def vault():
    """Opened fresh each time: the config, policy included, is read on open."""
    return vault_router.open_vault("test_vault")

def put(rel, text, *, agent=False, age_days=1):
    """A document, written by an agent through write_doc or by hand, last
    modified `age_days` ago."""
    v = vault()
    path = (v.vault_path / rel).resolve()
    if agent:
        v.write_doc(rel, text, agent_metadata={"generated_by": "agent-x",
                                               "timestamp": (NOW + timedelta(minutes=1)).isoformat()})
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        v.index_file(path)
    stamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path

def enable(**rules):
    return vault_router.set_prune_policy("test_vault", enabled=True, rules=rules or None)

def indexed_sources():
    return {d.source for d in vault().list_documents()}

def log_rows(vault_dir):
    rows, breaks = prune_log.read(vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME)
    assert breaks == []
    return rows

# ── the text hash is stored at index time ───────────────────────────────────

def test_every_chunk_carries_the_documents_text_hash(vault_dir):
    path = put("a.md", "# Title\n\nsome text")
    metadatas = chroma_store.get_document_records(get_doc_id(str(path)), vault().config)["metadatas"]
    assert {m["text_hash"] for m in metadatas} == {get_text_hash("# Title\n\nsome text")}
    assert vault().list_documents()[0].metadata in (None, {})  # built in, never shown as the document's own

def test_the_identical_check_reads_no_file_that_is_as_indexed(vault_dir, monkeypatch):
    put("a.md", "same words", age_days=3)
    put("b.md", "same words", age_days=2)
    monkeypatch.setattr("ctxvault.core.pruning.extract_text", lambda path: (_ for _ in ()).throw(AssertionError(path)))
    report = vault().prune(reasons={"duplicate"})
    assert {Path(c.target).name for c in report.candidates} == {"a.md", "b.md"}

def test_a_file_changed_after_indexing_is_read_again(vault_dir):
    put("a.md", "same words", age_days=3)
    b = put("b.md", "same words", age_days=2)
    b.write_text("different words now")
    assert vault().prune(reasons={"duplicate"}).candidates == []

# ── applying ────────────────────────────────────────────────────────────────

def test_a_person_names_a_human_written_copy_and_it_is_archived(vault_dir):
    kept = put("notes/a.md", "same words", age_days=1)
    copy = put("notes/old/a.md", "same words", age_days=5)

    report = vault_router.prune("test_vault", targets=["notes/old/a.md"], apply=True)

    assert [e.target for e in report.applied] == ["notes/old/a.md"]
    entry = report.applied[0]
    assert entry.who == "human" and entry.trigger == "manual" and entry.reason == "duplicate"
    assert not copy.exists() and kept.exists()
    assert (vault_dir / ARCHIVE_DIR / entry.archived_path).read_text() == "same words"
    assert indexed_sources() == {str(kept)}
    status = vault().status()
    assert status.unindexed == [] and [d.source for d in status.documents] == [str(kept)]

def test_naming_the_copy_that_stays_archives_nothing(vault_dir):
    put("a.md", "same words", age_days=1)
    put("b.md", "same words", age_days=5)
    report = vault_router.prune("test_vault", targets=["a.md"], apply=True)
    assert report.applied == [] and len(indexed_sources()) == 2

def test_the_policy_archives_only_agent_written_copies(vault_dir):
    human = put("human.md", "same words", age_days=9)
    agent_old = put("agent-old.md", "same words", agent=True, age_days=5)
    newest = put("newest.md", "same words", agent=True, age_days=1)
    enable()  # after the writes: with it on, write_doc would already have pruned

    report = vault_router.prune("test_vault", apply=True)

    assert [e.target for e in report.applied] == ["agent-old.md"]
    assert report.applied[0].who == "policy"
    assert human.exists() and newest.exists() and not agent_old.exists()
    assert [Path(c.target).name for c in report.held] == ["human.md"]

def test_with_the_policy_off_nothing_is_applied_unattended(vault_dir):
    put("a.md", "same words", agent=True, age_days=5)
    put("b.md", "same words", agent=True, age_days=1)
    report = vault_router.prune("test_vault", apply=True)
    assert report.applied == [] and "the policy is disabled" in report.skipped[0]
    assert not (vault_dir / ARCHIVE_DIR).exists()

def test_a_file_changed_since_the_report_is_left_alone(vault_dir):
    put("a.md", "same words", age_days=1)
    copy = put("b.md", "same words", age_days=5)
    v = vault()
    report = v.prune(targets=["b.md"])
    copy.write_text("edited in between")
    v._apply(report, policy=v.prune_policy(), named=True, trigger="manual")
    assert report.applied == [] and report.skipped == ["b.md: changed since it was found"]
    assert copy.exists()

def test_a_copy_whose_original_went_away_is_left_alone(vault_dir):
    kept = put("a.md", "same words", age_days=1)
    copy = put("b.md", "same words", age_days=5)
    v = vault()
    report = v.prune(targets=["b.md"])
    kept.unlink()
    v._apply(report, policy=v.prune_policy(), named=True, trigger="manual")
    assert report.applied == [] and "no longer a duplicate" in report.skipped[0]
    assert copy.exists()

def test_naming_something_that_is_not_a_candidate_says_so(vault_dir):
    put("a.md", "alone")
    report = vault_router.prune("test_vault", targets=["a.md"], apply=True)
    assert report.applied == [] and report.skipped == ["a.md: not a candidate"]

# ── restore ─────────────────────────────────────────────────────────────────

def test_restore_puts_it_back_indexed_and_still_agent_written(vault_dir):
    old = put("deep/er/old.md", "same words", agent=True, age_days=5)
    put("new.md", "same words", agent=True, age_days=1)
    enable()
    archived = vault_router.prune("test_vault", apply=True).applied[0]
    mtime = (vault_dir / ARCHIVE_DIR / archived.archived_path).stat().st_mtime

    entry = vault_router.restore("test_vault", "deep/er/old.md")

    assert entry.state == "restored" and old.read_text() == "same words"
    assert old.stat().st_mtime == mtime
    metadata = chroma_store.get_document_records(get_doc_id(str(old)), vault().config)["metadatas"][0]
    assert metadata["generated_by"] == "agent-x"
    # the archive keeps only its log: the folders the file sat in are gone
    assert [p.name for p in (vault_dir / ARCHIVE_DIR).iterdir()] == [prune_log.LOG_NAME]
    assert [r["kind"] for r in log_rows(vault_dir)] == ["archive", "restore"]

def test_a_restored_document_is_never_archived_again_unattended(vault_dir):
    """A restore is a person's decision; the policy does not undo it, on any
    pass. It stays in the report, held, and naming it still prunes it."""
    old = put("a/setup.md", "same words", agent=True, age_days=5)
    put("new.md", "same words", agent=True, age_days=1)
    enable()
    vault().index_files()
    assert not old.exists()
    vault_router.restore("test_vault", "a/setup.md")

    vault().sync_index()
    vault().index_files()
    put("newer.md", "same words", agent=True, age_days=0)          # write_doc's own pass
    report = vault_router.prune("test_vault", apply=True)

    assert old.exists()
    assert [e.target for e in vault().prune_log()].count("a/setup.md") == 1   # the first archive only
    held = next(c for c in report.held if c.target == str(old))
    assert not held.auto_allowed and held.signals["restored"]

    named = vault_router.prune("test_vault", targets=["a/setup.md"], apply=True)
    assert [(e.target, e.who) for e in named.applied] == [("a/setup.md", "human")] and not old.exists()

def test_restore_will_not_overwrite_a_file_written_since(vault_dir):
    put("a.md", "same words", age_days=1)
    copy = put("b.md", "same words", age_days=5)
    vault_router.prune("test_vault", targets=["b.md"], apply=True)
    put("b.md", "a new b")

    with pytest.raises(FileAlreadyExistError):
        vault_router.restore("test_vault", "b.md")
    assert copy.read_text() == "a new b"

    vault_router.restore("test_vault", "b.md", overwrite=True)
    assert copy.read_text() == "same words"
    assert len([s for s in indexed_sources() if s == str(copy)]) == 1

def test_restoring_what_was_never_archived_raises(vault_dir):
    with pytest.raises(FileNotFoundError):
        vault_router.restore("test_vault", "nothing.md")

# ── purge ───────────────────────────────────────────────────────────────────

def test_purge_after_retention_and_never_while_the_policy_is_off(vault_dir):
    put("a.md", "same words", age_days=1)
    put("b.md", "same words", age_days=5)
    entry = vault_router.prune("test_vault", targets=["b.md"], apply=True).applied[0]
    archived = vault_dir / ARCHIVE_DIR / entry.archived_path

    later = NOW + timedelta(days=400)
    assert vault().purge_expired(now=later) == []          # policy off: kept
    assert vault().prune_log()[0].purge_due is None

    vault_router.set_prune_policy("test_vault", enabled=True, retention_days=30)
    assert vault().purge_expired(now=NOW + timedelta(days=29)) == []
    purged = vault().purge_expired(now=NOW + timedelta(days=31))

    assert [e.target for e in purged] == ["b.md"] and not archived.exists()
    assert vault().prune_log()[0].state == "purged"
    with pytest.raises(FileNotFoundError):
        vault_router.restore("test_vault", "b.md")

# ── the log ─────────────────────────────────────────────────────────────────

def test_the_log_chains_and_a_broken_log_stops_everything(vault_dir):
    put("a.md", "same words", age_days=1)
    put("b.md", "same words", age_days=5)
    copy = put("c.md", "same words", age_days=9)
    vault_router.prune("test_vault", targets=["b.md"], apply=True)
    path = vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME
    row = json.loads(path.read_text())
    assert row["prev"] == prune_log.GENESIS and row["n"] == 0

    path.write_text(path.read_text().replace('"reason":"duplicate"', '"reason":"stale"'))
    with pytest.raises(prune_log.PruneLogBroken):
        vault_router.prune("test_vault", targets=["c.md"], apply=True)
    assert copy.exists()

def test_a_torn_tail_is_ignored_with_a_warning_and_dropped_on_the_next_append(tmp_path):
    """An unterminated last line is a write that never finished, not a break."""
    path = tmp_path / prune_log.LOG_NAME
    prune_log.append(path, "archive", "human", target="x")
    whole = path.read_bytes()
    path.write_bytes(whole + b'{"n": 1, "kind": "arch')
    with pytest.warns(UserWarning, match="unterminated"):
        rows, breaks = prune_log.read(path)
    assert breaks == [] and [r["target"] for r in rows] == ["x"]

    with pytest.warns(UserWarning, match="unterminated"):
        prune_log.append(path, "archive", "human", target="y")
    assert path.read_bytes().startswith(whole)
    rows, breaks = prune_log.read(path)
    assert breaks == [] and [r["target"] for r in rows] == ["x", "y"]

def test_restore_works_after_a_crash_mid_append(vault_dir):
    put("a.md", "same words", age_days=1)
    copy = put("b.md", "same words", age_days=5)
    vault_router.prune("test_vault", targets=["b.md"], apply=True)
    path = vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME
    path.write_bytes(path.read_bytes() + b'{"n": 1, "kind": "restore", "who": "hu')

    with pytest.warns(UserWarning, match="unterminated"):
        vault_router.restore("test_vault", "b.md")
    assert copy.read_text() == "same words"
    assert [r["kind"] for r in log_rows(vault_dir)] == ["archive", "restore"]

def test_a_real_break_refuses_and_says_where_the_files_are(vault_dir):
    put("a.md", "same words", age_days=1)
    put("b.md", "same words", age_days=5)
    vault_router.prune("test_vault", targets=["b.md"], apply=True)
    path = vault_dir / ARCHIVE_DIR / prune_log.LOG_NAME
    path.write_text(path.read_text().replace('"who":"human"', '"who":"policy"'))
    with pytest.raises(prune_log.PruneLogBroken, match="does not chain") as raised:
        vault_router.restore("test_vault", "b.md")
    assert str(vault_dir / ARCHIVE_DIR) in str(raised.value)

# ── the policy on its own: index, sync, write_doc ───────────────────────────

def test_write_doc_archives_an_older_agent_copy_of_what_it_wrote(vault_dir):
    enable()
    human = put("human.md", "same words", age_days=9)
    old = put("old.md", "same words", agent=True, age_days=5)
    entries = vault().prune_log()
    assert [e.target for e in entries] == []  # one agent copy and one human copy: nothing yet

    put("new.md", "same words", agent=True, age_days=0)

    entries = vault().prune_log()
    assert [(e.target, e.who, e.trigger) for e in entries] == [("old.md", "policy", "write_doc")]
    assert human.exists() and not old.exists()

def test_index_and_sync_run_the_policy(vault_dir):
    put("a.md", "same words", agent=True, age_days=5)
    put("b.md", "same words", agent=True, age_days=1)
    enable()
    vault().index_files()
    assert [(e.target, e.trigger) for e in vault().prune_log()] == [("a.md", "index")]

    # written while the policy is on, c is the newest file at that moment:
    # write_doc keeps it and archives the older agent copy, b
    c = put("c.md", "same words", agent=True, age_days=6)
    assert [(e.target, e.trigger) for e in vault().prune_log()][-1] == ("b.md", "write_doc")

    vault_router.set_prune_policy("test_vault", rules={"stale": {"mode": "auto", "older_than_days": 3}})
    vault().sync_index()
    assert [(e.target, e.trigger) for e in vault().prune_log()][-1] == ("c.md", "sync")
    assert not c.exists()

def test_nothing_runs_on_its_own_while_the_policy_is_off(vault_dir):
    put("a.md", "same words", agent=True, age_days=5)
    put("b.md", "same words", agent=True, age_days=1)
    vault().index_files()
    vault().sync_index()
    assert not (vault_dir / ARCHIVE_DIR).exists()

# ── the archive is not part of the vault ────────────────────────────────────

def test_nothing_is_written_or_indexed_inside_the_archive(vault_dir):
    with pytest.raises(FileOutsideVaultError):
        vault().write_doc(f"{ARCHIVE_DIR}/sneaky.md", "x")
    inside = vault_dir / ARCHIVE_DIR / "x.md"
    inside.parent.mkdir()
    inside.write_text("x")
    with pytest.raises(FileOutsideVaultError):
        vault().index_file(inside)

# ── the policy in the config ────────────────────────────────────────────────

def test_the_policy_is_stored_only_once_set_and_keeps_its_rules_when_off(vault_dir):
    assert "prune" not in get_vault_config("test_vault")
    enable(stale={"mode": "auto", "older_than_days": 90})
    vault_router.set_prune_policy("test_vault", enabled=False)
    stored = get_vault_config("test_vault")["prune"]
    assert stored["enabled"] is False and stored["retention_days"] == 30
    assert stored["rules"]["stale"] == {"mode": "auto", "older_than_days": 90}
    assert stored["rules"]["duplicate"] == {"mode": "auto"}

@pytest.mark.parametrize("rules", [
    {"duplicate_partial": {"mode": "auto"}},
    {"nonsense": {"mode": "report"}},
    {"stale": {"mode": "sometimes"}},
    {"duplicate_partial": {"threshold": 1.5}},
])
def test_rules_that_cannot_hold_are_refused(vault_dir, rules):
    with pytest.raises(ValueError):
        vault_router.set_prune_policy("test_vault", rules=rules)
    assert "prune" not in get_vault_config("test_vault")

def test_a_retention_of_less_than_a_day_is_refused(vault_dir):
    """With 0, one pass would archive and purge: a delete nobody could undo."""
    with pytest.raises(ValueError):
        vault_router.set_prune_policy("test_vault", enabled=True, retention_days=0)
    assert "prune" not in get_vault_config("test_vault")
    assert CliRunner().invoke(app, ["prune", "test_vault", "--retention-days", "0"]).exit_code != 0

# ── the CLI ─────────────────────────────────────────────────────────────────

def test_the_cli_round_trip(vault_dir):
    runner = CliRunner()
    put("a.md", "same words", age_days=1)
    copy = put("sub/b.md", "same words", age_days=5)

    out = runner.invoke(app, ["prune", "test_vault", "--enable", "--rule", "stale=report,older_than_days=90d"]).output
    assert "prune policy enabled" in out and "older_than_days=90" in out

    out = runner.invoke(app, ["prune", "test_vault", "--apply", "--doc", "sub/b.md"]).output
    assert "APPLIED" in out and "sub/b.md" in out and not copy.exists()

    out = runner.invoke(app, ["prune", "test_vault", "--log"]).output
    assert "sub/b.md" in out and "by you" in out and "purges" in out

    result = runner.invoke(app, ["restore", "test_vault", "sub/b.md"])
    assert result.exit_code == 0 and copy.exists()

    assert runner.invoke(app, ["prune", "test_vault", "--rule", "duplicate_partial=auto"]).exit_code == 1

def test_append_works_under_a_mandatory_lock(tmp_path, monkeypatch):
    """Windows locks are mandatory: while the log's first byte is locked, no
    other handle may read it. Emulated here, so Linux CI catches a read that
    goes around the locked handle."""
    held = {"locked": False}

    class FakeMsvcrt:
        LK_LOCK = 1

        @staticmethod
        def locking(fd, mode, nbytes):
            held["locked"] = True

    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if held["locked"] and self.name == prune_log.LOG_NAME:
            raise PermissionError(13, "Permission denied")
        return real_read_bytes(self)

    monkeypatch.setattr(prune_log, "fcntl", None)
    monkeypatch.setattr(prune_log, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    path = tmp_path / prune_log.LOG_NAME
    for n in range(3):
        prune_log.append(path, "archive", "human", target=f"x{n}")
        held["locked"] = False   # closing the file releases it
    rows, breaks = prune_log.read(path)
    assert breaks == [] and [r["n"] for r in rows] == [0, 1, 2]

def test_a_busy_windows_lock_raises_instead_of_spinning(tmp_path, monkeypatch):
    """LK_LOCK already retries for about ten seconds; past that, one error."""
    calls = []

    class BusyMsvcrt:
        LK_LOCK = 1

        @staticmethod
        def locking(fd, mode, nbytes):
            calls.append(mode)
            raise OSError(36, "Resource deadlock avoided")

    monkeypatch.setattr(prune_log, "fcntl", None)
    monkeypatch.setattr(prune_log, "msvcrt", BusyMsvcrt)
    path = tmp_path / prune_log.LOG_NAME
    with pytest.raises(prune_log.PruneLogBusy):
        prune_log.append(path, "archive", "human", target="x")
    assert calls == [1] and path.read_bytes() == b""
