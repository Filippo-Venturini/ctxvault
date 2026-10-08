"""
LangChain + CtxVault Episodic Memory Demo

An agent that follows a customer account over time. Every fact it learns
is recorded with a validity window, corrected when reality changes, and
retrieved as of any moment in the past.

Sessions:
- Session 1: the agent records what it learns during an onboarding call
- Session 2: three months later facts change, and are superseded or closed
- Session 3: current briefing, time travel, and the history of a belief

Run:
    python app.py

Requires:
    OPENAI_API_KEY environment variable
"""

import os
import time
import subprocess
import requests
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

API_URL = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).parent
VAULT_NAME = "account-memory"

# Fixed timestamps keep the demo reproducible: the three sessions happen
# in March, June and September of the same year.
MARCH = "2026-03-02T09:00:00+00:00"
APRIL = "2026-04-10T00:00:00+00:00"
JUNE = "2026-06-15T09:00:00+00:00"

# ANSI colors for CLI
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

# =====================================================================
# Server
# =====================================================================

def start_server():
    """Start CtxVault API in background."""
    print(f"{BLUE}[SERVER] Starting CtxVault API...{RESET}")

    proc = subprocess.Popen(
        ["uvicorn", "ctxvault.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        try:
            requests.get(API_URL, timeout=1)
            print(f"{GREEN}[SERVER] API ready{RESET}\n")
            return proc
        except:
            time.sleep(0.3)

    raise RuntimeError("CtxVault API failed to start")

# =====================================================================
# Vault helpers
# =====================================================================

def api(method: str, path: str, **kwargs):
    return requests.request(method, f"{API_URL}/ctxvault{path}", timeout=None, **kwargs)

def write_episode(content: str, entities: list, salience: float, valid_from: str):
    """Record a new statement, open ended until something closes it."""
    res = api("POST", "/episodes/write", json={
        "vault_name": VAULT_NAME,
        "content": content,
        "entities": entities,
        "source": "account_assistant",
        "salience": salience,
        "valid_from": valid_from,
    }).json()

    return res["episode"]["id"]

def supersede_episode(episode_id: str, content: str, valid_from: str):
    """Replace a statement with a corrected one, keeping both linked."""
    res = api("POST", f"/episodes/{episode_id}/supersede", json={
        "vault_name": VAULT_NAME,
        "content": content,
        "source": "account_assistant",
        "valid_from": valid_from,
    }).json()

    return res["episode"]["id"]

def invalidate_episode(episode_id: str, valid_to: str, reason: str):
    """Close a statement that stopped holding, without deleting it."""
    api("POST", f"/episodes/{episode_id}/invalidate", json={
        "vault_name": VAULT_NAME,
        "valid_to": valid_to,
        "reason": reason,
    })

def query_episodes(entities: list = None, valid_at: str = None, limit: int = 10):
    """Retrieve what holds now, or what held at a past instant."""
    res = api("POST", "/episodes/query", json={
        "vault_name": VAULT_NAME,
        "entities": entities or [],
        "valid_at": valid_at,
        "order_by": "salience",
        "limit": limit,
    }).json()

    return res.get("results", [])

def episode_history(episode_id: str):
    """Every version of a statement, oldest first."""
    res = api("GET", f"/episodes/{episode_id}/history", params={"vault_name": VAULT_NAME}).json()

    return res.get("chain", [])

# =====================================================================
# LLM
# =====================================================================

def get_llm():
    """Initialize LLM."""
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)

# =====================================================================
# Session 1 - Onboarding call
# =====================================================================

def session_1():
    """March - The agent records what it learns about a new account."""
    print("=" * 70)
    print(f"{CYAN}SESSION 1 - Monday, March 2, 2026{RESET}")
    print("=" * 70)
    print()

    print(f"{MAGENTA}[USER] Logging the Nordwind onboarding call...{RESET}\n")

    facts = [
        ("Sarah Klein is the main contact for the Nordwind account", ["Nordwind", "Sarah Klein"], 0.9),
        ("Nordwind is on the Starter plan", ["Nordwind"], 0.7),
        ("Nordwind is evaluating a competitor for the Q3 renewal", ["Nordwind"], 0.8),
        ("Nordwind onboarding is blocked on SSO configuration", ["Nordwind"], 0.6),
    ]

    episode_ids = {}
    for content, entities, salience in facts:
        print(f"{YELLOW}[FACT]{RESET} {content}")
        episode_ids[content] = write_episode(content, entities, salience, MARCH)
        time.sleep(0.3)

    print()
    print(f"{GREEN}[VAULT] Recorded {len(facts)} episodes, all valid from March 2{RESET}")
    print(f"{GREEN}[ASSISTANT] Noted. I will keep these up to date as things change.{RESET}")
    print()

    return episode_ids

# =====================================================================
# Session 2 - The account changes
# =====================================================================

def session_2(episode_ids: dict):
    """June - Facts change. Corrections replace them, they are not overwritten."""
    print("=" * 70)
    print(f"{CYAN}SESSION 2 - Monday, June 15, 2026{RESET}")
    print("=" * 70)
    print()

    print(f"{MAGENTA}[USER] Quarterly check in. A few things moved.{RESET}\n")

    contact_id = episode_ids["Sarah Klein is the main contact for the Nordwind account"]
    plan_id = episode_ids["Nordwind is on the Starter plan"]
    competitor_id = episode_ids["Nordwind is evaluating a competitor for the Q3 renewal"]

    print(f"{YELLOW}[CHANGE]{RESET} Sarah left. Marco Rossi took over the account.")
    new_contact_id = supersede_episode(
        contact_id,
        "Marco Rossi is the main contact for the Nordwind account",
        JUNE,
    )
    print(f"{GREEN}[VAULT]  Superseded: the old contact closes on June 15, the new one opens there{RESET}")
    print()

    print(f"{YELLOW}[CHANGE]{RESET} They upgraded to the Pro plan.")
    supersede_episode(plan_id, "Nordwind is on the Pro plan", JUNE)
    print(f"{GREEN}[VAULT]  Superseded: the Starter plan is now a closed episode{RESET}")
    print()

    print(f"{YELLOW}[CHANGE]{RESET} The competitor evaluation is over, they renewed with us.")
    invalidate_episode(competitor_id, JUNE, "renewed with us instead")
    print(f"{GREEN}[VAULT]  Closed: nothing replaces it, so it is invalidated and not superseded{RESET}")
    print()

    print(f"{YELLOW}[FACT]{RESET} Nordwind asked for a quarterly business review in September")
    write_episode(
        "Nordwind asked for a quarterly business review in September",
        ["Nordwind"],
        0.75,
        JUNE,
    )
    print(f"{GREEN}[VAULT]  Recorded{RESET}")
    print()

    return new_contact_id

# =====================================================================
# Session 3 - Briefing, time travel and history
# =====================================================================

def session_3(contact_id: str):
    """September - Current state, past state, and how a belief got here."""
    print("=" * 70)
    print(f"{CYAN}SESSION 3 - Tuesday, September 1, 2026{RESET}")
    print("=" * 70)
    print()

    print(f"{MAGENTA}[USER] Prepare me for the Nordwind call.{RESET}\n")

    print(f"{BLUE}[ASSISTANT] Retrieving what currently holds...{RESET}")
    current = query_episodes(entities=["Nordwind"])

    print(f"{GREEN}[VAULT] {len(current)} open episodes{RESET}")
    for episode in current:
        print(f"     {episode['content']}")
    print()

    # The closed facts are still in the vault, but they never reach the
    # prompt: the validity filter excludes them before ranking happens.
    print(f"{BLUE}[ASSISTANT] Drafting the briefing from current facts only...{RESET}")

    llm = get_llm()
    prompt = ChatPromptTemplate.from_template(
        """These are the facts that currently hold about the account:

{context}

Write a three line briefing for the account manager before the call.
Be concrete and mention only what is in the facts."""
    )

    chain = prompt | llm
    briefing = chain.invoke({"context": "\n".join(f"- {e['content']}" for e in current)})

    print()
    print(f"{GREEN}[ASSISTANT] {briefing.content}{RESET}")
    print()

    print(f"{MAGENTA}[USER] What did we believe back in April?{RESET}\n")

    past = query_episodes(entities=["Nordwind"], valid_at=APRIL)
    print(f"{GREEN}[VAULT] {len(past)} episodes valid on April 10{RESET}")
    for episode in past:
        print(f"     {episode['content']}")
    print()

    print(f"{MAGENTA}[USER] Who was the contact before Marco, and when did it change?{RESET}\n")

    chain_items = episode_history(contact_id)
    print(f"{GREEN}[VAULT] {len(chain_items)} versions of this statement{RESET}")
    for version in chain_items:
        until = version["valid_to"] or "open"
        print(f"     {version['content']}")
        print(f"       valid from {version['valid_from']} to {until}")
    print()

# =====================================================================
# Main
# =====================================================================

def main():
    if not os.getenv("OPENAI_API_KEY"):
        print(f"{YELLOW}ERROR: OPENAI_API_KEY environment variable not set{RESET}")
        print(f"{YELLOW}Please set it with: export OPENAI_API_KEY=your_key{RESET}")
        return

    print("=" * 70)
    print("Account Assistant with Episodic Memory Demo")
    print("=" * 70)
    print()
    print("This demo follows one account across six months. Facts are")
    print("recorded with a validity window, corrected when they change,")
    print("and never deleted.")
    print()

    server = start_server()

    try:
        episode_ids = session_1()
        time.sleep(1)

        contact_id = session_2(episode_ids)
        time.sleep(1)

        session_3(contact_id)

        print("=" * 70)
        print(f"{GREEN}Demo complete!{RESET}")

    finally:
        server.terminate()
        print(f"{BLUE}[SERVER] Stopped{RESET}")

if __name__ == "__main__":
    main()
