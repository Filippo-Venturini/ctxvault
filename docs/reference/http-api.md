# HTTP API

Start the server with `uvicorn ctxvault.api.app:app`, then call it from any language.

**Base URL:** `http://127.0.0.1:8000/ctxvault`

## Semantic vault endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Semantic search on a semantic vault |
| `/docs` | GET | List indexed documents in a semantic vault |
| `/docs/{doc_id}/content` | GET | Retrieve an indexed document's text |
| `/docs/write` | POST | Write and index a new document |
| `/delete` | DELETE | Remove document from a semantic vault |
| `/reindex` | PUT | Re-index documents in a semantic vault |

## Skill vault endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | List available skills in a skill vault |
| `/skill` | GET | Read a skill's instructions |
| `/skills/write` | POST | Write a new skill to a skill vault |

## Episodic vault endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/episodes/write` | POST | Record an episode |
| `/episodes/query` | POST | Retrieve episodes by entity, validity, source and ranking |
| `/episodes` | GET | Episode counts for a vault |
| `/episodes/entities` | GET | List the entities a vault knows, with their episode counts |
| `/episodes/{episode_id}` | GET | Read a single episode |
| `/episodes/{episode_id}/history` | GET | Read the supersession chain |
| `/episodes/{episode_id}/invalidate` | POST | Close an episode |
| `/episodes/{episode_id}/supersede` | POST | Replace an episode with a corrected one |
| `/episodes/{episode_id}/revise` | POST | Restate an episode more precisely |
| `/episodes/{episode_id}/confirm` | POST | Record that a statement was asserted again |
| `/episodes/{episode_id}/dispute` | POST | Record that two open statements cannot both hold |

## Shared endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | PUT | Index entire vault or specific path |
| `/vaults` | GET | List all initialized vaults |

## Agent authorization

Requests to restricted vaults require the `X-CtxVault-Agent` header. The value must match an agent name attached to that vault via `ctxvault attach`. Requests without the header, or with an unrecognized agent name, return `403`.
```http
X-CtxVault-Agent: my-agent
```
```python
requests.post("http://127.0.0.1:8000/ctxvault/query",
    headers={"X-CtxVault-Agent": "my-agent"},
    json={"vault_name": "my-vault", "query": "attention mechanisms", "n_results": 3}
)
```

Requests to public vaults do not require the header. `/index` and `/vaults` never require it.

## Interactive documentation

 Start the server and visit `http://127.0.0.1:8000/docs`
