"""Run the LongMemEval harness: one configuration, one split, one results folder."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ctxvault.consolidation import OpenAICompatibleModel
from ctxvault.core.embedding import DEFAULT_EMBEDDING_MODEL

from benchmarks.longmemeval.chat import ChatClient, TokenMeter
from benchmarks.longmemeval.data import DATASET_REPO, SPLITS, download_split, load_from_path, sha256_file
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
    parser.add_argument("--judge-base-url", help="Judge endpoint (defaults to --base-url).")
    parser.add_argument("--judge-api-key", help="Judge key (defaults to --api-key).")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--n-results", type=int, default=DEFAULT_N_RESULTS, help="Chunks or episodes retrieved.")
    parser.add_argument("--embedding-model", help="Override the vault embedding model.")
    return parser.parse_args(argv)


def _extraction_model(args: argparse.Namespace, client: ChatClient):
    if args.config in ("episodic", "episodic+semantic"):
        name = args.extract_model or args.answer_model
        return OpenAICompatibleModel(
            name, base_url=args.base_url, api_key=args.api_key,
            allow_remote=args.allow_remote, timeout=args.timeout,
            usage_callback=client.meter.record,
        ), name
    return None, None


def grade_rows(questions, hypotheses: dict[str, str], labels: dict[str, dict], client, judge_model: str | None):
    rows = []
    for question in questions:
        hypothesis = hypotheses.get(question.question_id)
        if hypothesis is None:
            continue
        recorded = labels.get(question.question_id, {})
        grader = recorded.get("grader")
        if question.abstention or question.question_type == "single-session-preference":
            # Also discard any inappropriate label cached by an older harness.
            grader = None
        elif grader is None:
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


@contextmanager
def _work_root(path: Path | None):
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ctxvault-lme-", dir=path, ignore_cleanup_errors=True) as root:
        yield Path(root)


def run(args: argparse.Namespace) -> Path:
    source = args.data or download_split(args.split, cache=args.cache_dir)
    questions = load_from_path(source, limit=args.limit)
    if not questions:
        raise SystemExit("No questions to run.")

    split = "custom" if args.data else args.split
    run_name = args.run_name or _slug(f"{args.config}-{split}-{args.answer_model}")
    out = args.results_dir / run_name
    out.mkdir(parents=True, exist_ok=True)
    already = written_ids(out / HYPOTHESES) if args.resume else set()
    if not args.resume and (out / HYPOTHESES).exists():
        raise SystemExit(
            f"{out / HYPOTHESES} already exists. Pass --resume to continue, or choose another --run-name."
        )

    previous = load_labels(out / MANIFEST) if args.resume else {}
    if already and not previous:
        raise SystemExit("Cannot recover resume accounting without the previous manifest.")
    meter = TokenMeter.from_io(previous.get("token_counts") or {})
    client = ChatClient(
        base_url=args.base_url, api_key=args.api_key,
        allow_remote=args.allow_remote, timeout=args.timeout, meter=meter,
    )
    judge_client = client
    if args.judge_model and (args.judge_base_url is not None or args.judge_api_key is not None):
        judge_client = ChatClient(
            base_url=args.judge_base_url or args.base_url,
            api_key=args.judge_api_key if args.judge_api_key is not None else args.api_key,
            allow_remote=args.allow_remote, timeout=args.timeout, meter=meter,
        )
    extraction, extract_name = _extraction_model(args, client)
    diagnostics = {
        key: int((previous.get("extraction_diagnostics") or {}).get(key, 0))
        for key in (
            "sessions_consolidated", "sessions_with_unparseable_reply",
            "claims_written", "claims_rejected",
        )
    }
    manifest = {
        "ctxvault_commit": ctxvault_commit(),
        "config": args.config,
        "split": split,
        "models": {
            "extraction": extract_name,
            "answer": args.answer_model,
            "judge": args.judge_model,
        },
        "prompt_version": {
            "extraction": extraction.prompt_version if extraction is not None else None,
            "answer": ANSWER_PROMPT_VERSION,
            "judge": JUDGE_PROMPT_VERSION if args.judge_model else None,
        },
        "n_results": args.n_results,
        "embedding_model": (args.embedding_model or DEFAULT_EMBEDDING_MODEL)
            if args.config != "full-context" else None,
        "dataset": DATASET_REPO if not args.data else "custom",
        "dataset_sha256": sha256_file(source),
        "run_name": out.name,
    }
    if args.config in ("episodic", "episodic+semantic"):
        manifest["extraction_diagnostics"] = diagnostics
    for key in ("config", "split", "models", "prompt_version", "n_results", "embedding_model", "dataset_sha256"):
        if key in previous and previous[key] != manifest[key]:
            raise SystemExit(f"Cannot resume: {key} differs from the previous manifest. Choose a new --run-name.")
    if already - {q.question_id for q in questions}:
        raise SystemExit("Cannot resume a selection that excludes previously answered questions.")

    # Always create our own temporary child, never delete a caller-owned directory
    # or use dataset question IDs as paths. Keep --workdir itself in place.
    with _work_root(args.workdir) as work_root:
        started = time.monotonic() - float(previous.get("wall_time_seconds") or 0)
        try:
            pending = [q for q in questions if q.question_id not in already]
            for index, question in enumerate(pending, start=1):
                print(f"[{index}/{len(pending)}] {question.question_id}", flush=True)
                with tempfile.TemporaryDirectory(prefix="question-", dir=work_root, ignore_cleanup_errors=True) as workdir:
                    tokens_before = meter.as_io()
                    diagnostics_before = diagnostics.copy()
                    try:
                        memory = memory_for(
                            args.config, question, workdir=Path(workdir),
                            extraction_model=extraction, n_results=args.n_results,
                            embedding_model=args.embedding_model, diagnostics=diagnostics,
                        )
                        system, user = answer_prompt(question, memory)
                        hypothesis = client.complete(
                            args.answer_model, stage="answer", system=system, user=user,
                        ).text.strip()
                        append_hypothesis(out / HYPOTHESES, question.question_id, hypothesis)
                    except BaseException:
                        # Only completed hypotheses contribute to tokens per question.
                        for stage, counts in tokens_before.items():
                            meter.stage(stage).prompt = counts["in"]
                            meter.stage(stage).completion = counts["out"]
                        diagnostics.update(diagnostics_before)
                        raise
                    already.add(question.question_id)
                # The vault is gone before judging or ingesting the next question.
                _write_manifest_and_scores(
                    out, questions=questions, already=already,
                    client=judge_client, manifest=manifest, started=started,
                )
            _write_manifest_and_scores(
                out, questions=questions, already=already,
                client=judge_client, manifest=manifest, started=started,
            )
        finally:
            _write_manifest(out, already=already, client=judge_client, manifest=manifest, started=started)
    print(f"Wrote {out}", flush=True)
    return out


def _write_manifest_and_scores(out, *, questions, already, client, manifest, started):
    hypotheses = {row["question_id"]: row["hypothesis"] for row in read_hypotheses(out / HYPOTHESES)}
    labels_path = out / "_labels.json"
    labels = load_labels(labels_path)
    answered = [q for q in questions if q.question_id in already]
    rows = grade_rows(answered, hypotheses, labels, client, manifest["models"]["judge"])
    write_labels(labels_path, labels)
    write_json(out / SCORES, build_scores(rows))
    _write_manifest(out, already=already, client=client, manifest=manifest, started=started)


def _write_manifest(out, *, already, client, manifest, started):
    manifest.update({
        "question_count": len(already),
        "token_counts": client.meter.as_io(),
        "wall_time_seconds": round(time.monotonic() - started, 3),
    })
    write_json(out / MANIFEST, manifest)


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
