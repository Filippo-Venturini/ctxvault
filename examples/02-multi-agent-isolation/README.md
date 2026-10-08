# 02 · Multi-Agent Isolation

Two agents, two restricted vaults. Isolation enforced at the
infrastructure layer, not through metadata filtering or prompt rules.

This example builds on the single-vault setup of Example 01 and
introduces the core isolation primitive: each agent has an explicit
authorization list, checked server-side on every request.

---

## Scenario

- **research-agent**: authorized to query the research vault only
- **atlas-agent**: authorized to query the Project Atlas vault only
- **router**: classifies each query and dispatches it to the appropriate
  agent (this is application logic, separate from the isolation mechanism)

The router can make mistakes. It does not matter. If an agent attempts
to query a vault it is not authorized for, the server returns 403
regardless of how the request was made. The isolation does not depend
on the correctness of the application code.

---

## What this demonstrates

- Vault topology declared via CLI, enforced server-side
- Agent identity passed per-request via header
- Authorization verified independently of routing logic
- 403 on unauthorized access: structural, not configured

---

## Setup

### 1. Install dependencies
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
```

### 2. Inspect the topology

Before running the application, verify the vault configuration:
```bash
ctxvault vaults
```
```

Found 2 vaults

── local ──────────────────────────
> atlas-vault [RESTRICTED]
  path:    .../vaults/atlas-vault
  allowed agents:  atlas-agent

> research-vault [RESTRICTED]
  path:    .../vaults/research-vault
  allowed agents:  research-agent
```

The access control is already in effect. Neither agent can reach the
other's vault, and this is visible and verifiable independently of the
application code.

### 3. Run
```bash
python app.py
```

---

## Example output
```
QUERY: What are the key principles of quantum computing?
[ROUTER] Detected research query → routing to Research Agent
[RESEARCH AGENT] Retrieving from research vault...
ANSWER: The key principles are superposition, entanglement...

QUERY: What is Project Atlas and when is it launching?
[ROUTER] Detected atlas query → routing to Atlas Agent
[ATLAS AGENT] Retrieving from atlas vault...
ANSWER: Project Atlas is our next-generation platform...
```

---

## The difference from metadata filtering

The conventional approach to multi-agent isolation uses a shared vector
store with metadata filters: each agent queries the same index but
with a filter that restricts which documents it can see. It works until
it doesn't: a filter misconfigured, a schema that grows complex, and
an agent surfaces documents it shouldn't.

Here, each vault is a separate index. There is no shared retrieval path
between agents. research-agent and atlas-agent cannot reach each other's
vault through any query, not because a filter prevents it, but because
the path does not exist. The isolation is structural.

---

## Next

**Example 03** introduces persistent memory across sessions: the same
vault primitive used not for isolation but for long-term agent memory.