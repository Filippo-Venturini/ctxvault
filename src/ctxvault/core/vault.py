from pathlib import Path
from ctxvault.utils.config import load_config, save_config
from ctxvault.core.exceptions import VaultAlreadyExistsError

def init_vault(path: str)-> tuple[str, str]:
    existing_config = load_config()
    if existing_config is not None:
        raise VaultAlreadyExistsError(existing_path=existing_config["db_path"])

    db_path = Path(path).resolve()
    db_path.mkdir(parents=True, exist_ok=True)
    vault_path, config_path = save_config(str(db_path))
    return vault_path, config_path