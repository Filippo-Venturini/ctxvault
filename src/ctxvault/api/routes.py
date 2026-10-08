from ctxvault.api.schemas import *
from ctxvault.core.exceptions import *
from ctxvault.models.vaults import SkillInput
from fastapi import APIRouter, FastAPI, HTTPException, Request
from ctxvault.core import vault_router

app = FastAPI()

ctxvault_router = APIRouter(prefix="/ctxvault", tags=["CtxVault"])

def check_vault_access(vault_name: str, request: Request):
    agent = request.headers.get("X-CtxVault-Agent")
    if not vault_router.is_agent_authorized(vault_name, agent):
        raise VaultAccessDeniedError(f"Agent '{agent}' is not authorized to access vault '{vault_name}'")

@ctxvault_router.put(
    "/index",
    summary="Index documents into a vault",
    description="Chunk, embed, and store documents for semantic search."
)
async def index(index_request: IndexRequest)-> IndexResponse:
    try:
        indexed_files, skipped_files = vault_router.index_files(vault_name=index_request.vault_name, path=index_request.file_path)

        return IndexResponse(indexed_files=indexed_files, skipped_files=skipped_files)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@ctxvault_router.post(
    "/query",
    summary="Perform semantic search",
    description="Run a vector similarity search against indexed vault documents."
)
async def query(query_request: QueryRequest, request: Request)-> QueryResponse:
    try:
        check_vault_access(vault_name=query_request.vault_name, request=request)

        result = vault_router.query(vault_name=query_request.vault_name, text=query_request.query, filters=query_request.filters, n_results=query_request.n_results)

        if not result.results:
            raise HTTPException(status_code=404, detail="No results found.")

        return QueryResponse(results=result.results)
    except EmptyQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.delete(
    "/delete",
    summary="Delete document from vault",
    description="Remove a document and its embeddings from a vault."
)
async def delete(vault_name: str, file_path: str | None = None, request: Request = None)-> DeleteResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        deleted_files, skipped_files = vault_router.delete_files(vault_name=vault_name, path=file_path)

        return DeleteResponse(deleted_files=deleted_files, skipped_files=skipped_files)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Vault {vault_name} doesn't exist.")
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.put(
    "/reindex",
    summary="Re-index vault documents",
    description="Rebuild embeddings for existing documents in a vault."
)
async def reindex(reindex_request: ReindexRequest, request: Request)-> ReindexResponse:
    try:
        check_vault_access(vault_name=reindex_request.vault_name, request=request)

        reindexed_files, skipped_files = vault_router.reindex_files(vault_name=reindex_request.vault_name, path=reindex_request.file_path)

        return ReindexResponse(reindexed_files=reindexed_files, skipped_files=skipped_files)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Vault {reindex_request.vault_name} doesn't exist.")
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.get(
    "/vaults",
    summary="List all vaults",
    description="Return all registered vaults and their paths."
)
async def vaults()-> ListVaultsResponse:
    vaults = vault_router.list_vaults()
    print(vaults)
    return ListVaultsResponse(vaults=vaults)
    
@ctxvault_router.get(
    "/docs",
    summary="List vault documents",
    description="Return all indexed documents in the specified vault."
)
async def docs(vault_name: str, request: Request)-> ListDocsResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        documents = vault_router.list_documents(vault_name=vault_name)
        return ListDocsResponse(vault_name=vault_name, documents=documents)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.get(
    "/docs/{doc_id}/content",
    summary="Retrieve indexed document text",
    description="Return text reconstructed from stored semantic chunks for recovery and diff workflows.",
)
async def doc_content(doc_id: str, vault_name: str, request: Request) -> DocContentResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        document = vault_router.get_document_content(vault_name=vault_name, doc_id=doc_id)
        return DocContentResponse(vault_name=vault_name, document=document)
    except DocumentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.post(
    "/docs/write",
    summary="Write and index a document to a semantic vault",
    description="Write a file to a semantic vault and automatically index it for retrieval."
)
async def write_doc(write_request: WriteDocRequest, request: Request)-> WriteDocResponse:
    try:
        check_vault_access(vault_name=write_request.vault_name, request=request)

        vault_router.write_doc(vault_name=write_request.vault_name,
                         file_path=write_request.file_path, 
                         content=write_request.content, 
                         overwrite=write_request.overwrite, 
                         agent_metadata=write_request.agent_metadata.model_dump() if write_request.agent_metadata else None)
        
        return WriteDocResponse(file_path=write_request.file_path)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileAlreadyExistError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@ctxvault_router.post(
    "/skills/write",
    summary="Write a new skill to a skill vault",
    description="Write a skill file to a skill vault making it available for usage."
)
async def write_skill(write_request: WriteSkillRequest, request: Request)-> WriteSkillResponse:
    try:
        check_vault_access(vault_name=write_request.vault_name, request=request)
        
        skill_input = SkillInput(name=write_request.skill_name, description=write_request.description, instructions=write_request.instructions)
        
        filename = vault_router.write_skill(vault_name=write_request.vault_name, skill=skill_input,overwrite=write_request.overwrite)
        
        return WriteSkillResponse(filename=filename)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileAlreadyExistError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@ctxvault_router.get(
    "/skills",
    summary="List vault skills",
    description="Return all the skills available in the specified vault."
)
async def docs(vault_name: str, request: Request)-> ListSkillsResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        skills = vault_router.list_skills(vault_name=vault_name)
        return ListSkillsResponse(vault_name=vault_name, skills=skills)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@ctxvault_router.get(
    "/skill",
    summary="Retrieve skill details and instructions",
    description="Write a file to a vault and optionally index it for retrieval."
)
async def read_skill(vault_name: str, skill_name: str, request: Request)-> SkillResponse:
    try: 
        check_vault_access(vault_name=vault_name, request=request)
        skill = vault_router.read_skill(vault_name=vault_name, skill_name=skill_name)

        return SkillResponse(skill=skill)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@ctxvault_router.post(
    "/episodes/write",
    summary="Record an episode in an episodic vault",
    description="Store a statement with its validity window, entities and salience."
)
async def write_episode(write_request: WriteEpisodeRequest, request: Request)-> EpisodeResponse:
    try:
        check_vault_access(vault_name=write_request.vault_name, request=request)

        episode = vault_router.write_episode(
            vault_name=write_request.vault_name,
            content=write_request.content,
            entities=write_request.entities,
            source=write_request.source,
            confidence=write_request.confidence,
            salience=write_request.salience,
            occurred_at=write_request.occurred_at,
            valid_from=write_request.valid_from,
            valid_to=write_request.valid_to,
            metadata=write_request.metadata,
        )

        return EpisodeResponse(vault_name=write_request.vault_name, episode=episode)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@ctxvault_router.post(
    "/episodes/query",
    summary="Retrieve episodes",
    description="Filter by entity, validity and source; rank by relevance, recency, salience or a blend."
)
async def query_episodes(query_request: QueryEpisodesRequest, request: Request)-> QueryEpisodesResponse:
    try:
        check_vault_access(vault_name=query_request.vault_name, request=request)

        result = vault_router.query_episodes(
            vault_name=query_request.vault_name,
            text=query_request.query,
            entities=query_request.entities or None,
            source=query_request.source,
            min_confidence=query_request.min_confidence,
            valid_at=query_request.valid_at,
            known_at=query_request.known_at,
            include_closed=query_request.include_closed,
            metadata_filters=query_request.metadata_filters or None,
            order_by=query_request.order_by,
            limit=query_request.limit,
            half_life_days=query_request.half_life_days,
            weights=query_request.weights,
            reinforce=query_request.reinforce,
        )

        return QueryEpisodesResponse(
            vault_name=query_request.vault_name,
            query=result.query,
            order_by=result.order_by,
            results=result.results,
        )
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@ctxvault_router.get(
    "/episodes/{episode_id}",
    summary="Read a single episode",
    description="Return one episode with both of its time windows."
)
async def get_episode(episode_id: str, vault_name: str, request: Request)-> EpisodeResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        episode = vault_router.get_episode(vault_name=vault_name, episode_id=episode_id)
        return EpisodeResponse(vault_name=vault_name, episode=episode)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.get(
    "/episodes/{episode_id}/history",
    summary="Read an episode's supersession chain",
    description="Return every version of a statement, oldest first."
)
async def episode_history(episode_id: str, vault_name: str, request: Request)-> EpisodeHistoryResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        history = vault_router.episode_history(vault_name=vault_name, episode_id=episode_id)
        return EpisodeHistoryResponse(vault_name=vault_name, episode_id=history.episode_id, chain=history.chain)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.post(
    "/episodes/{episode_id}/invalidate",
    summary="Close an episode",
    description="Mark a statement as no longer true without deleting it."
)
async def invalidate_episode(episode_id: str, invalidate_request: InvalidateEpisodeRequest, request: Request)-> EpisodeResponse:
    try:
        check_vault_access(vault_name=invalidate_request.vault_name, request=request)

        episode = vault_router.invalidate_episode(
            vault_name=invalidate_request.vault_name,
            episode_id=episode_id,
            valid_to=invalidate_request.valid_to,
            reason=invalidate_request.reason,
        )

        return EpisodeResponse(vault_name=invalidate_request.vault_name, episode=episode)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except EpisodeAlreadyClosedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))

@ctxvault_router.post(
    "/episodes/{episode_id}/supersede",
    summary="Replace an episode with a corrected one",
    description="Close the old statement and open its successor in a single transaction."
)
async def supersede_episode(episode_id: str, supersede_request: SupersedeEpisodeRequest, request: Request)-> EpisodeResponse:
    try:
        check_vault_access(vault_name=supersede_request.vault_name, request=request)

        episode = vault_router.supersede_episode(
            vault_name=supersede_request.vault_name,
            episode_id=episode_id,
            content=supersede_request.content,
            entities=supersede_request.entities or None,
            source=supersede_request.source,
            confidence=supersede_request.confidence,
            salience=supersede_request.salience,
            occurred_at=supersede_request.occurred_at,
            valid_from=supersede_request.valid_from,
            metadata=supersede_request.metadata,
        )

        return EpisodeResponse(vault_name=supersede_request.vault_name, episode=episode)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except EpisodeAlreadyClosedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@ctxvault_router.get(
    "/episodes",
    summary="Episode counts for a vault",
    description="Return how many episodes a vault holds and how many are still open."
)
async def episode_stats(vault_name: str, request: Request)-> EpisodeStatsResponse:
    try:
        check_vault_access(vault_name=vault_name, request=request)

        stats = vault_router.episode_stats(vault_name=vault_name)
        return EpisodeStatsResponse(vault_name=vault_name, **stats)
    except VaultNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnsupportedVaultOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAgentNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VaultAccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
