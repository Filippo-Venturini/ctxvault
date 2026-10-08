# 04 · Composed Topology

Five vaults, three agents, one system. Each agent has a different
profile of access: private knowledge, shared technical context, and
a public base accessible to all.

This example builds on the isolation primitive of Example 02 and shows
how vault topologies compose: not just isolated silos, but a structured
knowledge graph where access boundaries reflect real organizational
boundaries.

---

## Scenario

A three-tier customer support system. Each tier has access to exactly
the knowledge it needs, no more.

- **L1 agent**: handles standard requests. Accesses public documentation
  and its own procedural vault. No visibility into technical internals.
- **L2 agent**: handles technical escalations. Accesses public docs,
  its own technical procedures, and a shared vault with known issues and
  internal tooling, shared with L3.
- **L3 agent**: handles engineering incidents. Accesses the shared
  technical vault and its own engineering runbooks with architecture
  notes and recovery procedures.

When L1 cannot resolve a ticket, it escalates to L2. When L2 cannot
resolve it, it escalates to L3. Each tier accumulates the context
retrieved by the previous one.

---

## Vault topology

```
public-vault   [PUBLIC]      →  l1-agent, l2-agent, l3-agent
l1-vault       [RESTRICTED]  →  l1-agent
l2-vault       [RESTRICTED]  →  l2-agent
l3-vault       [RESTRICTED]  →  l3-agent
tech-vault     [RESTRICTED]  →  l2-agent, l3-agent
```

L1 and L3 have no shared retrieval path. L1 cannot reach technical
internals. L3 cannot reach L2's procedures. The boundaries are
structural, not enforced by routing logic or prompt rules.

---

## Setup

### 1. Install dependencies
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
```

### 2. Inspect the topology
```bash
ctxvault vaults
```

```
Found 5 vaults

> public-vault [PUBLIC]
  path:    .../vaults/public-vault

> l1-vault [RESTRICTED]
  path:    .../vaults/l1-vault
  agents:  l1-agent

> l2-vault [RESTRICTED]
  path:    .../vaults/l2-vault
  agents:  l2-agent

> l3-vault [RESTRICTED]
  path:    .../vaults/l3-vault
  agents:  l3-agent

> tech-vault [RESTRICTED]
  path:    .../vaults/tech-vault
  agents:  l2-agent, l3-agent
```

### 3. Run
```bash
python app.py
```

---

## What happens

Three tickets are routed through the system in sequence, each requiring
a different tier to resolve.

**Ticket 1**: password reset, resolved at L1. Public FAQ and L1
procedures are sufficient. No escalation.

**Ticket 2**: webhook timeout on large payloads, escalated to L2.
L1 cannot diagnose integration issues. L2 finds the known issue in
tech-vault and provides the workaround.

**Ticket 3**: data corruption in production, escalated to L3. L2
identifies it as an engineering incident and escalates. L3 retrieves
the recovery procedure from its runbooks and the incident context
from tech-vault.

---

## Project structure

```
04-composed-topology/
├── app.py
├── requirements.txt
├── .ctxvault/
    ├── config.json
    └── vaults/
        ├── public-vault/
        │   ├── faq.md
        │   └── product-docs.md
        ├── l1-vault/
        │   └── l1-procedures.md
        ├── l2-vault/
        │   └── l2-procedures.md
        ├── l3-vault/
        │   └── l3-runbooks.md
        └── tech-vault/
            └── known-issues.md
```