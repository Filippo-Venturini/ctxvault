"""Consolidation: turns in, episodes out, through the existing verbs.

An optional layer that sits outside the core, as a client of an episodic
vault. The core never calls a model and knows nothing about this package;
anyone with their own extractor keeps using the core alone.

The model interprets, code decides how to write: claims extracted by a model
are validated against the schema in `claims`, and malformed ones are dropped
before anything reaches a vault.
"""

from ctxvault.consolidation.claims import (
    ChunkProvenance,
    Claim,
    ClaimDurability,
    ClaimKind,
    ExternalProvenance,
    Provenance,
    ValidFromPrecision,
    parse_claims,
)
from ctxvault.consolidation.endpoint import ModelEndpointError, OpenAICompatibleModel, Prompts
from ctxvault.consolidation.model import ConsolidationModel, Relation, RelationDecision, Turn
from ctxvault.consolidation.pipeline import ConsolidationResult, Operation, consolidate

__all__ = [
    "Claim",
    "ClaimKind",
    "ClaimDurability",
    "ValidFromPrecision",
    "Provenance",
    "ChunkProvenance",
    "ExternalProvenance",
    "parse_claims",
    "Turn",
    "Relation",
    "RelationDecision",
    "ConsolidationModel",
    "Operation",
    "ConsolidationResult",
    "consolidate",
    "OpenAICompatibleModel",
    "Prompts",
    "ModelEndpointError",
]
