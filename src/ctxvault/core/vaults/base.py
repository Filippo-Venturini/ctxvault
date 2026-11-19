from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar
from datetime import datetime, timedelta, timezone
from ctxvault.core import prune_log as log
from ctxvault.models.pruning import Candidate, PruneAction, PruneLogEntry, PruneMode, PrunePolicy, PruneReport, PruneTrigger, ReasonSpec
from ctxvault.models.vaults import VaultOperation
from ctxvault.utils.config import attach_agent_to_vault, delete_vault, detach_agent_from_vault, is_authorized, make_public as _make_public
from ctxvault.core.exceptions import FileAlreadyExistError, FileOutsideVaultError, FileTypeNotPresentError, PathOutsideVaultError, UnsupportedFileTypeError, UnsupportedVaultOperationError
from ctxvault.utils.text_extraction import SUPPORTED_EXT

# Where pruned files wait to be restored or purged, inside the vault and
# outside everything that walks it.
ARCHIVE_DIR = ".ctxvault-archive"

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

        if abs_path.is_relative_to(self.archive_path):
            raise FileOutsideVaultError(f"The file to write is inside {ARCHIVE_DIR}/, where pruned files wait; "
                                        "it would be written but never indexed.")

        if abs_path.exists() and not overwrite:
            raise FileAlreadyExistError("File already exist in the Context Vault. Use overwrite flag to overwrite it.")
        
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")

    def prune_policy(self) -> PrunePolicy:
        return PrunePolicy.for_vault(self.config, self.prune_reasons)

    def prune(self, *, reasons: set[str] | None = None, targets: list[str] | None = None,
              policy: PrunePolicy | None = None, apply: bool = False,
              trigger: PruneTrigger = "manual") -> PruneReport:
        """What this vault would prune, and why; with `apply`, also prune it.

        `reasons` limits the report to some of the type's reasons, `targets`
        to some documents (paths inside the vault) or episodes. `policy`
        replaces the stored one for this call, e.g. with a one-off threshold.

        Applying with `targets` is a person naming what to prune: every named
        candidate with an action is applied, human-written or not. Applying
        without them is the policy: only what it allows unattended.
        """
        self._require_operation(VaultOperation.PRUNE)
        policy = policy or self.prune_policy()
        unknown = set(reasons or ()) - set(self.prune_reasons)
        if unknown:
            raise ValueError(f"Unknown prune reason(s): {', '.join(sorted(unknown))}. "
                             f"Known: {', '.join(self.prune_reasons)}.")
        report = self._find_candidates(policy=policy, reasons=reasons or set(self.prune_reasons))
        self._hold_restored(report)
        if targets:
            wanted = {self._prune_target(t) for t in targets}
            report.candidates = [c for c in report.candidates if c.target in wanted]
            report.held = [c for c in report.held if c.target in wanted]
        if apply:
            self._apply(report, policy=policy, named=bool(targets), trigger=trigger)
            if targets:
                found = {c.target for c in report.candidates}
                report.skipped += [f"{self._display(t)}: not a candidate" for t in sorted(wanted - found)]
        return report

    # ── applying, the log, restore and purge ────────────────────────────────

    @property
    def prune_log_path(self) -> Path:
        return self.archive_path / log.LOG_NAME

    def _display(self, target: str) -> str:
        return target

    def _hold_restored(self, report: PruneReport) -> None:
        """A document a person restored is theirs: the policy never archives it
        again unattended. It stays in the report, held, with when it was
        restored; naming it still prunes it. Read from the log's restore rows,
        by target and text hash. A log that does not chain is left to
        applying, which refuses on its own: a report never fails on it."""
        rows, _ = log.read(self.prune_log_path)
        archives = {r["n"]: r for r in rows if r["kind"] == "archive"}
        restored = {}
        for r in rows:
            if r["kind"] == "restore" and r.get("entry") in archives:
                archive = archives[r["entry"]]
                restored[(archive["target"], archive.get("text_hash"))] = r["at"]
        if not restored:
            return
        for candidate in report.candidates:
            at = restored.get((self._display(candidate.target), candidate.signals.get("text_hash")))
            if at and candidate.auto_allowed:
                candidate.auto_allowed = False
                candidate.signals["restored"] = at
                report.held.append(candidate)

    def _apply(self, report: PruneReport, *, policy: PrunePolicy, named: bool, trigger: PruneTrigger) -> None:
        """Apply what the report allows: every named candidate, or only what
        the policy may do unattended. Each target is checked again first and
        left alone if it is no longer what the report found."""
        log.rows_or_refuse(self.prune_log_path)
        who = "human" if named else "policy"
        if not named and not policy.enabled:
            report.skipped.append("the policy is disabled: nothing is applied unattended; name documents to prune them")
        done: set[str] = set()
        for candidate in report.candidates:
            if candidate.suggested_action == PruneAction.NONE or candidate.target in done:
                continue
            if not (named or candidate.auto_allowed):
                continue
            why = self._why_not_apply(candidate)
            if why:
                report.skipped.append(f"{self._display(candidate.target)}: {why}")
                continue
            report.applied.append(self._apply_candidate(candidate, who=who, trigger=trigger, policy=policy))
            done.add(candidate.target)

    def prune_log(self, policy: PrunePolicy | None = None) -> list[PruneLogEntry]:
        """Every archive on the log, each with what happened to it since."""
        policy = policy or self.prune_policy()
        rows = log.rows_or_refuse(self.prune_log_path)
        entries: dict[int, PruneLogEntry] = {}
        for row in rows:
            if row["kind"] == "archive":
                at = datetime.fromisoformat(row["at"])
                due = (at + timedelta(days=policy.retention_days)).isoformat() if policy.enabled else None
                entries[row["n"]] = PruneLogEntry(
                    id=row["hash"][:12], n=row["n"], at=row["at"], who=row["who"], trigger=row["trigger"],
                    target=row["target"], reason=row["reason"], action=row["action"], signals=row.get("signals") or {},
                    archived_path=row.get("archived"), text_hash=row.get("text_hash"),
                    agent_metadata=row.get("agent_metadata"), purge_due=due)
            elif row["kind"] in ("restore", "purge") and row.get("entry") in entries:
                entry = entries[row["entry"]]
                if row["kind"] == "restore":
                    entry.restored_at, entry.purge_due = row["at"], None
                else:
                    entry.purged_at, entry.purge_due = row["at"], None
        return list(entries.values())

    def restore(self, target: str, *, overwrite: bool = False) -> PruneLogEntry:
        """Put the last archived document at `target` back, and index it again."""
        self._require_operation(VaultOperation.PRUNE)
        name = self._log_target(target)
        archived = [e for e in self.prune_log() if e.target == name and e.state == "archived"]
        if not archived:
            raise FileNotFoundError(f"Nothing archived at {name}.")
        entry = archived[-1]
        self._restore_entry(entry, overwrite=overwrite)
        row = log.append(self.prune_log_path, "restore", "human", entry=entry.n, target=entry.target)
        entry.restored_at, entry.purge_due = row["at"], None
        self._after_restore(entry)
        return entry

    def purge_expired(self, policy: PrunePolicy | None = None, now: datetime | None = None) -> list[PruneLogEntry]:
        """Delete for good what has been archived longer than the policy keeps
        it. A disabled policy purges nothing: archived files stay until a
        person removes them."""
        self._require_operation(VaultOperation.PRUNE)
        policy = policy or self.prune_policy()
        if not policy.enabled:
            return []
        now = now or datetime.now(timezone.utc)
        purged = []
        for entry in self.prune_log(policy):
            if entry.state == "archived" and datetime.fromisoformat(entry.purge_due) <= now:
                self._purge_entry(entry)
                row = log.append(self.prune_log_path, "purge", "policy", entry=entry.n, target=entry.target)
                entry.purged_at, entry.purge_due = row["at"], None
                purged.append(entry)
        return purged

    def _evaluate(self, trigger: PruneTrigger) -> PruneReport | None:
        """What the policy does on its own after `trigger`: apply what it may
        unattended, then purge what has expired. Nothing while it is off."""
        policy = self.prune_policy()
        if not policy.enabled:
            return None
        unattended = {name for name, spec in self.prune_reasons.items()
                      if spec.auto_eligible and policy.mode(name) == PruneMode.AUTO}
        report = (self.prune(reasons=unattended, policy=policy, apply=True, trigger=trigger) if unattended
                  else PruneReport(vault_name=self.vault_name, policy_enabled=True))
        self.purge_expired(policy)
        return report

    # subclass hooks
    def _log_target(self, target: str) -> str:
        """A target as the log names it."""
        return target

    def _why_not_apply(self, candidate: Candidate) -> str | None:
        """Why the candidate is no longer what the report found, or None."""
        return None

    def _apply_candidate(self, candidate: Candidate, *, who: str, trigger: PruneTrigger,
                         policy: PrunePolicy) -> PruneLogEntry:
        raise NotImplementedError

    def _restore_entry(self, entry: PruneLogEntry, *, overwrite: bool) -> None:
        raise NotImplementedError

    def _after_restore(self, entry: PruneLogEntry) -> None:
        pass

    def _purge_entry(self, entry: PruneLogEntry) -> None:
        raise NotImplementedError

    def _sweep_archive(self, folder: Path) -> None:
        """The folders an archive move or purge left empty, removed, up to the archive itself."""
        root = self.archive_path
        folder = folder.resolve()
        while folder != root and folder.is_relative_to(root) and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent

    def _prune_target(self, target: str) -> str:
        """A target as the vault's candidates name it."""
        return target

    def _find_candidates(self, policy: PrunePolicy, reasons: set[str]) -> PruneReport:
        """The report for these reasons. Never has side effects."""
        raise NotImplementedError

    @abstractmethod
    def index_files(self, path: str | None = None) -> tuple[list[str], list[str]]:
        pass
