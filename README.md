<div align="center">
<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_white_text.svg" width="400" height="100">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_black_text.svg" width="400" height="100">
    <img alt="Logo" src="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_black_text.svg" width="400" height="100">
</picture>

<h3>Local memory infrastructure for AI agents</h3>
<p><i>Isolated vaults. Typed memory. Agent-autonomous. Human-observable.</i></p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/ctxvault.svg)](https://pypi.org/project/ctxvault/)
![Python](https://img.shields.io/pypi/pyversions/ctxvault)
![PyPI - Downloads](https://img.shields.io/pypi/dm/ctxvault)

[Installation](#installation) • [Quick Start](#quick-start) • [Examples](#examples) • [Documentation](#documentation) • [API Reference](#api-reference)

</div>

---

## What is CtxVault?

Most agent frameworks treat memory as an afterthought — a shared vector store where isolation depends on configuration staying correct and everything, facts and procedures alike, gets embedded into the same undifferentiated index. The agent cannot tell what it knows from how it should act.

CtxVault is built around a different primitive. Memory is organized into **vaults** — self-contained, directory-backed units with explicit types. A semantic vault holds documents and a vector index, queryable by meaning: the agent's **semantic memory**. A skill vault holds skills that shape how the agent behaves: its **procedural memory**. Isolation is structural, the topology is defined explicitly — one vault per agent, a shared knowledge base, private skills for a specific role, or any combination — with access control that determines exactly which agents can reach which vault.

The result is a memory layer that behaves like real infrastructure: typed, composable, observable, persistent and entirely local.

<div align="center">
  <img 
    src="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/ctxvault_schema.svg"
    alt="CtxVault architecture schema"
    width="1200"
  >
</div>

---

## Core Principles

### Typed memory: semantic and procedural

Classical cognitive architectures — from [ACT-R (Anderson et al., 2004)](https://en.wikipedia.org/wiki/ACT-R) to [CoALA (Sumers et al., 2024)](https://arxiv.org/abs/2309.02427) — separate an agent's long-term memory into distinct modules: semantic memory for world knowledge, and procedural memory for skills and behavioral rules. Most agent frameworks ignore this distinction and store everything in a single vector index.

In CtxVault, the separation is structural. A **semantic vault** holds documents, indexes them into a vector store, and supports retrieval by meaning — it is the agent's knowledge base. A **skill vault** holds natural-language procedures with explicit names and descriptions — it is the agent's behavioral repertoire. The agent queries one to know *what*, and reads the other to know *how*.

Both vault types share the same infrastructure primitives: public or restricted, local or global, composable in any topology. The difference is what they store and how the agent uses it.

<div align="center">
  <img 
    src="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/typed_memory_schema.svg"
    alt="Typed memory: an agent queries a semantic vault for knowledge and reads a skill vault for behavioral instructions, combining both into output"
    width="1200"
  >
</div>

### Structural isolation and access control

Isolation enforced through prompt logic or metadata schemas is fragile — it grows harder to reason about as systems scale, and fails silently when it breaks.

In CtxVault, each vault is an independent index. Agents have no shared retrieval path unless one is explicitly defined. Vaults can be declared restricted, with access granted to specific agents directly through the CLI. The boundary is part of the architecture, not a rule written in a config file that someone might later get wrong.

```
Found 3 vaults

> agent-a-vault [RESTRICTED]
  path:    ~/.ctxvault/vaults/agent-a-vault
  agents:  agent-a

> shared-vault [PUBLIC]
  path:    ~/.ctxvault/vaults/shared-vault

> agent-c-vault [RESTRICTED]
  path:    ~/.ctxvault/vaults/agent-c-vault
  agents:  agent-c
```

---

### Persistent memory across sessions

Agents lose all context when a session ends. CtxVault gives them a knowledge base that persists across conversations, queryable by meaning rather than exact match. Context written in one session is retrievable days later using semantically related language.

<div align="center">
  <img 
    src="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/ctxvault-demo.gif" 
    alt="Agent saves context in session one — new chat, new session, memory intact"
    width="1200"
  >
  <p><sub>Persistent memory across sessions — shown with Claude Desktop, works with any MCP-compatible client.</sub></p>
</div>

---

### Observable and human-controllable

When agents write to memory autonomously, visibility into what they write is not a debugging feature — it is the foundation of a trustworthy system.

Every vault is a plain directory on your machine. You can read it, edit it, and query it directly through the CLI at any point, independent of what any agent is doing. You also contribute to the same memory layer directly: drop documents into a vault, index with one command, and the agent queries that knowledge alongside what it has written on its own.

```bash
# Inspect what your agent has written in the vault
ctxvault list my-vault

# Query its knowledge base directly  
ctxvault query my-vault "what decisions were made last week?"

# Add your own documents and index them
ctxvault index my-vault
```

---

### Local-first

No cloud, no telemetry, no external services. Vaults are plain directories on your machine, the storage layer is entirely local. What you connect to that knowledge base is your choice.

---

## Integration Modes

CtxVault exposes the same vault layer through three interfaces. Use whichever fits your context, or combine them freely.

**CLI** — Human-facing. Monitor vaults, inspect agent-written content, add your own documents, query knowledge bases directly.

**HTTP API** — Programmatic integration. Connect LangChain, LangGraph, or any custom pipeline to vaults via REST. Full CRUD, semantic search, and agent write support.

**MCP server** — For autonomous agents. Give any MCP-compatible client direct vault access with no integration code required. The agent handles `list_vaults`, `query`, `write`, and `list_docs` on its own.

---

## CtxVault vs Alternatives

| | CtxVault | ChromaDB + custom | LangChain Memory | Mem0 |
|--|----------|-------------------|------------------|------|
| Vault isolation | ✓ | ✗ — you build it | ✗ | ✗ |
| Access control | ✓ | ✗ — you build it | ✗ | ✗ |
| Typed memory (semantic + procedural) | ✓ | ✗ | ✗ | ✗ |
| Agent-written memory | ✓ | ✗ — you build it | Partial | Partial |
| Human CLI observability | ✓ | ✗ | ✗ | ✗ |
| Local-first | ✓ | ✓ | ✓ | ✗ (cloud) |
| MCP server | ✓ | ✗ — you build it | ✗ | ✗ |

---

## Examples

Three scenarios — each with full code and setup instructions.

| | Example | What it shows |
|--|---------|---------------|
| 🟢 | [**Personal Research Assistant**](examples/01-simple-rag/) | Single vault, single agent. Semantic RAG over PDF, MD, TXT, DOCX with source attribution. ~100 lines.  |
| 🔴 | [**Multi-Agent Isolation**](examples/02-multi-agent-isolation/) | Two agents, two vaults. Each agent has no retrieval path to the other's vault — isolation enforced at the infrastructure layer, not through metadata filtering. ~200 lines.|
| 🔵 | [**Persistent Memory Agent**](examples/03-persistent-memory/) | An agent that recalls context across sessions using semantic queries. "financial constraints" retrieves "cut cloud costs by 15%" written three days prior. |
| 🟡 | [**Composed Topology**](examples/04-composed-topology/) | Three agents, five vaults — private, shared between a subset, and public. A tiered support system where access boundaries reflect organizational boundaries. |
| 🟣 | [**Procedural Memory Agent**](examples/05-procedural-memory-agent/) | One agent, two vault types — semantic and skill — integrated via MCP. Retrieves knowledge for *what* to say and skills for *how* to say it. | |

---

## Installation

**Requirements:** Python 3.10+

### From PyPI
```bash
pip install ctxvault
```

### From source (uv — recommended)
```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
uv sync            # creates .venv and installs all dependencies
uv run ctxvault    # run the CLI
```

### From source (pip)
```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

---

## Quick Start

Both CLI and API follow the same workflow: create a vault → add documents → index → query. Choose CLI for manual use, API for programmatic integration.

### CLI Usage

```bash
# 1. Initialize a vault (run from your project root)
ctxvault init my-vault

# 2. Add your documents to the vault folder
# Default location: .ctxvault/vaults/my-vault/
# Drop your .txt, .md, .pdf or .docx files there

# 3. Index documents
ctxvault index my-vault

# 4. Query semantically
ctxvault query my-vault "transformer architecture"

# 5. List indexed documents
ctxvault docs my-vault

# 6. List all your vaults
ctxvault vaults

# For a machine-wide vault available everywhere
ctxvault init my-vault --global
```

### Agent Integration

Give your agent **persistent semantic memory** in minutes. Start the server:
```bash
uvicorn ctxvault.api.app:app
```
Then write, store, and recall context across sessions:
```python
import requests
from langchain_openai import ChatOpenAI

API = "http://127.0.0.1:8000/ctxvault"

# 1. Create a vault
requests.post(f"{API}/init", json={"vault_name": "agent-memory"})

# 2. Agent writes what it learns to memory
requests.post(f"{API}/write", json={
    "vault_name": "agent-memory",
    "filename": "session_monday.md",
    "content": "Discussed Q2 budget: need to cut cloud costs by 15%. "
               "Competitor pricing is 20% lower than ours."
})

# 3. Days later — query with completely different words
results = requests.post(f"{API}/query", json={
    "vault_name": "agent-memory",
    "query": "financial constraints from last week",  # ← never mentioned in the doc
    "top_k": 3
}).json()["results"]

# 4. Ground your LLM in retrieved memory
context = "\n".join(r["text"] for r in results)
answer = ChatOpenAI().invoke(f"Context:\n{context}\n\nQ: What are our cost targets?")
print(answer.content)
# → "You mentioned a 15% cloud cost reduction target, with competitor pricing 20% lower."
```
> **Any LLM works** — swap `ChatOpenAI` for Ollama, Anthropic, or any provider.
> Ready to go further? See the [examples](#examples) for full RAG pipelines and multi-agent architectures — or browse the [API Reference](#api-reference) and the interactive docs at `http://127.0.0.1:8000/docs`.

---

### MCP Integration (Claude Desktop, Cursor, and any MCP-compatible client)

Give any MCP-compatible AI client direct access to your vaults — no code required. The agent handles `list_vaults`, `query`, `write`, and `list_docs` autonomously.

**Install:**
```bash
uv tool install ctxvault
```

**Add to your `mcp.json`** (Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` — macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "ctxvault": {
      "command": "ctxvault-mcp"
    }
  }
}
```

Restart your client. The agent can now query your existing vaults, write new context, and list available knowledge — all locally, all under your control.

**Restricted vaults:** if you are integrating programmatically and need to access a restricted vault, pass the agent name at startup:
```json
{
  "mcpServers": {
    "ctxvault": {
      "command": "ctxvault-mcp",
      "args": ["--agent", "my-agent"]
    }
  }
}
```

The `--agent` argument is optional and only required for restricted vaults.

---

## Documentation

### CLI Commands

All commands require a vault name. Default vault location: `~/.ctxvault/vaults/<name>/`

---

#### `init`
Initialize a new vault. Vaults are public by default — any agent can access them.
Pass `--restricted` to create a restricted vault, accessible only to explicitly
attached agents. Pass `--type skill` to create a skill vault for procedural memory
instead of the default semantic vault.

```bash
ctxvault init <name> [--type <type>] [--path <path>] [--global] [--restricted] [--embedding-model <model>]
```

**Arguments:**
- `<name>` - Vault name (required)
- `--type <type>` - Vault type: `semantic` or `skill` (optional, default: `semantic`)
- `--path <path>` - Custom vault location (optional, default: `~/.ctxvault/vaults/<name>`)
- `--global` - Create a global vault in ~/.ctxvault, available from anywhere on the machine
- `--restricted` - Create vault as restricted (optional, default: public)
- `--embedding-model <model>` - sentence-transformers model for this semantic vault (optional, default: `all-MiniLM-L6-v2`). The model is pinned at init time and used for all indexing and querying on the vault. Semantic vaults only.


**Example:**
```bash
ctxvault init my-vault                          # semantic vault (default)
ctxvault init my-vault --type skill             # skill vault for procedural memory
ctxvault init my-vault --global --type skill    # global skill vault
ctxvault init my-vault --restricted
ctxvault init my-vault --embedding-model all-mpnet-base-v2   # custom embedding model
```

---

#### `attach`
Attach an agent to a vault, granting it access. If the vault is public, attaching
an agent automatically makes it restricted — only explicitly attached agents will
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

#### `detach`
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

#### `publish`
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

#### `index`

Index a vault. On a **semantic** vault, this parses documents, generates embeddings, and stores them in the vector index. On a **skill** vault, this scans all .md files, reads their frontmatter, and rebuilds the skill index.

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

#### `query`
Perform semantic search on a **semantic** vault.
```bash
ctxvault query <vault> <text>
```

**Arguments:**
- `<vault>` - Vault name (required)
- `<text>` - Search query (required)

**Example:**
```bash
ctxvault query my-vault "attention mechanisms"
```

---

#### `docs`
List all indexed documents in a **semantic** vault.
```bash
ctxvault docs <vault>
```

**Arguments:**
- `<vault>` - Vault name (required)

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

#### `skills`

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

#### `skill`

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

#### `delete`
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

#### `reindex`
Re-index documents in a **semantic** vault.
```bash
ctxvault reindex <vault> [--path <path>]
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--path <path>` - Specific file or directory to re-index (optional, default: entire vault)

**Example:**
```bash
ctxvault reindex my-vault
ctxvault reindex my-vault --path docs/
```

---

#### `vaults`
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
```

---

**Vault management:**
- By default, `ctxvault init` creates a local vault pinned to the current directory —
  similar to how `git init` works. A `.ctxvault/` folder is created in the current
  directory containing `config.json` and the vault data. Commit `config.json` to make
  the setup portable and reproducible across machines.
- Use `--path` to store vault data in a custom location. The `.ctxvault/` config folder
  always stays in the current directory regardless of `--path`.
- Use `--global` for machine-wide vaults stored in `~/.ctxvault`, accessible from
  anywhere without being tied to a project.
- Config lookup: CtxVault searches for a local config from the current directory upward,
  then falls back to `~/.ctxvault`. This means you can run any command from anywhere
  inside a project and it will find your local vaults automatically.
- Global vaults are always visible alongside local ones. If a local and global vault
  share the same name, the local one takes precedence.

**Access control:**
- Vaults are public by default — any agent can access them
- `init --restricted` or `attach` make a vault restricted
- Once restricted, only explicitly attached agents can access it
- `publish` reverts a restricted vault to public
- Access is enforced server-side on every request — not in application code

**Vault types:**
- CtxVault supports two vault types, reflecting the distinction between semantic and procedural memory
- A **semantic vault** (`--type semantic`, default) stores documents and a vector index for retrieval by meaning
- A **skill vault** (`--type skill`) stores natural-language procedures that shape agent behavior
- Both types support the same access control and topology primitives

| Command   | Semantic vault | Skill vault |
|-----------|----------------|-------------|
| `init`    | ✓              | ✓           |
| `index`   | ✓              | ✓           |
| `query`   | ✓              | ✗           |
| `docs`    | ✓              | ✗           |
| `skills`  | ✗              | ✓           |
| `skill`   | ✗              | ✓           |
| `reindex` | ✓              | ✗           |
| `delete`  | ✓              | ✗           |
| `vaults`  | ✓              | ✓           |
| `attach`  | ✓              | ✓           |
| `detach`  | ✓              | ✓           |
| `publish` | ✓              | ✓           |

Skills are `.md` files with YAML frontmatter defining the skill's name and description, followed by the instructions in markdown. You can create them manually or let an agent write them via the API or MCP server.

```markdown
---
name: Weekly Engineering Update
description: How to write the weekly engineering status update for stakeholders
---

You are writing the weekly engineering update...

## Required structure
...

## Hard rules
- Never exceed 250 words.
- Never start with a greeting.
```

Drop the file into a skill vault and run `ctxvault index <vault>` — the skill is immediately available to any agent that queries the vault.

---

---

### API Reference

**Base URL:** `http://127.0.0.1:8000/ctxvault`

**Semantic vault endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Semantic search on a semantic vault |
| `/docs` | GET | List indexed documents in a semantic vault |
| `/docs/write` | POST | Write and index a new document |
| `/delete` | DELETE | Remove document from a semantic vault |
| `/reindex` | PUT | Re-index documents in a semantic vault |

**Skill vault endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | List available skills in a skill vault |
| `/skill` | GET | Read a skill's instructions |
| `/skills/write` | POST | Write a new skill to a skill vault |

**Shared endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | PUT | Index entire vault or specific path |
| `/vaults` | GET | List all initialized vaults |

**Agent authorization:**

Requests to restricted vaults require the `X-CtxVault-Agent` header. The value must match an agent name attached to that vault via `ctxvault attach`. Requests without the header, or with an unrecognized agent name, return `403`.
```http
X-CtxVault-Agent: my-agent
```
```python
requests.post("http://127.0.0.1:8000/ctxvault/query",
    headers={"X-CtxVault-Agent": "my-agent"},
    json={"vault_name": "my-vault", "query": "attention mechanisms", "top_k": 3}
)
```

Requests to public vaults do not require the header. `/index` and `/vaults` never require it.

**Interactive documentation:** Start the server and visit `http://127.0.0.1:8000/docs`

---

## Roadmap

- [x] CLI MVP
- [x] FastAPI server
- [x] Multi-vault support
- [x] Agent write API
- [x] MCP server support
- [x] Access control
- [x] Typed memory (semantic + procedural vaults)
- [ ] Episodic memory (session logs, interaction history)
- [ ] Graph-backed semantic memory
- [ ] File watcher / auto-sync
- [ ] Context pruning

---

## Contributing

Contributions welcome! Please check the [issues](https://github.com/Filippo-Venturini/ctxvault/issues) for open tasks.

**Development setup:**
```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault

# With uv (recommended)
uv sync --extra dev
uv run pytest

# With pip
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

---

## Citation

If you use CtxVault in your research or project, please cite:
```bibtex
@software{ctxvault2026,
  author = {Filippo Venturini},
  title = {CtxVault: Local Semantic Knowledge Vault for AI Agents},
  year = {2026},
  url = {https://github.com/Filippo-Venturini/ctxvault}
}
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Security

[![MseeP.ai Security Assessment](https://mseep.net/pr/filippo-venturini-ctxvault-badge.png)](https://mseep.ai/app/filippo-venturini-ctxvault)
[![Verified on MseeP](https://mseep.ai/badge.svg)](https://mseep.ai/app/2f4c1ef5-2f5d-4b22-af46-259206879fc0)

---

## Acknowledgments

Built with [ChromaDB](https://www.trychroma.com/), [LangChain](https://www.langchain.com/) and [FastAPI](https://fastapi.tiangolo.com/).

---

<div align="center">
<sub>Made by <a href="https://github.com/Filippo-Venturini">Filippo Venturini</a> · <a href="https://github.com/Filippo-Venturini/ctxvault/issues">Report an issue</a> · ⭐ Star if useful</sub>
</div>
