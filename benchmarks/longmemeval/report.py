"""Merge every complete results folder into one table: config × model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.longmemeval.output import MANIFEST, SCORES, manifest_is_complete

HERE = Path(__file__).resolve().parent


def load_run(folder: Path) -> dict | None:
    manifest_path = folder / MANIFEST
    scores_path = folder / SCORES
    if not manifest_path.is_file() or not scores_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest_is_complete(manifest):
        return None
    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    return {"folder": folder.name, "manifest": manifest, "scores": scores}


def tokens_per_question(manifest: dict) -> float | None:
    counts = manifest.get("token_counts") or {}
    total = 0
    for stage in counts.values():
        if isinstance(stage, dict):
            total += int(stage.get("in") or 0) + int(stage.get("out") or 0)
    count = manifest.get("question_count") or 0
    if not count:
        return None
    return round(total / count, 1)


def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}" if value <= 1 else f"{value:.4f}"


def render(runs: list[dict]) -> str:
    header = (
        f"{'config':<20} {'split':<8} {'answer model':<24} {'n':>5} "
        f"{'grader':>8} {'judge':>8} {'tokens/q':>10} {'folder'}"
    )
    lines = [header, "-" * len(header)]
    for run in runs:
        manifest = run["manifest"]
        overall = (run["scores"].get("overall") or {})
        model = (manifest.get("models") or {}).get("answer") or "-"
        tokens = tokens_per_question(manifest)
        lines.append(
            f"{str(manifest.get('config', '-')):<20} "
            f"{str(manifest.get('split', '-')):<8} "
            f"{str(model):<24} "
            f"{int(manifest.get('question_count') or 0):>5} "
            f"{format_pct(overall.get('grader')):>8} "
            f"{format_pct(overall.get('judge')):>8} "
            f"{(tokens if tokens is not None else '-'):>10} "
            f"{run['folder']}"
        )
    if len(runs) == 0:
        lines.append("(no complete results folders)")
    return "\n".join(lines) + "\n"


def collect(results_dir: Path) -> list[dict]:
    runs = []
    if not results_dir.is_dir():
        return runs
    for folder in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        loaded = load_run(folder)
        if loaded:
            runs.append(loaded)
    runs.sort(key=lambda run: (
        str(run["manifest"].get("config") or ""),
        str(run["manifest"].get("split") or ""),
        str((run["manifest"].get("models") or {}).get("answer") or ""),
        run["folder"],
    ))
    return runs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.longmemeval.report",
        description="Merge complete LongMemEval results folders into one table.",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=HERE / "results",
        help="Directory that contains one folder per run (default: benchmarks/longmemeval/results).",
    )
    args = parser.parse_args(argv)
    text = render(collect(args.results_dir))
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
