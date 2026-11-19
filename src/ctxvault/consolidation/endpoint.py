"""A model behind an OpenAI-compatible endpoint, and the prompts it is given.

The endpoint is local unless the caller says otherwise: what goes through it
is the text of real conversations. The prompts are data: plain files, one set
per language, with a version that is stored on every write they cause.
"""

import ipaddress
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field

from ctxvault.consolidation.claims import Claim
from ctxvault.consolidation.model import Turn
from ctxvault.models.episodes import Episode

# Ollama's OpenAI-compatible endpoint, the most common local server.
DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_TIMEOUT = 120.0

class ModelEndpointError(RuntimeError):
    """The endpoint could not be reached, or did not answer as a chat
    completion. Raised rather than swallowed: a run that cannot reach its
    model has not consolidated anything, and its caller should know."""

class Prompts(BaseModel):
    """The two instructions the model is given, and the version of the pair."""

    version: str = Field(min_length=1)
    extract: str = Field(min_length=1)
    relate: str = Field(min_length=1)

    @classmethod
    def load(cls, language: str = "en") -> "Prompts":
        """The prompts shipped with the library for one language."""
        root = resources.files("ctxvault.consolidation") / "prompts" / language
        if not root.is_dir():
            raise ValueError(f"No prompts shipped for language '{language}'. Use Prompts.from_dir for your own.")
        return cls._read(root)

    @classmethod
    def from_dir(cls, path: str | Path) -> "Prompts":
        """Prompts of your own: a directory with extract.md, relate.md and a
        VERSION file. Copy a shipped set and edit it; change VERSION when you
        do, so the writes of the two can be told apart."""
        root = Path(path)
        if not root.is_dir():
            raise ValueError(f"'{path}' is not a directory.")
        return cls._read(root)

    @classmethod
    def _read(cls, root) -> "Prompts":
        def text(name: str) -> str:
            file = root / name
            if not file.is_file():
                raise ValueError(f"The prompts in '{root}' have no {name}.")
            return file.read_text(encoding="utf-8").strip()

        return cls(version=text("VERSION"), extract=text("extract.md"), relate=text("relate.md"))

def _is_loopback(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

def _parse_json(text: str) -> Any:
    """The JSON a model answered with, whether bare, fenced or wrapped in a
    sentence. None when there is none: the pipeline reads that as nothing
    usable, which is what it is."""
    candidates = [text.strip()]
    candidates += [block.strip() for block in _FENCE.findall(text)]
    for opening, closing in (("{", "}"), ("[", "]")):
        start, end = text.find(opening), text.rfind(closing)
        if 0 <= start < end:
            candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None

def _conversation(turns: list[Turn]) -> str:
    # Numbered from 0, so a claim can say which turns it was drawn from.
    return "\n".join(f"{n} [{turn.at or 'undated'}] {turn.speaker}: {turn.text}" for n, turn in enumerate(turns))

def _comparison(claim: Claim, candidates: list[Episode]) -> str:
    said = {"statement": claim.statement, "subject": claim.subject}
    if claim.speaker:
        said["speaker"] = claim.speaker
    if claim.valid_from:
        said["valid_from"] = claim.valid_from
    on_file = [{"id": c.id, "statement": c.content, "valid_from": c.valid_from} for c in candidates]
    return (
        "New claim:\n" + json.dumps(said, ensure_ascii=False)
        + "\n\nStatements on file:\n" + "\n".join(json.dumps(item, ensure_ascii=False) for item in on_file)
    )

class OpenAICompatibleModel:
    """A `ConsolidationModel` that asks a chat-completions endpoint.

    Works with any server that speaks the OpenAI chat API: Ollama, llama.cpp,
    LM Studio, vLLM, or a hosted provider. The endpoint must be on this
    machine unless `allow_remote` is set, because the conversations it reads
    leave the process. Temperature is 0, so two runs with the same model and
    prompts are as close as the server allows.
    ``usage_callback(stage, prompt_tokens, completion_tokens)`` is called after
    each successful response; stage is "extract" or "relate". Missing usage is
    reported as zero. ``last_extraction_unparseable`` distinguishes an unusable
    extraction reply from a valid empty claims list and resets on each extract.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        allow_remote: bool = False,
        prompts: Prompts | None = None,
        language: str = "en",
        json_mode: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        usage_callback: Callable[[str, int, int], None] | None = None,
    ):
        if not allow_remote and not _is_loopback(base_url):
            raise ValueError(
                f"'{base_url}' is not on this machine. Conversations would leave it: "
                "pass allow_remote=True if that is what you want."
            )
        self.name = model
        self.prompts = prompts or Prompts.load(language)
        self.prompt_version = self.prompts.version
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # Asks the server for a JSON object. Turn it off for a server that
        # rejects `response_format`; the answer is parsed either way.
        self.json_mode = json_mode
        self.timeout = timeout
        self.usage_callback = usage_callback
        self.last_extraction_unparseable = False

    def _chat(self, instructions: str, content: str, *, stage: str) -> str:
        body: dict[str, Any] = {
            "model": self.name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": content},
            ],
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            response = requests.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ModelEndpointError(f"Could not reach the model at {self.base_url}: {exc}") from exc
        if response.status_code != 200:
            raise ModelEndpointError(f"The model at {self.base_url} answered {response.status_code}: {response.text[:200]}")
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelEndpointError(f"The model at {self.base_url} did not answer as a chat completion.") from exc

        if self.usage_callback is not None:
            usage = payload.get("usage") or {}
            self.usage_callback(
                stage, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
            )
        return text

    def extract(self, turns: list[Turn]) -> list[Any]:
        self.last_extraction_unparseable = False
        answer = _parse_json(self._chat(self.prompts.extract, _conversation(turns), stage="extract"))
        if isinstance(answer, dict):
            answer = answer.get("claims")
        self.last_extraction_unparseable = not isinstance(answer, list)
        return answer if isinstance(answer, list) else []

    def relate(self, claim: Claim, candidates: list[Episode]) -> Any:
        return _parse_json(self._chat(self.prompts.relate, _comparison(claim, candidates), stage="relate"))
