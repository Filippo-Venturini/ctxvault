"""ctxvault: typed, local memory for agents.

Importing the package gives the in-process client and the models its
methods return. The CLI, the HTTP API and the MCP server live in their own
subpackages and are not imported here.
"""

from ctxvault.client import Client
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.core.vaults.skill import SkillVault
from ctxvault.models.documents import DocumentContent, SemanticDocumentInfo, SkillDocumentInfo
from ctxvault.models.episodes import (
    Episode,
    EpisodeHistory,
    EpisodeMatch,
    EpisodeQueryResult,
    VaultEntity,
)
from ctxvault.models.query_result import ChunkMatch, QueryResult
from ctxvault.models.vaults import SkillInput, SkillOutput, VaultType

__all__ = [
    "Client",
    "VaultType",
    "SemanticVault",
    "SkillVault",
    "EpisodicVault",
    "ChunkMatch",
    "QueryResult",
    "SemanticDocumentInfo",
    "DocumentContent",
    "SkillInput",
    "SkillOutput",
    "SkillDocumentInfo",
    "Episode",
    "EpisodeMatch",
    "EpisodeQueryResult",
    "EpisodeHistory",
    "VaultEntity",
]
