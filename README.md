# CtxVault

Local semantic search vault for LLMs.

CtxVault lets you index documents locally, generate embeddings, and query them with semantic search.  
Designed as a lightweight RAG backend for agents, scripts, and LLM workflows.

## Why CtxVault

- 100% local (no cloud, no data sharing)
- simple CLI
- works offline
- persistent vector store (Chroma)
- file-based workflow
- agent/API ready (future)

Ideal for:
- personal knowledge bases
- private documents
- local RAG pipelines
- AI agents needing contextual memory

---

## Install

Python 3.10+

```bash
pip install -e .
````

---

## Quickstart

Initialize a vault:

```bash
ctxvault init ./my-vault
```

Index files or folders:

```bash
ctxvault index ./my-vault/docs
```

Query:

```bash
ctxvault query "what is project Orion?"
```

---

## CLI Commands

### init

Initialize a vault directory.

```bash
ctxvault init <path>
```

---

### index

Index a file or directory.

```bash
ctxvault index <path>
```

---

### query

Semantic search inside the vault.

```bash
ctxvault query "<text>"
```

---

### delete

Remove a document from the vault.

```bash
ctxvault delete <path>
```

---

### reindex

Reindex a document after changes.

```bash
ctxvault reindex <path>
```

---

### list

List indexed documents.

```bash
ctxvault list
```

---

## Privacy

All processing happens locally.
No data is sent to external services.

---

## Roadmap

* [x] CLI MVP
* [ ] FastAPI server
* [ ] sync and file watcher
* [ ] multi-vault support

---

## License

MIT
