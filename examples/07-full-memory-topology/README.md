# 07 · Full Memory Topology

The capstone: every primitive of the library in one topology. Three
agents, six vaults, all three memory types, access rules per vault, and a
year of facts replayed with the dates they were learned. The scenario is a
small bakery. It is the dataset behind the [live demo](https://filippo-venturini.github.io/ctxvault/demo.html)
and what `ctxvault ui` shows best.

Where 04 shows how access composes, 05 adds skills and 06 adds time, this
one has all three at once, in a place anyone understands: a shop with a
counter, a kitchen and an owner.

---

## Scenario

A neighbourhood bakery runs three assistants.

- **counter-agent** answers customers. It reads the product sheets, follows
  the counter procedures (how to take a cake order, how to handle a return,
  how to close), and checks what holds today about hours, payments and
  orders.
- **kitchen-agent** bakes. It follows the kitchen procedures (starting the
  ovens, the sourdough schedule, allergen handling) and keeps the facts
  about suppliers: which mill, which dairy, which days they deliver.
- **owner-agent** runs the shop. It alone reads the accounting, and it sees
  both sets of facts.

Over a year the facts move. The mill changes, so the old statement is
superseded. The Saturday hours are said more precisely, so they are revised.
The loyalty card ends with nothing in its place, so it is invalidated. The
weekday opening hours are confirmed again and again. The sign on the door
says the shop closes at 19:00 and the owner says 19:30, so the two
statements are in dispute. And the Sunday opening is recorded a week before
it becomes true.

---

## Vault topology

```
product-sheets      [PUBLIC]      semantic   everyone
accounting          [RESTRICTED]  semantic   owner-agent
counter-procedures  [RESTRICTED]  skill      counter-agent
kitchen-procedures  [RESTRICTED]  skill      kitchen-agent
store-facts         [RESTRICTED]  episodic   counter-agent, owner-agent
supplier-facts      [RESTRICTED]  episodic   kitchen-agent, owner-agent
```

The counter never sees the accounting or the suppliers. The kitchen never
sees the hours. The owner sees everything but the procedures, which are not
its job.

---

## What this demonstrates

- The three vault types side by side, each holding what it is for:
  documents, procedures, facts with a lifetime.
- A topology where every agent has a different profile: a public base,
  private vaults, and two vaults shared between two agents.
- The whole episodic vocabulary in one story: record, confirm, revise,
  supersede, invalidate, dispute, a fact dated in the future.
- The in-process Python client: no server, the script opens the vaults and
  writes them directly, replaying the year with the dates it happened
  (`recorded_at` and `at` on the write calls).
- `ctxvault ui`: the map of vaults and agents, and the time cursor over the
  year.

No LLM is involved. The example is about the memory, not about a model
reading it; the only download is the embedding model, on first index.

---

## Setup

### 1. Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Build the memory
```bash
python app.py
```

The script indexes the documents and the skills, replays the year of facts
into the two episodic vaults, and prints what each agent can reach, what
the counter says today about the hours (one statement flagged as disputed),
and what the kitchen knew about flour last winter against what it knows
today. It can be run again: the episodic vaults are rebuilt from scratch.

### 3. Look at it
```bash
ctxvault ui
```

From this folder. Hover a vault or an agent on the map. Open `store-facts`,
switch to **Over time**, drag the cursor back through the year: the
statements that held on that day, what is new since, what is no longer
true, what was revised. Click a statement for its two timelines (in the
world, in the memory), its versions, who confirmed it, what contradicts it.

### 4. Snapshot
```bash
python app.py --export demo.html
```

One self-contained file, no server, with a note at the top for whoever opens
it without knowing what it is.

The published demo (`docs/demo.html` in the repository) is this snapshot,
built from a copy of the folder under a neutral home so that the page
carries no personal paths:

```bash
D=$(mktemp -d) && mkdir -p "$D/home" && cp -r examples/07-full-memory-topology "$D/home/bakery"
(cd "$D/home/bakery" && HOME="$D/home" HF_HOME="$HOME/.cache/huggingface" python app.py --export "$OLDPWD/docs/demo.html")
rm -rf "$D"
```

---

## Files

```
.ctxvault/config.json                   the six vaults and who may reach them
.ctxvault/vaults/product-sheets/        three product sheets, markdown
.ctxvault/vaults/accounting/            pricing rules, invoice handling
.ctxvault/vaults/counter-procedures/    three skills with frontmatter
.ctxvault/vaults/kitchen-procedures/    three skills with frontmatter
.ctxvault/vaults/store-facts/           episodes.db, built by app.py
.ctxvault/vaults/supplier-facts/        episodes.db, built by app.py
app.py                                  builds the memory and walks through it
```
