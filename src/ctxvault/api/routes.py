from pathlib import Path
from ctxvault.api.schemas import DeleteResponse, IndexRequest, IndexResponse, InitRequest, InitResponse, ListResponse, QueryRequest, QueryResponse, ReindexRequest, ReindexResponse, WriteRequest, WriteResponse
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, UnsupportedFileTypeError, VaultAlreadyExistsError, VaultNotInitializedError
from fastapi import APIRouter, FastAPI, HTTPException, Query
from ctxvault.core import vault

app = FastAPI()

ctxvault_router = APIRouter(prefix="/ctxvault", tags=["CtxVault"])

@ctxvault_router.post("/init")
async def init(init_request: InitRequest)-> InitResponse:
    try:
        vault_path, config_path = vault.init_vault(path=init_request.vault_path)
        return InitResponse(vault_path=vault_path, config_path=config_path)
    except VaultAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=f"Vault already initialized at {e.existing_path}")

@ctxvault_router.put("/index")
async def index(index_request: IndexRequest):
    indexed_files, skipped_files = vault.index_files(base_path=Path(index_request.file_path))

    return IndexResponse(indexed_files=indexed_files, skipped_files=skipped_files)

@ctxvault_router.post("/query")
async def query(query_request: QueryRequest)-> QueryResponse:

    if not query_request.query.strip():
        raise HTTPException(status_code=400, detail="Empty query.")

    result = vault.query(text=query_request.query)

    if not result.results:
        raise HTTPException(status_code=404, detail="No results found.")

    return QueryResponse(results=result.results)

@ctxvault_router.delete("/delete")
async def delete(file_path: str = Query(...))-> DeleteResponse:
    deleted_files, skipped_files = vault.delete_files(base_path=Path(file_path))

    return DeleteResponse(deleted_files=deleted_files, skipped_files=skipped_files)

@ctxvault_router.put("/reindex")
async def reindex(reindex_request: ReindexRequest)-> ReindexResponse:
    reindexed_files, skipped_files = vault.index_files(base_path=Path(reindex_request.file_path))

    return ReindexResponse(reindexed_files=reindexed_files, skipped_files=skipped_files)

@ctxvault_router.get("/list")
async def list()-> ListResponse:
    documents = vault.list_documents()
    return ListResponse(documents=documents)

@ctxvault_router.post("/write")
async def write(write_request: WriteRequest)-> WriteResponse:
    try:
        vault.write_file(file_path=Path(write_request.file_path), content=write_request.content, overwrite=write_request.overwrite)
        return WriteResponse(file_path=write_request.file_path)
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileAlreadyExistError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))