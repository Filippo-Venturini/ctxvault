from ctxvault.core.exceptions import VaultTypeNotValidError
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.core.vaults.skill import SkillVault
from ctxvault.models.documents import SemanticDocumentInfo, SkillDocumentInfo, DocumentContent
from ctxvault.models.episodes import Episode, EpisodeHistory, EpisodeQueryResult
from ctxvault.models.query_result import QueryResult
from ctxvault.models.vaults import SkillOutput, SkillInput, VaultOperation, VaultType
from ctxvault.utils.config import create_vault, get_vault_config, get_vaults

# Explicit, and deliberately not a default: a vault whose type this version does
# not know must fail loudly. Falling back to semantic would silently open an
# episodic vault written by a newer ctxvault as a document store.
_VAULT_CLASSES = {
    VaultType.SEMANTIC.value: SemanticVault,
    VaultType.SKILL.value: SkillVault,
    VaultType.EPISODIC.value: EpisodicVault,
}

def _get_vault(vault_name: str):
    config = get_vault_config(vault_name)
    vault_type = config.get("type", VaultType.SEMANTIC.value)

    vault_class = _VAULT_CLASSES.get(vault_type)
    if vault_class is None:
        raise VaultTypeNotValidError(
            f"Vault '{vault_name}' has unknown type '{vault_type}'. "
            f"Known types: {', '.join(_VAULT_CLASSES)}."
        )

    return vault_class(vault_name, config)

def warmup() -> None:
    """
    Pre-initializes heavy components (ChromaDB, embedding model) so that
    the first tool call in long-running server contexts (MCP, FastAPI) is
    not penalized by lazy initialization costs.
    """
    from ctxvault.core import querying, indexer
    from ctxvault.core.embedding import embed_list
    from ctxvault.storage import chroma_store

    embed_list(chunks=["warmup"])

def is_agent_authorized(vault_name: str, agent_name: str) -> bool:
    vault = _get_vault(vault_name=vault_name)
    return vault.is_agent_authorized(agent_name=agent_name)

def attach_agent(vault_name: str, agent_name: str) -> None:
    vault = _get_vault(vault_name=vault_name)
    vault.attach_agent(agent_name=agent_name)

def detach_agent(vault_name: str, agent_name: str) -> None:
    vault = _get_vault(vault_name=vault_name)
    vault.detach_agent(agent_name=agent_name)

def make_public(vault_name: str) -> None:
    vault = _get_vault(vault_name=vault_name)
    vault.make_public()

def purge_vault(vault_name: str) -> None:
    vault = _get_vault(vault_name=vault_name)
    vault.purge_vault()

def init_vault(vault_name: str, vault_type: str | VaultType = VaultType.SEMANTIC, restricted: bool = False, path: str | None = None, global_vault: bool = False, embedding_model: str | None = None)-> tuple[str, str]:
    if isinstance(vault_type, str):
        try:
            vault_type = VaultType(vault_type)
        except ValueError:
            raise VaultTypeNotValidError(f"Vault type not valid: {vault_type}. Choose between: {', '.join(VaultType.list())}")

    vault_path, config_path = create_vault(vault_name=vault_name, vault_type=vault_type, restricted=restricted, vault_path=path, global_vault=global_vault, embedding_model=embedding_model)
    return str(vault_path), config_path

def index_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.INDEX)
    return vault.index_files(path=path)

def query(text: str, vault_name: str, filters: dict | None = None, n_results: int = 5)-> QueryResult:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.QUERY)
    return vault.query(text=text, filters=filters, n_results=n_results)

def delete_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.DELETE)
    return vault.delete_files(path=path)

def reindex_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.REINDEX)
    return vault.reindex_files(path=path)

def write_doc(vault_name: str, file_path: str, content: str, overwrite: bool = True, agent_metadata: dict | None = None)-> None:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.WRITE_DOC)
    vault.write_doc(file_path=file_path, content=content, overwrite=overwrite, agent_metadata=agent_metadata)

def write_skill(vault_name: str, skill: SkillInput, overwrite: bool = True)-> str:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.WRITE_SKILL)
    return vault.write_skill(skill=skill, overwrite=overwrite)

def list_documents(vault_name: str)-> list[SemanticDocumentInfo]:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.LIST_DOCUMENTS)
    return vault.list_documents()

def get_document_content(vault_name: str, doc_id: str) -> DocumentContent:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.READ_DOC_CONTENT)
    return vault.get_document_content(doc_id=doc_id)

def list_skills(vault_name: str)-> list[SkillDocumentInfo]:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.LIST_SKILLS)
    return vault.list_skills()

def read_skill(vault_name: str, skill_name: str)-> SkillOutput:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.READ_SKILL)
    return vault.read_skill(skill_name=skill_name)

def list_vaults()-> list[dict]:
    return get_vaults()

def write_episode(vault_name: str, content: str, **kwargs)-> Episode:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.WRITE_EPISODE)
    return vault.write_episode(content=content, **kwargs)

def get_episode(vault_name: str, episode_id: str)-> Episode:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.READ_EPISODE)
    return vault.get_episode(episode_id=episode_id)

def query_episodes(vault_name: str, text: str | None = None, **kwargs)-> EpisodeQueryResult:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.QUERY_EPISODES)
    return vault.query_episodes(text=text, **kwargs)

def invalidate_episode(vault_name: str, episode_id: str, valid_to: str | None = None, reason: str | None = None)-> Episode:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.INVALIDATE_EPISODE)
    return vault.invalidate_episode(episode_id=episode_id, valid_to=valid_to, reason=reason)

def supersede_episode(vault_name: str, episode_id: str, content: str, **kwargs)-> Episode:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.SUPERSEDE_EPISODE)
    return vault.supersede_episode(episode_id=episode_id, content=content, **kwargs)

def episode_history(vault_name: str, episode_id: str)-> EpisodeHistory:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.READ_EPISODE)
    return vault.history(episode_id=episode_id)

def mark_recalled(vault_name: str, episode_ids: list[str])-> None:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.WRITE_EPISODE)
    vault.mark_recalled(episode_ids=episode_ids)

def episode_stats(vault_name: str)-> dict:
    vault = _get_vault(vault_name=vault_name)
    vault._require_operation(VaultOperation.READ_EPISODE)
    return vault.stats()