# 03 · Persistent Memory Agent

An agent that accumulates context across sessions and retrieves it
semantically, days later and with different words.

This example demonstrates the persistent memory Core Principle directly:
a vault used not for document retrieval but as a living memory layer
that the agent writes to autonomously and queries across time.

---

## Scenario

Three sessions simulated across a week. In session one the agent saves
meeting notes, cost targets, and action items. In session two it recalls
them using semantically related language: "financial constraints" finds
"15% cost cut" written three days prior. In session three it synthesizes
patterns across all accumulated sessions.

This is not state restoration. LangGraph checkpointers can replay an
exact conversation, but they cannot semantically search across multiple
sessions from different days. The vault provides that layer.

---

## What this demonstrates

- Agent writing to vault autonomously via the write API
- Semantic recall across sessions with fuzzy queries
- Cross-session synthesis from accumulated memory
- Vault as long-term memory, not just document index

---

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
python app.py
```

---

## What happens

**Session 1: Monday**
The agent saves five interactions from the day into a single markdown
file in the vault. The session ends. Memory persists.

**Session 2: Wednesday**
```
QUERY: What financial constraints did I mention?
→ Finds: "15% cost cut" + "competitor pricing 20% lower"

QUERY: Were there any action items?
→ Finds: "prepare slides by Friday" + "follow up on vendor negotiation"
```
The queries never mention "cost" or "slides": semantic search finds
the relevant content by meaning.

**Session 3: Monday (one week later)**
The agent adds new context, then retrieves broadly across both sessions
and synthesizes the week's themes, decisions, and next steps.

---

## Project structure
```
03-persistent-memory/
├── .ctxvault/
│   ├── config.json
│   └── vaults/
│       └── assistant-memory/
├── app.py
└── requirements.txt
```

No pre-written documents: the agent generates its own memory files
at runtime.

---

### Inspect the memory vault

After running the demo, verify what the agent has written:
```bash
ctxvault docs assistant-memory
```
```
Found 2 documents in 'assistant-memory'

  1. session_2026-02-17_001.md
     .md · 3 chunks

  2. session_2026-02-24_002.md
     .md · 2 chunks
```

The agent generated these files autonomously during the sessions.
They persist on disk: run the demo again and the vault accumulates
further, or query it directly from the CLI at any time.

---

## Next

All three examples use the same vault primitive. **Example 01** shows
it as a document index. **Example 02** shows it as an isolated
per-agent knowledge base. This example shows it as long-term memory.
The infrastructure is the same, the topology changes.