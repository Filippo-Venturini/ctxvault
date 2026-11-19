# Consolidation

Turn a conversation into episodes, without writing the extractor yourself.

CtxVault's core never calls a language model: it stores what it is told and keeps track of when it held. Deciding *what* to store from a conversation, and whether a new statement confirms, refines, contradicts or replaces an old one, is judgement, and judgement needs a model. `ctxvault.consolidation` is an optional layer that does it. It sits outside the core, as a client of an episodic vault, and uses only the vault's public verbs. If you have your own extractor, keep using the core alone.

```python
from ctxvault import Client
from ctxvault.consolidation import OpenAICompatibleModel, consolidate

facts = Client().episodic("account-memory")
model = OpenAICompatibleModel("qwen2.5:7b")           # Ollama on this machine, by default

turns = [
    {"speaker": "Giuseppe", "text": "I moved to Mestre in March.", "at": "2026-03-10T09:00:00+00:00"},
]
result = consolidate(facts, turns, model)

for operation in result.operations:
    print(operation.verb, operation.claim.statement, operation.target_id)
```

## How it decides

The model interprets, code decides how to write.

1. **Turns to claims.** The model reads the turns and returns claims: a subject, a statement, who said it, whether it lasts, and a date when the conversation gave one. Each claim is validated against a schema; what does not fit is dropped.
2. **Candidates.** Code asks the vault what it already holds about the claim's subject, as of the time of the conversation.
3. **Relation.** The model is shown the claim next to those candidates and returns one label and the episode it is about.
4. **Verb.** A fixed mapping turns the label into a call:

| Relation | Meaning | Verb |
|---|---|---|
| `new` | nothing on file covers it | `write_episode` |
| `confirms` | the same thing, said again | `confirm_episode` |
| `refines` | the same thing, said more precisely | `revise_episode` |
| `replaces` | the world changed | `supersede_episode` |
| `contradicts` | both cannot hold, and nothing says which is wrong | `write_episode`, then `dispute_episodes` |

The model never calls a verb. An answer that does not fit, or that names an episode it was not shown, is read as `new`, with a note on the operation. A statement that only holds for a moment (`of_the_day`) is written without being related to anything.

## Checking and undoing a run

Every write and every event carries the run that made it: `run_id`, the model and the prompt version. A whole run is two queries:

```python
facts.query_episodes(metadata_filters={"run_id": result.run_id}, include_closed=True)        # what it wrote
facts.query_episodes(event_metadata_filters={"run_id": result.run_id}, include_closed=True)  # what it confirmed, disputed or closed
```

Nothing a run does is destructive. A wrong supersede closed an episode that `reopen_episode` brings back once its successor is invalidated, and `history()` shows both.

To see what a run would do without writing anything, pass `dry_run=True`: the same operations come back, none applied.

## Options

- **`at`**: when the conversation happened, for replaying past sessions. It becomes the transaction time of every write, and the start of validity of a claim that gives no date. Defaults to the last dated turn, else now.
- **`kinds=["first_party"]`**: refuse claims about people other than the speaker.
- **`provenance`**: where the turns came from, stored on every claim the model returns without one, e.g. `[{"type": "external", "source": "session-42"}]`.
- **`run_id`**: your own identifier for the run, instead of a generated one.

## The model

`OpenAICompatibleModel` talks to any server with the OpenAI chat API: Ollama, llama.cpp, LM Studio, vLLM, or a hosted provider.

The endpoint must be on this machine unless you say otherwise, because the text of the conversations is sent to it:

```python
OpenAICompatibleModel("gpt-4.1-mini", base_url="https://api.openai.com/v1", api_key="...", allow_remote=True)
```

Requests use temperature 0. If your server rejects `response_format`, pass `json_mode=False`; the answer is parsed either way.

For token accounting, pass `usage_callback(stage, prompt_tokens, completion_tokens)`.
The callback runs once after each successful response; `stage` is `"extract"`
or `"relate"`, and counts come from the endpoint's `usage` object. A missing
usage object is reported as zero, not an estimate. No callback runs on an HTTP
or malformed chat-completion error.

```python
usage = []
model = OpenAICompatibleModel("qwen2.5:7b", usage_callback=lambda *call: usage.append(call))
```

After each `extract`, `model.last_extraction_unparseable` is true if the reply
could not be read as a claims list. A valid empty claims list leaves it false.
The flag resets at the next extraction; relation calls do not change it.
Individual invalid claims are still counted in `consolidate(...).dropped`.

To use something else entirely, pass any object with a `name`, a `prompt_version`, and two methods: `extract(turns)` returning raw claims, and `relate(claim, candidates)` returning `{"relation": ..., "episode_id": ...}`. Both answers are validated by the layer.

## The prompts

The prompts are plain files shipped with the library, one set per language. To change them, copy the directory, edit it, and bump its `VERSION` so the writes of the two sets can be told apart:

```python
from ctxvault.consolidation import Prompts

model = OpenAICompatibleModel("qwen2.5:7b", prompts=Prompts.from_dir("my-prompts"))
```

A directory holds `extract.md`, `relate.md` and `VERSION`. English ships today.
