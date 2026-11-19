"""What the layer asks of a model, and what it hands it.

The model does two things and nothing else: it reads turns and returns raw
claims, and it reads one claim next to the episodes it might relate to and
returns a label. It never sees a verb and never writes: both of its answers
are validated here before code acts on them.
"""

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, model_validator

from ctxvault.consolidation.claims import Claim
# One definition of a turn: the layer reads the same turns the core writes as
# a session, so a transcript and the claims drawn from it cannot drift apart.
from ctxvault.core.transcripts import Turn
from ctxvault.models.episodes import Episode

# How a claim relates to what the vault already holds. "new" is about nothing
# on file; "confirms" says the same thing again; "refines" says it more
# precisely, the world unchanged; "contradicts" cannot hold together with it
# and nothing says which is wrong; "replaces" means the world changed.
Relation = Literal["new", "confirms", "refines", "contradicts", "replaces"]

class RelationDecision(BaseModel):
    """The model's answer for one claim: a label, and the episode it is about.

    Every relation but "new" names one of the candidates the model was shown.
    """

    relation: Relation
    episode_id: str | None = None

    @model_validator(mode="after")
    def _target_goes_with_relation(self) -> "RelationDecision":
        if self.relation == "new":
            self.episode_id = None
        elif not self.episode_id:
            raise ValueError(f"relation '{self.relation}' needs the episode it is about.")
        return self

@runtime_checkable
class ConsolidationModel(Protocol):
    """Anything that can extract claims and relate them: a real endpoint, or a
    stub in tests. `name` and `prompt_version` are stored with every write, so
    what one model and one prompt did stays a query."""

    name: str
    prompt_version: str

    def extract(self, turns: list[Turn]) -> list[Any]:
        """Raw claims, one item per statement. Validated by the layer: an item
        that does not fit the claim schema is dropped."""
        ...

    def relate(self, claim: Claim, candidates: list[Episode]) -> Any:
        """A raw `RelationDecision` for this claim. Validated by the layer: an
        answer that does not fit, or names an episode that was not among
        `candidates`, is read as "new"."""
        ...
