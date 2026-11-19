# Changelog

All notable changes to CtxVault are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `OpenAICompatibleModel` accepts a per-call `usage_callback(stage, prompt_tokens, completion_tokens)` and exposes `last_extraction_unparseable` for extraction diagnostics (#78).
- **Reopen a closed episode.** `reopen_episode(...)` makes a closed episodic statement current again without erasing the close: the closure, its reason and the reopen are all kept, so "what held on day X" still answers correctly; an as-of `known_at` instant between a close and its reopen still sees the episode as closed (#48).
- **Event metadata.** `confirm_episode`, `dispute_episodes` and `invalidate_episode` accept optional JSON `metadata`, stored with the event rather than on the episode, and returned by `history()`, `attestations()` and `disputes()` (#51). `query_episodes(..., event_metadata_filters=...)` keeps episodes whose confirm, dispute or close carries every given key/value (#51).
- **Event metadata on reopens, and on the closes produced by `supersede` and `revise`** (#57), so the events of one consolidation run can be queried together; `history()` lists each attestation once after a `revise`, the copies the revision made marked `inherited`, while `event_metadata_filters` still matches them (#57).
- **Python 3.13 support** (#71).
- **Consolidation layer**, an opt-in `ctxvault.consolidation` module not imported by the core: the claim schema (#49), the extraction pipeline `consolidate(vault, turns, model, ...)` (#59), and `OpenAICompatibleModel` for any chat-completions endpoint with the shipped prompts (#61). The client talks to loopback endpoints only unless `allow_remote=True`, since the text of the conversations is sent to it.
- **Consolidation topology as configuration** (#46). `consolidate_session(config, turns, model, ...)` writes facts to the episodic vault a `ConsolidationConfig` names; with `transcripts_vault` set, the session is also written to that semantic vault and every claim carries a chunk reference to the turns it was drawn from, which `sources(episode)` resolves back to text. The presets `facts_only(name)` and `facts_and_transcripts(name)` create the vaults and return the config. Claims have a `turns` field, and `consolidate` accepts `turn_provenance`.
- **`.html`, `.htm` and `.csv` documents in semantic vaults**, alongside `.txt`, `.md`, `.pdf` and `.docx` (#62). HTML is read with the standard library, dropping scripts, styles and markup; each CSV data row is indexed as one line with header names beside values. No new required dependency.
- **Transcripts and chunk references** in the core (#45). `write_session(vault, path, turns)` writes a conversation to a semantic vault as one line per turn, dated from its turns and never from the file, with session dates as filterable metadata, and returns the chunk each turn starts in. `chunk_reference(...)` names a chunk with the hash of its text, and `resolve_chunk(reference, agent=...)` answers exactly one of `holds`, `changed`, `moved`, `missing`, `unreachable` or `refused`; `changed` never carries text.
- **Memory viewer:** an episode's closes and reopens are listed in order, a reopen appears as its own kind on the changes timeline, and event metadata is a collapsed row that expands to the values (#58).

### Changed

- **Consolidation prompts are `en-2`.** Turns are sent to the model numbered, and the extraction prompt asks which turns each claim comes from. The layer's `Turn` is now the core's (`ctxvault.core.transcripts.Turn`), one class instead of two (#46).
- **Episodic vault files migrate on open to schema v4, v5 and v6.** v4 stores closes as intervals (`episode_closures`), v5 adds `metadata` columns to the attestation, dispute and closure tables, and v6 adds `reopen_metadata` on closures and `inherited` on attestations. Once migrated, a vault cannot be opened by earlier releases (#48, #51, #57).
- **An as-of read before a close returns the fields it did not know yet.** A `known_at` instant before an episode was closed now returns `valid_to` and `superseded_by` empty; 0.9.1 returned the later values (#48).
- **As-of event queries honour `known_at`.** `event_metadata_filters` only considers an event recorded at or before that instant (#57).
- **Windows paths.** Registered vault paths are returned absolute with `/` separators, and converted to native separators before opening Explorer (#64).

### Fixed

- Rewriting a document so that it has fewer chunks, through `write_doc` or by editing the file and running `index`, no longer leaves the old document's trailing chunks in the index (#45).
- HTML exports inline `.woff2` fonts as `font/woff2` even when the system MIME table has no entry, so an export keeps its typography (#64).

## [0.9.1] - 2026-11-10

### Added

- `ctxvault mcp` starts the MCP server; MCP clients can run it with `uvx ctxvault mcp` and nothing installed, and `ctxvault-mcp` keeps working.
- CtxVault is listed on the official MCP registry as `io.github.Filippo-Venturini/ctxvault`.
- `reindex --embedding-model` pins an embedding model to an existing episodic vault and embeds what it already holds.

### Changed

- Docs: MCP setup via `uvx`, the `mcp` command in the CLI reference, and a rewritten comparison table in the README.

## [0.9.0] - 2026-11-06

### Added

- **Memory viewer.** `ctxvault ui` shows every registered vault, its type and the agents that can reach it; semantic vaults show their documents and the chunks an agent receives, skill vaults render their procedures, episodic vaults show what holds today, the open disputes and a time cursor. `ctxvault ui --export file.html` writes a self-contained snapshot, and the viewer is served at `/ui` for local requests only.
- **Token-based chunking.** Documents are split in the embedding model's own tokens up to its input limit; markdown splits on headings and each chunk keeps its heading path. New vaults compare by cosine distance, and every hit carries a `similarity` between 0 and 1.
- `ctxvault docs --status` lists documents edited or deleted since indexing, and files never indexed; `ctxvault reindex --stale` brings the index back in line.
- Episodic: stats report what holds now and the open disputes, `ctxvault episodes --values <key>` lists the values a metadata key takes, and writes and closings accept their own timestamps.

## [0.8.2] - 2026-11-02

### Added

- **Confirm**: an episode gains an attestation; `confirmed_count` and `last_confirmed_at` tell a fact heard once from one heard many times, as of any past instant.
- **Dispute**: two open statements cannot both hold; both stay, each flagged in `disputed_with`, and `episodes --disputed` lists the open ones.
- **Revise**: the same fact said better; the revision inherits attestations, entities, salience and open disputes, and the original stays in history as the earlier wording.
- All three are available over HTTP, MCP and the CLI.

### Changed

- The episodic schema moves to v3 (attestations and disputes tables, `revised_by`). Existing vaults migrate automatically on first open and cannot then be opened by earlier releases.

### Fixed

- `invalidate` with an impossible `valid_to` returns 400 instead of 500; MCP optional arguments accept null (#37, #38), thanks to @vishalhabib99.

## [0.8.1] - 2026-10-12

### Added

- `list_entities` returns every entity in an episodic vault with its episode count, instead of leaving the answer to be read off a `query` that silently stops at 200.

## [0.8.0] - 2026-10-08

### Added

- **Episodic vaults**, a third vault type for statements that have a lifetime: `ctxvault init <name> --type episodic`, backed by a single SQLite file inside the vault, answering "what holds right now, and what held back then".

## [0.7.1] - 2026-06-29

### Added

- Per-vault embedding model selection: `ctxvault init my-vault --embedding-model all-mpnet-base-v2`. The choice is stored in the vault's `config.json` and used by both `index` and `query`; omitting it keeps `all-MiniLM-L6-v2`, so existing vaults need no migration.

## [0.7.0] - 2026-06-17

### Fixed

- Dropped the stale `vault_config` kwarg in `SemanticVault.reindex_files()`, which was forwarded into `reindex_file()` and made reindex operations fail silently on certain vault configurations.

## [0.6.4] - 2026-05-27

### Added

- **Indexed document inspection**: `ctxvault docs <vault> --show <doc-id>` displays the text reconstructed from stored chunks alongside document metadata: source path, file type, chunk count, indexed timestamp, and a SHA-256 `reconstructed_text_hash`. A warning is shown whenever a document spans more than one chunk.
- **Indexed document export**: `ctxvault docs <vault> --export <doc-id> --output <path>` writes the reconstructed text to a file, for diffing against a potentially modified or corrupted source file before re-indexing.
- `GET /docs/{doc_id}/content` returns the same reconstructed text and metadata programmatically (404 if the document id is not found, 400 on a skill vault).

## [0.6.3] - 2026-04-13

### Added

- **Retrieval benchmarks**: `benchmarks/retrieval/` with BEIR and CoIR evaluation scripts comparing CtxVault's full pipeline against raw ChromaDB and LangChain retriever, tested on NFCorpus, SciFact, CoSQA and StackOverflow-QA. Shared `benchmarks/utils.py` for dataset loaders, metrics and formatting; existing internal benchmarks moved to `benchmarks/internal/`.

### Fixed

- **Query crash on stale chunk IDs**: `vault.query()` could crash with `'NoneType' object is not subscriptable` when the Chroma vector index contained entries whose backing records no longer existed (e.g. after delete/reindex flows). Unresolvable hits are filtered out before results are built, with a warning counting the skipped entries.

## [0.6.2] - 2026-04-10

### Fixed

- **MCP handshake timeout**: embedding model warmup moved to a background task, so the MCP server becomes available immediately (typically under 1 second) instead of blocking until warmup completes. The server now connects reliably to Claude Desktop and other MCP clients even when initialization takes 1–2 minutes on first startup.
- Embedding-dependent tools (`query`, `write_doc`, `write_skill`) return a clear "still warming up, please retry in 30-60 seconds" message if called before initialization completes, instead of hanging or timing out silently.

### Added

- **`warmup_status` tool**: clients can check whether the embedding model has finished initializing (`ready` or `warming_up`).

## [0.6.1] - 2026-04-07

### Changed

- **Smart chunking**: the fixed 50-word chunking is replaced by a strategy-based system. Markdown files split on headers, preserving hierarchy context; all other files use recursive splitting (paragraphs → lines → words). Default chunk size increased from 50 to 400 words with 100-word overlap. Benchmarked on BEIR and CoIR with consistent improvements and no regressions. The improvement is automatic — re-index your vaults to benefit from it.

### Added

- **uv support**: `uv sync` and `uv run` work out of the box for development, with `.python-version` and `uv.lock` for reproducible installs. pip continues to work as before.
- Benchmark scripts for local A/B comparison, BEIR (NanoBEIR) and CoIR, run from the `benchmarks/` directory.

## [0.6.0] - 2026-04-02

### Added

- **Skill vaults**, a second vault type for procedural memory: `ctxvault init my-skills --type skill` holds `.md` files with YAML frontmatter defining a name and description, followed by markdown instructions. Drop them into the vault, run `ctxvault index`, and they are available to any agent. `ctxvault skills <vault>` lists all skills; `ctxvault skill <vault> <name>` reads one.
- HTTP endpoints `GET /skills`, `GET /skill` and `POST /skills/write`; MCP tools `list_skills`, `read_skill` and `write_skill`.

### Changed

- `ctxvault init` accepts `--type semantic` (default) or `--type skill` to specify the vault type at creation.
- `ctxvault vaults` displays the vault type (`[SEMANTIC]` or `[SKILL]`) alongside access-control status.

## [0.5.0] - 2026-03-12

### Changed

- **`ctxvault init` is now local-first** (breaking): it creates a local vault in the current directory by default instead of a global one, writing `.ctxvault/config.json` alongside the vault data so the setup is committable and portable out of the box. Replace existing `ctxvault init <name>` calls with `ctxvault init <name> --global` for machine-wide vaults stored in `~/.ctxvault`. `--path` now controls where vault data is stored, while the `.ctxvault/` config folder always stays in the current directory.

### Removed

- `/init` API endpoint — vault initialization is a human-facing operation and belongs in the CLI. Existing API integrations for query, write and retrieval are unaffected.

## [0.4.2] - 2026-03-12

### Added

- **Local vaults & project-scoped config**: `init --path .` initializes the vault inside a `.ctxvault/` directory at the given path, with its own `config.json` that can be committed for reproducible setups. Config lookup walks up the directory tree and falls back to `~/.ctxvault/config.json`, so any command finds the local vaults without `--path`. Local and global vaults are visible simultaneously (local takes precedence on a name clash), and `ctxvault vaults` lists them in two sections, local first.

## [0.4.1] - 2026-03-09

### Fixed

- Relative `--path` values are now resolved against the vault root instead of the current working directory. Previously, commands like `ctxvault delete my-vault --path paper.pdf` would silently return `Deleted: 0`.
- The `BertModel LOAD REPORT` warning and the loading progress bar printed by `sentence-transformers` are now fully suppressed; tool output is clean across all platforms.

### Added

- `delete` improvements: `--path` is optional (omit it to delete all documents and indexes in the vault), and a new `--purge` flag permanently removes the vault, its documents and indexes, and deregisters it from the config. `--path` and `--purge` are mutually exclusive.

## [0.4.0] - 2026-03-04

### Added

- **Access control**: vaults can be declared restricted, with access granted to specific agents via CLI — `ctxvault attach <vault> <agent>`, `ctxvault detach <vault> <agent>`, `ctxvault publish <vault>`. Attaching an agent to a public vault makes it restricted automatically. Restricted vaults require the `X-CtxVault-Agent` header on all API requests; unauthorized requests return 403.
- Example 04 · Composed Topology: a three-tier support system with five vaults, showing how vault topologies compose to reflect organizational boundaries.

## [0.3.0] - 2026-02-26

### Added

- **MCP server**: CtxVault now runs as an MCP server alongside the existing CLI and API. Any MCP-compatible client can query vaults, write context and list documents autonomously — `uv tool install ctxvault`, add `ctxvault-mcp` to your `mcp.json`.

### Fixed

- Multiple vaults in the same session shared the same ChromaDB collection, causing cross-vault data contamination.

## [0.2.0] - 2026-02-23

### Added

- **FastAPI server**: CtxVault runs as a local HTTP server, accessible via REST API (`uvicorn ctxvault.api.app:app`).
- **Agent write support**: agents write content directly to a vault via `/write` — context generated at runtime gets indexed and becomes semantically queryable immediately.
- **Multi-vault architecture**: isolated vaults per context, each fully independent — separate knowledge domains, separate agents, zero cross-contamination.
- Three end-to-end examples: Personal Research Assistant, Multi-Agent Isolation, and Persistent Memory Agent.

## [0.1.0] - 2026-01-26

### Added

- First public release — CLI MVP: `init`, `index` files/folders, semantic `query`, `delete`, `reindex`, `list`, local embeddings, and a Chroma persistent store. Core and CLI tested with GitHub Actions.

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
