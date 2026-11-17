"""Pruning: what a vault would remove, and why, before anything is removed.

A vault type declares the reasons it can prune for. `prune()` finds the
candidates and reports them with the raw signals behind each one; it changes
nothing. Applying a report, the archive and `restore` are built on this.
"""

from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field

class PruneMode(str, Enum):
    OFF = "off"          # not looked for
    REPORT = "report"    # reported, only ever applied by a person naming the target
    AUTO = "auto"        # applied unattended, when the target is auto-allowed

class PruneAction(str, Enum):
    ARCHIVE = "archive"        # semantic: move the file to .archive/ and drop it from the index
    INVALIDATE = "invalidate"  # episodic, later: maps onto invalidate_episode
    NONE = "none"              # reported only: nothing to apply

class ReasonSpec(NamedTuple):
    default_mode: PruneMode
    # False keeps a reason report-only whatever the config says: a partial
    # overlap is two documents that both say one thing, not a copy.
    auto_eligible: bool

class PruneRule(BaseModel):
    mode: PruneMode
    threshold: float | None = Field(default=None, gt=0.0, le=1.0)
    older_than_days: int | None = Field(default=None, ge=1)

class PrunePolicy(BaseModel):
    """A vault's pruning policy. Absent from the config means disabled: the
    vault still reports, with the type's default rules, but applies nothing
    unattended."""

    enabled: bool = False
    retention_days: int = Field(default=30, ge=0)
    rules: dict[str, PruneRule] = Field(default_factory=dict)

    @classmethod
    def for_vault(cls, config: dict, reasons: dict[str, ReasonSpec]) -> "PrunePolicy":
        stored = config.get("prune") or {}
        rules = {name: PruneRule(mode=spec.default_mode) for name, spec in reasons.items()}
        for name, rule in (stored.get("rules") or {}).items():
            if name in rules:
                rules[name] = PruneRule.model_validate(rule)
        return cls(
            enabled=bool(stored.get("enabled", False)),
            retention_days=stored.get("retention_days", 30),
            rules=rules,
        )

    def mode(self, reason: str) -> PruneMode:
        rule = self.rules.get(reason)
        return rule.mode if rule else PruneMode.OFF

class Candidate(BaseModel):
    target: str                  # semantic: the document's source path; episodic: an episode id
    reason: str                  # one of the vault type's declared reasons
    # Raw, never folded into a score: what was measured, and with what.
    signals: dict[str, str | int | float | bool] = Field(default_factory=dict)
    suggested_action: PruneAction
    group: str | None = None     # ties together the sides of one duplicate group
    # Whether the policy may apply this without a person: the policy is on,
    # the reason is in auto mode and eligible for it, and the target's
    # provenance allows it (for documents: agent-written and unedited since).
    auto_allowed: bool = False

class PruneReport(BaseModel):
    vault_name: str
    policy_enabled: bool
    counts: dict[str, int] = Field(default_factory=dict)      # e.g. documents, chunks
    candidates: list[Candidate] = Field(default_factory=list)
    # Candidates whose reason could run unattended but whose target needs a
    # person: a human-written document is only ever pruned by naming it.
    held: list[Candidate] = Field(default_factory=list)
    # What the report could not look at, and why: a check left off, files gone.
    notes: list[str] = Field(default_factory=list)
    signals: dict[str, str | int | float] = Field(default_factory=dict)  # e.g. the model
