from pydantic import BaseModel

class InitRequest(BaseModel):
    vault_path: str

class InitResponse(BaseModel):
    vault_path: str
    config_path: str

class IndexRequest(BaseModel):
    file_path: str

class IndexResponse(BaseModel):
    indexed_files: list[str]
    skipped_files: list[str]