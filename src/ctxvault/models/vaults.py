from enum import Enum
from pathlib import Path
from pydantic import BaseModel

class VaultType(Enum):
    SEMANTIC = "semantic"
    SKILL = "skill"
    EPISODIC = "episodic"

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
    WRITE_EPISODE = "write_episode"
    READ_EPISODE = "read_episode"
    QUERY_EPISODES = "query_episodes"
    INVALIDATE_EPISODE = "invalidate_episode"
    SUPERSEDE_EPISODE = "supersede_episode"
    REVISE_EPISODE = "revise_episode"

class SkillInput(BaseModel):
    name: str
    description: str
    instructions: str
    
class SkillOutput(BaseModel):
    name: str
    description: str
    instructions: str
    # frontmatter fields beyond name and description, as the author wrote them
    metadata: dict | None
    path: Path