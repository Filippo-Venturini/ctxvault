<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo_white_final.svg" width="200" height="200">
  
  <source media="(prefers-color-scheme: light)" srcset="logo_black.svg" width="200" height="200">
  
  <img alt="Logo" src="logo_white_final.svg">
</picture>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/ctxvault.svg)](https://pypi.org/project/ctxvault/)
![Python](https://img.shields.io/pypi/pyversions/ctxvault)
![PyPI - Downloads](https://img.shields.io/pypi/dm/ctxvault)

</div>

# CtxVault

**Local semantic search vault for LLMs.**

CtxVault lets you index documents locally, generate embeddings, and query them with semantic search.
It acts as a lightweight **RAG backend** for agents, scripts, and APIs.

Designed to be:

* simple
* local-first
* plug & play
* automation friendly

---

## Why CtxVault

* 100% local (no cloud, no telemetry)
* simple CLI
* works offline
* persistent vector store (Chroma)
* file-based workflow (drag & drop files)
* usable as both CLI tool and API server
* ideal as a RAG memory layer for agents

### Ideal for

* personal knowledge bases
* private/company documents
* local RAG pipelines
* AI agents memory
* developer tools & automation scripts

---

# Installation

Python **3.10+**

### From PyPI (recommended)

```bash
pip install ctxvault
```

### From source (dev mode)

```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
pip install -e .
```

---

# Quickstart (CLI)

Initialize a vault:

```bash
ctxvault init ./my-vault
```

Add documents:

```bash
ctxvault index ./my-vault/docs
```

Query:

```bash
ctxvault query "what is project Orion?"
```

List indexed documents:

```bash
ctxvault list
```

---

# CLI Commands

### init

Initialize a vault directory.

```bash
ctxvault init <path>
```

---

### index

Index a file or directory recursively.

```bash
ctxvault index <path>
```

---

### query

Semantic search.

```bash
ctxvault query "<text>"
```

Returns the most relevant chunks.

---

### delete

Remove a document from the vault.

```bash
ctxvault delete <path>
```

---

### reindex

Re-index a modified file.

```bash
ctxvault reindex <path>
```

---

### list

Show all indexed documents with metadata.

```bash
ctxvault list
```

---

# API Server (FastAPI)

CtxVault can also run as an HTTP service for agents or external tools.

## Start the server

From your environment:

```bash
uvicorn ctxvault.api.main:app --reload
```

Server will start at:

```
http://127.0.0.1:8000
```

---

## Interactive docs (recommended)

FastAPI automatically provides Swagger UI:

```
http://127.0.0.1:8000/docs
```

Use this to explore and test endpoints interactively.

This is preferred over manually documenting every request.

---

## Available endpoints

Base path: `/ctxvault`

| Method | Endpoint   | Description       |
| ------ | ---------- | ----------------- |
| POST   | `/init`    | initialize vault  |
| PUT    | `/index`   | index file/folder |
| POST   | `/query`   | semantic search   |
| GET    | `/list`    | list indexed docs |
| DELETE | `/delete`  | delete file       |
| PUT    | `/reindex` | reindex file      |
| POST   | `/write`   | write & index file|      |

---

## Example (curl)

### Query

```bash
curl -X POST http://127.0.0.1:8000/ctxvault/query \
  -H "Content-Type: application/json" \
  -d '{"query":"what is project Orion?"}'
```

---

# CLI vs API – when to use what?

### Use CLI when

* working locally
* indexing manually
* debugging
* scripting
* personal usage

### Use API when

* integrating with agents
* LangGraph / LangChain workflows
* backend services
* automation pipelines
* multi-process access

Both share the same core engine.

---

# Examples

Real integrations are available in:

```
examples/
```

Planned:

* agent integration
* LangGraph workflow
* notebook demo
* API usage scripts

---

# Privacy

All processing happens locally.

* no cloud
* no telemetry
* no external calls
* your documents never leave your machine

---

# Roadmap

* [x] CLI MVP
* [x] FastAPI server
* [ ] sync / file watcher
* [ ] multi-vault support

---

# License

MIT

---
