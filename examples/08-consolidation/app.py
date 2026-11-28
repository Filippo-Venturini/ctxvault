"""
08 · Consolidation

Three short conversations on different days are turned into episodes by a
local model, with no extractor written by hand. A later conversation changes
something an earlier one said, and the vault records the change instead of
overwriting the fact.

    ollama pull qwen2.5:7b
    python app.py

Needs Ollama running on this machine. Set MODEL to use another model.
"""

import os
from pathlib import Path

from ctxvault import Client
from ctxvault.consolidation import OpenAICompatibleModel, consolidate
from ctxvault.core.exceptions import VaultNotFoundError

# every ctxvault command resolves the project's vaults from the working
# directory, and so does the client: this script runs from its own folder
os.chdir(Path(__file__).parent)

MODEL = os.getenv("MODEL", "qwen2.5:7b")
VAULT = "personal-facts"

BOLD, DIM, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m"

# Three conversations, replayed with the day they happened. `at` on each
# turn dates it, and consolidate(..., at=) dates the run.
SESSIONS = [
    ("2026-03-02T18:00:00+00:00", [
        {"speaker": "Giulia", "text": "I live in Lisbon and I work at Brightline as a product designer.", "at": "2026-03-02T18:00:00+00:00"},
        {"speaker": "Giulia", "text": "I am vegetarian, so no meat in the restaurant booking please.", "at": "2026-03-02T18:01:00+00:00"},
    ]),
    ("2026-04-14T09:30:00+00:00", [
        {"speaker": "Giulia", "text": "Big news, I moved to Porto last week.", "at": "2026-04-14T09:30:00+00:00"},
        {"speaker": "Giulia", "text": "Still at Brightline, I just work remotely from there now.", "at": "2026-04-14T09:31:00+00:00"},
    ]),
    ("2026-06-20T17:00:00+00:00", [
        {"speaker": "Giulia", "text": "I left Brightline on Friday and I am freelancing now.", "at": "2026-06-20T17:00:00+00:00"},
    ]),
]

# A fourth conversation, only planned: nothing from it is written.
PREVIEW = ("2026-07-05T10:00:00+00:00", [
    {"speaker": "Giulia", "text": "I am vegetarian, still. And I have started learning Portuguese.", "at": "2026-07-05T10:00:00+00:00"},
])

def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}\n{DIM}{'─' * 68}{RESET}")

def show(result) -> None:
    print(f"  model {result.model}, prompts {result.prompt_version}, "
          f"{result.extracted} claims extracted, {result.dropped} dropped")
    if not result.operations:
        print(f"  {YELLOW}no operations{RESET}")
    for op in result.operations:
        state = "planned" if result.dry_run else ("applied" if op.applied else "not applied")
        print(f"  {GREEN}{op.verb:<18}{RESET} {op.relation:<10} {op.claim.statement}  {DIM}[{state}]{RESET}")
        if op.note:
            print(f"      {YELLOW}note: {op.note}{RESET}")
        if op.error:
            print(f"      {YELLOW}error: {op.error}{RESET}")

def main() -> None:
    client = Client()
    try:
        client.purge(VAULT)   # start from an empty vault, so the script can be run twice
    except VaultNotFoundError:
        pass
    client.init(VAULT, "episodic")
    facts = client.episodic(VAULT)

    # Ollama on this machine, by default. Temperature is 0.
    # a small model on CPU can need more than the default two minutes per call
    model = OpenAICompatibleModel(MODEL, timeout=600)

    changed = None
    for at, turns in SESSIONS:
        section(f"Conversation on {at[:10]}")
        result = consolidate(facts, turns, model, at=at)
        show(result)
        for op in result.operations:
            # the episode that took the place of an older one
            if op.verb == "supersede_episode" and op.episode_id and changed is None:
                changed = op.episode_id

    section("What holds today")
    for episode in facts.query_episodes(entities=["Giulia"]).results:
        print(f"  {episode.content}")

    section("What held on 2026-03-15")
    for episode in facts.query_episodes(entities=["Giulia"], valid_at="2026-03-15T00:00:00+00:00").results:
        print(f"  {episode.content}")

    section("History of a changed fact")
    if changed:
        for version in facts.history(changed).chain:
            print(f"  {version.content}")
            print(f"    {DIM}valid from {version.valid_from} to {version.valid_to or 'open'}{RESET}")
    else:
        print(f"  {YELLOW}the model did not mark any fact as replaced in this run{RESET}")

    section(f"Dry run: conversation on {PREVIEW[0][:10]}")
    before = len(facts.query_episodes(include_closed=True).results)
    show(consolidate(facts, PREVIEW[1], model, at=PREVIEW[0], dry_run=True))
    after = len(facts.query_episodes(include_closed=True).results)
    print(f"  episodes in the vault: {before} before, {after} after")

if __name__ == "__main__":
    main()
