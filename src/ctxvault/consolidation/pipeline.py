"""The pipeline: turns in, episodes out, through the vault's own verbs.

Four steps, and the model only takes part in two of them:

1. turns -> claims: the model extracts, the schema validates, what does not
   fit is dropped;
2. candidate lookup: code asks the vault what it already holds about the
   claim's subject;
3. relation: the model labels the claim against those candidates;
4. label -> verb: a fixed mapping, in code.

The layer is a client of the vault. It writes directly, because nothing in an
episodic vault is destroyed: a wrong supersede closes an episode that
`reopen_episode` brings back, and every write carries the run that made it.
`dry_run` returns the same operations without applying them.
"""

import uuid
from collections.abc import Iterable
from datetime import date, datetime, time, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from ctxvault.consolidation.claims import Claim, ClaimKind, Provenance, _normalise_valid_from, parse_claims
from ctxvault.consolidation.model import ConsolidationModel, Relation, RelationDecision, Turn
from ctxvault.core.exceptions import EpisodeAlreadyClosedError, EpisodeNotFoundError
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.models.episodes import Episode

Verb = Literal["write_episode", "confirm_episode", "revise_episode", "supersede_episode", "dispute_episodes"]

# The whole of step 4. A contradiction is two verbs: the new statement is
# written, then put in dispute with the one it cannot hold together with.
VERBS: dict[Relation, tuple[Verb, ...]] = {
    "new": ("write_episode",),
    "confirms": ("confirm_episode",),
    "refines": ("revise_episode",),
    "replaces": ("supersede_episode",),
    "contradicts": ("write_episode", "dispute_episodes"),
}

DEFAULT_MAX_CANDIDATES = 5
# Below this, an episode that does not share the claim's subject is not
# shown to the model: it is more likely noise than the same fact.
DEFAULT_MIN_SIMILARITY = 0.5

class Operation(BaseModel):
    """One verb call the layer decided on, applied or only planned."""

    verb: Verb
    relation: Relation
    claim: Claim
    # The episode already in the vault that the verb acts on. None for a
    # plain write.
    target_id: str | None = None
    # The episode this claim became: set once a write, a revision or a
    # supersession is applied, and on the dispute that follows a write.
    episode_id: str | None = None
    applied: bool = False
    # Why the verb was not applied, when the vault refused it.
    error: str | None = None
    # Why the relation is not the one the model gave, when it was not usable.
    note: str | None = None

class ConsolidationResult(BaseModel):
    """What one run did, or with `dry_run` what it would do."""

    run_id: str
    model: str
    prompt_version: str
    at: str
    dry_run: bool
    extracted: int = 0   # raw items the model returned
    dropped: int = 0     # of those, how many did not fit the schema or the allowed kinds
    operations: list[Operation] = Field(default_factory=list)

def _instant(value: str) -> str:
    """An ISO 8601 date or time as a UTC instant, which is what the vault
    compares. A date is its first moment."""
    normalised = _normalise_valid_from(value)
    try:
        return datetime.combine(date.fromisoformat(normalised), time.min, timezone.utc).isoformat()
    except ValueError:
        pass
    parsed = datetime.fromisoformat(normalised[:-1] + "+00:00" if normalised.endswith("Z") else normalised)
    return parsed.astimezone(timezone.utc).isoformat()

def _moment(at: str | None, turns: list[Turn]) -> str:
    """When the conversation happened: given, else its last dated turn, else now."""
    if at:
        return _instant(at)
    dated = [_instant(turn.at) for turn in turns if turn.at]
    return max(dated) if dated else datetime.now(timezone.utc).isoformat()

def _candidates(vault: EpisodicVault, claim: Claim, moment: str, limit: int, min_similarity: float) -> list[Episode]:
    """What the vault held, at the time of the conversation, that this claim
    could be about: statements on the same subject first, then anything
    close enough in wording."""
    found: list[Episode] = list(
        vault.query_episodes(claim.statement, entities=[claim.subject], valid_at=moment, limit=limit).results
    )
    if len(found) < limit:
        seen = {episode.id for episode in found}
        for match in vault.query_episodes(claim.statement, valid_at=moment, limit=limit).results:
            if match.id in seen or (match.similarity or 0.0) < min_similarity:
                continue
            found.append(match)
            if len(found) == limit:
                break
    return found

def _decide(model: ConsolidationModel, claim: Claim, candidates: list[Episode]) -> tuple[RelationDecision, str | None]:
    """The model's label, or "new" with the reason when its answer cannot be
    used. Nothing is lost that way: the statement is still written, and a
    duplicate is cheaper to fix than a wrong close."""
    try:
        decision = RelationDecision.model_validate(model.relate(claim, candidates))
    except ValidationError:
        return RelationDecision(relation="new"), "the model's relation did not fit the schema"

    if decision.episode_id is not None and decision.episode_id not in {c.id for c in candidates}:
        return RelationDecision(relation="new"), f"the model named an episode it was not shown: {decision.episode_id}"

    return decision, None

class _Run:
    """One consolidation run: what every write of it carries, and how each
    verb is called."""

    def __init__(self, vault: EpisodicVault, model: ConsolidationModel, run_id: str, moment: str, dry_run: bool):
        self.vault = vault
        self.moment = moment
        self.dry_run = dry_run
        self.attribution = {"run_id": run_id, "model": model.name, "prompt_version": model.prompt_version}

    def _provenance(self, claim: Claim) -> dict:
        return {"provenance": [p.model_dump(exclude_none=True) for p in claim.provenance]} if claim.provenance else {}

    def _statement_metadata(self, claim: Claim) -> dict:
        """What goes on an episode this claim becomes."""
        metadata = {**self.attribution, "claim_kind": claim.kind, "durability": claim.durability}
        if claim.valid_from_precision:
            metadata["valid_from_precision"] = claim.valid_from_precision
        return {**metadata, **self._provenance(claim)}

    def _event_metadata(self, claim: Claim) -> dict:
        """What goes on a confirm, a dispute or a close this claim causes."""
        return {**self.attribution, **self._provenance(claim)}

    def _valid_from(self, claim: Claim) -> str:
        return _instant(claim.valid_from) if claim.valid_from else self.moment

    def _confidence(self, claim: Claim) -> dict:
        # Passed only when the model stated one: the vault's own default
        # applies otherwise, as for any writer that says nothing.
        return {} if claim.confidence is None else {"confidence": claim.confidence}

    def _call(self, verb: Verb, claim: Claim, target_id: str | None, written_id: str | None) -> str | None:
        """Apply one verb; the id of the episode the claim became, if any."""
        vault = self.vault
        if verb == "write_episode":
            return vault.write_episode(
                claim.statement, entities=[claim.subject], source=claim.speaker,
                valid_from=self._valid_from(claim), recorded_at=self.moment,
                metadata=self._statement_metadata(claim), **self._confidence(claim),
            ).id
        if verb == "confirm_episode":
            vault.confirm_episode(target_id, at=self.moment, source=claim.speaker, metadata=self._event_metadata(claim))
            return None
        if verb == "revise_episode":
            return vault.revise_episode(
                target_id, claim.statement, source=claim.speaker, confidence=claim.confidence,
                metadata=self._statement_metadata(claim), event_metadata=self._event_metadata(claim),
                at=self.moment,
            ).id
        if verb == "supersede_episode":
            return vault.supersede_episode(
                target_id, claim.statement, source=claim.speaker,
                valid_from=self._valid_from(claim), metadata=self._statement_metadata(claim),
                event_metadata=self._event_metadata(claim), at=self.moment, **self._confidence(claim),
            ).id
        vault.dispute_episodes(written_id, target_id, at=self.moment, metadata=self._event_metadata(claim))
        return written_id

    def carry_out(self, claim: Claim, decision: RelationDecision, note: str | None) -> list[Operation]:
        operations: list[Operation] = []
        written_id: str | None = None

        for verb in VERBS[decision.relation]:
            operation = Operation(
                verb=verb, relation=decision.relation, claim=claim, note=note,
                target_id=None if verb == "write_episode" else decision.episode_id,
            )
            operations.append(operation)
            if self.dry_run:
                continue
            if verb == "dispute_episodes" and written_id is None:
                operation.error = "not applied: the statement it disputes with was not written."
                continue
            try:
                written_id = self._call(verb, claim, operation.target_id, written_id)
            except (ValueError, EpisodeNotFoundError, EpisodeAlreadyClosedError) as exc:
                # The vault refused: the target was closed meanwhile, or the
                # dates do not fit. One claim's failure does not cost the others.
                operation.error = str(exc)
                continue
            operation.applied = True
            operation.episode_id = written_id

        return operations

def consolidate(
    vault: EpisodicVault,
    turns: Iterable[Turn | dict],
    model: ConsolidationModel,
    *,
    at: str | None = None,
    run_id: str | None = None,
    kinds: Iterable[ClaimKind] | None = None,
    provenance: Iterable[Provenance | dict] | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    dry_run: bool = False,
) -> ConsolidationResult:
    """Turn a conversation into episodes of `vault`.

    `at` is when the conversation happened, for callers replaying the past:
    it is the transaction time of every write and the start of validity of a
    claim that gives none. It defaults to the last dated turn, else to now.
    `kinds` restricts the claims kept, e.g. to refuse those about third
    parties. `provenance` is given to every claim the model returned without
    one, for a caller that knows where the turns came from.

    Claims are handled in order, and each one sees what the ones before it
    wrote. A claim "of the day" is written without being related to anything:
    it is true of a moment, not something a later claim replaces. With
    `dry_run` nothing is written, so later claims are related to the vault as
    it stood before the run.
    """
    conversation = [Turn.model_validate(turn) for turn in turns]
    given = TypeAdapter(list[Provenance]).validate_python(list(provenance or []))
    moment = _moment(at, conversation)
    result = ConsolidationResult(
        run_id=run_id or uuid.uuid4().hex, model=model.name, prompt_version=model.prompt_version,
        at=moment, dry_run=dry_run,
    )
    if not conversation:
        return result

    raw: Any = model.extract(conversation)
    items = list(raw) if isinstance(raw, (list, tuple)) else []
    claims = parse_claims(items, kinds=kinds)
    result.extracted = len(items)
    result.dropped = len(items) - len(claims)

    run = _Run(vault=vault, model=model, run_id=result.run_id, moment=moment, dry_run=dry_run)
    for claim in claims:
        if given and not claim.provenance:
            claim = claim.model_copy(update={"provenance": given})

        decision, note = RelationDecision(relation="new"), None
        if claim.durability == "durable":
            candidates = _candidates(vault, claim, moment, max_candidates, min_similarity)
            # With nothing on file to relate to, there is nothing to ask.
            if candidates:
                decision, note = _decide(model, claim, candidates)

        result.operations.extend(run.carry_out(claim, decision, note))

    return result
