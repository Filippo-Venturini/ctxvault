from typing import Any, Literal
from pydantic import BaseModel, Field

# How an episode can be ordered once the structured filters have been applied.
# "relevance" needs a query text; the others work on any result set.
EpisodeOrder = Literal["relevance", "recency", "salience", "composite"]

class Episode(BaseModel):
    """A single statement the vault believed, with both of its time axes.

    Valid time (`valid_from` / `valid_to`) is when the statement holds in the
    world. Transaction time (`recorded_at` / `invalidated_at`) is when this
    vault believed it. The two are independent: learning today that something
    stopped being true last month closes the valid window in the past while the
    transaction window closes now.
    """

    id: str
    content: str
    entities: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: float = 1.0
    salience: float = 0.5

    occurred_at: str | None = Field(
        default=None,
        description="When the described event happened, when that differs from the start of validity.",
    )
    valid_from: str
    valid_to: str | None = Field(
        default=None,
        description="End of validity in the world. None means still valid.",
    )
    recorded_at: str
    invalidated_at: str | None = Field(
        default=None,
        description="When the vault stopped believing this. None means still believed.",
    )
    superseded_by: str | None = None

    recall_count: int = 0
    last_recalled_at: str | None = None
    # Derived, never stored: how many times the statement was asserted again
    # after being recorded, and when last. Repetition is evidence, not a new
    # episode. Read as of `known_at` when a query asks for a past instant.
    confirmed_count: int = 0
    last_confirmed_at: str | None = None
    # Derived: the open episodes this one cannot hold together with. A
    # dispute lasts exactly as long as both sides stay open.
    disputed_with: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.valid_to is None and self.invalidated_at is None

    @property
    def disputed(self) -> bool:
        return bool(self.disputed_with)

class EpisodeMatch(Episode):
    """An episode returned by a query, with the scores that ranked it."""

    score: float = 0.0
    similarity: float | None = None
    recency: float | None = None

class EpisodeQueryResult(BaseModel):
    query: str | None = None
    order_by: EpisodeOrder
    results: list[EpisodeMatch]

class EpisodeHistory(BaseModel):
    """The full supersession chain an episode belongs to, oldest first."""

    episode_id: str
    chain: list[Episode]

class VaultEntity(BaseModel):
    """One entity the vault knows about, and how much it is talked about.

    `entity_norm` is the key episodes are matched on; `entity` is a surface
    spelling to show a human. `episode_count` is what makes the list usable as
    a vocabulary: a caller can keep the entities worth matching on and drop the
    ones mentioned once.
    """

    entity: str
    entity_norm: str
    episode_count: int
    last_recorded_at: str | None = None
