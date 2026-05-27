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