# MCP tools

What an agent sees when it is connected to `ctxvault-mcp`: every tool, its description as the agent reads it, and its parameters. To connect a client, see [Through an MCP client](../connect/mcp.md).

Restricted vaults answer only when the server was started with `--agent <name>` and that agent is attached to the vault; a tool called on any other restricted vault fails with an access error.

## Discovery

### `list_vaults`

List all available vaults. Use this before querying or writing to discover which vaults exist and choose the right one.

### `warmup_status`

Check if the embedding model has finished initializing. Use this to verify warmup status before attempting queries or writes.

## Semantic vaults

### `query`

Search for relevant information in a CtxVault vault using semantic similarity. Use this when the user asks a question that might be answered by their personal knowledge base or documents. Returns the most relevant text chunks with their source files.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `query` | `str` | required |

### `list_docs`

List all indexed documents inside a specific vault. Use this to understand what knowledge is available before performing a search.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |

### `write_doc`

Save new information or agent-generated content to a semantic vault for future retrieval. Use this only with semantic vaults, to persist important context, summaries, or notes that should be remembered across sessions. Supports .txt, .md, and .docx formats.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `file_path` | `str` | required |
| `content` | `str` | required |
| `generated_by` | `str` | required |
| `overwrite` | `bool` | `False` |

## Skill vaults

### `list_skills`

List all available skills inside a specific vault. Use this to understand what skills are available before trying to fetch one.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |

### `read_skill`

Read one skill from a skill vault: its name, description and full instructions. Use this after list_skills, once you know which procedure fits the task, and follow the instructions it returns.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `skill_name` | `str` | required |

### `write_skill`

Create and store a new skill in a skill vault. Use this to persist procedural knowledge, instructions, or how-to guides that agents can retrieve and execute later. The skill will be indexed by name and description for fast lookup. Use this only with skill vaults.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `skill_name` | `str` | required |
| `description` | `str` | required |
| `instructions` | `str` | required |
| `overwrite` | `bool` | `False` |

## Episodic vaults

### `write_episode`

Record something that happened or something the user stated, in an episodic vault. Use this for facts with a lifetime — situations, preferences, relationships, plans — rather than for documents. Give the entities it is about so it can be looked up later, and a salience between 0 and 1 for how much it matters.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `content` | `str` | required |
| `entities` | `list[str]` | `[]` |
| `source` | `str | None` | `None` |
| `salience` | `float` | `0.5` |
| `confidence` | `float` | `1.0` |
| `occurred_at` | `str | None` | `None` |
| `valid_from` | `str | None` | `None` |

### `query_episodes`

Retrieve episodes from an episodic vault. By default only statements that still hold are returned. Filter by entity for 'everything about X', pass valid_at to ask what was true at a past moment, or known_at to ask what the vault had already learned by then. Query text is optional and ranks results; without it the newest come first.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `query` | `str` | `''` |
| `entities` | `list[str]` | `[]` |
| `valid_at` | `str | None` | `None` |
| `known_at` | `str | None` | `None` |
| `include_closed` | `bool` | `False` |
| `order_by` | `str | None` | `None` |
| `limit` | `int` | `10` |

### `confirm_episode`

Record that a statement already in the vault was asserted again. Use this when you hear something the vault already holds, instead of writing it a second time: the episode stays as it is and gains one attestation, so a fact heard once can be told from one heard many times.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |
| `at` | `str | None` | `None` |
| `source` | `str | None` | `None` |

### `supersede_episode`

Replace an episode with a corrected or updated version. The old statement is closed exactly where the new one begins and the two are linked, so the history of what changed stays readable. Entities and salience carry over from the old episode unless you pass new ones. Use this whenever new information contradicts something already recorded.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |
| `content` | `str` | required |
| `entities` | `list[str]` | `[]` |
| `source` | `str | None` | `None` |
| `salience` | `float | None` | `None` |

### `revise_episode`

Restate an episode more precisely, when the world did not change but you can now say it better ('lives in Padova' -> 'lives in Padova, in the Arcella'). The revision opens where the original did and inherits its attestations and open disputes; the original stays in the history but is no longer what the vault states. Use supersede_episode instead when the world changed.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |
| `content` | `str` | required |
| `entities` | `list[str]` | `[]` |
| `source` | `str | None` | `None` |
| `salience` | `float | None` | `None` |

### `invalidate_episode`

Mark an episode as no longer true, without deleting it. Use this when something ends and nothing replaces it. If a corrected version exists instead, use supersede_episode so the two stay linked.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |
| `valid_to` | `str | None` | `None` |
| `reason` | `str` | `''` |

### `dispute_episodes`

Record that two open statements cannot both hold, when you cannot tell which one is wrong. Neither is closed: both keep coming back from queries, each flagged with the other in disputed_with, so you can ask instead of assert. The dispute ends by itself when one side is invalidated or superseded. If you do know which one is wrong, use supersede_episode or invalidate_episode instead.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |
| `other_id` | `str` | required |
| `note` | `str` | `''` |

### `episode_history`

Show every version of a statement, oldest first. Use this to explain why the vault believes something, or to see what an episode used to say before it was corrected.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `episode_id` | `str` | required |

### `list_entities`

List the entities an episodic vault knows about, with how many episodes mention each one. This is the vault's vocabulary: use it to find out what subjects exist before querying for them, to spot the name a person or thing is recorded under, or to see what has gone quiet. Unlike query_episodes it enumerates rather than ranks, so nothing is left out. By default only entities named by statements that still hold are listed; pass include_closed to see everything the vault ever recorded.

| Parameter | Type | Default |
|-----------|------|---------|
| `vault_name` | `str` | required |
| `include_closed` | `bool` | `False` |
| `valid_at` | `str | None` | `None` |
| `min_episodes` | `int` | `1` |
