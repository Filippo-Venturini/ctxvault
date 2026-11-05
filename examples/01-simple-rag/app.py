"""
LangChain + CtxVault RAG Demo

Single vault, single agent. Local semantic search over a document collection
with grounded answer generation and source attribution.

Documents:
- rag_survey_paper.pdf
- personal_notes.md
- blog_article.txt
- rag_comparison.txt

Run:
    python app.py

Requires:
    OPENAI_API_KEY environment variable
"""

import os
import time
import subprocess
import requests
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

API_URL = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).parent
VAULT_NAME = "personal-vault"

# ANSI colors for CLI
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# =====================================================================
# Server
# =====================================================================

def start_server():
    """Start CtxVault API in background."""
    print(f"{BLUE}[SERVER] Starting CtxVault API...{RESET}")
    
    proc = subprocess.Popen(
        ["uvicorn", "ctxvault.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    for _ in range(30):
        try:
            requests.get(API_URL, timeout=1)
            print(f"{GREEN}[SERVER] API ready{RESET}\n")
            return proc
        except:
            time.sleep(0.3)
    
    raise RuntimeError("CtxVault API failed to start")

# =====================================================================
# Vault helpers
# =====================================================================

def api(method: str, path: str, **kwargs):
    return requests.request(method, f"{API_URL}/ctxvault{path}", timeout=None, **kwargs)

def setup_vault():
    """Initialize vault and index documents."""    
    print(f"{BLUE}[SETUP] Indexing research documents...{RESET}")

    api("PUT", "/index", json={"vault_name": VAULT_NAME})
    print(f"{GREEN}[SETUP] Documents indexed{RESET}\n")

def retrieve(query: str, top_k: int = 3):
    """Retrieve relevant documents from vault."""
    res = api("POST", "/query", json={
        "vault_name": VAULT_NAME,
        "query": query,
        "top_k": top_k
    }).json()
    
    return [
        Document(page_content=r["text"], metadata={"source": r.get("source", "?")})
        for r in res.get("results", [])
    ]

# =====================================================================
# RAG Chain
# =====================================================================

def create_chain():
    """Build LangChain RAG pipeline."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    prompt = ChatPromptTemplate.from_template(
        """You are a research assistant. Answer the question using ONLY the provided context from the user's document collection.

Context from documents:
{context}

Question: {question}

Answer:"""
    )
    
    def format_docs(docs):
        return "\n\n".join([
            f"[Source: {d.metadata.get('source', '?')}]\n{d.page_content}"
            for d in docs
        ])
    
    chain = (
        {
            "context": lambda x: format_docs(retrieve(x["question"])),
            "question": lambda x: x["question"],
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    
    return chain

# =====================================================================
# Main
# =====================================================================

def main():
    if not os.getenv("OPENAI_API_KEY"):
        print(f"{YELLOW}ERROR: OPENAI_API_KEY environment variable not set{RESET}")
        print(f"{YELLOW}Please set it with: export OPENAI_API_KEY=your_key{RESET}")
        return
    
    print("=" * 70)
    print("Single-Vault RAG Demo")
    print("=" * 70)
    print()
    
    server = start_server()
    
    try:
        setup_vault()
        chain = create_chain()
        
        # Example queries demonstrating RAG capabilities
        queries = [
            "What are the main benefits of using RAG over fine-tuning?",
            "How does the RAG architecture work? Explain the pipeline.",
            "Compare RAG-Sequence and RAG-Token approaches from the paper."
        ]
        
        for query in queries:
            print("=" * 70)
            print(f"{BLUE}QUERY:{RESET} {query}")
            print("=" * 70)
            print()
            
            # Show retrieval
            docs = retrieve(query, top_k=2)
            print(f"{YELLOW}Retrieved from:{RESET}")
            for doc in docs:
                source = doc.metadata.get('source', '?')
                print(f"  - {source}")
            print()
            
            # Generate answer
            answer = chain.invoke({"question": query})
            print(f"{GREEN}ANSWER:{RESET}")
            print(answer)
            print("\n")
    
    finally:
        server.terminate()
        print(f"{BLUE}[SERVER] Stopped{RESET}")

if __name__ == "__main__":
    main()