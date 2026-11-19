"""An OpenAI-compatible chat client that records token use per stage.

The consolidation layer reports extraction and relation usage through its
public callback; this client is for answering and judging. Temperature is
always 0. A remote endpoint is refused unless `allow_remote` is set, because the
conversations leave the machine.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_TIMEOUT = 120.0

STAGES = ("extract", "relate", "answer", "judge")


def _is_loopback(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class TokenCounts:
    prompt: int = 0
    completion: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt += prompt
        self.completion += completion

    def as_io(self) -> dict[str, int]:
        return {"in": self.prompt, "out": self.completion}


@dataclass
class TokenMeter:
    extract: TokenCounts = field(default_factory=TokenCounts)
    relate: TokenCounts = field(default_factory=TokenCounts)
    answer: TokenCounts = field(default_factory=TokenCounts)
    judge: TokenCounts = field(default_factory=TokenCounts)

    def stage(self, name: str) -> TokenCounts:
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise ValueError(f"Unknown token stage {name!r}.") from exc

    @classmethod
    def from_io(cls, counts: dict) -> "TokenMeter":
        meter = cls()
        for stage in STAGES:
            values = counts.get(stage) or {}
            meter.stage(stage).add(int(values.get("in") or 0), int(values.get("out") or 0))
        return meter

    def record(self, stage: str, prompt: int, completion: int) -> None:
        self.stage(stage).add(prompt, completion)

    def as_io(self) -> dict[str, dict[str, int]]:
        return {name: getattr(self, name).as_io() for name in STAGES}


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int


class ChatClient:
    """One chat-completions server, shared by every stage of a run."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        allow_remote: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        meter: TokenMeter | None = None,
    ):
        if not allow_remote and not _is_loopback(base_url):
            raise ValueError(
                f"'{base_url}' is not on this machine. Conversations would leave it: "
                "pass --allow-remote if that is what you want."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.meter = meter or TokenMeter()

    def complete(
        self,
        model: str,
        *,
        stage: str,
        system: str | None = None,
        user: str,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> Completion:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        body: dict[str, Any] = {"model": model, "temperature": 0, "messages": messages}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not reach the model at {self.base_url}: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(
                f"The model at {self.base_url} answered {response.status_code}: {response.text[:200]}"
            )
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"The model at {self.base_url} did not answer as a chat completion."
            ) from exc
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        self.meter.stage(stage).add(prompt_tokens, completion_tokens)
        return Completion(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
