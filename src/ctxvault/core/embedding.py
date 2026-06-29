import logging
import transformers
from sentence_transformers import SentenceTransformer

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Cache one SentenceTransformer per model name. A vault pins its model at init
# time (see `ctxvault init --embedding-model`), so a process touching several
# vaults may need more than one model loaded; keying by name keeps each loaded
# exactly once while still supporting per-vault models.
_MODELS: dict[str, SentenceTransformer] = {}

def get_model(model_name: str | None = None) -> SentenceTransformer:
    name = model_name or DEFAULT_EMBEDDING_MODEL
    model = _MODELS.get(name)
    if model is None:
        loggers = [
            "sentence_transformers",
            "transformers",
            "transformers.modeling_utils",
            "transformers.utils.logging",
            "huggingface_hub",
            "huggingface_hub.file_download",
            "huggingface_hub._commit_api",
        ]
        original_levels = {}
        for logger_name in loggers:
            logger = logging.getLogger(logger_name)
            original_levels[logger_name] = logger.level
            logger.setLevel(logging.ERROR)

        original_verbosity = transformers.logging.get_verbosity()
        transformers.logging.set_verbosity_error()
        transformers.logging.disable_progress_bar()

        try:
            model = SentenceTransformer(name)
        finally:
            transformers.logging.set_verbosity(original_verbosity)
            transformers.logging.enable_progress_bar()
            for logger_name, level in original_levels.items():
                logging.getLogger(logger_name).setLevel(level)

        _MODELS[name] = model

    return model

def embed_list(chunks: list[str], model_name: str | None = None) -> list[list[float]]:
    return get_model(model_name).encode(sentences=chunks, show_progress_bar=False).tolist()