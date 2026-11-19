"""Load LongMemEval questions from a local file or a checked HuggingFace cache.

The official release lives at `xiaowu0162/longmemeval-cleaned` (the earlier
`xiaowu0162/longmemeval` dump is deprecated). Split names in this harness
(`oracle`, `s`, `m`) match #47; the on-disk files keep the cleaned names.
Nothing from the dataset is committed to the repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

DATASET_REPO = "xiaowu0162/longmemeval-cleaned"
_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/main/{filename}"

# LFS SHA-256 of the cleaned release, as published by HuggingFace.
SPLITS = {
    "oracle": {
        "filename": "longmemeval_oracle.json",
        "sha256": "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c",
    },
    "s": {
        "filename": "longmemeval_s_cleaned.json",
        "sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
    },
    "m": {
        "filename": "longmemeval_m_cleaned.json",
        "sha256": "9d79e5524794a2e6900a3aa9cb7d9152c5a3e8319c9a87c25494ba1eacee495f",
    },
}

# "2023/05/28 (Sun) 06:47" — weekday is optional so fixtures can omit it.
_LME_DATE = re.compile(
    r"^(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})"
    r"(?: \([A-Za-z]{3}\))? (?P<H>\d{2}):(?P<M>\d{2})$"
)


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


@dataclass(frozen=True)
class Session:
    id: str
    date: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Question:
    question_id: str
    question_type: str
    question: str
    answer: str
    question_date: str
    sessions: tuple[Session, ...]

    @property
    def abstention(self) -> bool:
        return self.question_id.endswith("_abs")

    @property
    def last_session_date(self) -> str | None:
        return self.sessions[-1].date if self.sessions else None


def cache_dir(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    root = os.environ.get("CTXVAULT_CACHE") or os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "ctxvault" / "longmemeval"
    return Path.home() / ".cache" / "ctxvault" / "longmemeval"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_lme_datetime(value: str) -> datetime:
    """A LongMemEval timestamp, or an ISO 8601 date/time, as a UTC instant."""
    text = value.strip()
    match = _LME_DATE.match(text)
    if match:
        return datetime(
            int(match["y"]), int(match["m"]), int(match["d"]),
            int(match["H"]), int(match["M"]), tzinfo=timezone.utc,
        )
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value: str | datetime) -> str:
    moment = value if isinstance(value, datetime) else parse_lme_datetime(value)
    return moment.isoformat()


def question_instant(question_date: str, last_session_date: str | None) -> datetime:
    """When the question is asked, as a UTC instant.

    LongMemEval question dates were often annotated as a day without a time, so
    the clock can fall earlier on the same day as the last session. The official
    clarification (xiaowu0162/LongMemEval#8) is to treat a same-day question as
    immediately after that last session, otherwise later facts would be invisible
    to an as-of read.
    """
    asked = parse_lme_datetime(question_date)
    if not last_session_date:
        return asked
    last = parse_lme_datetime(last_session_date)
    if asked.date() == last.date() and asked <= last:
        return last + timedelta(seconds=1)
    return asked


def _turns(raw: Iterable[dict]) -> tuple[Turn, ...]:
    turns: list[Turn] = []
    for item in raw:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role and content:
            turns.append(Turn(role=role, content=content))
    return tuple(turns)


def parse_record(record: dict) -> Question:
    ids = list(record.get("haystack_session_ids") or [])
    dates = list(record.get("haystack_dates") or [])
    sessions_raw = list(record.get("haystack_sessions") or [])
    if not (len(ids) == len(dates) == len(sessions_raw)):
        raise ValueError(
            f"{record.get('question_id')}: haystack_session_ids, haystack_dates "
            "and haystack_sessions must be the same length."
        )
    sessions = [
        Session(id=str(session_id), date=str(date), turns=_turns(turns))
        for session_id, date, turns in zip(ids, dates, sessions_raw)
    ]
    # Oracle haystacks are not guaranteed to be in date order; s and m are.
    sessions.sort(key=lambda session: (parse_lme_datetime(session.date), session.id))
    answer = record.get("answer")
    return Question(
        question_id=str(record["question_id"]),
        question_type=str(record["question_type"]),
        question=str(record["question"]),
        answer="" if answer is None else str(answer),
        question_date=str(record["question_date"]),
        sessions=tuple(sessions),
    )


def load_from_path(path: Path | str, *, limit: int | None = None) -> list[Question]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of LongMemEval questions.")
    questions = [parse_record(record) for record in data]
    if limit is not None:
        questions = questions[:limit]
    return questions


def download_split(
    split: str,
    *,
    cache: Path | str | None = None,
    urlopen=urllib.request.urlopen,
) -> Path:
    """Download one split into the cache, or reuse a file whose checksum matches."""
    if split not in SPLITS:
        raise ValueError(f"Unknown split {split!r}. Use one of: {', '.join(SPLITS)}.")
    meta = SPLITS[split]
    dest = cache_dir(cache) / meta["filename"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and sha256_file(dest) == meta["sha256"]:
        return dest

    url = _RESOLVE.format(repo=DATASET_REPO, filename=meta["filename"])
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ctxvault-longmemeval"})
    digest = hashlib.sha256()
    try:
        with urlopen(request) as response, tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    got = digest.hexdigest()
    if got != meta["sha256"]:
        tmp.unlink(missing_ok=True)
        raise ValueError(
            f"Checksum mismatch for {meta['filename']}: got {got}, expected {meta['sha256']}."
        )
    tmp.replace(dest)
    return dest


def load_questions(
    split: str = "oracle",
    *,
    path: Path | str | None = None,
    cache: Path | str | None = None,
    limit: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[Question]:
    """Load a split from `path`, or download it into the cache first."""
    source = Path(path) if path else download_split(split, cache=cache, urlopen=urlopen)
    return load_from_path(source, limit=limit)
