from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar
from ctxvault.models.pruning import PrunePolicy, PruneReport, ReasonSpec
from ctxvault.models.vaults import VaultOperation
from ctxvault.utils.config import attach_agent_to_vault, delete_vault, detach_agent_from_vault, is_authorized, make_public as _make_public
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, PathOutsideVaultError, UnsupportedFileTypeError, UnsupportedVaultOperationError
from ctxvault.utils.text_extraction import SUPPORTED_EXT

# Where pruned files wait to be restored or purged, inside the vault and
# outside everything that walks it.
ARCHIVE_DIR = ".archive"

class BaseVault(ABC):
    supported_operations: frozenset[VaultOperation] = frozenset()
    # The reasons this vault type can prune for. A type that declares none
    # also leaves PRUNE out of supported_operations.
    prune_reasons: ClassVar[dict[str, ReasonSpec]] = {}

    def __init__(self, vault_name: str, config: dict):
        self.vault_name = vault_name
        self.config = config
        self.vault_path = Path(config["vault_path"])
        self.db_path = Path(config.get("db_path")) if config.get("db_path") else None

    def _get_base_path(self, path: str | None) -> Path:
        if not path:
            return self.vault_path
        
        input_path = Path(path)
        if input_path.is_absolute():
            base_path = input_path
        else:
            base_path = (self.vault_path / input_path).resolve()
        
        if not base_path.is_relative_to(self.vault_path.resolve()):
            raise PathOutsideVaultError("The path must be inside the Context Vault.")
        
        if not base_path.exists():
            raise FileNotFoundError(f"Path not found inside the vault: {base_path}")
        
        return base_path
    
    @property
    def archive_path(self) -> Path:
        return (self.vault_path / ARCHIVE_DIR).resolve()

    def _excluded_dirs(self) -> list[Path]:
        """What a walk of the vault's files never enters: the index database
        and the prune archive."""
        excluded = [self.db_path] if self.db_path is not None else []
        return excluded + [self.archive_path]

    def iter_files(self, path: Path, exclude_dirs: list[Path] | None = None):
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

    def _require_operation(self, operation: VaultOperation) -> None:
        if operation not in self.supported_operations:
            raise UnsupportedVaultOperationError(
                f"Operation '{operation.value}' is not supported by {self.__class__.__name__}."
            )
    
    def is_agent_authorized(self, agent_name: str) -> bool:
        return is_authorized(vault_name=self.vault_name, agent_name=agent_name)
    
    def attach_agent(self, agent_name: str) -> None:
        attach_agent_to_vault(vault_name=self.vault_name, agent_name=agent_name)

    def detach_agent(self, agent_name: str) -> None:
        detach_agent_from_vault(vault_name=self.vault_name, agent_name=agent_name)

    def make_public(self) -> None:
        _make_public(vault_name=self.vault_name)

    def purge_vault(self) -> None:
        delete_vault(vault_name=self.vault_name)

    def delete_file(self, file_path: Path)-> None:
        if file_path.suffix not in SUPPORTED_EXT:
            raise UnsupportedFileTypeError("File already out of the Context Vault because its type is not supported.")

        if not file_path.resolve().is_relative_to(self.vault_path):
            raise FileOutsideVaultError("The file to delete is already outside the Context Vault.")
        
        if file_path.exists():
            file_path.unlink()
    
    def delete_files(self, path: str | None = None)-> tuple[list[str], list[str]]:
        base_path = self._get_base_path(path=path)

        deleted_files = []
        skipped_files = []

        for file in self.iter_files(path=base_path, exclude_dirs=self._excluded_dirs()):
            try:
                self.delete_file(file_path=file)
                deleted_files.append(str(file))
            except Exception as e:
                skipped_files.append(f"{str(file)} ({e})")

        return deleted_files, skipped_files

    def write_file(self, file_path: str, content: str, overwrite: bool = True, agent_metadata: dict | None = None)-> None:
        file_path = Path(file_path)

        if not file_path.suffix:
            raise FileTypeNotPresentError("File type not present in the file path.")

        if file_path.suffix not in SUPPORTED_EXT:
            raise UnsupportedFileTypeError("File type not supported.")
        
        abs_path = (self.vault_path / file_path).resolve()

        if not abs_path.is_relative_to(self.vault_path):
            raise FileOutsideVaultError("The file to write must have a path inside the Context Vault.")

        if abs_path.exists() and not overwrite:
            raise FileAlreadyExistError("File already exist in the Context Vault. Use overwrite flag to overwrite it.")
        
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")

    def prune_policy(self) -> PrunePolicy:
        return PrunePolicy.for_vault(self.config, self.prune_reasons)

    def prune(self, *, reasons: set[str] | None = None, targets: list[str] | None = None,
              policy: PrunePolicy | None = None) -> PruneReport:
        """What this vault would prune, and why. Changes nothing.

        `reasons` limits the report to some of the type's reasons, `targets`
        to some documents (paths inside the vault) or episodes. `policy`
        replaces the stored one for this call, e.g. with a one-off threshold.
        """
        self._require_operation(VaultOperation.PRUNE)
        policy = policy or self.prune_policy()
        unknown = set(reasons or ()) - set(self.prune_reasons)
        if unknown:
            raise ValueError(f"Unknown prune reason(s): {', '.join(sorted(unknown))}. "
                             f"Known: {', '.join(self.prune_reasons)}.")
        report = self._find_candidates(policy=policy, reasons=reasons or set(self.prune_reasons))
        if targets:
            wanted = {self._prune_target(t) for t in targets}
            report.candidates = [c for c in report.candidates if c.target in wanted]
            report.held = [c for c in report.held if c.target in wanted]
        return report

    def _prune_target(self, target: str) -> str:
        """A target as the vault's candidates name it."""
        return target

    def _find_candidates(self, policy: PrunePolicy, reasons: set[str]) -> PruneReport:
        """The report for these reasons. Never has side effects."""
        raise NotImplementedError

    @abstractmethod
    def index_files(self, path: str | None = None) -> tuple[list[str], list[str]]:
        pass
