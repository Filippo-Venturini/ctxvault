"""Run the LongMemEval harness: one configuration, one split, one results folder."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from benchmarks.longmemeval.chat import ChatClient, CountingConsolidationModel, TokenMeter
from benchmarks.longmemeval.data import DATASET_REPO, SPLITS, load_questions
from benchmarks.longmemeval.grade import grader_correct, judge_correct
from benchmarks.longmemeval.output import (
    HYPOTHESES,
    MANIFEST,
    SCORES,
    append_hypothesis,
    build_scores,
    read_hypotheses,
    write_json,
    written_ids,
)
from benchmarks.longmemeval.prompts import ANSWER_PROMPT_VERSION, JUDGE_PROMPT_VERSION, answer_prompt
from benchmarks.longmemeval.replay import CONFIGS, DEFAULT_N_RESULTS, memory_for

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def ctxvault_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "run"


def default_results_dir() -> Path:
    return HERE / "results"


def load_labels(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def write_labels(path: Path, labels: dict[str, dict]) -> None:
    import json
    path.write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.longmemeval",
        description="Replay LongMemEval into CtxVault and write a comparable results folder.",
    )
    parser.add_argument("--config", required=True, choices=CONFIGS, help="Memory configuration to run.")
    parser.add_argument("--split", default="oracle", choices=list(SPLITS), help="Dataset split (default: oracle).")
    parser.add_argument("--data", type=Path, help="Local JSON instead of downloading a split.")
    parser.add_argument("--limit", type=int, help="Only the first N questions (cheap runs).")
    parser.add_argument("--resume", action="store_true", help="Skip questions already in hypotheses.jsonl.")
    parser.add_argument("--run-name", help="Results folder name, under --results-dir.")
    parser.add_argument("--results-dir", type=Path, default=default_results_dir())
    parser.add_argument("--cache-dir", type=Path, help="Where to store the downloaded dataset.")
    parser.add_argument("--workdir", type=Path, help="Where per-question vaults are created (deleted after each).")
    parser.add_argument("--answer-model", required=True, help="OpenAI-compatible model that writes the hypothesis.")
    parser.add_argument("--extract-model", help="Model used by ctxvault.consolidation (episodic configs).")
    parser.add_argument("--judge-model", help="Model that applies the official LongMemEval yes/no prompt.")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--n-results", type=int, default=DEFAULT_N_RESULTS, help="Chunks or episodes retrieved.")
    parser.add_argument("--embedding-model", help="Override the vault embedding model.")
    return parser.parse_args(argv)


def _extraction_model(args: argparse.Namespace, client: ChatClient):
    if args.config in ("episodic", "episodic+semantic"):
        name = args.extract_model or args.answer_model
        return CountingConsolidationModel(client, name), name
    return None, None


def grade_rows(questions, hypotheses: dict[str, str], labels: dict[str, dict], client, judge_model: str | None):
    rows = []
    for question in questions:
        hypothesis = hypotheses.get(question.question_id)
        if hypothesis is None:
            continue
        recorded = labels.get(question.question_id, {})
        grader = recorded.get("grader")
        if grader is None:
            grader = grader_correct(hypothesis, question.answer)
        judge = recorded.get("judge")
        if judge is None and judge_model is not None:
            judge = judge_correct(question, hypothesis, client, judge_model)
        labels[question.question_id] = {"grader": grader, "judge": judge}
        rows.append({
            "question_id": question.question_id,
            "question_type": question.question_type,
            "grader": grader,
            "judge": judge,
        })
    return rows


def run(args: argparse.Namespace) -> Path:
    if args.config == "episodic+semantic":
        raise SystemExit(
            "The episodic+semantic configuration needs date-aware transcript "
            "ingestion (#45) and is not implemented in this harness yet."
        )
    questions = load_questions(
        args.split, path=args.data, cache=args.cache_dir, limit=args.limit,
    )
    if not questions:
        raise SystemExit("No questions to run.")

    run_name = args.run_name or _slug(f"{args.config}-{args.split}-{args.answer_model}")
    out = args.results_dir / run_name
    out.mkdir(parents=True, exist_ok=True)
    already = written_ids(out / HYPOTHESES) if args.resume else set()
    if not args.resume and (out / HYPOTHESES).exists():
        raise SystemExit(
            f"{out / HYPOTHESES} already exists. Pass --resume to continue, or choose another --run-name."
        )

    meter = TokenMeter()
    client = ChatClient(
        base_url=args.base_url, api_key=args.api_key,
        allow_remote=args.allow_remote, timeout=args.timeout, meter=meter,
    )
    extraction, extract_name = _extraction_model(args, client)
    if extraction is not None:
        # Record the real prompt version in the manifest later.
        args._extract_prompt_version = extraction.prompt_version
    else:
        args._extract_prompt_version = None

    work_root = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="ctxvault-lme-"))
    started = time.monotonic()
    pending = [q for q in questions if q.question_id not in already]
    try:
        for index, question in enumerate(pending, start=1):
            print(f"[{index}/{len(pending)}] {question.question_id}", flush=True)
            workdir = work_root / question.question_id
            memory = memory_for(
                args.config, question, workdir=workdir,
                extraction_model=extraction, n_results=args.n_results,
                embedding_model=args.embedding_model,
            )
            system, user = answer_prompt(question, memory)
            hypothesis = client.complete(
                args.answer_model, stage="answer", system=system, user=user,
            ).text.strip()
            append_hypothesis(out / HYPOTHESES, question.question_id, hypothesis)
            already.add(question.question_id)
            _write_manifest_and_scores(
                out, args=args, questions=questions, already=already,
                client=client, extract_name=extract_name, started=started,
            )
    finally:
        # Best-effort: leave --workdir in place if the caller passed one.
        if not args.workdir:
            import shutil
            shutil.rmtree(work_root, ignore_errors=True)

    _write_manifest_and_scores(
        out, args=args, questions=questions, already=already,
        client=client, extract_name=extract_name, started=started,
    )
    print(f"Wrote {out}", flush=True)
    return out


def _write_manifest_and_scores(out, *, args, questions, already, client, extract_name, started):
    hypotheses = {row["question_id"]: row["hypothesis"] for row in read_hypotheses(out / HYPOTHESES)}
    labels_path = out / "_labels.json"
    labels = load_labels(labels_path)
    # Only grade questions we have answered in this folder.
    answered = [q for q in questions if q.question_id in already]
    rows = grade_rows(answered, hypotheses, labels, client, args.judge_model)
    write_labels(labels_path, labels)
    write_json(out / SCORES, build_scores(rows))
    write_json(out / MANIFEST, {
        "ctxvault_commit": ctxvault_commit(),
        "config": args.config,
        "split": "custom" if args.data else args.split,
        "question_count": len(already),
        "models": {
            "extraction": extract_name,
            "answer": args.answer_model,
            "judge": args.judge_model,
        },
        "prompt_version": {
            "extraction": getattr(args, "_extract_prompt_version", None),
            "answer": ANSWER_PROMPT_VERSION,
            "judge": JUDGE_PROMPT_VERSION if args.judge_model else None,
        },
        "token_counts": client.meter.as_io(),
        "wall_time_seconds": round(time.monotonic() - started, 3),
        "dataset": DATASET_REPO,
        "run_name": out.name,
    })


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
