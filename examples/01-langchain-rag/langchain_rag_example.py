"""
LangChain + CtxVault local RAG demo

Run:
    python app.py

What happens automatically:
- starts CtxVault API
- initializes vault
- indexes sample_docs/
- launches interactive chat

Optional:
    export OPENAI_API_KEY=...
"""

import os
import time
import subprocess
import requests
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

API_URL = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).parent
VAULT_PATH = str(BASE_DIR / "vault")

# ANSI colors for CLI
OK = "\033[92m"
RUN = "\033[94m"
INFO = "\033[0m"
WARN = "\033[93m"
ENDC = "\033[0m"

# ---------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------

def start_server():
    """Start CtxVault API in background."""
    print(f"{RUN}[RUN] Starting CtxVault API...{ENDC}")

    proc = subprocess.Popen(
        ["uvicorn", "ctxvault.api.app:app"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # wait until ready
    for _ in range(20):
        try:
            requests.get(API_URL, timeout=0.5)
            print(f"{OK}[OK] API ready{ENDC}\n")
            return proc
        except:
            time.sleep(0.3)

    raise RuntimeError("CtxVault API failed to start")

# ---------------------------------------------------------------------
# Vault helpers
# ---------------------------------------------------------------------

def api(method: str, path: str, **kwargs):
    return requests.request(method, f"{API_URL}/ctxvault{path}", timeout=None, **kwargs)

def setup_vault():
    print(f"{INFO}[INFO] Initializing vault...{ENDC}")
    api("POST", "/init", json={"vault_path": VAULT_PATH})
    print(f"{OK}[OK] Vault initialized{ENDC}\n")

    print(f"{INFO}[INFO] Indexing knowledge base...{ENDC}")
    api("PUT", "/index", json={"file_path": VAULT_PATH})
    print(f"{OK}[OK] Vault ready{ENDC}\n")

# ---------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------

def retrieve(query: str, top_k: int = 3):
    res = api("POST", "/query", json={"query": query, "top_k": top_k}).json()
    return [
        Document(page_content=r["text"], metadata={"source": r.get("source", "?")})
        for r in res.get("results", [])
    ]

# ---------------------------------------------------------------------
# LLM (real or retrieval-only)
# ---------------------------------------------------------------------

def get_llm():
    if not os.getenv("OPENAI_API_KEY"):
        print(f"{WARN}[WARN] OPENAI_API_KEY not set – running in retrieval-only mode. Only documents will be shown.{ENDC}\n")
        return None

    from langchain_openai import ChatOpenAI
    print(f"{INFO}[INFO] Using OpenAI GPT-4o-mini{ENDC}\n")
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ---------------------------------------------------------------------
# RAG chain
# ---------------------------------------------------------------------

def create_chain():
    llm = get_llm()
    if not llm:
        return None

    prompt = ChatPromptTemplate.from_template(
        """Answer using ONLY this context:

{context}

Question: {question}
"""
    )

    def format_docs(docs):
        return "\n\n".join(d.page_content for d in docs)

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

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    Path(VAULT_PATH).mkdir(exist_ok=True)

    server = start_server()

    try:
        setup_vault()
        chain = create_chain()

        print(f"{INFO}[INFO] Enter your query (type 'quit' to exit):{ENDC}\n")

        while True:
            q = input(">>> ").strip()
            if q.lower() in {"quit", "exit"}:
                print(f"{OK}[OK] Exiting...{ENDC}")
                break

            if chain:
                answer = chain.invoke({"question": q})
                print(f">>> {answer}\n")
            else:
                docs = retrieve(q)
                print(f"{INFO}[INFO] Retrieved documents:\n{ENDC}")
                for d in docs:
                    print(f"{RUN}--- {d.metadata.get('source','?')} ---{ENDC}")
                    print(f"{d.page_content[:500]}\n")
                    print("-" * 50)

    finally:
        server.terminate()


if __name__ == "__main__":
    main()
