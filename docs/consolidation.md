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

To use something else entirely, pass any object with a `name`, a `prompt_version`, and two methods: `extract(turns)` returning raw claims, and `relate(claim, candidates)` returning `{"relation": ..., "episode_id": ...}`. Both answers are validated by the layer.

## The prompts

The prompts are plain files shipped with the library, one set per language. To change them, copy the directory, edit it, and bump its `VERSION` so the writes of the two sets can be told apart:

```python
from ctxvault.consolidation import Prompts

model = OpenAICompatibleModel("qwen2.5:7b", prompts=Prompts.from_dir("my-prompts"))
```

A directory holds `extract.md`, `relate.md` and `VERSION`. English ships today.

## Transcripts and chunk references

A claim can point back at the words it came from. Write the conversation itself into a semantic vault, then attach a reference to the chunk each claim rests on. Both functions are in the core, so they work without the layer.

```python
from ctxvault import Client
from ctxvault.core.transcripts import Turn, write_session
from ctxvault.core.references import chunk_reference, resolve_chunk

transcripts = Client().semantic("transcripts")
written = write_session(transcripts, "sessions/42.txt", turns, session_id="42",
                        agent_metadata={"generated_by": "harness"})
ref = chunk_reference("transcripts", written.doc_id, written.turn_chunks[3])   # the chunk turn 3 starts in
resolve_chunk(ref, agent="briefing-bot").state   # "holds"
```

**`write_session`** writes one `.txt` document with one line per turn, `2026-03-01 09:05  user: text`, the time in UTC (an undated turn has no time in front). Every chunk keeps the times of the turns it holds, even when it starts mid-session. The session's dates come from its dated turns, never from the file: `session_started` and `session_ended` (ISO), `session_started_ts` and `session_ended_ts` (epoch seconds, for `$lt` / `$gt` filters), and `session_dated`. A session with no dated turn is undated. Writing the same path again replaces the session under the same `doc_id`. It returns `turn_chunks`: for each turn, the chunk it starts in.

**`resolve_chunk`** checks a reference against the vault as it is now, and gives exactly one answer:

| state | when |
|---|---|
| `holds` | the chunk is there, with the same text. `text` is returned |
| `changed` | the document is there, but the chunk's text differs or the chunk is past its end. No text |
| `moved` | the `doc_id` is gone, but the reference's `path` in this vault has the same chunk: a vault moved to another folder. `text` and the new `doc_id` are returned |
| `missing` | the document is neither under its `doc_id` nor at its `path` |
| `unreachable` | the vault is not registered here, is not a semantic vault, or could not be read |
| `refused` | the agent may not read the vault, or `path` is not a plain relative path inside it |

`unreachable` and `refused` are never `missing`: they mean the source could not be checked, not that it is gone. Access is checked before anything is read, so a refused caller learns nothing about the document.
