from pathlib import Path
from ctxvault.models.documents import DocumentInfo
from ctxvault.models.query_result import ChunkMatch, QueryResult
from ctxvault.utils.config import load_config, save_config
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, UnsupportedFileTypeError, VaultAlreadyExistsError, VaultNotInitializedError
from ctxvault.utils.text_extraction import SUPPORTED_EXT
from ctxvault.core import indexer
from ctxvault.core import querying
from sympy import content

def init_vault(path: str)-> tuple[str, str]:
    existing_config = load_config()
    if existing_config is not None:
        raise VaultAlreadyExistsError(existing_path=existing_config["vault_path"])

    vault_path = Path(path).resolve()
    db_path = vault_path / "chroma"
    vault_path.mkdir(parents=True, exist_ok=True)
    db_path.mkdir(parents=True, exist_ok=True)
    config_path = save_config(vault_path=str(vault_path), db_path=str(db_path))
    return str(vault_path), config_path

def iter_files(path: Path):
    if path.is_file():
        yield path
    else:
        yield from (
            p for p in path.rglob("*")
            if p.is_file()
        )

def index_files(base_path: Path)-> tuple[list[str], list[str]]:
    indexed_files = []
    skipped_files = []

    for file in iter_files(path=base_path):
        try:
            index_file(file_path=file)
            indexed_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return indexed_files, skipped_files

def index_file(file_path:Path)-> None:
    vault_config = load_config()
    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")
    if vault_config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    
    vault_path = Path(vault_config["vault_path"])

    if not file_path.resolve().is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to index is outside the Context Vault.")

    indexer.index_file(file_path=str(file_path))

def query(text: str)-> QueryResult:
    result_dict = querying.query(query_txt=text)
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
            source=metadata["source"]
        ))
    
    return QueryResult(query=text, results=chunks_match)

def delete_files(base_path: Path)-> tuple[list[str], list[str]]:
    deleted_files = []
    skipped_files = []

    for file in iter_files(path=base_path):
        try:
            delete_file(file_path=file)
            deleted_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return deleted_files, skipped_files

def delete_file(file_path: Path)-> None:
    vault_config = load_config()

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File already out of the Context Vault because its type is not supported.")

    if vault_config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    
    vault_path = Path(vault_config["vault_path"])

    if not file_path.resolve().is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to delete is already outside the Context Vault.")
    
    indexer.delete_file(file_path=str(file_path))

def reindex_files(base_path: Path)-> tuple[list[str], list[str]]:
    reindexed_files = []
    skipped_files = []

    for file in iter_files(path=base_path):
        try:
            reindex_file(file_path=file)
            reindexed_files.append(str(file))
        except Exception as e:
            skipped_files.append(f"{str(file)} ({e})")

    return reindexed_files, skipped_files

def reindex_file(file_path: Path)-> None:
    vault_config = load_config()
    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")
    if vault_config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    
    vault_path = Path(vault_config["vault_path"])

    if not file_path.resolve().is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to reindex is outside the Context Vault.")

    indexer.reindex_file(file_path=str(file_path))

def list_documents()-> list[DocumentInfo]:
    return querying.list_documents()

def write_file(file_path: Path, content: str, overwrite: bool = True):
    vault_config = load_config()

    if not file_path.suffix:
        raise FileTypeNotPresentError("File type not present in the file path.")

    if file_path.suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError("File type not supported.")
    if vault_config is None:
        raise VaultNotInitializedError("Context Vault not initialized in this path. Execute 'ctxvault init' first.")
    
    vault_path = Path(vault_config["vault_path"])
    abs_path = (vault_path / file_path).resolve()

    if not abs_path.is_relative_to(vault_path):
        raise FileOutsideVaultError("The file to write must have a path inside the Context Vault.")

    if abs_path.exists() and not overwrite:
        raise FileAlreadyExistError("File already exist in the Context Vault. Use overwrite flag to overwrite it.")
    
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    index_file(file_path=abs_path)