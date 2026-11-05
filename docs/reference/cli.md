# CLI

All commands require a vault name. A vault lives in the project's `.ctxvault/vaults/<name>/` by default, or in `~/.ctxvault/vaults/<name>/` with `--global`: see [Local and global vaults](../how-it-works/local-and-global.md).

---

## `init`
Initialize a new vault. Vaults are public by default: any agent can access them.
Pass `--restricted` to create a restricted vault, accessible only to explicitly
attached agents. Pass `--type skill` to create a skill vault for procedural memory, or
`--type episodic` for a bi-temporal store of statements, instead of the default
semantic vault.

```bash
ctxvault init <name> [--type <type>] [--path <path>] [--global] [--restricted] [--embedding-model <model>]
```

**Arguments:**
- `<name>` - Vault name (required)
- `--type <type>` - Vault type: `semantic`, `skill` or `episodic` (optional, default: `semantic`)
- `--path <path>` - Custom location for the vault's data (optional, default: `.ctxvault/vaults/<name>` in the current directory, or in `~/.ctxvault` with `--global`)
- `--global` - Create a global vault in ~/.ctxvault, available from anywhere on the machine
- `--restricted` - Create vault as restricted (optional, default: public)
- `--embedding-model <model>` - sentence-transformers model for this vault (optional). The model is pinned at init time and used for all indexing and querying on the vault. Semantic vaults default to `all-MiniLM-L6-v2`; episodic vaults have no vectors at all unless a model is set, and fall back to structured retrieval and keyword scoring. Not supported on skill vaults.


**Example:**
```bash
ctxvault init my-vault                          # semantic vault (default)
ctxvault init my-vault --type skill             # skill vault for procedural memory
ctxvault init my-vault --type episodic          # episodic vault for statements over time
ctxvault init my-vault --global --type skill    # global skill vault
ctxvault init my-vault --restricted
ctxvault init my-vault --embedding-model all-mpnet-base-v2   # custom embedding model
```

---

## `attach`
Attach an agent to a vault, granting it access. If the vault is public, attaching
an agent automatically makes it restricted: only explicitly attached agents will
be able to access it from that point on.
```bash
ctxvault attach <vault> <agent>
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<agent>` - Agent name (required)

**Example:**
```bash
ctxvault attach my-vault my-agent
```

---

## `detach`
Remove an agent's access from a restricted vault.
```bash
ctxvault detach <vault> <agent>
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<agent>` - Agent name (required)

**Example:**
```bash
ctxvault detach my-vault my-agent
```

---

## `publish`
Make a restricted vault public, removing all access restrictions and granting
access to any agent.
```bash
ctxvault publish <vault>
```

**Arguments:**
- `<vault>` - Vault name (required)

**Example:**
```bash
ctxvault publish my-vault
```

---

## `index`

Index a vault. On a **semantic** vault, this parses documents, cuts them into chunks and stores their embeddings in the vector index. Chunks are cut in the vault's own embedding model's tokens, to that model's input limit (254 tokens for the default model, 15% of overlap between consecutive chunks), so every chunk is embedded whole; markdown is chunked on its headings, each section prefixed with its heading path. On a **skill** vault, this scans all .md files, reads their frontmatter, and rebuilds the skill index. **Episodic** vaults have no files to index and reject the command.

```bash
ctxvault index <vault> [--path <path>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--path <path>` - Specific file or directory to index (optional, default: entire vault)

**Example:**
```bash
ctxvault index my-vault
ctxvault index my-vault --path docs/papers/
```

---

## `query`
Perform semantic search on a **semantic** vault.
```bash
ctxvault query <vault> <text> [--limit <n>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<text>` - Search query (required)
- `--limit <n>`, `-n <n>` - Number of chunks to return (optional, default: `5`)

Each hit carries the chunk, its document, the metadata the writing agent attached, and a `similarity` in `[0, 1]` (1 - cosine distance). A vault indexed by a version before 0.9 compares by squared L2 distance instead and reports only the raw `score`; `ctxvault reindex <vault>` on the whole vault moves it to cosine.

**Example:**
```bash
ctxvault query my-vault "attention mechanisms"
ctxvault query my-vault "attention mechanisms" --limit 20
```

---

## `docs`
List all indexed documents in a **semantic** vault.
```bash
ctxvault docs <vault> [--status]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--status` - For each document, whether its file is unchanged since indexing, changed, or gone, plus the files in the vault never indexed. A stale document still answers queries, from the old text; `reindex --stale` brings the index back

**Example:**
```bash
ctxvault docs my-vault
```
```
Found 2 documents in 'my-vault'

  1. paper.pdf
     .pdf · 12 chunks

  2. notes.md
     .md · 3 chunks
```

---

## `skills`

List all indexed skills in a skill vault.

```bash
ctxvault skills <vault>
```

**Arguments:**
- `<vault>` - Vault name (required, must be a skill vault)

**Example:**
```bash
ctxvault skills comms-skills
```
```
Found 3 skills in 'comms-skills'

  1. Weekly Engineering Update
     Type: Skill (.md) · Last Mod: 2026-03-15T10:30:00
     Description: How to write the weekly engineering status update for stakeholders

  2. Company Newsletter Contribution
     Type: Skill (.md) · Last Mod: 2026-03-15T10:30:00
     Description: How to write an engineering section for the monthly company newsletter

  3. FAQ Response
     Type: Skill (.md) · Last Mod: 2026-03-15T10:30:00
     Description: How to write answers to frequently asked questions from employees
```

---

## `skill`

Read a specific skill from a skill vault, displaying its name, description, metadata, and full instructions.

```bash
ctxvault skill <vault> <skill_name>
```

**Arguments:**
- `<vault>` - Vault name (required, must be a skill vault)
- `<skill_name>` - Skill name as defined in the frontmatter (required)

**Example:**
```bash
ctxvault skill comms-skills "Weekly Engineering Update"
```
```
----------------------------------------------------------------------------------------------------
SKILL: Weekly Engineering Update
Description: How to write the weekly engineering status update for stakeholders
----------------------------------------------------------------------------------------------------

You are writing the weekly engineering update...

## Required structure
...

## Hard rules
- Never exceed 250 words.
- Never start with a greeting.
```

---

## `write-episode`
Record a statement in an **episodic** vault. The episode is open-ended unless a
`--valid-to` is given: it holds from now until something closes it.

```bash
ctxvault write-episode <vault> <content> [--entity <name>]... [--source <who>] [--salience <0-1>] [--confidence <0-1>] [--occurred-at <iso>] [--valid-from <iso>] [--valid-to <iso>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<content>` - The statement to record (required)
- `--entity <name>`, `-e <name>` - An entity the statement is about; repeatable, and the main way episodes get looked up later
- `--source <who>` - Who or what reported it
- `--salience <0-1>` - How much this matters (optional, default: `0.5`)
- `--confidence <0-1>` - How sure the writer is (optional, default: `1.0`)
- `--occurred-at <iso>` - When the event happened, if it differs from when validity starts
- `--valid-from <iso>` / `--valid-to <iso>` - Explicit validity window

**Example:**
```bash
ctxvault write-episode memories "Anna studies literature in Bologna" -e Anna --source conversation --salience 0.8
```

---

## `episodes`
Query an **episodic** vault. By default only statements that still hold are
returned, ranked by recency, or by relevance when a query text is given.

```bash
ctxvault episodes <vault> [text] [--entity <name>]... [--valid-at <iso>] [--known-at <iso>] [--all] [--disputed] [--order-by <mode>] [--limit <n>] [--stats] [--entities]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `[text]` - Optional query text; ranks results by similarity, or by keyword overlap on a vault without an embedding model
- `--entity <name>`, `-e <name>` - Only episodes about this entity; repeatable
- `--source <who>` - Only episodes from this source
- `--valid-at <iso>` - What was true in the world at that instant
- `--known-at <iso>` - What the vault had already recorded by that instant
- `--all` - Include closed episodes
- `--disputed` - Only episodes in an open dispute with another one (see `dispute`)
- `--order-by <mode>` - `relevance`, `recency`, `salience` or `composite` (a blend of the three)
- `--limit <n>`, `-n <n>` - Maximum results (optional, default: `10`)
- `--stats` - Print counts instead of episodes
- `--entities` - List the vault's entities and how often each is mentioned, instead of episodes. Honours `--all` and `--valid-at`
- `--min-episodes <n>` - With `--entities`, hide entities mentioned fewer than `n` times
- `--values <key>` - List the distinct values of this metadata key and how many episodes carry each, instead of episodes. Honours `--all` and `--valid-at`

**Example:**
```bash
ctxvault episodes memories --entity Anna
ctxvault episodes memories --entity Anna --valid-at 2026-05-01T00:00:00+00:00   # what was true in May
ctxvault episodes memories "university" --order-by composite
ctxvault episodes memories --stats
ctxvault episodes memories --entities                                       # what subjects exist at all
```

---

## `episode`
Read a single episode, or the whole chain of versions it belongs to.

```bash
ctxvault episode <vault> <episode_id> [--history]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>` - Episode id (required)
- `--history` - Print every version of the statement, oldest first

**Example:**
```bash
ctxvault episode memories 6f1c... --history
```

---

## `invalidate`
Close an episode: the statement stops holding, but is never deleted and stays
reachable with `--all`, `--valid-at` or `--history`.

```bash
ctxvault invalidate <vault> <episode_id> [--valid-to <iso>] [--reason <text>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>` - Episode id (required)
- `--valid-to <iso>` - When it stopped holding (optional, default: now). Learning late that something ended in the past is the normal case
- `--reason <text>` - Why it was closed; stored in the episode metadata

**Example:**
```bash
ctxvault invalidate memories 6f1c... --valid-to 2026-07-12T00:00:00+00:00 --reason "the dog died"
```

---

## `supersede`
Replace an episode with a corrected version. The old statement closes exactly
where the new one opens, in one transaction, and the two stay linked.

```bash
ctxvault supersede <vault> <episode_id> <content> [--entity <name>]... [--source <who>] [--salience <0-1>] [--valid-from <iso>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>` - Episode being replaced (required)
- `<content>` - The corrected statement (required)
- `--entity <name>`, `-e <name>` - Entities of the new statement; repeatable. Defaults to the superseded episode's entities
- `--source <who>` - Who reported the correction
- `--salience <0-1>` - Defaults to the superseded episode's salience
- `--valid-from <iso>` - The boundary between the two versions (optional, default: now)

**Example:**
```bash
ctxvault supersede memories 6f1c... "Anna studies literature in Milan" -e Anna --valid-from 2026-09-01T00:00:00+00:00
```

---

## `revise`
Restate an open episode more precisely, when the world did not change but
the wording can be said better: "lives in Padova" becomes "lives in Padova,
in the Arcella". Unlike `supersede`, nothing changes in valid time: the
revision opens where the original did and inherits its attestations, its
entities, its salience and its metadata, and any dispute still open against
it. The original is closed in transaction time only, with
`invalidation_reason: revised`: it is no longer what the vault states, it
stays in the history, and a query with `--known-at` before the revision
still finds it.

```bash
ctxvault revise <vault> <episode_id> <content> [--entity <name>]... [--source <who>] [--salience <0-1>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>` - Episode being restated (required); must still be open
- `<content>` - The more precise statement (required)
- `--entity <name>`, `-e <name>` - Entities of the revision; repeatable. Defaults to the original's
- `--source <who>` - Who restated it. Defaults to the original's source
- `--salience <0-1>` - Defaults to the original's salience

**Example:**
```bash
ctxvault revise memories 6f1c... "Anna studies literature in Milan, at the Statale"
```

---

## `confirm`
Record that an open statement was asserted again. The episode is left as it
is and gains one attestation; `confirmed_count` and `last_confirmed_at` are
read from those, as of `--known-at` when a query asks for a past instant. Use
it when you hear something the vault already holds, instead of writing it a
second time.

```bash
ctxvault confirm <vault> <episode_id> [--at <iso>] [--source <who>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>` - Episode id (required); must still be open
- `--at <iso>` - When it was reasserted (optional, default: now); cannot precede the episode's `valid_from`
- `--source <who>` - Who reasserted it (optional)

**Example:**
```bash
ctxvault confirm memories 6f1c... --source conversation
```

---

## `dispute`
Record that two open statements cannot both hold, when nobody can yet say
which is wrong. Neither is closed: both keep coming back from queries, each
listing the other in `disputed_with`. The dispute lasts exactly as long as
both episodes stay open, so it is resolved by `invalidate` or `supersede` on
one of them and needs no command of its own to end; a `revise` of either
side carries the dispute over to the revision. `episodes --disputed`
lists what is still unsettled.

```bash
ctxvault dispute <vault> <episode_id> <other_id> [--note <text>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<episode_id>`, `<other_id>` - The two episodes (required); both must still be open
- `--note <text>` - Why they cannot both hold (optional)

**Example:**
```bash
ctxvault dispute memories 6f1c... 9a2d... --note "one says Bologna, the other Padova"
ctxvault episodes memories --disputed
```

---

## `delete`
Remove documents from a vault or delete the vault entirely.
```bash
ctxvault delete <vault> [--path <path>] [--purge]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--path <path>` - File or directory path to delete, relative to the vault root (optional, deletes all documents if omitted)
- `--purge` - Permanently delete the vault, all its documents and indexes (cannot be used together with `--path`)

**Examples:**
```bash
ctxvault delete my-vault                        # removes all documents and indexes
ctxvault delete my-vault --path paper.pdf       # removes a specific document
ctxvault delete my-vault --purge                # removes the vault entirely
```

---

## `reindex`
Re-index documents in a **semantic** vault.
```bash
ctxvault reindex <vault> [--path <path>] [--stale]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--path <path>` - Specific file or directory to re-index (optional, default: entire vault)
- `--stale` - Only what `docs --status` reports: reindex the changed files, index the new ones, drop the documents whose file is gone

A whole-vault reindex also moves a collection made by a version before 0.9 to cosine distance, keeping each document's agent metadata.

**Example:**
```bash
ctxvault reindex my-vault
ctxvault reindex my-vault --path docs/
```

---

## `ui`
Open the memory viewer in the browser: every registered vault, its contents, and for episodic vaults the time cursor and the history of each statement. Read-only. With `--export`, write the page and a snapshot of every vault to one self-contained HTML file instead of serving it.

```bash
ctxvault ui [--port <port>] [--host <host>] [--no-browser] [--export <file.html>]
```

**Arguments:**
- `--port <port>` - Port to serve on (optional, default: `8765`)
- `--host <host>` - Interface to bind (optional, default: `127.0.0.1`). The viewer is the owner's view, like the CLI: it shows every vault, restricted ones included, so binding anything beyond loopback exposes them to whoever can reach the port
- `--no-browser` - Serve without opening a browser tab
- `--export <file.html>` - Write a self-contained snapshot of the memory to this file and exit
- `--note <text>` - With `--export`, a line shown at the top of the snapshot until dismissed: what it is, for whoever opens it without knowing

Like every command, `ui` finds a project's vaults through the `.ctxvault` folder nearest to where it runs, plus the global `~/.ctxvault`. The page says which registries it is reading.

The viewer is also mounted at `/ui` on the HTTP API server, for whoever already runs one. There it answers only requests from the machine running the server: the API may listen beyond localhost for agents, and the viewer is not gated by agent names.

---

## `vaults`
List all vaults with their paths, types, and access configuration.

```bash
ctxvault vaults
```

**Example:**
```bash
ctxvault vaults
```
```
Found 3 vaults (1 local, 2 global)

── local ──────────────────────────
  project-vault       [SEMANTIC] [PUBLIC]
  path:               /my-project/.ctxvault/vaults/project-vault

── global ─────────────────────────
  atlas-vault         [SEMANTIC] [RESTRICTED]  agents: atlas-agent
  path:               ~/.ctxvault/vaults/atlas-vault

  comms-skills        [SKILL]    [PUBLIC]
  path:               ~/.ctxvault/vaults/comms-skills

  account-memory      [EPISODIC] [PUBLIC]
  path:               ~/.ctxvault/vaults/account-memory
```

## Which command works on which vault

| Command         | Semantic vault | Skill vault | Episodic vault |
|-----------------|----------------|-------------|----------------|
| `init`          | ✓              | ✓           | ✓              |
| `index`         | ✓              | ✓           | ✗              |
| `query`         | ✓              | ✗           | ✗              |
| `docs`          | ✓              | ✗           | ✗              |
| `skills`        | ✗              | ✓           | ✗              |
| `skill`         | ✗              | ✓           | ✗              |
| `write-episode` | ✗              | ✗           | ✓              |
| `episodes`      | ✗              | ✗           | ✓              |
| `episode`       | ✗              | ✗           | ✓              |
| `invalidate`    | ✗              | ✗           | ✓              |
| `supersede`     | ✗              | ✗           | ✓              |
| `reindex`       | ✓              | ✗           | ✗              |
| `delete`        | ✓              | ✗           | ✗              |
| `vaults`        | ✓              | ✓           | ✓              |
| `attach`        | ✓              | ✓           | ✓              |
| `detach`        | ✓              | ✓           | ✓              |
| `publish`       | ✓              | ✓           | ✓              |

An episodic vault holds rows rather than files, so the file oriented commands
do not apply to it: there is nothing to index, reindex or delete on disk.
