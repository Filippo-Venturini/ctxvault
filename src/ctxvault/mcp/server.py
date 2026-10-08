from ctxvault.api.schemas import *
from ctxvault.core import vault_router
from ctxvault.core.exceptions import *
from ctxvault.models.vaults import SkillInput
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import logging
import argparse
import asyncio

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser()
parser.add_argument("--agent", type=str, default=None)
args, _ = parser.parse_known_args()

@asynccontextmanager
async def lifespan(server):
    logger.info("ctxvault MCP server starting...")
    
    warmup_task = asyncio.create_task(async_warmup())
    
    yield
    
    logger.info("ctxvault MCP server shutting down...")
    if not warmup_task.done():
        warmup_task.cancel()

AGENT_ID = args.agent

mcp = FastMCP("ctxvault", lifespan=lifespan)

warmup_complete = asyncio.Event()

async def async_warmup():
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, vault_router.warmup)
        warmup_complete.set()
        logger.info("Warm-up complete — embeddings ready")
    except Exception as e:
        logger.error(f"Warm-up failed: {e}")
        warmup_complete.set()

async def ensure_warmup(wait: bool = False, timeout_seconds: int = 90):
    """
    Check if warmup is complete. By default, raises an error if not ready.
    
    Args:
        wait: If True, wait for warmup to complete (up to timeout_seconds)
        timeout_seconds: Maximum time to wait if wait=True
    
    Raises:
        ValueError: If warmup not complete and wait=False
        ValueError: If warmup times out when wait=True
    """
    if not warmup_complete.is_set():
        if not wait:
            raise ValueError(
                "Embedding model is still initializing. This typically takes 1-2 minutes on first startup. "
                "Please retry this operation in 30-60 seconds. Subsequent operations will be instant."
            )
        
        logger.info("Waiting for embeddings to load...")
        try:
            await asyncio.wait_for(warmup_complete.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise ValueError(
                "Embedding model initialization timed out. Please check server logs and retry."
            )

@mcp.tool(description="Check if the embedding model has finished initializing. Use this to verify warmup status before attempting queries or writes.")
def warmup_status() -> WarmupStatusResponse:
    return WarmupStatusResponse(
        ready = warmup_complete.is_set(),
        status = "ready" if warmup_complete.is_set() else "warming_up",
        message = "Embedding model is ready" if warmup_complete.is_set() else "Embedding model is initializing (1-2 minutes)"
    )

def check_access(vault_name: str, agent_name: str):
    if not vault_router.is_agent_authorized(vault_name, agent_name):
        raise PermissionError(f"Agent '{agent_name}' is not authorized to access vault '{vault_name}'")

@mcp.tool(description="Search for relevant information in a CtxVault vault using semantic similarity. Use this when the user asks a question that might be answered by their personal knowledge base or documents. Returns the most relevant text chunks with their source files.")
async def query(vault_name: str, query: str) -> QueryResponse:
    await ensure_warmup()
    
    try:
        check_access(vault_name, AGENT_ID)
        result = vault_router.query(vault_name=vault_name, text=query, filters=None)
        return QueryResponse(results=result.results)
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except EmptyQueryError:
        raise ValueError("Query text cannot be empty.")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

@mcp.tool(description="Save new information or agent-generated content to a semantic vault for future retrieval. Use this only with semantic vaults, to persist important context, summaries, or notes that should be remembered across sessions. Supports .txt, .md, and .docx formats.")
async def write_doc(vault_name: str, file_path: str, content: str, generated_by: str, overwrite: bool = False)-> WriteDocResponse:
    await ensure_warmup()
    
    try:
        check_access(vault_name, AGENT_ID)
        timestamp = datetime.now(timezone.utc).isoformat()
        vault_router.write_doc(vault_name=vault_name,
                         file_path=file_path, 
                         content=content, 
                         overwrite=overwrite, 
                         agent_metadata=AgentMetadata(generated_by=generated_by, timestamp=timestamp))
        
        return WriteDocResponse(file_path=file_path)
    except VaultNotFoundError as e:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise ValueError(f"Error writing file: {e}")
    except FileAlreadyExistError as e:
        raise ValueError(f"File already exists: {e}")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)
    except Exception as e:
        raise ValueError(f"Unexpected error writing file: {e}")

@mcp.tool(description="List all available vaults. Use this before querying or writing to discover which vaults exist and choose the right one.")
def list_vaults()-> ListVaultsResponse:
    vaults = vault_router.list_vaults()
    return ListVaultsResponse(vaults=vaults)

@mcp.tool(description="List all indexed documents inside a specific vault. Use this to understand what knowledge is available before performing a search.")
def list_docs(vault_name: str) -> ListDocsResponse:
    try:        
        check_access(vault_name, AGENT_ID)
        documents = vault_router.list_documents(vault_name=vault_name)
        return ListDocsResponse(vault_name=vault_name, documents=documents)
    except VaultNotFoundError as e:
        raise ValueError(f"Vault {vault_name} doesn't exist.")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)
    
@mcp.tool(description="Create and store a new skill in a skill vault. Use this to persist procedural knowledge, instructions, or how-to guides that agents can retrieve and execute later. The skill will be indexed by name and description for fast lookup. Use this only with skill vaults.")
async def write_skill(vault_name: str, skill_name: str, description: str, instructions: str, overwrite: bool = False)-> WriteSkillResponse:
    await ensure_warmup()
    
    try:
        check_access(vault_name, AGENT_ID)
        skill_input = SkillInput(name=skill_name, description=description, instructions=instructions)
        filename = vault_router.write_skill(vault_name=vault_name, skill = skill_input, overwrite=overwrite)
        
        return WriteSkillResponse(filename=filename)
    except VaultNotFoundError as e:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise ValueError(f"Error writing file: {e}")
    except FileAlreadyExistError as e:
        raise ValueError(f"File already exists: {e}")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)
    except Exception as e:
        raise ValueError(f"Unexpected error writing file: {e}")
    
@mcp.tool(description="List all available skills inside a specific vault. Use this to understand what skills are available before trying to fetch one.")
def list_skills(vault_name: str) -> ListSkillsResponse:
    try:        
        check_access(vault_name, AGENT_ID)
        skills = vault_router.list_skills(vault_name=vault_name)
        return ListSkillsResponse(vault_name=vault_name, skills=skills)
    except VaultNotFoundError as e:
        raise ValueError(f"Vault {vault_name} doesn't exist.")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

@mcp.tool(description="")
def read_skill(vault_name: str, skill_name: str)-> SkillResponse:
    try:
        check_access(vault_name, AGENT_ID)
        skill = vault_router.read_skill(vault_name=vault_name, skill_name=skill_name)
        return SkillResponse(skill=skill)
    except VaultNotFoundError as e:
        raise ValueError(e)
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

@mcp.tool(description="Record something that happened or something the user stated, in an episodic vault. Use this for facts with a lifetime — situations, preferences, relationships, plans — rather than for documents. Give the entities it is about so it can be looked up later, and a salience between 0 and 1 for how much it matters.")
def write_episode(vault_name: str, content: str, entities: list[str] = [], source: str = None, salience: float = 0.5, confidence: float = 1.0, occurred_at: str = None, valid_from: str = None) -> EpisodeResponse:
    try:
        check_access(vault_name, AGENT_ID)
        episode = vault_router.write_episode(
            vault_name=vault_name,
            content=content,
            entities=entities,
            source=source or AGENT_ID,
            salience=salience,
            confidence=confidence,
            occurred_at=occurred_at,
            valid_from=valid_from,
        )
        return EpisodeResponse(vault_name=vault_name, episode=episode)
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)
    except Exception as e:
        raise ValueError(f"Unexpected error writing episode: {e}")

@mcp.tool(description="Retrieve episodes from an episodic vault. By default only statements that still hold are returned. Filter by entity for 'everything about X', pass valid_at to ask what was true at a past moment, or known_at to ask what the vault had already learned by then. Query text is optional and ranks results; without it the newest come first.")
def query_episodes(vault_name: str, query: str = None, entities: list[str] = [], valid_at: str = None, known_at: str = None, include_closed: bool = False, order_by: str = None, limit: int = 10) -> QueryEpisodesResponse:
    try:
        check_access(vault_name, AGENT_ID)
        result = vault_router.query_episodes(
            vault_name=vault_name,
            text=query,
            entities=entities or None,
            valid_at=valid_at,
            known_at=known_at,
            include_closed=include_closed,
            order_by=order_by,
            limit=limit,
        )
        return QueryEpisodesResponse(
            vault_name=vault_name,
            query=result.query,
            order_by=result.order_by,
            results=result.results,
        )
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)
    except ValueError as e:
        raise ValueError(e)

@mcp.tool(description="Mark an episode as no longer true, without deleting it. Use this when something ends and nothing replaces it. If a corrected version exists instead, use supersede_episode so the two stay linked.")
def invalidate_episode(vault_name: str, episode_id: str, valid_to: str = None, reason: str = None) -> EpisodeResponse:
    try:
        check_access(vault_name, AGENT_ID)
        episode = vault_router.invalidate_episode(vault_name=vault_name, episode_id=episode_id, valid_to=valid_to, reason=reason)
        return EpisodeResponse(vault_name=vault_name, episode=episode)
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except (EpisodeNotFoundError, EpisodeAlreadyClosedError) as e:
        raise ValueError(e)
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

@mcp.tool(description="Replace an episode with a corrected or updated version. The old statement is closed exactly where the new one begins and the two are linked, so the history of what changed stays readable. Entities and salience carry over from the old episode unless you pass new ones. Use this whenever new information contradicts something already recorded.")
def supersede_episode(vault_name: str, episode_id: str, content: str, entities: list[str] = [], source: str = None, salience: float = None) -> EpisodeResponse:
    try:
        check_access(vault_name, AGENT_ID)
        episode = vault_router.supersede_episode(
            vault_name=vault_name,
            episode_id=episode_id,
            content=content,
            entities=entities or None,
            source=source or AGENT_ID,
            salience=salience,
        )
        return EpisodeResponse(vault_name=vault_name, episode=episode)
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except (EpisodeNotFoundError, EpisodeAlreadyClosedError) as e:
        raise ValueError(e)
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

@mcp.tool(description="Show every version of a statement, oldest first. Use this to explain why the vault believes something, or to see what an episode used to say before it was corrected.")
def episode_history(vault_name: str, episode_id: str) -> EpisodeHistoryResponse:
    try:
        check_access(vault_name, AGENT_ID)
        history = vault_router.episode_history(vault_name=vault_name, episode_id=episode_id)
        return EpisodeHistoryResponse(vault_name=vault_name, episode_id=history.episode_id, chain=history.chain)
    except VaultNotFoundError:
        raise ValueError(f"Vault '{vault_name}' does not exist.")
    except EpisodeNotFoundError as e:
        raise ValueError(e)
    except UnsupportedVaultOperationError as e:
        raise ValueError(e)

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()