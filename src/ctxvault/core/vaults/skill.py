import json
import warnings
from pathlib import Path
from ctxvault.core.exceptions import SkillNotFoundError
from ctxvault.models.vaults import SkillInput, SkillOutput, VaultOperation
import frontmatter
from datetime import datetime
from ctxvault.core.vaults.base import BaseVault
from ctxvault.models.documents import SkillDocumentInfo

INDEX_FILE = "skills-index.json"

class SkillVault(BaseVault):
    supported_operations = frozenset({
        VaultOperation.INDEX,
        VaultOperation.WRITE_SKILL,
        VaultOperation.LIST_SKILLS,
        VaultOperation.READ_SKILL,
    })

    @property
    def _index_path(self) -> Path:
        return self.vault_path / INDEX_FILE

    def _load_index(self) -> dict:
        if not self._index_path.exists():
            return {}
        return json.loads(self._index_path.read_text())

    def _save_index(self, index: dict) -> None:
        self._index_path.write_text(json.dumps(index, indent=2))

    def _rebuild_index(self) -> tuple[dict, list[str]]:
        """Scan all .md files and rebuild index. Returns (index, conflicts)."""
        index = {}
        conflicts = []

        for md_file in self.vault_path.glob("*.md"):
            if md_file.name == INDEX_FILE or md_file.name.startswith("."):
                continue
            post = frontmatter.load(md_file)
            name = post.get("name", md_file.stem)
            name_key = name.lower()

            if name_key in index:
                conflicts.append(name)
            else:
                index[name_key] = {
                    "name": name,
                    "file": md_file.name,
                    "description": post.get("description")
                }

        return index, conflicts

    def index_files(self, path: str | None = None) -> tuple[list[str], list[str]]:
        index, conflicts = self._rebuild_index()
        self._save_index(index)
        indexed = [v["file"] for v in index.values()]
        skipped = [f"Conflict: skill '{n}' appears in multiple files" for n in conflicts]
        return indexed, skipped

    def read_skill(self, skill_name: str) -> SkillOutput:
        index = self._load_index()
        entry = index.get(skill_name.lower())
        if not entry:
            raise SkillNotFoundError(f"Skill '{skill_name}' not found.")
        
        file_path = self.vault_path / entry["file"]
        if not file_path.is_file():
            raise SkillNotFoundError(f"Skill '{skill_name}' is in the index but its file {entry['file']} is gone; run `ctxvault index` to drop it.")
        post = frontmatter.load(file_path)
        # whatever the author put in the frontmatter beyond the two fields the
        # library reads: the skill's own metadata, shown as written
        extra = {k: v for k, v in post.metadata.items() if k not in ("name", "description")}
        return SkillOutput(
            name=entry["name"],
            description=entry["description"],
            instructions=post.content,
            metadata=extra or None,
            path=file_path
        )

    def write_skill(self, skill: SkillInput, overwrite: bool = True) -> str:
        post = frontmatter.Post(skill.instructions, name=skill.name, description=skill.description)
        content = frontmatter.dumps(post)
        filename = f"{skill.name.lower().replace(' ', '-')}.md"
        self.write_file(file_path=filename, content=content, overwrite=overwrite)

        index = self._load_index()
        index[skill.name.lower()] = {
            "name": skill.name,
            "file": filename,
            "description": skill.description
        }
        self._save_index(index)

        return filename

    def list_skills(self) -> list[SkillDocumentInfo]:
        index = self._load_index()
        result = []
        for entry in index.values():
            file_path = self.vault_path / entry["file"]
            if not file_path.is_file():
                # removed by hand since the last `index`: said, and skipped
                warnings.warn(f"Skill '{entry['name']}' is in the index but its file {entry['file']} is gone; run `ctxvault index` to drop it.")
                continue
            stats = file_path.stat()
            result.append(SkillDocumentInfo(
                source=entry["file"],
                filetype=".md",
                size_bytes=stats.st_size,
                skill_name=entry["name"],
                description=entry["description"],
                # aware, in the machine's zone: every other timestamp the
                # library hands out carries its offset
                last_modified=datetime.fromtimestamp(stats.st_mtime).astimezone().isoformat()
            ))
        return result