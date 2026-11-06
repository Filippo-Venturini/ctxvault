# Over HTTP

For agents in another process, another language, or another machine, and for more than one process sharing the same vaults: run the HTTP server, and every vault operation is a REST call.

## Start the server

```bash
pip install ctxvault
uvicorn ctxvault.api.app:app            # http://127.0.0.1:8000
```

The server reads the same registry as the CLI: start it from your project's root to see the project's vaults, alongside the global ones. Vaults are created with the CLI (`ctxvault init`); the API reads and writes them. To reach it from other machines, bind it with `--host 0.0.0.0` and put it behind your own network controls: restricted vaults are protected by agent name, not by authentication.

## Give an agent persistent memory

```bash
ctxvault init agent-memory
```

```python
import requests

API = "http://127.0.0.1:8000/ctxvault"

# The agent writes what it learns: the document is saved in the vault and indexed at once
requests.post(f"{API}/docs/write", json={
    "vault_name": "agent-memory",
    "file_path": "session_monday.md",
    "content": "Discussed Q2 budget: need to cut cloud costs by 15%. "
               "Competitor pricing is 20% lower than ours.",
    "overwrite": True,
}).raise_for_status()

# Days later, it asks with completely different words
results = requests.post(f"{API}/query", json={
    "vault_name": "agent-memory",
    "query": "financial constraints from last week",
    "n_results": 3,
}).json()["results"]

context = "\n".join(r["text"] for r in results)
# Ground any LLM in it: "Context:\n{context}\n\nQ: What are our cost targets?"
```

Episodic vaults work the same way, with statements instead of documents:

```python
requests.post(f"{API}/episodes/write", json={
    "vault_name": "account-memory",
    "content": "Sarah Klein is the main contact",
    "entities": ["Sarah Klein"],
    "salience": 0.9,
})

requests.post(f"{API}/episodes/query", json={
    "vault_name": "account-memory",
    "entities": ["Sarah Klein"],
}).json()["results"]        # what holds today
```

## Restricted vaults

A restricted vault answers only the agents attached to it (`ctxvault attach <vault> <agent>`). Every request names its agent in a header:

```python
requests.post(f"{API}/query",
    headers={"X-CtxVault-Agent": "my-agent"},
    json={"vault_name": "my-vault", "query": "attention mechanisms", "n_results": 3},
)
```

Without the header, or with an agent that is not attached, a restricted vault returns `403`. Public vaults do not need it.

## Reference

Every endpoint is listed in the [HTTP API reference](../reference/http-api.md). The running server also serves interactive documentation at `http://127.0.0.1:8000/docs`, and the memory viewer at `http://127.0.0.1:8000/ui`.
