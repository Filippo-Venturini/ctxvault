# 06 · Episodic Memory Agent

One agent, one account, six months. Facts are recorded with a validity
window, corrected when reality changes, and never deleted.

This example introduces the episodic vault: a vault type for statements
that have a lifetime. Where a semantic vault answers "what do we know"
and a skill vault answers "how do we do this", an episodic vault answers
"what holds right now, and what held back then".

---

## Scenario

An account assistant follows the Nordwind account. In March it records
four facts from the onboarding call. In June three of them change: the
main contact leaves, the plan is upgraded, and a competitor evaluation
ends without a replacement. In September the agent prepares a briefing.

The briefing contains only what currently holds. The superseded facts
are still in the vault, reachable by history or by asking what was true
in April, but they never reach the prompt. That is the difference
between an episodic vault and a vector index: a stale fact is excluded
by a condition, not outranked by a score.

---

## What this demonstrates

- Recording statements with an explicit validity window
- Superseding a fact: the old one closes exactly where the new one opens
- Invalidating a fact that ends with nothing replacing it
- Retrieval of current state, with closed facts structurally excluded
- Time travel with `valid_at`: what the account looked like in April
- The supersession chain: how a belief got where it is

---

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
python app.py
```

---

## What happens

**Session 1, March**
Four episodes are written, all valid from March 2 and all open ended.

```
Sarah Klein is the main contact for the Nordwind account
Nordwind is on the Starter plan
Nordwind is evaluating a competitor for the Q3 renewal
Nordwind onboarding is blocked on SSO configuration
```

**Session 2, June**
Reality moves, and the vault records the move rather than overwriting it.

```
supersede  contact  Sarah Klein → Marco Rossi        both linked, boundary June 15
supersede  plan     Starter → Pro                    both linked, boundary June 15
invalidate competitor evaluation                     closed, nothing replaces it
write      quarterly business review in September    new, open ended
```

A supersede and an invalidate are not the same operation. The first says
"this was replaced by that", the second says "this simply ended". Only
the first leaves a chain to follow.

**Session 3, September**
```
QUERY: everything about Nordwind
→ Marco Rossi is the contact, Pro plan, SSO blocker, QBR in September

QUERY: everything about Nordwind, valid_at April 10
→ Sarah Klein is the contact, Starter plan, competitor evaluation, SSO blocker

HISTORY of the contact episode
→ Sarah Klein   valid from March 2 to June 15
→ Marco Rossi   valid from June 15 to open
```

The LLM only ever sees the first set. The second and third are there for
the human asking why the agent believes what it believes.

---

## Project structure
```
06-episodic-memory/
├── .ctxvault/
│   ├── config.json
│   └── vaults/
│       └── account-memory/
├── app.py
└── requirements.txt
```

No pre-written documents. An episodic vault holds rows in a SQLite file,
created on first write, and the agent fills it at runtime.

---

### Inspect the memory vault

After running the demo, look at what the agent recorded:
```bash
ctxvault episodes account-memory --entity Nordwind
```
```
Found 4 episodes (ordered by recency)

  1. Nordwind asked for a quarterly business review in September
     2026-06-15T09:00:00+00:00 → open
     salience 0.75 · confidence 1.00 · source account_assistant
     entities: Nordwind
```

Then ask what was true before the account changed hands:
```bash
ctxvault episodes account-memory --entity Nordwind --valid-at 2026-04-10T00:00:00+00:00
```

And count what is open against what is closed:
```bash
ctxvault episodes account-memory --stats
```
```
6 episodes in 'account-memory'
  open:   4
  closed: 2
```

Nothing was removed along the way. The two closed episodes are the ones
that stopped holding in June.

---

## Next

The five examples before this one use vaults that answer *what* and
*how*. This one adds *when*. The infrastructure is unchanged: the same
vault primitive, the same access control, the same CLI. What changes is
that memory now has a timeline, which is what an agent needs to stay
coherent across months rather than across a session.
