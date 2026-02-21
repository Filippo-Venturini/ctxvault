<div align="center">
<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_white_text.svg" width="400" height="100">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_black_text.svg" width="400" height="100">
    <img alt="Logo" src="https://raw.githubusercontent.com/Filippo-Venturini/ctxvault/main/assets/logo_black_text.svg" width="400" height="100">
</picture>

<h3>Semantic knowledge vault for AI agents and RAG pipelines</h3>
<p><i>Local-first semantic memory you control. No cloud, no complexity.</i></p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/ctxvault.svg)](https://pypi.org/project/ctxvault/)
![Python](https://img.shields.io/pypi/pyversions/ctxvault)
![PyPI - Downloads](https://img.shields.io/pypi/dm/ctxvault)

[Installation](#installation) • [Quick Start](#quick-start) • [Examples](#examples) • [Documentation](#documentation) • [API Reference](#api-reference)

</div>

---

## What is CtxVault?

CtxVault is a **local semantic search engine** for LLM applications. Index documents, generate embeddings, and query with semantic search — all running on your machine.

**Built for:**
- **Personal RAG** - private knowledge bases with semantic search
- **Multi-agent systems** - shared or isolated memory layers  
- **Persistent memory** - agent memory that survives across sessions
- **Privacy-first workflows** - your data never leaves your machine

Works as both a CLI tool and API server. Zero cloud dependencies.

---

## Why CtxVault?

**100% Local**  
No API keys, no cloud services, no telemetry. Runs entirely offline with your own compute.

**Multi-Vault Architecture**  
Run isolated vaults for different contexts. Separate personal notes from company docs, or give each agent its own knowledge domain.

**Agent-Ready**  
Built-in FastAPI server for seamless integration with LangChain, LangGraph, and custom agent workflows. Write and query memory programmatically.

**Developer-First**  
Simple CLI for manual work. HTTP API for automation. Works offline. No configuration overhead.

---

## Installation

**Requirements:** Python 3.10+

### From PyPI
```bash
pip install ctxvault
```

### From source
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
# 1. Initialize a vault
ctxvault init my-vault

# 2. Add your documents to the vault folder
# Default location: ~/.ctxvault/vaults/my-vault/
# Drop your .txt, .md, .pdf or .docx files there

# 3. Index documents
ctxvault index my-vault

# 4. Query semantically
ctxvault query my-vault "transformer architecture"

# 5. List indexed documents
ctxvault list my-vault

# 6. List all your vaults
ctxvault vaults
```

### API Usage

Start the server:
```bash
uvicorn ctxvault.api.app:app
```

Then interact programmatically — see the full API workflow in [API Reference](#api-reference) or explore the interactive docs at `http://127.0.0.1:8000/docs`.

---

## Examples

Production-ready examples in [`/examples`](examples/):

**[01-simple-rag](examples/01-simple-rag/README.md)** - Personal research assistant with semantic search over multi-format documents (PDF, MD, TXT, DOCX)

**[02-multi-agent-isolation](examples/02-multi-agent-isolation/README.md)** - Privacy-aware multi-agent system with isolated knowledge vaults per agent

**[03-persistent-memory](examples/03-persistent-memory/README.md)** - Agent with long-term memory that persists and recalls semantically across sessions

Each example includes setup instructions, code, and detailed README.

---

## Documentation

### CLI Commands

All commands require a vault name. Default vault location: `~/.ctxvault/vaults/<name>/`

---

#### `init`
Initialize a new vault.
```bash
ctxvault init <name> [--path <path>]
```

**Arguments:**
- `<name>` - Vault name (required)
- `--path <path>` - Custom vault location (optional, default: `~/.ctxvault/vaults/<name>`)

**Example:**
```bash
ctxvault init my-vault
ctxvault init my-vault --path /data/vaults
```

---

#### `index`
Index documents in vault.
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
Perform semantic search.
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

#### `list`
List all indexed documents in vault.
```bash
ctxvault list <vault>
```

**Arguments:**
- `<vault>` - Vault name (required)

**Example:**
```bash
ctxvault list my-vault
```

---

#### `delete`
Remove document from vault.
```bash
ctxvault delete <vault> --path <path>
```

**Arguments:**
- `<vault>` - Vault name (required)
- `--path <path>` - File path to delete (required)

**Example:**
```bash
ctxvault delete my-vault --path paper.pdf
```

---

#### `reindex`
Re-index documents in vault.
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
List all vaults and their paths.
```bash
ctxvault vaults
```

**Example:**
```bash
ctxvault vaults
```

---

**Vault management:**
- Default location: `~/.ctxvault/vaults/<vault-name>/`
- Vault registry: `~/.ctxvault/config.json` tracks all vault names and their paths
- Custom paths: Use `--path` flag during `init` to create vault at custom location
- All other commands use vault name (path lookup via config.json)

**Multi-vault support:**
```bash
# Work with specific vault
ctxvault research query "topic"

# Default vault location: ~/.ctxvault/vaults/
# Override with --path for custom locations
```

---

### API Reference

**Base URL:** `http://127.0.0.1:8000/ctxvault`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/init` | POST | Initialize vault |
| `/index` | PUT | Index entire vault or specific path |
| `/query` | POST | Semantic search |
| `/write` | POST | Write and index new file |
| `/docs` | GET | List indexed documents |
| `/delete` | DELETE | Remove document from vault |
| `/reindex` | PUT | Re-index entire vault or specific path |
| `/vaults` | GET | List all the initialized vaults |

**Interactive documentation:** Start the server and visit `http://127.0.0.1:8000/docs`

---

## Use Cases

**Personal Knowledge Management**
- Research paper collections
- Study notes and learning progress
- Documentation and how-to guides

**Enterprise Applications**
- Internal knowledge bases
- Team collaboration memory
- Meeting notes with cross-session recall

**AI Agent Infrastructure**
- RAG backends for chatbots
- Multi-agent shared memory
- Persistent agent context across sessions

**Developer Tools**
- Codebase semantic search
- Documentation assistants
- Debug solution tracking

---

## How It Works
```
Documents → Chunking → Embeddings → ChromaDB → Semantic Search
```

1. **Ingestion:** Documents split into chunks (configurable size)
2. **Embedding:** Chunks embedded using sentence-transformers
3. **Storage:** Vectors stored in local ChromaDB
4. **Retrieval:** Queries embedded and matched via cosine similarity
5. **Results:** Top-k most relevant chunks returned

**Supported formats:** `.txt`, `.md`, `.pdf`, `.docx`

**Architecture:** ChromaDB (vector store) + FastAPI (server) + Click (CLI)

---

## CtxVault vs Alternatives

| Feature | CtxVault | Pinecone/Weaviate | LangChain VectorStores | Mem0/Zep |
|---------|----------|-------------------|------------------------|----------|
| **Local-first** | ✓ | ✗ (cloud) | ✓ | ✗ (cloud APIs) |
| **Multi-vault** | ✓ | ✗ | ✗ | Partial |
| **CLI + API** | ✓ | API only | Code only | API only |
| **Zero config** | ✓ | ✗ (setup required) | ✗ (code integration) | ✗ (external service) |
| **Agent write support** | ✓ | ✓ | ✗ | ✓ |
| **Privacy** | 100% local | Cloud | Depends on backend | Cloud |

**When to use CtxVault:**
- You need local-first semantic search
- Multiple isolated knowledge contexts
- Simple setup without external services
- Integration with LangChain/LangGraph workflows

**When to use alternatives:**
- Cloud-native architecture required
- Need advanced features (e.g., hybrid search, reranking)
- Already invested in specific cloud ecosystem

---

## Roadmap

- [x] CLI MVP
- [x] FastAPI server
- [x] Multi-vault support
- [x] Agent write API
- [ ] File watcher / auto-sync
- [ ] Hybrid search (semantic + keyword)

---

## Contributing

Contributions welcome! Please check the [issues](https://github.com/Filippo-Venturini/ctxvault/issues) for open tasks.

**Development setup:**
```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
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

## Acknowledgments

Built with [ChromaDB](https://www.trychroma.com/), [LangChain](https://www.langchain.com/) and [FastAPI](https://fastapi.tiangolo.com/).

---

<div align="center">
<sub>Made with focus on privacy and developer experience</sub>
</div>
