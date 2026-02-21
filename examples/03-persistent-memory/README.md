# Persistent Memory Agent

**Agent with long-term memory that persists across sessions using semantic recall.**

## Scenario

You have a personal assistant that helps throughout your week. Unlike traditional chatbots that forget everything when you close them, this assistant **remembers**.

**Monday:** You share meeting notes, tasks, thoughts
**Wednesday:** You ask "What did I say about competitors?" → Assistant recalls semantically
**Next Monday:** You ask "Summarize my week" → Assistant synthesizes patterns across all sessions

This is **temporal semantic memory** - not possible with conversation state alone.

---

## What This Demonstrates

**Core capability:** CtxVault as persistent memory layer with cross-session intelligence

- **Accumulation:** Agent saves context from multiple interactions
- **Semantic recall:** Fuzzy queries find relevant past context (not keyword matching)
- **Temporal synthesis:** Cross-session pattern recognition and intelligence
- **True persistence:** Memory survives across days/weeks, not just within a single run

**Real use case:** Personal assistants, research companions, team collaboration tools.

---

## Quick Start

### 1. Install dependencies
```bash
python -m venv .venv-example-03 && source .venv-example-03/bin/activate  # Windows: .venv-example-03\Scripts\activate
pip install -r requirements.txt
```

### 2. Set OpenAI API key
```bash
export OPENAI_API_KEY=your_key
```

### 3. Run
```bash
python app.py
```

The demo simulates 3 sessions over a week, showing how the assistant builds and uses persistent memory.

---

## What to Watch For

### Session 1 (Day 1)
Assistant accumulates **5 interactions** throughout the day:
- Meeting notes
- Cost reduction targets
- Competitor analysis
- Action items

All saved to vault as temporal memory.

---

### Session 2 (Day 3)
Notice how **semantic queries** find relevant context:
```
Query: "What financial constraints did I mention?"
→ Finds: "15% cost cut" + "competitor pricing 20% lower"

Query: "Did I discuss anything about competitors?"
→ Finds: competitor pricing analysis

Query: "Were there any action items?"
→ Finds: "prepare slides by Friday" + "follow up on vendor negotiation"
```

**This is not keyword matching** - it's true semantic understanding.
"Financial constraints" finds "cost cut" and "pricing" because they're semantically related.

---

### Session 3 (Day 7)
**Cross-session synthesis**:
```
User: "Summarize the key themes from my week"

Agent retrieves from ALL sessions and synthesizes:
  • 3 main themes identified (cost optimization, competitive analysis, vendor management)
  • Key decisions tracked
  • Next steps prioritized
```

**This cross-session intelligence is impossible with state alone.**

LangGraph state can restore exact conversation, but it **cannot semantically search and synthesize across multiple sessions from days ago.**

---

## Example Output
```
SESSION 1 - Monday, February 17
[09:30] Meeting with Sarah about Q2 budget review...
[11:15] Need to cut cloud costs by 15%...
[14:45] Competitors pricing 20% lower...
Saved 5 interactions → session_2026-02-17_001.md

SESSION 2 - Wednesday, February 19
[QUERY] What financial constraints did I mention?
    Found in: session_2026-02-17_001.md
[ASSISTANT] You mentioned 15% cost cut on cloud infrastructure
             and competitor pricing 20% lower...

SESSION 3 - Monday, February 24
[QUERY] Summarize key themes from my week
  Retrieved 5 pieces from 2 sessions
  Weekly Synthesis:
    1. Cost Optimization - 15% reduction target, 18% achieved
    2. Competitive Analysis - pricing gap identified
    3. Vendor Management - renegotiation opportunities
```

---

## Project Structure
```
03-persistent-memory/
├── app.py                
├── requirements.txt
└── README.md
```

No pre-written documents needed - agent creates its own memory files dynamically.

---

## How It Works
```
Session 1 (Day 1):
  User shares context
       ↓
  Agent saves to vault
       ↓
  session_2026-02-17_001.md created

Session 2 (Day 3):
  User asks fuzzy question
       ↓
  Semantic search in vault
       ↓
  Retrieves relevant context from Day 1
       ↓
  LLM synthesizes answer

Session 3 (Day 7):
  User asks for synthesis
       ↓
  Broad semantic query across ALL sessions
       ↓
  LLM identifies patterns, themes, decisions
```

**Key insight:** CtxVault provides the **semantic memory layer**, LangGraph provides the **intelligence layer**. Combined = powerful persistent agent.

---

## Why This Matters

**Traditional approach:**
- Conversation state lost between sessions
- No semantic search over history
- Can't synthesize patterns across time

**With CtxVault persistent memory:**
- Context survives indefinitely
- Semantic recall with fuzzy queries
- Cross-session pattern recognition
- True long-term assistant behavior

---

## CtxVault vs Alternatives

| Feature | LangGraph State | Memory DBs (Mem0/Zep) | CtxVault |
|---------|----------------|----------------------|----------|
| Persist across sessions | ❌ (checkpointer restores exact state) | ✅ | ✅ |
| Semantic search | ❌ | ✅ | ✅ |
| Simple setup | ✅ | ❌ (external services) | ✅ |
| Local-first | ✅ | ❌ (cloud APIs) | ✅ |
| Agent-generated content | ❌ | Partial | ✅ |

CtxVault combines the simplicity of local-first with the power of semantic memory.

---

## Customization

### Change the scenario

Edit the `interactions` lists in `session_1()` and `session_3()`:
```python
interactions = [
    {"time": "09:00", "text": "Your custom context here"},
    {"time": "10:30", "text": "Another interaction"},
]
```

### Adjust queries

Modify the `queries` list in `session_2()`:
```python
queries = [
    "Your custom question here",
    "Another semantic query",
]
```

### Use different LLM

Replace OpenAI with Anthropic, Ollama, or any provider:
```python
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-sonnet-4")
```

CtxVault is **LLM-agnostic** - works with any provider.

---

## Real-World Applications

**Personal use:**
- Research assistant tracking findings over weeks
- Study companion remembering learning progress
- Personal knowledge base with semantic recall

**Enterprise use:**
- Team assistant tracking project context
- Meeting notes with cross-session synthesis
- Customer support agent with persistent customer context

**Developer tools:**
- Coding assistant learning from past sessions
- Documentation helper with temporal knowledge
- Debug assistant tracking solution patterns

---

## Key Takeaway

**CtxVault enables true persistent memory for agents.**

Not just state restoration - **semantic search across temporal context**.

Perfect for:
- Long-term assistants
- Knowledge accumulation over time
- Cross-session intelligence
- Privacy-conscious memory (100% local)

---

**Want more?** Check out:
- Example 01 (simple RAG) for basic retrieval
- Example 02 (multi-agent isolation) for privacy-aware architectures