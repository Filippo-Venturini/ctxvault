"""The claim schema: the contract between extraction, provenance and benchmarks.

A claim is one statement a model extracted from what it heard or read, before
the layer decides how it relates to what the vault already holds. It is not
an episode: it has no id, no transaction time and no lifecycle. Those belong
to the vault, and a claim only becomes one through the existing verbs.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Who a claim is about, relative to who said it. Claims about people who are
# not speaking are their own kind so that a deployment can refuse them as a
# whole. The kind is required: a claim that does not declare it is dropped
# rather than assumed to be about its speaker.
ClaimKind = Literal["first_party", "third_party"]

# "durable" holds until something replaces it (where someone lives); "of_the_day"
# is true of a moment and not worth reconciling against later claims (what
# someone had for lunch).
ClaimDurability = Literal["durable", "of_the_day"]

# How much of `valid_from` the source actually said. People say "sometime in
# March" or "about a year ago": the layer normalises to an instant and records
# the precision here, so nothing downstream mistakes the instant for a fact.
ValidFromPrecision = Literal["day", "month", "year", "approx"]

class ChunkProvenance(BaseModel):
    """A span of a transcript indexed in a vault the caller may or may not read.

    `chunk_hash` is what the chunk read when the claim was extracted: chunks
    are rebuilt on reindex, so a hash that no longer matches means the
    transcript changed and the index no longer points at the same text.
    """

    type: Literal["chunk"] = "chunk"
    vault: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    chunk_hash: str = Field(min_length=1)

class ExternalProvenance(BaseModel):
    """A source that lives outside CtxVault: a file, a URL, a message."""

    type: Literal["external"] = "external"
    source: str = Field(min_length=1)
    locator: str | None = Field(
        default=None,
        description="Where in the source, e.g. a message id or a line range.",
    )

Provenance = Annotated[ChunkProvenance | ExternalProvenance, Field(discriminator="type")]

def _parse_iso(value: str) -> datetime:
    # Python 3.10's fromisoformat does not accept a trailing "Z".
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)

class Claim(BaseModel):
    """One statement extracted from a conversation or a document.

    `subject` is who or what the statement is about; `speaker` is who said it.
    They differ whenever someone talks about a third party, which is why
    `kind` exists. `valid_from` is None when the source gave no time, in which
    case the layer uses the moment the statement was made.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    speaker: str | None = None
    kind: ClaimKind
    durability: ClaimDurability = "durable"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    valid_from: str | None = None
    valid_from_precision: ValidFromPrecision = "day"
    provenance: Provenance | None = None

    @field_validator("valid_from")
    @classmethod
    def _valid_from_is_iso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            _parse_iso(value)
        except ValueError as exc:
            raise ValueError(f"valid_from is not an ISO 8601 date: {value!r}") from exc
        return value

def parse_claims(
    items: Iterable[Any],
    *,
    kinds: Iterable[ClaimKind] | None = None,
) -> list[Claim]:
    """Validate raw model output into claims, dropping what does not fit.

    A malformed item is skipped, not raised: one bad claim in a batch should
    not cost the others. `kinds` restricts which kinds are kept (None keeps
    every kind), so a deployment can switch off claims about third parties.
    """
    allowed = set(kinds) if kinds is not None else None
    claims: list[Claim] = []

    for item in items:
        try:
            claim = Claim.model_validate(item)
        except ValidationError:
            continue

        if allowed is not None and claim.kind not in allowed:
            continue

        claims.append(claim)

    return claims
