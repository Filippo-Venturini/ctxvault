class UnsupportedFileTypeError(Exception):
    """Raised when a file type is not supported by the extractor."""
    pass

class FileTypeNotPresentError(Exception):
    """Raised when a file type is not present in the file path."""
    pass

class ExtractionError(Exception):
    """Raised when text extraction fails for reasons other than file type."""
    pass

class VaultTypeNotValidError(Exception):
    """Raised when trying to initialize a vault with a not valid type"""
    pass

class VaultAlreadyExistsError(Exception):
    """Raised when a Context Vault is already initialized at that path."""
    def __init__(self, existing_path: str):
        self.existing_path = existing_path
        super().__init__(f"Vault already initialized at {existing_path}")

class VaultNotInitializedError(Exception):
    """Raised when a Context Vault is not initialized at that path."""
    pass

class VaultNotFoundError(Exception):
    """Raised when trying to operate with a Vault that doesn't exist"""
    pass

class VaultPathMissingError(VaultNotFoundError):
    """Raised when a vault is registered but its folder is gone.

    A subclass of VaultNotFoundError: for every caller the vault is not there.
    Opening it must not recreate the folder, or a moved or unmounted vault
    would come back silently empty and look healthy.
    """
    pass

class FileOutsideVaultError(Exception):
    """Raised when try to index a file outside the Context Vault."""
    pass

class PathOutsideVaultError(Exception):
    """Raised when try to perform an action outside the Context Vault."""
    pass

class FileAlreadyExistError(Exception):
    """Raised when try to write a file that already exist in the Context Vault without the overwrite flag."""
    pass

class EmptyQueryError(Exception):
    """Raised when trying to query a vault with an empty query."""
    pass

class VaultAccessDeniedError(Exception):
    """Raised when agents try to access a restricted vault they are not authorized to access."""
    pass

class UnsupportedVaultOperationError(Exception):
    """Raised when trying to perform an unsupported operation on a specific vault type."""
    pass

class SkillNotFoundError(Exception):
    """Raised when trying to read a skill not present in the vault."""
    pass

class MissingAgentNameError(Exception):
    """Raised when agents try to access a restricted vault without providing an agent name."""
    pass

class DocumentNotFoundError(Exception):
    """Raised when a document id is not present in the semantic store."""
    pass

class EpisodeNotFoundError(Exception):
    """Raised when an episode id is not present in the episodic store."""
    pass

class EpisodeAlreadyClosedError(Exception):
    """Raised when trying to invalidate or supersede an episode that is already closed."""
    pass

class EpisodeAlreadyOpenError(Exception):
    """Raised when trying to reopen an episode that is already current."""
    pass

class EpisodeSuccessorStillOpenError(Exception):
    """Raised when reopening a replaced episode whose successor is still current."""
    def __init__(self, episode_id: str, successor_id: str):
        self.episode_id = episode_id
        self.successor_id = successor_id
        super().__init__(
            f"Episode '{episode_id}' was replaced by '{successor_id}', which is still current; "
            "invalidate or supersede the successor first."
        )

class EpisodeWasRevisedError(Exception):
    """Raised when reopening a statement that was restated more precisely.

    Attestations and disputes already moved to the revision, which is the
    statement to reopen or close instead.
    """
    def __init__(self, episode_id: str, revision_id: str):
        self.episode_id = episode_id
        self.revision_id = revision_id
        super().__init__(
            f"Episode '{episode_id}' was revised by '{revision_id}'; "
            "reopen the revision instead. Attestations and disputes already moved there."
        )

class SchemaVersionError(Exception):
    """Raised when an episodic store was written by a newer version of ctxvault."""
    pass
