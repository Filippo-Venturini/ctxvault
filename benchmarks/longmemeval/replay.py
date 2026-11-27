"""Ingest one question's sessions into a fresh vault, then gather memory for it.

Sessions are applied in date order. For an episodic vault, `consolidate(..., at=)`
is the session date, so the write's transaction time is a replay of the past.
The question is then asked as of `question_instant` (see data.py).

Combined replay resolves the selected facts' transcript references, then searches
the dated transcripts for details extraction missed. It does not compare scores
across the episodic and semantic vaults.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from ctxvault import Client
from ctxvault.consolidation import ConsolidationConfig, Turn, consolidate, consolidate_session, sources
from ctxvault.core.embedding import DEFAULT_EMBEDDING_MODEL
from ctxvault.core.transcripts import write_session
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.storage import chroma_store, sqlite_store

from benchmarks.longmemeval.data import Question, Session, question_instant, to_iso
from benchmarks.longmemeval.prompts import format_history

ConfigName = Literal["full-context", "semantic-only", "episodic", "episodic+semantic"]
CONFIGS: tuple[ConfigName, ...] = ("full-context", "semantic-only", "episodic", "episodic+semantic")

SEMANTIC_VAULT = "lme-semantic"
EPISODIC_VAULT = "lme-episodic"
DEFAULT_N_RESULTS = 8
# An extracted fact is one short sentence, about a tenth of a transcript chunk,
# so facts have a budget of their own instead of sharing the chunk count.
DEFAULT_N_FACTS = 30


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


def ingest_semantic(vault: SemanticVault, sessions: tuple[Session, ...] | list[Session]) -> None:
    for index, session in enumerate(sessions):
        turns = [Turn(speaker=turn.role, text=turn.content, at=to_iso(session.date)) for turn in session.turns]
        if turns:
            write_session(vault, f"session-{index}.txt", turns, session_id=session.id)


def ingest_episodic(
    vault: EpisodicVault,
    sessions: tuple[Session, ...] | list[Session],
    model,
    *,
    diagnostics: dict[str, int] | None = None,
    transcript_config=None,
) -> None:
    for index, session in enumerate(sessions):
        turns = [
            Turn(speaker=turn.role, text=turn.content, at=to_iso(session.date))
            for turn in session.turns
        ]
        if not turns:
            continue
        if transcript_config is None:
            result = consolidate(vault, turns, model, at=to_iso(session.date))
        else:
            result = consolidate_session(
                transcript_config, turns, model, session_id=f"session-{index}", at=to_iso(session.date),
            )
        if diagnostics is not None:
            diagnostics["sessions_consolidated"] += 1
            diagnostics["sessions_with_unparseable_reply"] += int(
                getattr(model, "last_extraction_unparseable", False)
            )
            # A contradiction has a second, dispute operation: count the claim once.
            primary = [op for op in result.operations if op.verb != "dispute_episodes"]
            diagnostics["claims_written"] += sum(op.applied for op in primary)
            diagnostics["claims_rejected"] += result.dropped + sum(not op.applied for op in primary)


def _semantic_matches(vault: SemanticVault, question: Question, *, n_results: int):
    moment = question_instant(question.question_date, question.last_session_date)
    return vault.query(question.question, n_results=n_results, filters={
        "$and": [{"session_dated": {"$eq": True}}, {"session_ended_ts": {"$lte": moment.timestamp()}}],
    }).results


def retrieve_semantic(vault: SemanticVault, question: Question, *, n_results: int) -> str:
    matches = _semantic_matches(vault, question, n_results=n_results)
    if not matches:
        return "(no retrieved chunks)"
    blocks = []
    for match in matches:
        # The file's name, not its path: the vault lives in a temporary folder.
        source = Path(match.source).name if match.source else (match.doc_id or match.chunk_id)
        blocks.append(f"[{source}]\n{match.text}")
    return "\n\n".join(blocks)


def _episodes_for(vault: EpisodicVault, question: Question, *, limit: int):
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
    return result.results


def _format_episodes(episodes) -> str:
    if not episodes:
        return "(no retrieved episodes)"
    return "\n".join(f"- ({episode.valid_from or ''}) {episode.content}" for episode in episodes)


def retrieve_episodic(vault: EpisodicVault, question: Question, *, limit: int) -> str:
    return _format_episodes(_episodes_for(vault, question, limit=limit))


def retrieve_combined(vault: EpisodicVault, transcripts: SemanticVault, question: Question, *,
                      limit: int, facts: int | None = None) -> str:
    """`facts` episodes first, then up to `limit` transcript chunks."""
    episodes = _episodes_for(vault, question, limit=facts if facts is not None else limit)
    chunks, seen = [], set()
    for episode in episodes:
        for resolution in sources(episode):
            if resolution.state not in ("holds", "moved") or not resolution.text:
                continue
            key = (resolution.doc_id, resolution.chunk_index)
            if key not in seen:
                seen.add(key)
                chunks.append(resolution.text)
            if len(chunks) >= limit:
                break
        if len(chunks) >= limit:
            break
    if len(chunks) < limit:
        # Request the full budget so hits already included as citations cannot
        # crowd out the remaining slots. Facts and citations retain priority.
        for match in _semantic_matches(transcripts, question, n_results=limit):
            key = (match.doc_id, match.chunk_index)
            if key not in seen:
                seen.add(key)
                chunks.append(match.text)
            if len(chunks) >= limit:
                break
    fallback = "\n\n".join(chunks) or "(no retrieved transcript chunks)"
    return (
        f"Episodic facts:\n{_format_episodes(episodes)}\n\n"
        f"Transcript fallback (consult only when the facts are insufficient):\n{fallback}"
    )


def memory_for(
    config: ConfigName,
    question: Question,
    *,
    workdir: Path,
    extraction_model=None,
    n_results: int = DEFAULT_N_RESULTS,
    n_facts: int = DEFAULT_N_FACTS,
    embedding_model: str | None = None,
    diagnostics: dict[str, int] | None = None,
) -> str:
    """Build the memory block the answer model will see for this question."""
    if config == "full-context":
        return format_history(question.sessions)
    if config not in CONFIGS:
        raise ValueError(f"Unknown configuration {config!r}.")

    embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
    with isolated_workdir(workdir):
        client = Client()
        if config == "semantic-only":
            client.init(SEMANTIC_VAULT, "semantic", embedding_model=embedding_model)
            vault = client.semantic(SEMANTIC_VAULT)
            try:
                ingest_semantic(vault, question.sessions)
                return retrieve_semantic(vault, question, n_results=n_results)
            finally:
                chroma_store.close_client(vault.config)
        if extraction_model is None:
            raise ValueError("The episodic configuration needs an extraction model.")
        if config == "episodic+semantic":
            client.init("lme-facts", "episodic", embedding_model=embedding_model)
            client.init("lme-transcripts", "semantic", embedding_model=embedding_model)
            topology = ConsolidationConfig(facts_vault="lme-facts", transcripts_vault="lme-transcripts")
            vault = client.episodic(topology.facts_vault)
            transcripts = client.semantic(topology.transcripts_vault)
            try:
                ingest_episodic(vault, question.sessions, extraction_model,
                                diagnostics=diagnostics, transcript_config=topology)
                return retrieve_combined(vault, transcripts, question, limit=n_results, facts=n_facts)
            finally:
                chroma_store.close_client(transcripts.config)
        client.init(EPISODIC_VAULT, "episodic", embedding_model=embedding_model)
        vault = client.episodic(EPISODIC_VAULT)
        ingest_episodic(vault, question.sessions, extraction_model, diagnostics=diagnostics)
        return retrieve_episodic(vault, question, limit=n_facts)
