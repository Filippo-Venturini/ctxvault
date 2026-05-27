from enum import Enum
from pathlib import Path
from pydantic import BaseModel

class VaultType(Enum):
    SEMANTIC = "semantic"
    SKILL = "skill"

    @classmethod
    def list(cls):
        return [v.value for v in cls]
    
class VaultOperation(str, Enum):
    INDEX = "index"
    QUERY = "query"
    REINDEX = "reindex"
    DELETE = "delete"
    WRITE_DOC = "write_doc"
    WRITE_SKILL = "write_skill"
    LIST_DOCUMENTS = "list_documents"
    READ_DOC_CONTENT = "read_doc_content"
    LIST_SKILLS = "list_skills"
    READ_SKILL = "read_skill"

class SkillInput(BaseModel):
    name: str
    description: str
    instructions: str
    
class SkillOutput(BaseModel):
    name: str
    description: str
    instructions: str
    metadata: str | None
    path: Path