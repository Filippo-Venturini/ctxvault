# From Python, in-process

For scripts, tests, pipelines and agents that own their memory: import the client and call the vaults directly, with no server to start.

```bash
pip install ctxvault
```

The same vaults, from code in the same process. Nothing to start: the client opens the vault the CLI registered and returns the same typed models the API serializes.

```python
from ctxvault import Client

memory = Client(agent="briefing-bot")

# Episodic memory: record, correct, ask as of any moment
facts = memory.episodic("account-memory")
contact = facts.write_episode("Sarah Klein is the main contact", entities=["Sarah Klein"], salience=0.9)
facts.supersede_episode(contact.id, "Marco Rossi is the main contact", entities=["Marco Rossi"])
facts.query_episodes(entities=["Marco Rossi"]).results        # what holds now
facts.query_episodes(valid_at="2026-04-10T00:00:00+00:00")    # what held then
facts.history(contact.id).chain                               # how the belief changed

# Semantic and procedural memory, from the same client
memory.semantic("knowledge").query("transformer architecture", n_results=3).results
memory.skills("procedures").read_skill("Deploy Service").instructions

# The registry, as the CLI sees it
memory.init("notes", "episodic")
memory.vaults()
```

`vault(name)` returns whatever type the name resolves to; `semantic`, `skills` and `episodic` insist on one type and fail before a wrong method call would. The `agent` plays the part of the `X-CtxVault-Agent` header: a restricted vault opens only for an agent attached to it.

The client is for the process that owns the vault. SQLite and Chroma are built for a single writer, so two processes that must share a vault (an agent writing while a consolidation job runs) go through one HTTP server instead.

The client methods mirror the CLI commands one to one: see the [CLI reference](../reference/cli.md) for what each operation does and returns.
