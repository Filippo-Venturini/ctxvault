# Personal Research Assistant with RAG

Build a **semantic search engine over your personal document collection** in ~100 lines of code.

## Scenario

You're researching Retrieval-Augmented Generation (RAG). You've collected:
- Academic papers (PDF)
- Personal notes (Markdown)
- Blog articles (Text)
- Comparison docs (DOCX)

Instead of manually searching through files, you want to **ask questions and get answers grounded in your documents**.

This is exactly what CtxVault + LangChain enables.

---

## What This Demonstrates

**Core capability:** Local semantic search as a RAG backend

- **Multi-format support**: PDF, MD, TXT, DOCX - all indexed automatically
- **Semantic retrieval**: Finds relevant content by meaning, not keywords
- **Citation tracking**: See which documents were used for each answer
- **Zero setup complexity**: Runs entirely locally, no cloud dependencies

**Real use case:** Personal knowledge management for researchers, students, developers.

---

## Quick Start

### 1. Install dependencies
```bash
python -m venv .venv-example-01 && source .venv-example-01/bin/activate  # Windows: .venv-example-01\Scripts\activate
pip install -r requirements.txt
```

### 2. Set OpenAI API key
```bash
export OPENAI_API_KEY=your_key
```

> **Note:** Want to use local LLMs? Replace `ChatOpenAI` with `Ollama` in the code. CtxVault works with any LLM.

### 3. Run
```bash
python app.py
```

The script automatically:
1. Starts CtxVault API server
2. Creates a vault named `research-vault`
3. Indexes all documents in `docs/` folder
4. Runs example queries showing RAG in action

---

## Example Output
```
QUERY: What are the main benefits of using RAG over fine-tuning?

Retrieved from:
  - rag_comparison.txt
  - personal_notes.md

ANSWER:
The main benefits of RAG over fine-tuning are:

1. Easy knowledge updates - just add documents without retraining
2. Cost-effective - no expensive training compute required
3. Transparency - retrieved documents provide citations
4. Privacy-friendly - data stays in your infrastructure
5. Works with any LLM without model training

RAG is particularly suited for dynamic knowledge that changes frequently
and large document collections.
```

---

## Project Structure
```
01-simple-rag/
├── docs/                          # Your document collection
│   ├── rag_survey_paper.pdf       # Academic paper
│   ├── personal_notes.md          # Markdown notes
│   ├── blog_article.txt           # Blog post
│   └── rag_comparison.txt         # Comparison doc
├── app.py                         # RAG pipeline (100 lines)
├── requirements.txt
└── README.md
```

---

## Why This Matters

**Traditional approach:**
- Full-text search → keyword matching → miss semantic matches
- Manual file browsing → time-consuming → frustrating
- Copy-paste from docs → tedious → error-prone

**With CtxVault RAG:**
- Ask natural language questions → get precise answers
- Semantic search → finds relevant content even with different wording
- Citations included → verify sources instantly

---

## How It Works
```
User Question
      ↓
[CtxVault Retriever]
      ↓
Retrieve top-k relevant document chunks
      ↓
[LangChain Chain]
      ↓
Pass chunks + question to LLM
      ↓
Generated Answer (grounded in your docs)
```

**Key insight:** CtxVault handles the hard parts (embeddings, vector search, indexing). You just query and generate.

---

## Customization

### Use your own documents

Replace files in `docs/` folder with your own:
- Research papers
- Meeting notes  
- Documentation
- Code comments
- Articles you've saved

Any text-based format works: `.txt`, `.md`, `.pdf`, `.docx`

### Change queries

Edit the `queries` list in `app.py`:
```python
queries = [
    "Your question here",
    "Another question",
]
```

### Use local LLMs

Replace OpenAI with Ollama:
```python
from langchain_community.llms import Ollama

llm = Ollama(model="llama2")
```

CtxVault is **LLM-agnostic** - works with OpenAI, Anthropic, Ollama, or any provider.

---

## Key Takeaway

**CtxVault makes RAG trivial.**

No complex setup. No vector database configuration. No embedding management.

Just:
1. Point it at your documents
2. Query semantically  
3. Get answers

Perfect for:
- Personal knowledge bases
- Research paper collections
- Documentation search
- Study assistants
- Internal company docs

---

**Want more?** 
- Example 02 (multi-agent isolation) for privacy-aware architectures
- Example 03 (persistent memory) for long-term semantic memory that persists across sessions