"""The output contract from #47: hypotheses.jsonl, manifest.json, scores.json."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

HYPOTHESES = "hypotheses.jsonl"
MANIFEST = "manifest.json"
SCORES = "scores.json"

REQUIRED_MANIFEST = (
    "ctxvault_commit",
    "config",
    "split",
    "question_count",
    "models",
    "prompt_version",
    "token_counts",
    "wall_time_seconds",
)


def read_hypotheses(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows.append({"question_id": row["question_id"], "hypothesis": row.get("hypothesis", "")})
    return rows


def written_ids(path: Path) -> set[str]:
    return {row["question_id"] for row in read_hypotheses(path)}


def append_hypothesis(path: Path, question_id: str, hypothesis: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"question_id": question_id, "hypothesis": hypothesis}, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def accuracy(flags: Iterable[bool | None]) -> float | None:
    values = [1.0 if flag else 0.0 for flag in flags if flag is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def build_scores(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate grader and judge labels. Disagreements are listed by id."""
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[row["question_type"]].append(row)

    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "grader": accuracy(item.get("grader") for item in items),
            "judge": accuracy(item.get("judge") for item in items),
        }

    disagreements = [
        {
            "question_id": row["question_id"],
            "question_type": row["question_type"],
            "grader": row.get("grader"),
            "judge": row.get("judge"),
        }
        for row in rows
        if row.get("grader") is not None
        and row.get("judge") is not None
        and bool(row["grader"]) != bool(row["judge"])
    ]
    return {
        "overall": block(rows),
        "per_question_type": {name: block(items) for name, items in sorted(by_type.items())},
        "disagreements": disagreements,
    }


def manifest_is_complete(manifest: dict[str, Any]) -> bool:
    return all(key in manifest and manifest[key] is not None for key in REQUIRED_MANIFEST)
