# Changelog

All notable changes to CtxVault are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with entries grouped as Added / Changed / Fixed. User-visible changes that land
on `dev` add an entry under `Unreleased`.

## [Unreleased]

### Changed

- **Episodic vaults migrate automatically on first open.** Since v0.9.1 the episodic
  schema moved through v4 (closes stored as intervals with a `reason` and reopen
  links), v5 (metadata on confirm, dispute and invalidate events) and v6 (event
  attribution on reopen, supersede and revise). A vault written by v0.9.1 keeps its
  history; legacy closes keep their reason and reopen with `prior_valid_to = NULL`,
  so reopening a pre-v4 close cannot restore the written-in `valid_to`.

### Added

- **Reopen a closed episode** without erasing the close (#48): the closure keeps its
  reason and gains `reopened_at`; as-of (`known_at`) queries still see the episode as
  closed at any moment between the close and the reopen.
- **Event metadata** on confirm, dispute and invalidate (#51), and on reopen,
  supersede and revise closes (#57), filterable in queries via event-metadata filters.
- **Consolidation layer** (#49, #59, #61, part of #46): the claim schema, an
  extraction pipeline that turns conversation turns into validated claims, and
  `OpenAICompatibleModel`, which speaks to any chat-completions endpoint. The client
  refuses a non-loopback `base_url` unless `allow_remote=True`, since the text of the
  conversations is sent to it; default prompts ship as data (`extract.md`, `relate.md`,
  versioned) and the layer is documented in `docs/consolidation.md`.
- **Memory viewer** (#58): episode closes and reopens listed in the detail panel,
  reopens marked on the changes timeline, and event metadata shown collapsed by
  default.
- **Semantic vaults index `.html` and `.csv`** (#62) alongside `.txt`, `.md`, `.pdf`
  and `.docx` — HTML text via the standard library, CSV as one indexed line per data
  row with header names kept beside the values. No new dependency.

### Fixed

- **Windows vault paths** (#64): the registry and the Python client return absolute
  paths with `/` separators, and opening a vault in Windows Explorer converts the
  registered path to native separators.
- **UI HTML export** (#64) embeds `.woff2` fonts with the `font/woff2` MIME type even
  when the system MIME table lacks the entry, so exported snapshots keep their
  typography.

## [0.9.1] - 2026-11-10

### Added

- `ctxvault mcp` — new CLI subcommand that starts the MCP server. MCP clients can run
  it with `"command": "uvx", "args": ["ctxvault", "mcp"]` and nothing installed. The
  `ctxvault-mcp` entry point keeps working.
- CtxVault is listed on the official MCP registry as
  `io.github.Filippo-Venturini/ctxvault`.
- `reindex --embedding-model <model>` pins an embedding model to an existing episodic
  vault and embeds what it already holds.

### Changed

- Docs: MCP setup via `uvx` and the `mcp` command in the CLI reference; README
  comparison table rewritten.

## [0.9.0] - 2026-11-06

### Added

- **Memory viewer** — `ctxvault ui` shows every registered vault, its type and the
  agents that can reach it: semantic vaults with their documents, the chunks the agent
  receives and search by meaning; skill vaults with their procedures rendered from
  markdown; episodic vaults with what holds today, the open disputes, and a time
  cursor that rewinds the memory to any past day. `ctxvault ui --export file.html`
  writes a self-contained snapshot, and the viewer is also served at `/ui` by the HTTP
  server, to local requests only.
- **Better retrieval in semantic vaults**: documents are chunked in the embedding
  model's own tokens, up to its input limit; markdown splits on its headings and each
  chunk keeps its heading path. New vaults compare by cosine distance, and every hit
  carries a `similarity` between 0 and 1.
- **Index status**: `ctxvault docs --status` lists documents edited or deleted since
  indexing and files never indexed; `ctxvault reindex --stale` brings the index back
  in line.
- **Episodic vaults**: stats report what holds now and the open disputes;
  `ctxvault episodes --values <key>` lists the values a metadata key takes; writes and
  closings accept their own timestamps, so an existing history can be imported with
  its dates.
- Example 07 · Full Memory Topology: three agents, six vaults, all three memory types,
  a year of facts — the dataset behind the live demo.
- Documentation site with a quick start, setup guides for Python, HTTP and MCP, how
  vaults and access control work, and a reference for the CLI, the HTTP API and the
  MCP tools.

### Changed

- **Reindex semantic vaults** to get the new chunking and cosine similarity:
  `ctxvault reindex <vault>`. Until then, an existing vault keeps working with its old
  index and reports only the raw `score`.
- **Query results changed shape**: `ChunkMatch` no longer has `generated_by`,
  `artifact_type` and `topic` fields. The metadata a writing agent attached is now in
  `metadata`, and `similarity` is new. Code that read those fields from the Python
  client or the HTTP API needs updating.
- **Local registries store paths relative to the project.** Existing `config.json`
  files keep working, and new vaults can be committed with the project.

## [0.8.2] - 2026-11-02

### Added

- **Confirm** — `ctxvault confirm <vault> <id>`: the statement was asserted again.
  Nothing is rewritten; the episode gains an attestation, and `confirmed_count` /
  `last_confirmed_at` tell a fact heard once from one heard many times, as of any past
  instant.
- **Dispute** — `ctxvault dispute <vault> <id> <other>`: two open statements cannot
  both hold. Both stay, each flagged with the other in `disputed_with`, so an agent
  can ask instead of assert. The dispute resolves itself when either side is closed;
  `episodes --disputed` lists the open ones.
- **Revise** — `ctxvault revise <vault> <id> <content>`: the same fact, said better.
  Unlike supersede, nothing changes in valid time: the revision inherits attestations,
  entities, salience and open disputes, and the original stays in the history as the
  earlier wording. All three are available over HTTP, MCP and CLI.

### Changed

- **The episodic schema moves to v3** (attestations and disputes tables, `revised_by`
  column). Existing vaults migrate automatically on first open; once migrated they
  cannot be opened by ctxvault ≤ 0.8.1.

### Fixed

- `invalidate` with an impossible `valid_to` is a 400, not a 500.
- MCP optional arguments accept `null` (#37, #38, and the same for the new tools).

## [0.8.1] - 2026-10-12

### Added

- **`list_entities`** returns every entity in a vault with its episode count, reading
  the entity index directly rather than the episodes, so the answer is complete
  whatever the vault has grown to. It honours the same validity rules as the rest of
  the episodic surface: by default only entities still named by statements that hold,
  `valid_at` for a past moment, `include_closed` for the whole history. Available as
  HTTP `GET /ctxvault/episodes/entities`, MCP `list_entities`, CLI
  `ctxvault episodes <vault> --entities` (with `--min-episodes`), and Python
  `EpisodicVault.list_entities()`.

### Changed

- The typed memory diagram in the README now shows all three vault types, where it had
  been left showing two.

## [0.8.0] - 2026-10-08

### Added

- **Episodic vaults**, a third vault type for statements that have a lifetime:
  `ctxvault init <name> --type episodic` stores statements instead of files, backed by
  a single SQLite file inside the vault directory. Every episode is bi-temporal:
  `valid_from` / `valid_to` record when the statement holds in the world,
  `recorded_at` / `invalidated_at` record when the vault believed it, and the two move
  independently.
- **Supersession instead of overwriting**: correcting a statement closes the old
  episode exactly where its successor opens, in one transaction, and links the two.
  Entities and salience carry over from the predecessor unless new ones are given.
  `invalidate` covers the case where a statement ends and nothing replaces it, and
  closing an episode before its own `valid_from` is refused.
- **Retrieval that filters before it ranks**: entity, validity, source, confidence and
  metadata are applied in SQL, so a superseded fact is excluded by a condition rather
  than outranked by a score. Ranking is applied afterwards, by `relevance`, `recency`,
  `salience` or a `composite` blend with configurable weights and half-life.
  `valid_at` reconstructs what was true at a past instant, `known_at` reconstructs
  what the vault had already learned by then, and `history` returns every version of a
  statement, oldest first.
- **Optional vectors, no new dependencies**: an episodic vault created without
  `--embedding-model` never loads an embedding model, falling back to keyword scoring
  for text queries. Vaults that want semantic similarity pin a model at init time
  exactly like semantic vaults do.
- **Reinforcement**: episodes track `recall_count` and `last_recalled_at`, updated
  only when a query explicitly passes `reinforce`, so reading never mutates the store
  by accident.
- **Every interface**: 5 CLI commands (`write-episode`, `episodes`, `episode`,
  `invalidate`, `supersede`), 7 HTTP endpoints under `/episodes`, and 5 MCP tools
  (`write_episode`, `query_episodes`, `supersede_episode`, `invalidate_episode`,
  `episode_history`).
- **Schema versioning from day one**: the SQLite file carries a `schema_version` with
  the migration hook already wired, and a store written by a newer CtxVault is refused
  with a clear error instead of being misread.
- Example 06 · Episodic Memory: one customer account across six months, with facts
  superseded as the account changes and past states reconstructable.

### Fixed

- The test workflow triggered on `develop`, a branch that does not exist in this
  repository, so nothing ran CI on `dev` or on PRs targeting it.
- `vault_router` fell back to `SemanticVault` for unrecognised vault types instead of
  raising, which would silently open an episodic vault as a document store on an older
  version.
- `PUT /reindex` called `index_files` instead of `reindex_files`, leaving stale chunks
  in the index.
- `reindex_file` rebuilt chunks without the metadata the writing agent had attached,
  discarding it silently.
- `AgentMetadata` was closed to `generated_by` and `timestamp`, so custom metadata
  could be filtered on over HTTP but never written through it.
- `n_results` was hardcoded to 5 and not exposed, making over-fetch and re-rank
  impossible from the CLI, the API or the library.
- `mcp>=1.26.0` resolved to mcp 2.x, where `FastMCP` was renamed `MCPServer`, so
  `ctxvault-mcp` failed to import on a fresh install; pinned to `<2` until the server
  is migrated to the new API.

## [0.7.1] - 2026-06-29

### Added

- **Per-vault embedding model selection**: `ctxvault init` accepts
  `--embedding-model <model>` for semantic vaults. The chosen model is stored in the
  vault's `config.json` and used consistently by both `index` and `query`; a process
  touching multiple vaults loads each model exactly once via a per-name cache.
  Omitting the flag preserves the default (`all-MiniLM-L6-v2`), so all existing
  vaults continue to work without any migration. Passing `--embedding-model` on a
  skill vault is rejected immediately with a clear error.

## [0.7.0] - 2026-06-17

### Fixed

- Dropped the stale `vault_config` kwarg in `SemanticVault.reindex_files()`, which was
  forwarded into `reindex_file()` and made reindex operations fail silently on certain
  vault configurations.

## [0.6.4] - 2026-05-27

### Added

- **Indexed document inspection**: `ctxvault docs <vault> --show <doc-id>` displays
  the text reconstructed from stored chunks alongside document metadata: source path,
  file type, chunk count, indexed timestamp, and a SHA-256 `reconstructed_text_hash`.
  A warning is shown whenever a document spans more than one chunk.
- **Indexed document export**: `ctxvault docs <vault> --export <doc-id> --output
  <path>` writes the reconstructed text to a file, for diffing against a potentially
  modified or corrupted source file before re-indexing.
- `GET /docs/{doc_id}/content` returns the same reconstructed text and metadata
  programmatically (404 if the document id is not found, 400 on a skill vault).

## [0.6.3] - 2026-04-13

### Added

- **Retrieval benchmarks**: `benchmarks/retrieval/` with BEIR and CoIR evaluation
  scripts comparing CtxVault's full pipeline against raw ChromaDB and LangChain
  retriever, tested on NFCorpus, SciFact, CoSQA and StackOverflow-QA. Shared
  `benchmarks/utils.py` for dataset loaders, metrics and formatting; existing internal
  benchmarks moved to `benchmarks/internal/`.

### Fixed

- **Query crash on stale chunk IDs**: `vault.query()` could crash with `'NoneType'
  object is not subscriptable` when the Chroma vector index contained entries whose
  backing records no longer existed (e.g. after delete/reindex flows). Unresolvable
  hits are filtered out before results are built, with a warning counting the skipped
  entries.

## [0.6.2] - 2026-04-10

### Fixed

- **MCP handshake timeout**: embedding model warmup moved to a background task, so the
  MCP server becomes available immediately (typically under 1 second) instead of
  blocking until warmup completes. The server now connects reliably to Claude Desktop
  and other MCP clients even when initialization takes 1–2 minutes on first startup.
- Embedding-dependent tools (`query`, `write_doc`, `write_skill`) return a clear
  "still warming up, please retry in 30-60 seconds" message if called before
  initialization completes, instead of hanging or timing out silently.

### Added

- **`warmup_status` tool**: clients can check whether the embedding model has finished
  initializing (`ready` or `warming_up`).

## [0.6.1] - 2026-04-07

### Changed

- **Smart chunking**: the fixed 50-word chunking is replaced by a strategy-based
  system. Markdown files split on headers, preserving hierarchy context; all other
  files use recursive splitting (paragraphs → lines → words). Default chunk size
  increased from 50 to 400 words with 100-word overlap. Benchmarked on BEIR and CoIR
  with consistent improvements and no regressions. The improvement is automatic —
  re-index your vaults to benefit from it.

### Added

- **uv support**: `uv sync` and `uv run` work out of the box for development, with
  `.python-version` and `uv.lock` for reproducible installs. pip continues to work as
  before.
- Benchmark scripts for local A/B comparison, BEIR (NanoBEIR) and CoIR, run from the
  `benchmarks/` directory.

## [0.6.0] - 2026-04-02

### Added

- **Skill vaults**, a second vault type for procedural memory: `ctxvault init
  my-skills --type skill` holds `.md` files with YAML frontmatter defining a name and
  description, followed by markdown instructions. Drop them into the vault, run
  `ctxvault index`, and they are available to any agent. `ctxvault skills <vault>`
  lists all skills; `ctxvault skill <vault> <name>` reads one.
- HTTP endpoints `GET /skills`, `GET /skill` and `POST /skills/write`; MCP tools
  `list_skills`, `read_skill` and `write_skill`.

### Changed

- `ctxvault init` accepts `--type semantic` (default) or `--type skill` to specify the
  vault type at creation.
- `ctxvault vaults` displays the vault type (`[SEMANTIC]` or `[SKILL]`) alongside
  access-control status.

## [0.5.0] - 2026-03-12

### Changed

- **`ctxvault init` is now local-first** (breaking): it creates a local vault in the
  current directory by default instead of a global one, writing `.ctxvault/config.json`
  alongside the vault data so the setup is committable and portable out of the box.
  Replace existing `ctxvault init <name>` calls with `ctxvault init <name> --global`
  for machine-wide vaults stored in `~/.ctxvault`. `--path` now controls where vault
  data is stored, while the `.ctxvault/` config folder always stays in the current
  directory.

### Removed

- `/init` API endpoint — vault initialization is a human-facing operation and belongs
  in the CLI. Existing API integrations for query, write and retrieval are unaffected.

## [0.4.2] - 2026-03-12

### Added

- **Local vaults & project-scoped config**: `init --path .` initializes the vault
  inside a `.ctxvault/` directory at the given path, with its own `config.json` that
  can be committed for reproducible setups. Config lookup walks up the directory tree
  and falls back to `~/.ctxvault/config.json`, so any command finds the local vaults
  without `--path`. Local and global vaults are visible simultaneously (local takes
  precedence on a name clash), and `ctxvault vaults` lists them in two sections, local
  first.

## [0.4.1] - 2026-03-09

### Fixed

- Relative `--path` values are now resolved against the vault root instead of the
  current working directory. Previously, commands like `ctxvault delete my-vault
  --path paper.pdf` would silently return `Deleted: 0`.
- The `BertModel LOAD REPORT` warning and the loading progress bar printed by
  `sentence-transformers` are now fully suppressed; tool output is clean across all
  platforms.

### Added

- `delete` improvements: `--path` is optional (omit it to delete all documents and
  indexes in the vault), and a new `--purge` flag permanently removes the vault, its
  documents and indexes, and deregisters it from the config. `--path` and `--purge`
  are mutually exclusive.

## [0.4.0] - 2026-03-04

### Added

- **Access control**: vaults can be declared restricted, with access granted to
  specific agents via CLI — `ctxvault attach <vault> <agent>`, `ctxvault detach
  <vault> <agent>`, `ctxvault publish <vault>`. Attaching an agent to a public vault
  makes it restricted automatically. Restricted vaults require the
  `X-CtxVault-Agent` header on all API requests; unauthorized requests return 403.
- Example 04 · Composed Topology: a three-tier support system with five vaults,
  showing how vault topologies compose to reflect organizational boundaries.

## [0.3.0] - 2026-02-26

### Added

- **MCP server**: CtxVault now runs as an MCP server alongside the existing CLI and
  API. Any MCP-compatible client can query vaults, write context and list documents
  autonomously — `uv tool install ctxvault`, add `ctxvault-mcp` to your `mcp.json`.

### Fixed

- Multiple vaults in the same session shared the same ChromaDB collection, causing
  cross-vault data contamination.

## [0.2.0] - 2026-02-23

### Added

- **FastAPI server**: CtxVault runs as a local HTTP server, accessible via REST API
  (`uvicorn ctxvault.api.app:app`).
- **Agent write support**: agents write content directly to a vault via `/write` —
  context generated at runtime gets indexed and becomes semantically queryable
  immediately.
- **Multi-vault architecture**: isolated vaults per context, each fully independent —
  separate knowledge domains, separate agents, zero cross-contamination.
- Three end-to-end examples: Personal Research Assistant, Multi-Agent Isolation, and
  Persistent Memory Agent.

## [0.1.0] - 2026-01-26

### Added

- First public release — CLI MVP: `init`, `index` files/folders, semantic `query`,
  `delete`, `reindex`, `list`, local embeddings, and a Chroma persistent store. Core
  and CLI tested with GitHub Actions.

[Unreleased]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.9.1...dev
[0.9.1]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.6.4...v0.7.0
[0.6.4]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Filippo-Venturini/ctxvault/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Filippo-Venturini/ctxvault/releases/tag/v0.1.0
