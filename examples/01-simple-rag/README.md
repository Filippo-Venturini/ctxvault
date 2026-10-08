# 01 · Personal Research Assistant

The simplest CtxVault setup: one vault, one agent, local semantic search
over a document collection.

This example is the entry point: no multi-agent topology, no persistent
memory across sessions. Just a vault indexed over a set of documents and
a LangChain RAG pipeline querying it semantically.

---

## Scenario

A local collection of research documents (PDFs, markdown notes, plain
text articles) indexed into a single vault and queried in natural
language. Answers are grounded in the retrieved content, with citations
back to the source documents.

---

## What this demonstrates

- Initializing a vault and indexing a multi-format document collection
- Semantic retrieval as a LangChain retriever
- Grounded answer generation with source attribution
- Full local execution, no cloud dependencies

---

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
python app.py
```

> Any LLM works: replace `ChatOpenAI` with `Ollama` or any
> LangChain-compatible provider.

---

## Project structure
```
01-simple-rag/
├── .ctxvault/                        # Pinned vault config (commit this)
│   ├── config.json
│   └── vaults/
│       └── personal-vault/
│           ├── rag_survey_paper.pdf
│           ├── personal_notes.md
│           ├── blog_article.txt
│           └── rag_comparison.txt
├── app.py                            # RAG pipeline (~100 lines)
└── requirements.txt
```

---

## Example output
```
QUERY: What are the main benefits of using RAG over fine-tuning?

Retrieved from:
  - rag_comparison.txt
  - personal_notes.md

ANSWER:
RAG avoids retraining entirely: knowledge updates require only adding
documents to the vault. Retrieved content provides direct citations,
and the data never leaves your infrastructure.
```

---

## Next

**Example 02** introduces multiple agents with isolated vaults and access
control: the same vault primitive, composed into a multi-agent topology.