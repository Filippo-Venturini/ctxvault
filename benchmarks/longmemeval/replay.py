"""Ingest one question's sessions into a fresh vault, then gather memory for it.

Sessions are applied in date order. For an episodic vault, `consolidate(..., at=)`
is the session date, so the write's transaction time is a replay of the past.
The question is then asked as of `question_instant` (see data.py).

`episodic+semantic` is defined in #47 but needs date-aware transcript
ingestion from #45; this module refuses that configuration until then.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from ctxvault import Client
from ctxvault.consolidation import Turn, consolidate
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.storage import sqlite_store

from benchmarks.longmemeval.data import Question, Session, question_instant, to_iso
from benchmarks.longmemeval.prompts import format_history, format_session

ConfigName = Literal["full-context", "semantic-only", "episodic", "episodic+semantic"]
CONFIGS: tuple[ConfigName, ...] = ("full-context", "semantic-only", "episodic", "episodic+semantic")

SEMANTIC_VAULT = "lme-semantic"
EPISODIC_VAULT = "lme-episodic"
DEFAULT_N_RESULTS = 8


@contextmanager
def isolated_workdir(path: Path) -> Iterator[Path]:
    """Run vault registry calls inside `path`, so they never touch the caller's project."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".ctxvault").mkdir(exist_ok=True)
    config = path / ".ctxvault" / "config.json"
    if not config.exists():
        config.write_text('{"vaults": {}}')
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)
        sqlite_store.close_connections()


def _session_document(session: Session) -> str:
    return format_session(session) + "\n"


def ingest_semantic(vault: SemanticVault, sessions: tuple[Session, ...] | list[Session]) -> None:
    for session in sessions:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in session.id)
        vault.write_doc(f"{safe}.txt", _session_document(session), overwrite=True)


def ingest_episodic(
    vault: EpisodicVault,
    sessions: tuple[Session, ...] | list[Session],
    model,
    *,
    diagnostics: dict[str, int] | None = None,
) -> None:
    for session in sessions:
        turns = [
            Turn(speaker=turn.role, text=turn.content, at=to_iso(session.date))
            for turn in session.turns
        ]
        if not turns:
            continue
        result = consolidate(vault, turns, model, at=to_iso(session.date))
        if diagnostics is not None:
            diagnostics["sessions_consolidated"] += 1
            diagnostics["sessions_with_unparseable_reply"] += int(
                getattr(model, "last_extraction_unparseable", False)
            )
            # A contradiction has a second, dispute operation: count the claim once.
            primary = [op for op in result.operations if op.verb != "dispute_episodes"]
            diagnostics["claims_written"] += sum(op.applied for op in primary)
            diagnostics["claims_rejected"] += result.dropped + sum(not op.applied for op in primary)


def retrieve_semantic(vault: SemanticVault, question: Question, *, n_results: int) -> str:
    result = vault.query(question.question, n_results=n_results)
    if not result.results:
        return "(no retrieved chunks)"
    blocks = []
    for match in result.results:
        source = match.source or match.doc_id or match.chunk_id
        blocks.append(f"[{source}]\n{match.text}")
    return "\n\n".join(blocks)


def retrieve_episodic(vault: EpisodicVault, question: Question, *, limit: int) -> str:
    moment = to_iso(question_instant(question.question_date, question.last_session_date))
    result = vault.query_episodes(
        question.question, valid_at=moment, known_at=moment, limit=limit,
    )
    if not result.results:
        # Nothing ranked as similar: still give the answer model what held at
        # that instant, in recency order, so a stub or a keyword-less fact is
        # not silently dropped.
        result = vault.query_episodes(
            valid_at=moment, known_at=moment, order_by="recency", limit=limit,
        )
    if not result.results:
        return "(no retrieved episodes)"
    lines = []
    for episode in result.results:
        when = episode.valid_from or ""
        lines.append(f"- ({when}) {episode.content}")
    return "\n".join(lines)


def memory_for(
    config: ConfigName,
    question: Question,
    *,
    workdir: Path,
    extraction_model=None,
    n_results: int = DEFAULT_N_RESULTS,
    embedding_model: str | None = None,
    diagnostics: dict[str, int] | None = None,
) -> str:
    """Build the memory block the answer model will see for this question."""
    if config == "full-context":
        return format_history(question.sessions)
    if config == "episodic+semantic":
        raise ValueError(
            "The episodic+semantic configuration needs date-aware transcript "
            "ingestion (#45) and is not implemented yet."
        )
    if config not in CONFIGS:
        raise ValueError(f"Unknown configuration {config!r}.")

    with isolated_workdir(workdir):
        client = Client()
        if config == "semantic-only":
            client.init(SEMANTIC_VAULT, "semantic", embedding_model=embedding_model)
            vault = client.semantic(SEMANTIC_VAULT)
            ingest_semantic(vault, question.sessions)
            return retrieve_semantic(vault, question, n_results=n_results)
        if extraction_model is None:
            raise ValueError("The episodic configuration needs an extraction model.")
        client.init(EPISODIC_VAULT, "episodic", embedding_model=embedding_model)
        vault = client.episodic(EPISODIC_VAULT)
        ingest_episodic(vault, question.sessions, extraction_model, diagnostics=diagnostics)
        return retrieve_episodic(vault, question, limit=n_results)
