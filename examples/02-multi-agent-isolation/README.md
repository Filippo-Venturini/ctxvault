# LangGraph Multi-Vault Example

Privacy-aware multi-agent system with **isolated knowledge access**.

## Scenario

Two agents with different security clearances:

- **Public Agent** → accesses public research papers only
- **Internal Agent** → accesses confidential company documents only  
- **Router** → intelligently routes queries based on content

This demonstrates **semantic isolation** - the public agent literally cannot access internal docs, even if prompted to do so.

## Why This Matters

Traditional multi-agent systems share a single knowledge base. This creates:
- Privacy risks (agents see everything)
- Context pollution (irrelevant docs in retrieval)
- No access control at semantic layer

**CtxVault solves this** with multi-vault architecture:
- Each agent has its own isolated vault
- Router controls access at query time
- Zero chance of cross-contamination

## Setup

### 1. Install dependencies
```bash
python -m venv .venv-example-02 && source .venv-example-02/bin/activate  # Windows: .venv-example-02\Scripts\activate
pip install -r requirements.txt
```

### 2. Set OpenAI API key
```bash
export OPENAI_API_KEY="your-key-here"
```

### 3. Run
```bash
python app.py
```

## What Happens

The script:
1. Creates two vaults (`public` and `internal`)
2. Indexes sample documents into each vault
3. Runs example queries showing routing logic
4. Public queries → public vault only
5. Internal queries → internal vault only

## Example Output
```
QUERY: What are the key principles of quantum computing?
[ROUTER] Detected public query → routing to Public Agent
[PUBLIC AGENT] Retrieving from public vault...
ANSWER: The key principles are superposition, entanglement...

QUERY: What is Project Atlas and when is it launching?
[ROUTER] Detected internal query → routing to Internal Agent
[INTERNAL AGENT] Retrieving from internal vault...
ANSWER: Project Atlas is our next-generation semantic search platform...
```

## Try Your Own Queries

Modify the `queries` list in `main()` to test different scenarios:

**Public queries** (will use public vault):
- "How do neural networks learn?"
- "What is quantum entanglement?"

**Internal queries** (will use internal vault):
- "What are our revenue projections?"
- "What challenges does Project Atlas face?"

## Architecture Diagram
```
User Query
    ↓
[Router Node]
    ↓
    ├─→ "public" → [Public Agent] → query_vault("public") → Answer
    └─→ "internal" → [Internal Agent] → query_vault("internal") → Answer
```

## Key Takeaway

**CtxVault enables privacy-aware AI agents** without complex access control logic in your code.

Simply:
1. Create separate vaults for different security contexts
2. Route queries to appropriate vault
3. Each agent only sees what it should see

Perfect for:
- Enterprise systems with compliance requirements
- Multi-tenant applications
- Personal + work knowledge separation
- Agent specialization by domain

---

**Total code:** ~200 lines for complete multi-agent system with semantic isolation.

**Want more?** Check out:
- Example 01 (simple RAG) for basic retrieval
- Example 03 (persistent memory) for long-term semantic memory that persists across sessions