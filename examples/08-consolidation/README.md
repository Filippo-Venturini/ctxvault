# 08 · Consolidation

Turn conversations into episodes with a local model. Three short chats on
different days, a later one changes something an earlier one said, and the
vault records the change instead of overwriting the fact.

Examples 06 and 07 write episodes by hand. This one lets a model read the
turns and decide what to write, through `ctxvault.consolidation`.

---

## Scenario

Giulia talks to an assistant on three different days.

- March 2: she lives in Lisbon, works at Brightline and is vegetarian.
- April 14: she moved to Porto. She still works at Brightline.
- June 20: she left Brightline and is freelancing.

A fourth conversation (July 5) is only previewed with `dry_run=True`.

---

## What this demonstrates

- `consolidate(...)` with `OpenAICompatibleModel` pointed at Ollama
- Replaying past conversations with `at=`, so each write is dated to the day it happened
- The operations of each run (`write_episode`, `confirm_episode`, `supersede_episode`, ...) printed as they are decided
- The resulting memory, what held on an earlier date, and `history()` of a fact that changed
- `dry_run=True`: the same operations come back, nothing is written

---

## Setup

You need [Ollama](https://ollama.com) running on this machine and a small model:

```bash
ollama pull llama3.2:3b
```

Then:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

To use another model, set `MODEL`:

```bash
MODEL=qwen2.5:7b python app.py
```

No API key is involved. The conversations stay on this machine: the model
class refuses a remote endpoint unless you pass `allow_remote=True`.

---

## Notes

- Small models make mistakes here. A 3B model can miss a claim, pick the
  wrong relation (`new` where `replaces` was right) or give a date that was
  never said. The layer validates what comes back and never lets the model
  call a verb, but it cannot make a weak extraction good. The output of your
  run may differ from the one below, and from run to run on another machine.
- A small model on CPU is slow. `app.py` sets `timeout=600` per call
  because the default of two minutes can be too short.
- Nothing a run does is destructive. A wrong supersede can be undone with
  `reopen_episode`, and `history()` shows both versions.
- Every write carries the `run_id`, the model and the prompt version, so a
  run can be found again:
  ```python
  facts.query_episodes(metadata_filters={"run_id": result.run_id}, include_closed=True)
  ```

See [docs/consolidation.md](../../docs/consolidation.md) for how the
relation labels map to verbs.

---

## Observed

Run with `llama3.2:1b` on Ollama (Docker, CPU only), prompts `en-2`, ctxvault 0.10.0.
The 3B model was too slow on this machine (about 0.6 tokens/s) to finish a run.

- Extraction worked: 2 claims per conversation, 0 dropped, no invented dates.
- Claims stayed first-person ("I moved to Porto last week"), not rewritten as statements about Giulia.
- Every claim came back as `new`. "I moved to Porto" did not replace "I live in Lisbon", and "I left Brightline" did not close "works at Brightline".
- As a result nothing was superseded, all 6 episodes stay open, and the history section has no changed fact to show.
- The dry run behaved as documented: 2 planned operations, 6 episodes before and after.

The output depends on the model. A larger one may relate the claims correctly.

---

## Project structure
```
08-consolidation/
├── app.py
├── README.md
└── requirements.txt
```

No pre-written documents. The episodic vault is created in `.ctxvault/`
on first run and recreated each time the script starts.

---

## Next

Example 06 recorded the same kind of timeline by calling the verbs
directly. Here the verbs are chosen from the text. If you already have an
extractor you trust, keep using the core alone.
