"""The claim schema: the contract between extraction, provenance and benchmarks.

A claim is one statement a model extracted from what it heard or read, before
the layer decides how it relates to what the vault already holds. It is not
an episode: it has no id, no transaction time and no lifecycle. Those belong
to the vault, and a claim only becomes one through the existing verbs.

Where the model leaves something out, the schema fails closed: a missing kind
drops the claim, a missing confidence or precision stays None rather than
reading as certain.
"""

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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

    `chunk_hash` is the SHA-256 hex digest of the chunk's text exactly as
    `get_document_chunks()` returns it: overlap words included, nothing
    normalised. Chunks are rebuilt on reindex, so a hash that no longer matches
    means the transcript changed and the index no longer points at the same
    text. `path` is the document's path relative to its vault: `doc_id` is
    derived from the absolute path, so a vault moved to another directory
    changes every `doc_id`, and the relative path tells a moved document from
    a missing one.
    """

    type: Literal["chunk"] = "chunk"
    vault: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str | None = Field(default=None, min_length=1)

class ExternalProvenance(BaseModel):
    """A source that lives outside CtxVault: a file, a URL, a message."""

    type: Literal["external"] = "external"
    source: str = Field(min_length=1)
    locator: str | None = Field(
        default=None,
        description="Where in the source, e.g. a message id or a line range.",
    )

Provenance = Annotated[ChunkProvenance | ExternalProvenance, Field(discriminator="type")]

def _normalise_valid_from(value: str) -> str:
    """An ISO 8601 date stays as it is; a time gets an offset.

    A naive time is read as UTC and rewritten with its offset, so a replay in
    transaction time never depends on the machine's local zone.
    """
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        pass

    # Python 3.10's fromisoformat does not accept a trailing "Z".
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).isoformat()
    return value

class Claim(BaseModel):
    """One statement extracted from a conversation or a document.

    `subject` is who or what the statement is about; `speaker` is who said it.
    They differ whenever someone talks about a third party, which is why
    `kind` exists. `valid_from` is None when the source gave no time, in which
    case the layer uses the moment the statement was made; when it is given,
    its precision must be too. `provenance` lists every span the claim rests
    on: a question and its answer can sit in different chunks.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    speaker: str | None = None
    kind: ClaimKind
    durability: ClaimDurability = "durable"
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="None when the model gave none, so that it is not read as certain.",
    )
    valid_from: str | None = None
    valid_from_precision: ValidFromPrecision | None = None
    provenance: list[Provenance] = Field(default_factory=list)

    @field_validator("valid_from")
    @classmethod
    def _valid_from_is_iso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return _normalise_valid_from(value)
        except ValueError as exc:
            raise ValueError(f"valid_from is not an ISO 8601 date: {value!r}") from exc

    @model_validator(mode="after")
    def _precision_goes_with_valid_from(self) -> "Claim":
        if self.valid_from is not None and self.valid_from_precision is None:
            raise ValueError("valid_from_precision is required when valid_from is given.")
        if self.valid_from is None and self.valid_from_precision is not None:
            raise ValueError("valid_from_precision describes nothing without valid_from.")
        return self

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
