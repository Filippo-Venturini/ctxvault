from pathlib import Path
from ctxvault.api.schemas import DeleteRequest, DeleteResponse, IndexRequest, IndexResponse, InitRequest, InitResponse, ListRequest, ListResponse, QueryRequest, QueryResponse, ReindexRequest, ReindexResponse, WriteRequest, WriteResponse
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, UnsupportedFileTypeError, VaultAlreadyExistsError, VaultNotInitializedError
from fastapi import APIRouter, FastAPI, HTTPException, Query
from ctxvault.core import vault

app = FastAPI()

ctxvault_router = APIRouter(prefix="/ctxvault", tags=["CtxVault"])

#TODO: add catch for VaultNotFoundError

@ctxvault_router.post("/init")
async def init(init_request: InitRequest)-> InitResponse:
    try:
        vault_path, config_path = vault.init_vault(name=init_request.vault_name)
        return InitResponse(vault_path=vault_path, config_path=config_path)
    except VaultAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=f"Vault already initialized at {e.existing_path}")

@ctxvault_router.put("/index")
async def index(index_request: IndexRequest):
    indexed_files, skipped_files = vault.index_files(vault_name=index_request.vault_name, base_path=index_request.file_path)

    return IndexResponse(indexed_files=indexed_files, skipped_files=skipped_files)

@ctxvault_router.post("/query")
async def query(query_request: QueryRequest)-> QueryResponse:

    if not query_request.query.strip():
        raise HTTPException(status_code=400, detail="Empty query.")

    result = vault.query(vault_name=query_request.vault_name,text=query_request.query, filters=query_request.filters)

    if not result.results:
        raise HTTPException(status_code=404, detail="No results found.")

    return QueryResponse(results=result.results)

@ctxvault_router.delete("/delete")
async def delete(delete_request: DeleteRequest)-> DeleteResponse:
    deleted_files, skipped_files = vault.delete_files(vault_name=delete_request.vault_name, path=delete_request.file_path)

    return DeleteResponse(deleted_files=deleted_files, skipped_files=skipped_files)

@ctxvault_router.put("/reindex")
async def reindex(reindex_request: ReindexRequest)-> ReindexResponse:
    reindexed_files, skipped_files = vault.index_files(vault_name=reindex_request.vault_name, base_path=reindex_request.file_path)

    return ReindexResponse(reindexed_files=reindexed_files, skipped_files=skipped_files)

@ctxvault_router.get("/list")
async def list(listRequest: ListRequest)-> ListResponse:
    documents = vault.list_documents(vault_name=listRequest.vault_name)
    return ListResponse(documents=documents)

@ctxvault_router.post("/write")
async def write(write_request: WriteRequest)-> WriteResponse:
    try:
        vault.write_file(file_path=Path(write_request.file_path), content=write_request.content, overwrite=write_request.overwrite, agent_metadata=write_request.agent_metadata.model_du() if write_request.agent_metadata else None)
        return WriteResponse(file_path=write_request.file_path)
    except (VaultNotInitializedError, FileOutsideVaultError, UnsupportedFileTypeError, FileTypeNotPresentError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileAlreadyExistError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))