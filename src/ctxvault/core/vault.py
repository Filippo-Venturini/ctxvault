from pathlib import Path
from ctxvault.models.documents import DocumentInfo
from ctxvault.models.query_result import ChunkMatch, QueryResult
from ctxvault.utils.config import create_vault, get_vault_config, get_vaults
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, PathOutsideVaultError, UnsupportedFileTypeError
from ctxvault.utils.text_extraction import SUPPORTED_EXT

def _get_base_path(path: str, vault_path: Path)-> Path:
    if not path:
        base_path = vault_path
    else:
        base_path = Path(path)
        if not base_path.resolve().is_relative_to(vault_path):
            raise PathOutsideVaultError(f"The path must be inside the Context Vault.")
    return base_path

def init_vault(vault_name: str, path: str | None = None)-> tuple[str, str]:

    #TODO: check if a vault already exist in this path
    vault_path, config_path = create_vault(vault_name=vault_name, vault_path=path)
    return str(vault_path), config_path

def iter_files(path: Path, exclude_dirs: list[Path] | None = None):
    if exclude_dirs is None:
        exclude_dirs = []

    if path.is_file():
        if not any(path.resolve().is_relative_to(excl) for excl in exclude_dirs):
            yield path
        return

    for p in path.rglob("*"):
        if not p.is_file():
            continue

        if any(p.resolve().is_relative_to(excl) for excl in exclude_dirs):
            continue

        yield p

def index_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault_config = get_vault_config(vault_name)

    vault_path = Path(vault_config["vault_path"])
    db_path = Path(vault_config["db_path"])

    base_path = _get_base_path(path=path, vault_path=vault_path)
    
    indexed_files = []
    skipped_files = []

    for file in iter_files(path=base_path, exclude_dirs=[db_path]):
        try:
            index_file(file_path=file, vault_config=vault_config)
            indexed_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return indexed_files, skipped_files

def index_file(file_path:Path, vault_config: dict, agent_metadata: dict | None = None)-> None:
    from ctxvault.core import indexer

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")

    if not file_path.resolve().is_relative_to(Path(vault_config["vault_path"])):
        raise FileOutsideVaultError("The file to index is outside the Context Vault.")

    indexer.index_file(file_path=str(file_path), config=vault_config, agent_metadata=agent_metadata)

def query(text: str, vault_name: str, filters: dict | None = None)-> QueryResult:
    from ctxvault.core import querying

    vault_config = get_vault_config(vault_name)

    result_dict = querying.query(query_txt=text, config=vault_config, filters=filters)
    documents = result_dict["documents"][0]
    metadatas = result_dict["metadatas"][0]
    distances = result_dict["distances"][0]

    chunks_match = []
    for doc, metadata, distance in zip(documents, metadatas, distances):
        chunks_match.append(ChunkMatch(
            chunk_id=metadata["chunk_id"],
            chunk_index=metadata["chunk_index"],
            text=doc,
            score=distance,
            doc_id=metadata["doc_id"],
            source=metadata["source"],
            generated_by=metadata.get("generated_by"),
            artifact_type=metadata.get("artifact_type"),
            topic=metadata.get("topic")
        ))
    
    return QueryResult(query=text, results=chunks_match)

def delete_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault_config = get_vault_config(vault_name)
    vault_path=Path(vault_config["vault_path"])
    db_path = Path(vault_config["db_path"])

    base_path = _get_base_path(path=path, vault_path=vault_path)

    deleted_files = []
    skipped_files = []

    for file in iter_files(path=base_path, exclude_dirs=[db_path]):
        try:
            delete_file(file_path=file, vault_config=vault_config)
            deleted_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return deleted_files, skipped_files

def delete_file(file_path: Path, vault_config: dict)-> None:
    from ctxvault.core import indexer

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File already out of the Context Vault because its type is not supported.")
    
    vault_path = Path(vault_config["vault_path"])

    if not file_path.resolve().is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to delete is already outside the Context Vault.")
    
    indexer.delete_file(file_path=str(file_path), config=vault_config)

def reindex_files(vault_name: str, path: str | None = None)-> tuple[list[str], list[str]]:
    vault_config = get_vault_config(vault_name)
    vault_path=Path(vault_config["vault_path"])
    db_path = Path(vault_config["db_path"])

    base_path = _get_base_path(path=path, vault_path=vault_path)

    reindexed_files = []
    skipped_files = []

    for file in iter_files(path=base_path, exclude_dirs=[db_path]):
        try:
            reindex_file(file_path=file, vault_config=vault_config)
            reindexed_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return reindexed_files, skipped_files

def reindex_file(file_path: Path, vault_config: dict)-> None:
    from ctxvault.core import indexer

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")
    
    vault_path = Path(vault_config["vault_path"])

    if not file_path.resolve().is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to reindex is outside the Context Vault.")

    indexer.reindex_file(file_path=str(file_path), config=vault_config)

def list_documents(vault_name: str)-> list[DocumentInfo]:
    from ctxvault.core import querying

    vault_config = get_vault_config(vault_name)

    return querying.list_documents(config=vault_config)

def list_vaults()-> list[str]:
    return get_vaults()

def write_file(vault_name: str, file_path: str, content: str, overwrite: bool = True, agent_metadata: dict | None = None)-> None:
    vault_config = get_vault_config(vault_name)
    file_path = Path(file_path)

    if not file_path.suffix:
        raise FileTypeNotPresentError("File type not present in the file path.")

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")
    
    vault_path = Path(vault_config["vault_path"])
    abs_path = (vault_path / file_path).resolve()

    if not abs_path.is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to write must have a path inside the Context Vault.")

    if abs_path.exists() and not overwrite:
        raise FileAlreadyExistError("File already exist in the Context Vault. Use overwrite flag to overwrite it.")
    
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    index_file(file_path=abs_path, agent_metadata=agent_metadata, vault_config=vault_config)