"""Where the layer writes: topology as configuration.

The layer always writes facts to an episodic vault. Keeping the conversations
themselves is a choice: with `transcripts_vault` set, each session is also
written to that semantic vault and every claim points at the chunks its turns
are in; without it nothing but the facts is stored, and a claim points at the
external source the caller names, if any.

The configuration is plain data. The presets create the vaults and return it,
so a plug-and-play setup is still explicit: the same object anyone could have
written by hand.
"""

import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ctxvault.consolidation.claims import ChunkProvenance, ClaimKind, ExternalProvenance
from ctxvault.consolidation.model import ConsolidationModel, Turn
from ctxvault.consolidation.pipeline import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MIN_SIMILARITY,
    ConsolidationResult,
    _moment,
    consolidate,
)
from ctxvault.core.exceptions import VaultNotFoundError, VaultTypeNotValidError
from ctxvault.core.references import ChunkResolution, chunk_reference, resolve_chunk
from ctxvault.core.transcripts import SessionWrite, write_session
from ctxvault.models.episodes import Episode
from ctxvault.models.vaults import VaultType

# A session id becomes a file name, so it is held to what is one everywhere.
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

class ConsolidationConfig(BaseModel):
    """Which vaults a deployment's consolidation uses, and how strict it is."""

    model_config = ConfigDict(extra="forbid")

    facts_vault: str = Field(min_length=1)
    # None: facts only, no conversation is stored.
    transcripts_vault: str | None = Field(default=None, min_length=1)
    # The folder, inside the transcripts vault, that sessions are written to.
    transcripts_dir: str = Field(default="sessions", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    # None keeps every kind; ["first_party"] refuses claims about third parties.
    kinds: list[ClaimKind] | None = None
    max_candidates: int = Field(default=DEFAULT_MAX_CANDIDATES, ge=1)
    min_similarity: float = Field(default=DEFAULT_MIN_SIMILARITY, ge=0.0, le=1.0)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ConsolidationConfig":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

class SessionResult(ConsolidationResult):
    """A consolidation run, and where its transcript landed if one was kept."""

    transcript: SessionWrite | None = None

def _ensure_vault(client, name: str, vault_type: VaultType, embedding_model: str | None, global_vault: bool) -> None:
    """Create the vault, or accept the one already there if it is the right type."""
    try:
        existing = client.vault(name)
    except VaultNotFoundError:
        client.init(name, vault_type, embedding_model=embedding_model, global_vault=global_vault)
        return
    actual = existing.config.get("type", VaultType.SEMANTIC.value)
    if actual != vault_type.value:
        raise VaultTypeNotValidError(f"Vault '{name}' already exists and is {actual}, not {vault_type.value}.")

def facts_only(name: str, *, embedding_model: str | None = None, global_vault: bool = False,
               kinds: Iterable[ClaimKind] | None = None) -> ConsolidationConfig:
    """One episodic vault, `<name>-facts`. No conversation is stored.

    The vault is created as `ctxvault init` would: in this project, or with
    `global_vault` for every project. One that already exists is kept."""
    from ctxvault.client import Client

    config = ConsolidationConfig(facts_vault=f"{name}-facts", kinds=list(kinds) if kinds is not None else None)
    _ensure_vault(Client(), config.facts_vault, VaultType.EPISODIC, embedding_model, global_vault)
    return config

def facts_and_transcripts(name: str, *, embedding_model: str | None = None, global_vault: bool = False,
                          kinds: Iterable[ClaimKind] | None = None) -> ConsolidationConfig:
    """Two vaults: `<name>-facts` (episodic) and `<name>-transcripts`
    (semantic). Every session is kept, and every fact points back into it."""
    from ctxvault.client import Client

    config = ConsolidationConfig(
        facts_vault=f"{name}-facts", transcripts_vault=f"{name}-transcripts",
        kinds=list(kinds) if kinds is not None else None,
    )
    client = Client()
    _ensure_vault(client, config.facts_vault, VaultType.EPISODIC, embedding_model, global_vault)
    _ensure_vault(client, config.transcripts_vault, VaultType.SEMANTIC, embedding_model, global_vault)
    return config

def consolidate_session(
    config: ConsolidationConfig,
    turns: Iterable[Turn | dict],
    model: ConsolidationModel,
    *,
    session_id: str | None = None,
    source: str | None = None,
    at: str | None = None,
    run_id: str | None = None,
    agent: str | None = None,
    dry_run: bool = False,
) -> SessionResult:
    """Consolidate one session into the vaults `config` names.

    With a transcripts vault, the session is first written there as
    `<transcripts_dir>/<session_id>.txt` (writing the same id again replaces
    it), and each claim that names its turns carries a reference to the
    chunks those turns start in. A claim that names none carries no
    reference: the layer does not guess which words a fact came from. An
    undated turn is written with the conversation time when `at` gives one.

    Without a transcripts vault nothing but the facts is stored. `source`
    then names where the turns came from (a file, a URL, a thread), and
    becomes each claim's external provenance, with `session_id` as locator.

    `agent` is who is acting, for restricted vaults. With `dry_run` nothing
    is written, the transcript included, so the planned operations carry no
    chunk references.
    """
    from ctxvault.client import Client

    conversation = [Turn.model_validate(turn) for turn in turns]
    if session_id is not None and not _SESSION_ID.match(session_id):
        raise ValueError("session_id may hold letters, digits, '.', '_' and '-', and starts with a letter or digit.")

    client = Client(agent=agent)
    facts = client.episodic(config.facts_vault)
    transcripts = client.semantic(config.transcripts_vault) if config.transcripts_vault else None

    written: SessionWrite | None = None
    provenance: list[ExternalProvenance] = []
    turn_provenance: list[list[ChunkProvenance]] | None = None

    if transcripts is not None and conversation and not dry_run:
        if session_id is None:
            raise ValueError("A session kept as a transcript needs a session_id: it is the document's name.")
        # The transcript says what the layer was told: a turn with no time of
        # its own was said at the conversation's time, when the caller gave one.
        moment = _moment(at, conversation) if at else None
        kept = [turn if turn.at or moment is None else turn.model_copy(update={"at": moment}) for turn in conversation]
        written = write_session(
            transcripts, f"{config.transcripts_dir.strip('/')}/{session_id}.txt", kept,
            session_id=session_id, agent_metadata={"generated_by": agent} if agent else None,
        )
        references = {
            index: ChunkProvenance.model_validate(chunk_reference(config.transcripts_vault, written.doc_id, index))
            for index in sorted(set(written.turn_chunks))
        }
        turn_provenance = [[references[index]] for index in written.turn_chunks]
    elif transcripts is None and source:
        provenance = [ExternalProvenance(source=source, locator=session_id)]

    result = consolidate(
        facts, conversation, model, at=at, run_id=run_id, kinds=config.kinds,
        provenance=provenance, turn_provenance=turn_provenance,
        max_candidates=config.max_candidates, min_similarity=config.min_similarity, dry_run=dry_run,
    )
    return SessionResult(**result.model_dump(), transcript=written)

def sources(episode: Episode, *, agent: str | None = None) -> list[ChunkResolution]:
    """The transcript text a fact rests on, as it is now: one resolution per
    chunk reference in the episode's provenance, in order.

    The text fallback of a facts + transcripts setup: when a fact is not
    enough to answer, read what was actually said. Only `holds` and `moved`
    carry text; external provenance has nothing to resolve and is skipped.
    """
    recorded = (episode.metadata or {}).get("provenance") or []
    return [
        resolve_chunk(item, agent=agent)
        for item in recorded
        if isinstance(item, dict) and item.get("type") == "chunk"
    ]
