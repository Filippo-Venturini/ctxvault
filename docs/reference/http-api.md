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

`/docs/write` returns `pruned`: what the vault's prune policy archived because of the write, an older agent-written copy of the same text. It's empty unless the policy is on.

### Pruning

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/prune` | POST | Report what a semantic vault would prune, and why. With `apply`, prune it: the named `targets`, or without them only what the policy allows unattended |
| `/prune/policy` | GET | Read the vault's prune policy, or the defaults (disabled) when none is set |
| `/prune/policy` | PUT | Enable or disable the policy, set `retention_days` and per-reason `rules`. Fields left out are kept |
| `/prune/log` | GET | What pruning archived, restored and purged |
| `/prune/restore` | POST | Put an archived document back and index it again (`overwrite` to replace a file written there since) |

Reading the report, the policy and the log follows the usual access rules. Changing anything (`apply`, `PUT /prune/policy`, `/prune/restore`) is a person's decision, and a request that carries `X-CtxVault-Agent` gets `403`. The MCP server only has the report. A restricted vault always needs the header, so its policy is changed through the CLI or the Python client. A log that does not chain returns `409`, with where the archived files are. See [`prune`](cli.md#prune) for what each part does.

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
| `/episodes/query` | POST | Retrieve episodes by entity, validity, source, ranking, or event metadata |
| `/episodes` | GET | Episode counts for a vault |
| `/episodes/entities` | GET | List the entities a vault knows, with their episode counts |
| `/episodes/{episode_id}` | GET | Read a single episode |
| `/episodes/{episode_id}/history` | GET | Read the supersession chain, with confirmations, disputes and closes (event metadata included; inherited attestations listed once) |
| `/episodes/{episode_id}/invalidate` | POST | Close an episode |
| `/episodes/{episode_id}/reopen` | POST | Reopen a closed episode without erasing the close |
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
