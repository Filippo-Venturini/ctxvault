from pathlib import Path
import json
from ctxvault.core.exceptions import VaultNotInitializedError

CONFIG_DIR = Path.home() / ".ctxvault"
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_config(db_path: str)-> tuple[str,str]:
    CONFIG_DIR.mkdir(exist_ok=True)
    config = {"db_path": db_path}
    CONFIG_FILE.write_text(json.dumps(config))

    return db_path, str(CONFIG_FILE)

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return None
    return json.loads(CONFIG_FILE.read_text())

def get_db_path() -> str:
    config = load_config()
    if config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    return config["db_path"]