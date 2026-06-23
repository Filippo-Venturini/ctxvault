from pathlib import Path
import json
import shutil
from ctxvault.core.exceptions import VaultAlreadyExistsError, VaultNotFoundError, MissingAgentNameError
from ctxvault.models.vaults import VaultType

CTXVAULT_DIR_NAME = ".ctxvault"
GLOBAL_DIR = Path.home() / CTXVAULT_DIR_NAME

def _config_file(root: Path) -> Path:
    return root / "config.json"

def _vaults_dir(root: Path) -> Path:
    return root / "vaults"

def _find_local_root() -> Path | None:
    current = Path.cwd()
    while True:
        candidate = current / CTXVAULT_DIR_NAME
        if (candidate / "config.json").exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent

def _resolve_local_paths(local_config: dict, local_root: Path) -> dict:
    project_root = local_root.parent
    for vault_data in local_config["vaults"].values():
        if not Path(vault_data["vault_path"]).is_absolute():
            vault_data["vault_path"] = str((project_root / vault_data["vault_path"]).resolve())
            vault_data["db_path"] = str((project_root / vault_data["db_path"]).resolve()) if vault_data["db_path"] else None
    return local_config

def _load_config() -> tuple[dict, dict, Path | None]:
    if not _config_file(GLOBAL_DIR).exists():
        GLOBAL_DIR.mkdir(exist_ok=True)
        _vaults_dir(GLOBAL_DIR).mkdir(exist_ok=True)
        _config_file(GLOBAL_DIR).write_text(json.dumps({"vaults": {}}))

    global_config = json.loads(_config_file(GLOBAL_DIR).read_text())

    local_root = _find_local_root()

    if local_root is not None:
        local_config = json.loads(_config_file(local_root).read_text())
        local_config = _resolve_local_paths(local_config, local_root)
    else:
        local_config = {"vaults": {}}

    return global_config, local_config, local_root

def _save_config(data: dict, root: Path) -> None:
    _config_file(root).write_text(json.dumps(data))

def _get_vault_scope(vault_name: str, global_config: dict, local_config: dict) -> str | None:
    if vault_name in local_config["vaults"]:
        return "local"
    if vault_name in global_config["vaults"]:
        return "global"
    return None

def create_vault(vault_name: str, vault_type: VaultType, restricted: bool, vault_path: str | None, global_vault: bool = False, embedding_model: str | None = None) -> tuple[str, str]:
    # Embedding only happens in semantic vaults; skill vaults are curated and
    # never indexed, so a model override there would be silently meaningless.
    if embedding_model and vault_type != VaultType.SEMANTIC:
        raise ValueError("--embedding-model is only supported for semantic vaults.")

    if global_vault:
        global_config, _, _ = _load_config()
        config = global_config
        save_root = GLOBAL_DIR
        vault_path_abs = _vaults_dir(GLOBAL_DIR) / vault_name
    else:
        save_root = (Path.cwd() / CTXVAULT_DIR_NAME).resolve()
        save_root.mkdir(exist_ok=True)
        config = json.loads(_config_file(save_root).read_text()) if _config_file(save_root).exists() else {"vaults": {}}
        vault_path_abs = (Path(vault_path) / "vaults" / vault_name).resolve() if vault_path else _vaults_dir(save_root) / vault_name

    if vault_name in config["vaults"]:
        raise VaultAlreadyExistsError(f"Vault '{vault_name}' already exists.")

    db_path_posix = None
    vault_path_abs.mkdir(parents=True, exist_ok=True)

    if vault_type == VaultType.SEMANTIC:
        db_path = vault_path_abs / "chroma"
        db_path.mkdir(parents=True, exist_ok=True)
        
        if global_vault:
            db_path_posix = db_path.as_posix()
        else:
            db_path_posix = db_path.relative_to(save_root.parent).as_posix()

    vault_path_final = vault_path_abs.as_posix() if global_vault else vault_path_abs.relative_to(save_root.parent).as_posix()

    entry = {
        "type": vault_type.value,
        "vault_path": vault_path_final,
        "db_path": db_path_posix,
        "restricted": restricted,
        "allowed_agents": []
    }
    # Store the model only when overridden, so existing/default vaults keep their
    # current config shape and resolve to embedding.DEFAULT_EMBEDDING_MODEL.
    if embedding_model:
        entry["embedding_model"] = embedding_model

    config["vaults"][vault_name] = entry

    _save_config(data=config, root=save_root)
    return str(vault_path_abs), str(_config_file(save_root))

def get_vaults() -> list[dict]:
    global_config, local_config, _ = _load_config()

    result = []

    for name, data in local_config["vaults"].items():
        result.append({
            "name": name,
            "type": data.get("type"),
            "scope": "local",
            "vault_path": data.get("vault_path"),
            "db_path": data.get("db_path"),
            "restricted": data.get("restricted"),
            "allowed_agents": data.get("allowed_agents"),
            "embedding_model": data.get("embedding_model")
        })

    for name, data in global_config["vaults"].items():
        result.append({
            "name": name,
            "type": data.get("type"),
            "scope": "global",
            "vault_path": data.get("vault_path"),
            "db_path": data.get("db_path"),
            "restricted": data.get("restricted"),
            "allowed_agents": data.get("allowed_agents"),
            "embedding_model": data.get("embedding_model")
        })

    return result

def get_vault_config(vault_name: str) -> dict:
    global_config, local_config, _ = _load_config()
    vault_config = local_config["vaults"].get(vault_name) or global_config["vaults"].get(vault_name)
    if vault_config is None:
        raise VaultNotFoundError(f"Vault '{vault_name}' does not exist.")
    return vault_config

def is_authorized(vault_name: str, agent_name: str) -> bool:
    vault_config = get_vault_config(vault_name)

    is_restricted = vault_config.get("restricted", False)

    if is_restricted and agent_name is None:
        raise MissingAgentNameError(f"Trying to access restricted vault '{vault_name}' without providing an agent name.")

    allowed_agents = vault_config.get("allowed_agents", [])

    return not is_restricted or agent_name in allowed_agents

def attach_agent_to_vault(vault_name: str, agent_name: str) -> None:
    global_config, local_config, local_root = _load_config()

    scope = _get_vault_scope(vault_name, global_config, local_config)
    if scope is None:
        raise VaultNotFoundError(f"Vault '{vault_name}' does not exist.")

    config = local_config if scope == "local" else global_config
    save_root = local_root if scope == "local" else GLOBAL_DIR

    vault_config = config["vaults"][vault_name]
    if agent_name not in vault_config["allowed_agents"]:
        vault_config["allowed_agents"].append(agent_name)
    vault_config["restricted"] = True

    _save_config(data=config, root=save_root)

def detach_agent_from_vault(vault_name: str, agent_name: str) -> None:
    global_config, local_config, local_root = _load_config()

    scope = _get_vault_scope(vault_name, global_config, local_config)
    if scope is None:
        raise VaultNotFoundError(f"Vault '{vault_name}' does not exist.")

    config = local_config if scope == "local" else global_config
    save_root = local_root if scope == "local" else GLOBAL_DIR

    vault_config = config["vaults"][vault_name]
    if vault_config.get("restricted") and agent_name in vault_config.get("allowed_agents", []):
        vault_config["allowed_agents"].remove(agent_name)
        _save_config(data=config, root=save_root)

def make_public(vault_name: str) -> None:
    global_config, local_config, local_root = _load_config()

    scope = _get_vault_scope(vault_name, global_config, local_config)
    if scope is None:
        raise VaultNotFoundError(f"Vault '{vault_name}' does not exist.")

    config = local_config if scope == "local" else global_config
    save_root = local_root if scope == "local" else GLOBAL_DIR

    config["vaults"][vault_name]["allowed_agents"] = []
    config["vaults"][vault_name]["restricted"] = False

    _save_config(data=config, root=save_root)

def delete_vault(vault_name: str) -> None:
    global_config, local_config, local_root = _load_config()

    scope = _get_vault_scope(vault_name, global_config, local_config)
    if scope is None:
        raise VaultNotFoundError(f"Vault '{vault_name}' does not exist.")

    config = local_config if scope == "local" else global_config
    save_root = local_root if scope == "local" else GLOBAL_DIR

    vault_path = Path(config["vaults"][vault_name]["vault_path"])
    if vault_path.exists():
        shutil.rmtree(vault_path)

    del config["vaults"][vault_name]
    _save_config(data=config, root=save_root)