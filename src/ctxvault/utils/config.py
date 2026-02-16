from pathlib import Path
import json
from ctxvault.core.exceptions import VaultAlreadyExistsError, VaultNotFoundError, VaultNotInitializedError

"""
CONFIG_DIR = Path.home() / ".ctxvault"
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_config(vault_path: str, db_path: str)-> str:
    CONFIG_DIR.mkdir(exist_ok=True)
    config = {
        "vault_path": vault_path,
        "db_path": db_path
    }
    CONFIG_FILE.write_text(json.dumps(config))

    return str(CONFIG_FILE)

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return None
    return json.loads(CONFIG_FILE.read_text())

def get_db_path() -> str:
    config = load_config()
    if config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    return config["db_path"]
"""

CONFIG_DIR = Path.home() / ".ctxvault"
CONFIG_FILE = CONFIG_DIR / "config.json"
VAULTS_DIR = CONFIG_DIR / "vaults"

def _load_global_config() -> dict:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"active_vault": None}))
    return json.loads(CONFIG_FILE.read_text())

def _save_global_config(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data))

def _vault_file(name: str) -> Path:
    VAULTS_DIR.mkdir(exist_ok=True)
    return VAULTS_DIR / f"{name}.json"

def create_vault(name: str, vault_path: str) -> tuple[str, str]:
    vault_path = Path(vault_path).resolve()
    db_path = vault_path / "chroma"
    vault_path.mkdir(parents=True, exist_ok=True)
    db_path.mkdir(parents=True, exist_ok=True)

    config = _load_global_config()

    vault_file = _vault_file(name)
    if vault_file.exists():
        raise VaultAlreadyExistsError(f"Vault '{name}' already exists.")

    vault_file.write_text(json.dumps({
        "vault_path": str(vault_path),
        "db_path": str(db_path)
    }))

    if not config.get("active_vault"):
        config["active_vault"] = name
        _save_global_config(config)

    return str(vault_path), str(CONFIG_FILE)

def get_vaults() -> list[str]:
    return [f.stem for f in VAULTS_DIR.glob("*.json")]

def set_active_vault(name: str) -> None:
    if not _vault_file(name).exists():
        raise VaultNotFoundError(f"Vault '{name}' does not exist.")
    config = _load_global_config()
    config["active_vault"] = name
    _save_global_config(config)

def get_active_vault_name() -> str:
    config = _load_global_config()
    name = config.get("active_vault")
    if not name:
        raise VaultNotInitializedError("No active vault. Initialize one first.")
    return name

def get_active_vault_config() -> dict:
    config = _load_global_config()
    name = config.get("active_vault")
    if not name:
        raise VaultNotInitializedError("No active vault. Initialize one first.")
    return get_vault_config(name)

def get_vault_config(name: str) -> dict:
    vault_file = _vault_file(name)
    if not vault_file.exists():
        raise VaultNotFoundError(f"Vault '{name}' does not exist.")
    return json.loads(vault_file.read_text())