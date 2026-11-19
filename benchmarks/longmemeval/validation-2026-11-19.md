# LongMemEval real-model smoke verification — 2026-11-19

Three actual `--split oracle --limit 5` runs for PR #78, completed at
17:14 Asia/Shanghai. Dataset, embeddings and model inference are real, not
fixtures or canned responses. These are **pipeline smoke results, not an
accuracy comparison**: a tiny local model also judges its own answers.

## Results

```text
config               split    answer model                 n   grader    judge   tokens/q folder
------------------------------------------------------------------------------------------------
episodic             oracle   Qwen/Qwen2.5-0.5B-Instruct     5    60.0%    60.0%    10396.4 episodic-oracle-qwen2.5-0.5b
full-context         oracle   Qwen/Qwen2.5-0.5B-Instruct     5    20.0%    80.0%     7356.8 full-context-oracle-qwen2.5-0.5b
semantic-only        oracle   Qwen/Qwen2.5-0.5B-Instruct     5    20.0%    80.0%     2298.4 semantic-only-oracle-qwen2.5-0.5b
```

The adjacent run folders each contain the three contract files:
`hypotheses.jsonl`, `manifest.json`, `scores.json`. No dataset or model weights
are committed. The full 500-question oracle file downloaded successfully and
matched SHA-256 `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c`; each configuration answered its first five
questions (11 evidence sessions total).

## Runtime and cost

- Answer/extraction/judge: `Qwen/Qwen2.5-0.5B-Instruct`, public snapshot
  `7ae557604adf67be50417f59c2c2f167def9a775`.
- Retrieval embeddings: `sentence-transformers/all-MiniLM-L6-v2`, snapshot
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Full-context does not use embeddings.
- Local CPU float32, four generation threads, greedy `do_sample=False`, default
  maximum 512 new tokens per completion. The official judge uses 10. No
  constrained JSON decoder or input truncation.
- Python 3.13.5; torch 2.15.0, transformers 5.23.0, sentence-transformers 6.3.0, huggingface-hub 2.4.0.
- A loopback-only HTTP adapter used `AutoTokenizer.apply_chat_template` and
  `AutoModelForCausalLM.generate` with the above weights and reported the actual
  input/generated token lengths. No provider inference API or credentials:
  **paid API spend $0**. Public weight/dataset downloads only.
- 48 successful real model calls; summed server token counts exactly
  match the three manifests: 96069 input / 4189 output.
- Episodic diagnostics: 11 sessions, 2 unparseable replies, 17 claims applied,
  10 rejected. A valid empty extraction is not a parse failure. The small model
  is imperfect; these failures are now visible rather than silently ignored.

## Commands

From the repository root, with the current source installed/on PYTHONPATH,
point BASE at an OpenAI-compatible local server hosting the model above:

```sh
for CONFIG in full-context semantic-only episodic; do
  python -m benchmarks.longmemeval \
    --config "$CONFIG" --split oracle --limit 5 \
    --answer-model Qwen/Qwen2.5-0.5B-Instruct \
    --extract-model Qwen/Qwen2.5-0.5B-Instruct \
    --judge-model Qwen/Qwen2.5-0.5B-Instruct \
    --base-url "$BASE" --timeout 300 \
    --results-dir "$RESULTS" --cache-dir "$CACHE" --workdir "$WORK" \
    --run-name "$CONFIG-oracle-qwen2.5-0.5b"
done
python -m benchmarks.longmemeval.report --results-dir "$RESULTS"
```

Runs used an isolated HOME/cache/workdir, no remote-provider permission and no
API keys. After all runs, the inference server was **stopped**, then all three
commands were repeated with `--resume`. Every no-op resume succeeded with no
reachable model: token and extraction totals remained identical, cumulative
wall time did not decrease, and WORK contained no leftover vaults.

Inference used the implemented working tree, subsequently committed as
`74bdce0aa4dd17e8a555c2a5c5f5e4357d430cb5`; no executable logic changed during the runs. Those final no-op
resumes record this source commit in the manifests. This evidence-only commit
adds no code changes. No review comment or email was posted.

## Regression tests

- Focused benchmark/endpoint tests: **66 passed**.
- Full source branch suite: **423 passed**.
- Conflict-free merge-tree with upstream dev
  `2ae2eb4ff21c88dc6a807f5e00094ac8efcc1683`: **456 passed**.
- `compileall` and `git diff --check` passed.

Combined episodic+semantic and `write_session` ingestion remain a separate
follow-up after this PR merges, as requested by the maintainer.
