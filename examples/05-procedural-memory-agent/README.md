# 05 · Procedural Memory Agent

One agent, two vault types: semantic and skill. The same facts,
written three different ways, because three different procedures
were applied.

This example introduces the skill vault: a new vault type designed
to give agents procedural memory. Where a semantic vault answers
"what do we know", a skill vault answers "how do we do this".
The agent retrieves facts from one, procedures from the other,
and produces output that reflects both.

The integration uses MCP: the agent discovers vaults, reads skills,
and queries knowledge autonomously through the MCP server, with no
API calls written in application code.

---

## Scenario

An internal communications assistant for an engineering team. The
semantic vault holds company knowledge: team metrics, project
updates, team structure. The skill vault holds communication
procedures: exactly how to write a weekly stakeholder update, a
company newsletter, and an FAQ for employees.

The user asks for three different communications. The agent fetches
the relevant skill from the skill vault and follows it as a
behavioral instruction, not as content to summarize, but as a
procedure to execute.

The same facts appear in all three outputs. What changes is the
form: structure, tone, word limits, what to include and what to
omit, all defined by the skill.

---

## What this demonstrates

- Skill vault as procedural memory: instructions that shape agent
  behavior, not content the agent reports back
- Semantic vault and skill vault used together in a single system,
  each serving a distinct purpose
- The difference between declarative memory ("what we know") and
  procedural memory ("how we act")
- MCP as the integration layer: the agent uses `list_skills`,
  `read_skill`, and `query` autonomously with no glue code
- Skills as invisible behavioral constraints: the user sees the
  output, never the procedure

---

## Vault topology
```
company-knowledge  [PUBLIC]  →  semantic vault, team facts and metrics
comms-skills       [PUBLIC]  →  skill vault, communication procedures
```

The skill vault contains three skills, each defining a different
communication format. The agent selects the right one based on
the request.

---

## Setup

### 1. Install dependencies
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
```

### 2. Initialize vaults
```bash
ctxvault init company-knowledge
ctxvault init comms-skills
```

Inspect the skill vault before running:
```bash
ctxvault skills comms-skills
```
```
Found 3 skills in 'comms-skills'

  1. Weekly Engineering Update
     How to write the weekly engineering status update for stakeholders

  2. Company Newsletter Contribution
     How to write an engineering section for the monthly company newsletter

  3. FAQ Response
     How to write answers to frequently asked questions from employees
```

These are the procedures the agent will follow. They define structure,
tone, word limits, and hard rules.

### 3. Run
```bash
python app.py
```

---

## Project structure
```
05-procedural-memory-agent/
├── .ctxvault/
│   ├── config.json
│   └── vaults/
│       ├── company-knowledge/
│       │   ├── weekly-highlights.md
│       │   ├── team-metrics.md
│       │   └── team-structure.md
│       └── comms-skills/
│           ├── weekly-update.md
│           ├── newsletter.md
│           └── faq-response.md
├── app.py
└── requirements.txt
```

Skill files follow a simple format: frontmatter with name and
description, markdown body with the instructions:
```markdown
---
name: Weekly Engineering Update
description: How to write the weekly engineering status update for stakeholders
---

You are writing the weekly engineering update...

## Required structure
...

## Hard rules
- Never exceed 250 words.
- Never start with a greeting.
```

The frontmatter is the only contract with the vault. The filename is
irrelevant: drop the file, run `ctxvault index comms-skills`, and
the skill is available to any agent that queries the vault.

---

## Example output
```
REQUEST 1: Weekly Update

  ⤷ list_vaults
  ⤷ list_skills [comms-skills]
  ⤷ read_skill [comms-skills]
  ⤷ query [company-knowledge]

Shipped the new authentication service to production on Tuesday.
Zero downtime deployment.

- Shipped new authentication service: improved security and user experience.
- Resolved critical memory leak in data pipeline: eliminated 15% degradation.
- Completed migration of 3 legacy microservices. 2 remaining.
- API response times improved by 40ms on average.

Deployments: 7 (6 successful, 1 rolled back)
Incidents: 0
Velocity: 62 points (target: 58)
Test coverage: 84% (up from 81%)
...
```

The tool call trail shows the agent's reasoning: it identifies which
vault holds procedures, reads the relevant one, then retrieves facts
from the knowledge vault. The user sees only the final output.


