# Local and global vaults

Every vault is registered somewhere, and where it is registered decides who sees it: a project, or the whole machine.

## A project's vaults

`ctxvault init` works like `git init`: it creates a `.ctxvault/` folder in the directory you run it from, and the vault belongs to that project.

```
my-project/
└── .ctxvault/
    ├── config.json              # the registry: every vault, its type, who can reach it
    └── vaults/
        ├── product-sheets/      # semantic: your documents, and the chroma/ index
        ├── counter-procedures/  # skill: one markdown file per skill
        └── store-facts/         # episodic: episodes.db, a SQLite file
```

The registry stores paths relative to the project, so the setup moves with it: commit `config.json`, the documents and the skills, and a teammate who clones the project gets the same vaults. A semantic vault's `chroma/` index can always be rebuilt from its documents with `ctxvault index`; an episodic vault's `episodes.db` is the memory itself, with no other copy, so back it up like any other data.

## Machine-wide vaults

```bash
ctxvault init notes --global
```

A global vault lives in `~/.ctxvault` and is visible from anywhere on the machine, in every project. It suits memory that belongs to you rather than to a project, and agents that run outside any project, such as an MCP client started from your home directory.

## How a command finds its vaults

Every interface finds vaults the same way: the CLI, the Python client, the HTTP server, the MCP server and the memory viewer.

1. It looks for a `.ctxvault/config.json` in the current directory, then in each parent directory up to the root, and uses the first it finds: any command works from anywhere inside a project.
2. It adds the global vaults from `~/.ctxvault`.
3. If a local and a global vault share a name, the local one wins.

`ctxvault vaults` shows the result, both registries side by side:

```
Found 3 vaults (1 local, 2 global)

── local ──────────────────────────
  project-vault       [SEMANTIC] [PUBLIC]
  path:               /my-project/.ctxvault/vaults/project-vault

── global ─────────────────────────
  atlas-vault         [SEMANTIC] [RESTRICTED]  agents: atlas-agent
  path:               ~/.ctxvault/vaults/atlas-vault

  account-memory      [EPISODIC] [PUBLIC]
  path:               ~/.ctxvault/vaults/account-memory
```

## Keeping the data elsewhere

```bash
ctxvault init archive --path /data/archive
```

`--path` puts the vault's data in another directory, a larger disk for instance. The registry stays where it would have been, in the project's `.ctxvault/` or in `~/.ctxvault` with `--global`.
