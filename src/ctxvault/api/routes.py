from pathlib import Path
from ctxvault.api.schemas import DeleteResponse, IndexRequest, IndexResponse, InitRequest, InitResponse, QueryRequest, QueryResponse, ReindexRequest, ReindexResponse
from ctxvault.core.exceptions import VaultAlreadyExistsError
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

    if query_request.query == None:
        raise HTTPException(status_code=400, detail="Empty query.")

    result = vault.query(text=query_request.query)

    if not result.results:
        raise HTTPException(status_code=404, detail="No results found.")

    return QueryResponse(results=result.results)

@ctxvault_router.delete("/delete")
async def delete(file_path: str = Query(...)):
    deleted_files, skipped_files = vault.delete_files(base_path=Path(file_path))

    return DeleteResponse(deleted_files=deleted_files, skipped_files=skipped_files)

@ctxvault_router.put("/reindex")
async def reindex(reindex_request: ReindexRequest):
    reindexed_files, skipped_files = vault.index_files(base_path=Path(reindex_request.file_path))

    return ReindexResponse(reindexed_files=reindexed_files, skipped_files=skipped_files)


@ctxvault_router.get("/list")
async def list():
    return None