import logging
from typing import Callable

import transformers
from sentence_transformers import SentenceTransformer

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# How much of a chunk is repeated at the start of the next one, as a share of
# the chunk size, so that a split never cuts a thought in two.
OVERLAP_SHARE = 0.15

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

def token_budget(model_name: str | None = None) -> tuple[Callable[[str], int], int, int]:
    """How the vault's model counts text, and how much of it it reads at once.

    Returns (measure, chunk_size, overlap): the model's own token count, its
    input limit minus the special tokens it adds, and the overlap derived
    from that. Chunks cut to this budget are embedded whole; longer ones were
    silently truncated by the model, and the rest never reached the vector.
    """
    model = get_model(model_name)
    tokenizer = model.tokenizer
    # measuring a whole document is the point; the tokenizer need not warn
    # that it is longer than what the model reads at once
    if hasattr(tokenizer, "deprecation_warnings"):
        tokenizer.deprecation_warnings["sequence-length-is-longer-than-the-specified-maximum"] = True
    limit = int(model.max_seq_length or 512)
    specials = tokenizer.num_special_tokens_to_add() if hasattr(tokenizer, "num_special_tokens_to_add") else 2
    size = max(1, limit - specials)
    return (lambda text: len(tokenizer.encode(text, add_special_tokens=False)), size, round(size * OVERLAP_SHARE))

def embed_list(chunks: list[str], model_name: str | None = None) -> list[list[float]]:
    # positional: the first argument was renamed from `sentences` to `inputs`
    # in sentence-transformers 6, and the range pinned here spans both
    return get_model(model_name).encode(chunks, show_progress_bar=False).tolist()