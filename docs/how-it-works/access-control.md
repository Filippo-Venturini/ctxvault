# Access control

A vault is either **public**, open to any agent, or **restricted**, open only to the agents attached to it. Each vault is its own index, so an agent has no way to reach a restricted vault it is not attached to: the boundary is in the storage, not in a filter that every query has to remember to apply.

## Restricting a vault

```bash
ctxvault init billing --restricted        # restricted from the start
ctxvault attach billing finance-agent     # give an agent access; a public vault becomes restricted
ctxvault detach billing finance-agent     # take it away
ctxvault publish billing                  # open it to every agent again
```

Agents are names, nothing more: there is no separate list of agents to create. An agent exists for CtxVault as soon as it is attached to a vault.

## How an agent says who it is

Each interface carries the agent's name its own way, and checks it whenever the agent reads or writes a vault (on the HTTP API, indexing and listing the vaults are the exceptions: they take no name):

| Interface | How the agent is named |
|-----------|------------------------|
| Python client | `Client(agent="finance-agent")` |
| HTTP API | the `X-CtxVault-Agent: finance-agent` header on each request |
| MCP server | `ctxvault-mcp --agent finance-agent`, in the client's config |

Public vaults need no name. A restricted vault refuses a call without one, or from an agent that is not attached: the HTTP API answers `403`, the client and the MCP server raise an error.

The CLI and the [memory viewer](../memory-viewer.md) are the owner's views: they see every vault, restricted ones included, and take no agent name.

A name is a declaration, not a credential: access control keeps agents in their lanes, it does not authenticate them. Anything that can call the HTTP API can claim any name, so keep the server on localhost, or behind your own authentication when it has to listen beyond it.

## Topologies

Vaults compose into whatever shape a system needs:

- **Isolation**: one restricted vault per agent, so no agent can read another's memory. [Example 02](https://github.com/Filippo-Venturini/ctxvault/tree/main/examples/02-multi-agent-isolation)
- **Shared and private**: a public knowledge base for everyone, a vault shared by two agents, a private one for each. [Example 04](https://github.com/Filippo-Venturini/ctxvault/tree/main/examples/04-composed-topology)
- **Every type at once**: three agents, six vaults, semantic, skill and episodic, each reachable by exactly the agents that need it. [Example 07](https://github.com/Filippo-Venturini/ctxvault/tree/main/examples/07-full-memory-topology), and the [live demo](../demo.html) built from it, where hovering an agent shows the vaults it reaches and who else sees each one.
