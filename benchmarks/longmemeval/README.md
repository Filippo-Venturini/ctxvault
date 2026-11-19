# LongMemEval harness

One command replays [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
into CtxVault and writes results in a fixed format, so runs made with
different models and keys can be compared and merged. This is the harness
described in [#47](https://github.com/Filippo-Venturini/ctxvault/issues/47);
running it against a paid endpoint and contributing the folder is a separate
piece of work.

The official dataset is downloaded into a cache and checked against a pinned
SHA-256. Nothing from the dataset is stored in this repository. The source
is [xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
(the earlier longmemeval dump is deprecated).

## Configurations

| --config              | What the answer model sees |
|-----------------------|----------------------------|
| full-context          | The whole dated history in the prompt (the ceiling). |
| semantic-only         | Sessions indexed as documents; the top retrieved chunks. |
| episodic              | Sessions consolidated with ctxvault.consolidation; episodes that held as of the question date. |
| episodic+semantic     | Facts first, text as fallback. Reserved for the follow-up PR after this harness merges (using #76). |

Each question gets a fresh vault. Sessions are ingested in date order, with
at= set to the session date (replay in transaction time). The question is
then asked as of question_date. When that clock falls earlier on the same
day as the last session — a known LongMemEval annotation quirk — the harness
follows the official clarification and treats the question as immediately
after that session.

## Commands

The model flags accept any OpenAI-compatible endpoint. Temperature is 0.
A remote URL is refused unless you pass --allow-remote, because the
conversations leave the machine. Cheap runs use --split oracle,
--limit N and --resume.

From the repository root, with a local server (the default is Ollama):

```bash
python -m benchmarks.longmemeval \
  --config full-context --split oracle --limit 5 --resume \
  --answer-model qwen2.5:7b --judge-model qwen2.5:7b

python -m benchmarks.longmemeval \
  --config semantic-only --split oracle --limit 5 --resume \
  --answer-model qwen2.5:7b --judge-model qwen2.5:7b

python -m benchmarks.longmemeval \
  --config episodic --split oracle --limit 5 --resume \
  --answer-model qwen2.5:7b --extract-model qwen2.5:7b --judge-model qwen2.5:7b
```

A hosted endpoint (OpenAI or similar):

```bash
python -m benchmarks.longmemeval \
  --config full-context --split oracle --limit 5 --resume \
  --answer-model gpt-4o --judge-model gpt-4o \
  --base-url https://api.openai.com/v1 --allow-remote
```

OPENAI_API_KEY is read if --api-key is omitted. Use --data path.json
for a local file instead of downloading a split; its default run name and split
are `custom`, and its complete file SHA-256 is recorded too.

The judge can use a different endpoint and key, for example a local answer
model with `--judge-model gpt-4o --judge-base-url https://api.openai.com/v1
--judge-api-key ... --allow-remote`. Omitted judge options inherit the answer
endpoint/key. Keys are never written to the manifest. A remote judge receives
the question, gold answer and hypothesis; `--allow-remote` is required.

`--resume` carries all stage token totals, wall time and extraction diagnostics
forward, including a resume with nothing left to answer. It can extend a run
with a larger `--limit`; it refuses a different dataset checksum, model,
prompt version or retrieval configuration, or a selection that excludes
already answered questions. The previous manifest is required when hypotheses
exist, since missing historical usage cannot be reconstructed. Extraction and
answer usage and extraction diagnostics are counted only after the question's
hypothesis is saved. An interrupted question is retried without counting its
failed attempt toward tokens per question; these totals therefore exclude
failed-attempt costs. Wall time still includes interrupted work. Missing
provider usage is reported as zero, not estimated.

Per-question vaults live in fresh temporary children of `--workdir` (or the
system temporary directory) and are removed immediately after their hypothesis
is saved, before judging or ingesting another question. Each semantic vault's
Chroma client is released before removing its directory, including after an
ingestion or retrieval error. Temporary-directory cleanup errors (such as
Windows file locks) do not mask the original result or error. The caller's
workdir and any pre-existing files in it are left alone.

Merge every complete folder under results/:

```bash
python -m benchmarks.longmemeval.report
```

## Output

Each run writes benchmarks/longmemeval/results/<run-name>/:

- hypotheses.jsonl: one line per question, {"question_id": ..., "hypothesis": ...}, accepted as is by the official LongMemEval evaluation script.
- manifest.json: ctxvault commit, config, split, question count, extraction / answer / judge models, prompt version, cumulative token counts (in and out, per stage), cumulative wall time, `n_results`, embedding model (`null` for full-context), dataset SHA-256.
  Episodic manifests also contain cumulative `extraction_diagnostics`: `sessions_consolidated`, `sessions_with_unparseable_reply`, `claims_written` and `claims_rejected`. An unparseable reply is one without a usable claims list, distinct from a valid empty list. Written claims count applied writes, confirmations, revisions and supersessions once per claim (not the secondary dispute operation). Rejected claims count schema/kind rejections and refused primary writes; an unparseable reply has no countable claims and is tracked separately.
- scores.json: overall accuracy and accuracy per question type, from the judge model (the official yes/no prompt) and from a deterministic grader (every content word of the gold answer appears in the hypothesis). The grader is `null` for abstention (`_abs`) and `single-session-preference` questions, whose gold answers are explanations or rubrics; they do not enter grader accuracy or the disagreement list. The questions where both graders apply and disagree are listed.

The report includes the split column so oracle, `s`, `m` and custom runs remain distinguishable. A run with a missing or incomplete manifest is not merged by report. Anyone
with API keys can open a PR that adds one complete results/<run-name>/
folder. Small smoke runs belong in PR discussion rather than in `results/`,
so the default report contains full, comparable runs only.

## Token estimates

These are order-of-magnitude figures from the LongMemEval description, not
measurements from this harness. They are here so a run can be planned
before it is started.

- History size, as reported for Llama 3: LongMemEval_S concatenates to
  about 115k tokens per question (~40 sessions). The oracle split keeps only
  the evidence sessions, so the prompt is much smaller. LongMemEval_M has
  about 500 sessions per question and is not meant to fit in a 128k window;
  use it with semantic-only or episodic, not full-context.
- full-context: one answer call over the whole history, plus one short
  judge call. On S, the history dominates; 500 questions at 115k tokens is
  on the order of 6e7 input tokens, before answers and judges.
- semantic-only: indexing embeddings for every session, then one answer
  call over a handful of chunks (default 8) and one judge call. Input tokens
  to the answer model stay small; the cost is retrieval, not the prompt.
- episodic: one extraction call per session and a relate call per durable
  claim, then one answer call over the retrieved episodes and one judge call.
  Extraction cost scales with sessions times tokens, not with the concatenated
  history in a single prompt.

Use --limit and the oracle split to measure tokens per question on your
model, then read them off manifest.json.
