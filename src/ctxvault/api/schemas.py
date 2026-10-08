from typing import Any
from ctxvault.models.documents import SemanticDocumentInfo, SkillDocumentInfo, DocumentContent
from ctxvault.models.episodes import Episode, EpisodeMatch, EpisodeOrder
from ctxvault.models.query_result import ChunkMatch
from ctxvault.models.vaults import SkillOutput, VaultType
from pydantic import BaseModel, ConfigDict, Field

class VaultInfo(BaseModel):
    name: str
    type: VaultType
    scope: str
    vault_path: str
    restricted: bool
    allowed_agents: list[str] | None = None

class InitRequest(BaseModel):
    vault_name: str
    restricted: bool = False
    vault_path: str | None = None

class InitResponse(BaseModel):
    vault_path: str
    config_path: str

class IndexRequest(BaseModel):
    vault_name: str
    file_path: str | None = None

class IndexResponse(BaseModel):
    indexed_files: list[str]
    skipped_files: list[str]

class QueryRequest(BaseModel):
    vault_name: str
    query: str
    filters: dict | None = None
    n_results: int = Field(default=5, ge=1, le=100)

class QueryResponse(BaseModel):
    results: list[ChunkMatch]

class DeleteResponse(BaseModel):
    deleted_files: list[str]
    skipped_files: list[str]

class ReindexRequest(BaseModel):
    vault_name: str
    file_path: str | None = None

class ReindexResponse(BaseModel):
    reindexed_files: list[str]
    skipped_files: list[str]

class ListVaultsResponse(BaseModel):
    vaults: list[VaultInfo]

class ListDocsResponse(BaseModel):
    vault_name: str
    documents: list[SemanticDocumentInfo]

class DocContentResponse(BaseModel):
    vault_name: str
    document: DocumentContent

class ListSkillsResponse(BaseModel):
    vault_name: str
    skills: list[SkillDocumentInfo]

class AgentMetadata(BaseModel):
    # Open on purpose: agents attach their own fields here and they travel
    # through to the chunk metadata, where queries can filter on them.
    model_config = ConfigDict(extra="allow")

    generated_by: str
    timestamp: str

class WriteDocRequest(BaseModel):
    vault_name: str
    file_path: str
    content: str
    overwrite: bool
    agent_metadata: AgentMetadata | None = None

class WriteDocResponse(BaseModel):
    file_path: str

class WriteSkillRequest(BaseModel):
    vault_name: str
    skill_name: str
    description: str
    instructions: str
    overwrite: bool = True

class WriteSkillResponse(BaseModel):
    filename: str

class SkillResponse(BaseModel):
    skill: SkillOutput

class WarmupStatusResponse(BaseModel):
    ready: bool
    status: str
    message: str

class WriteEpisodeRequest(BaseModel):
    vault_name: str
    content: str
    entities: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    occurred_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class EpisodeResponse(BaseModel):
    vault_name: str
    episode: Episode

class QueryEpisodesRequest(BaseModel):
    vault_name: str
    query: str | None = None
    entities: list[str] = Field(default_factory=list)
    source: str | None = None
    min_confidence: float | None = None
    valid_at: str | None = None
    known_at: str | None = None
    include_closed: bool = False
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    order_by: EpisodeOrder | None = None
    limit: int = Field(default=10, ge=1, le=200)
    half_life_days: float = Field(default=30.0, gt=0.0)
    weights: dict[str, float] | None = None
    reinforce: bool = False

class QueryEpisodesResponse(BaseModel):
    vault_name: str
    query: str | None = None
    order_by: EpisodeOrder
    results: list[EpisodeMatch]

class InvalidateEpisodeRequest(BaseModel):
    vault_name: str
    valid_to: str | None = None
    reason: str | None = None

class SupersedeEpisodeRequest(BaseModel):
    vault_name: str
    content: str
    entities: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    salience: float | None = None
    occurred_at: str | None = None
    valid_from: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class EpisodeHistoryResponse(BaseModel):
    vault_name: str
    episode_id: str
    chain: list[Episode]

class EpisodeStatsResponse(BaseModel):
    vault_name: str
    total: int
    open: int
    closed: int
