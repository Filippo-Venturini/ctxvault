# Through an MCP client

For agents that run inside an MCP client, such as Claude Desktop, Claude Code or Cursor: the client starts `ctxvault-mcp` and the agent uses the vaults on its own, with no integration code.

## Install

```bash
uv tool install ctxvault        # or: pipx install ctxvault
```

This puts `ctxvault-mcp` on your PATH, where the client can start it.

## Configure the client

**Add to your `mcp.json`** (Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`; macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "ctxvault": {
      "command": "ctxvault-mcp"
    }
  }
}
```

Restart your client. The agent can now query your existing vaults, write new context, and list available knowledge, all locally and all under your control.

**Restricted vaults:** if you are integrating programmatically and need to access a restricted vault, pass the agent name at startup:
```json
{
  "mcpServers": {
    "ctxvault": {
      "command": "ctxvault-mcp",
      "args": ["--agent", "my-agent"]
    }
  }
}
```

The `--agent` argument is optional and only required for restricted vaults.

## What the agent can do

The agent discovers the vaults with `list_vaults`, then works with each according to its type: it queries and writes documents in a semantic vault, lists, reads and writes skills in a skill vault, and in an episodic vault records facts, confirms them when it hears them again, supersedes or revises them when they change, and holds contradictions open as disputes. Every tool, its description and its parameters are in the [MCP tools reference](../reference/mcp.md).

The server finds vaults the way the CLI does: the project registry nearest to the directory it starts in, plus the global `~/.ctxvault`. A client may start it outside your project, so vaults the agent should always reach are best created with `--global`.
