class UnsupportedFileTypeError(Exception):
    """Raised when a file type is not supported by the extractor."""
    pass

class ExtractionError(Exception):
    """Raised when text extraction fails for reasons other than file type."""
    pass

class VaultAlreadyExistsError(Exception):
    """Raised when a Context Vault is already initialized at that path."""
    def __init__(self, existing_path: str):
        self.existing_path = existing_path
        super().__init__(f"Vault already initialized at {existing_path}")

class VaultNotInitializedError(Exception):
    """Raised when a Context Vault is not initialized at that path."""
    pass