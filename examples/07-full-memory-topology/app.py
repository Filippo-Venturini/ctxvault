"""
07 · Full Memory Topology

Three agents, six vaults, all three memory types in one topology, and a
year of facts replayed with their dates. The scenario is a small bakery.
This example builds the whole memory of the shop and looks at it:
it is what `ctxvault ui` shows best, and it is the dataset behind the live
demo linked from the README.

- counter-agent  answers customers: product sheets, counter procedures,
                 and what holds today about hours, payments and orders
- kitchen-agent  bakes: kitchen procedures and what holds about suppliers
- owner-agent    runs the shop: accounting, and both sets of facts

Vaults:
  product-sheets      semantic   public
  accounting          semantic   owner-agent
  counter-procedures  skill      counter-agent
  kitchen-procedures  skill      kitchen-agent
  store-facts         episodic   counter-agent, owner-agent
  supplier-facts      episodic   kitchen-agent, owner-agent

No LLM is involved: this example is about the memory, not about a model
reading it. The only download is the embedding model, on first index.

    python app.py                      # build the memory, then `ctxvault ui`
    python app.py --export demo.html   # also write a self-contained snapshot
"""

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ctxvault import Client
from ctxvault.core.exceptions import VaultAccessDeniedError

# every ctxvault command resolves the project's vaults from the working
# directory, and so does the client: this script runs from its own folder
os.chdir(Path(__file__).parent)

BOLD, DIM, GREEN, YELLOW, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

def ago(days: int, hour: int = 9) -> str:
    """An instant `days` ago, at `hour`: the facts below are replayed with
    the dates they were learned, so the time cursor has a year to travel."""
    return (NOW - timedelta(days=days)).replace(hour=hour).isoformat()

def ahead(days: int, hour: int = 9) -> str:
    return (NOW + timedelta(days=days)).replace(hour=hour).isoformat()

def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}\n{DIM}{'─' * 68}{RESET}")

def say(agent: str, text: str, color: str = GREEN) -> None:
    print(f"  {color}{BOLD}[{agent}]{RESET} {text}")

# --- the documents and the skills ----------------------------------------------

def index_files() -> None:
    section("Indexing documents and skills")
    owner, counter, kitchen = Client("owner-agent"), Client("counter-agent"), Client("kitchen-agent")
    for client, name in ((owner, "product-sheets"), (owner, "accounting")):
        indexed, skipped = client.semantic(name).index_files()
        say(client.agent, f"{name}: {len(indexed)} documents indexed" + (f", {len(skipped)} skipped" if skipped else ""))
    for client, name in ((counter, "counter-procedures"), (kitchen, "kitchen-procedures")):
        indexed, _ = client.skills(name).index_files()
        say(client.agent, f"{name}: {len(indexed)} skills indexed")

# --- a year of facts ------------------------------------------------------------

def fresh_episodic(client: Client, name: str, agents: list[str]):
    """The vault emptied and registered again, so the script can be run twice."""
    client.purge(name)
    client.init(name, "episodic", restricted=True)
    for agent in agents:
        client.attach(name, agent)
    return client.episodic(name)

def replay_store_facts(owner: Client) -> None:
    section("Replaying a year of store facts")
    facts = fresh_episodic(owner, "store-facts", ["counter-agent", "owner-agent"])
    hours = {"topic": "hours"}

    weekdays = facts.write_episode("The shop opens at 7:00 on weekdays", entities=["opening hours"], source="owner",
                                   salience=0.9, valid_from=ago(330), recorded_at=ago(330), metadata=hours)
    for days, who in ((250, "counter staff"), (120, "counter staff"), (21, "customer")):
        facts.confirm_episode(weekdays.id, at=ago(days), source=who)
    say("owner-agent", "weekday opening hours, confirmed three times since")

    saturday = facts.write_episode("The shop opens at 8:00 on Saturdays", entities=["opening hours", "Saturday"], source="owner",
                                   valid_from=ago(330), recorded_at=ago(330), metadata=hours)
    facts.revise_episode(saturday.id, "The shop opens at 8:00 and closes at 13:00 on Saturdays", source="counter staff", at=ago(200))
    say("counter-agent", "Saturday hours revised: same fact, said more precisely")

    card = facts.write_episode("Card payments are accepted from 5 euro", entities=["payments"], source="owner",
                               valid_from=ago(330), recorded_at=ago(330), metadata={"topic": "payments"})
    facts.supersede_episode(card.id, "Card payments are accepted with no minimum", source="owner", at=ago(150), valid_from=ago(150))
    say("owner-agent", "card minimum superseded: the world changed")

    loyalty = facts.write_episode("A loyalty card gives a free coffee every ten", entities=["loyalty card"], source="owner",
                                  valid_from=ago(300), recorded_at=ago(300), metadata={"topic": "promotions"})
    facts.invalidate_episode(loyalty.id, valid_to=ago(60), at=ago(60), reason="programme closed")
    say("owner-agent", "loyalty card closed: nothing replaces it")

    orders = facts.write_episode("Cake orders need two days' notice", entities=["cake orders"], source="counter staff",
                                 valid_from=ago(280), recorded_at=ago(280), metadata={"topic": "orders"})
    facts.confirm_episode(orders.id, at=ago(100), source="counter staff")

    half_price = facts.write_episode("Bread is half price in the last hour", entities=["prices"], source="owner",
                                     valid_from=ago(330), recorded_at=ago(330), metadata={"topic": "prices"})
    facts.confirm_episode(half_price.id, at=ago(10), source="counter staff")

    facts.write_episode("Unsold bread goes to the food bank crate", entities=["food bank"], source="owner",
                        valid_from=ago(200), recorded_at=ago(200), metadata={"topic": "waste"})

    sign = facts.write_episode("The shop closes at 19:00 on weekdays", entities=["opening hours"], source="counter staff",
                               valid_from=ago(90), recorded_at=ago(90), metadata=hours)
    owner_says = facts.write_episode("The shop closes at 19:30 on weekdays", entities=["opening hours"], source="owner",
                                     valid_from=ago(15), recorded_at=ago(15), metadata=hours)
    facts.dispute_episodes(sign.id, owner_says.id, at=ago(15), note="the sign on the door says 19:00, the owner says 19:30")
    say("owner-agent", "closing time in dispute: two sources, nobody has settled it", YELLOW)

    facts.write_episode("The shop opens on Sundays, 8:00 to 12:00", entities=["opening hours", "Sunday"], source="owner",
                        valid_from=ahead(40), recorded_at=ago(7), metadata=hours)
    say("owner-agent", "Sunday opening recorded a week ago, true in forty days")

def replay_supplier_facts(owner: Client) -> None:
    section("Replaying a year of supplier facts")
    facts = fresh_episodic(owner, "supplier-facts", ["kitchen-agent", "owner-agent"])

    flour = facts.write_episode("Flour comes from Hillside Mill", entities=["flour", "Hillside Mill"], source="owner",
                                salience=0.9, valid_from=ago(330), recorded_at=ago(330), metadata={"topic": "flour"})
    facts.supersede_episode(flour.id, "Flour comes from Valley Mill", entities=["flour", "Valley Mill"], source="owner",
                            at=ago(170), valid_from=ago(170))
    say("owner-agent", "the mill changed in spring: the old fact is closed where the new one opens")

    delivery = facts.write_episode("Valley Mill delivers on Mondays before 6:00", entities=["Valley Mill", "deliveries"], source="kitchen",
                                   valid_from=ago(165), recorded_at=ago(165), metadata={"topic": "flour"})
    facts.confirm_episode(delivery.id, at=ago(40), source="kitchen")

    facts.write_episode("The dough needs 2% more water with Valley Mill flour", entities=["flour", "Valley Mill"], source="kitchen",
                        confidence=0.7, valid_from=ago(160), recorded_at=ago(160), metadata={"topic": "flour"})

    butter = facts.write_episode("Butter is delivered on Tuesdays", entities=["butter", "Meadow Dairy", "deliveries"], source="kitchen",
                                 valid_from=ago(330), recorded_at=ago(330), metadata={"topic": "dairy"})
    facts.supersede_episode(butter.id, "Butter is delivered on Tuesdays and Fridays", source="owner", at=ago(100), valid_from=ago(100))

    eggs = facts.write_episode("Eggs come from Brook Farm, free range", entities=["eggs", "Brook Farm"], source="owner",
                               valid_from=ago(320), recorded_at=ago(320), metadata={"topic": "eggs"})
    for days in (200, 30):
        facts.confirm_episode(eggs.id, at=ago(days), source="kitchen")

    facts.write_episode("The deck oven is under warranty", entities=["deck oven"], source="owner",
                        valid_from=ago(300), valid_to=ahead(120), recorded_at=ago(300), metadata={"topic": "equipment"})
    say("owner-agent", "the oven warranty has an end date already: true until next season")

# --- the memory, looked at ------------------------------------------------------

def walk_through() -> None:
    section("Who can reach what")
    for agent in ("counter-agent", "kitchen-agent", "owner-agent"):
        client = Client(agent)
        reach = []
        for vault in client.vaults():
            try:
                client.vault(vault["name"])
                reach.append(vault["name"])
            except VaultAccessDeniedError:
                pass
        say(agent, ", ".join(reach))

    section("What the counter says today about the hours")
    facts = Client("counter-agent").episodic("store-facts")
    for episode in facts.query_episodes(entities=["opening hours"], order_by="recency").results:
        flag = f"  {RED}in dispute{RESET}" if episode.disputed else ""
        confirmed = f"  {DIM}confirmed {episode.confirmed_count}x{RESET}" if episode.confirmed_count else ""
        say("counter-agent", f"{episode.content}{flag}{confirmed}")

    section("What the kitchen knew about flour last winter")
    kitchen = Client("kitchen-agent").episodic("supplier-facts")
    then = ago(250)
    for episode in kitchen.query_episodes(entities=["flour"], valid_at=then, known_at=then).results:
        say("kitchen-agent", f"{episode.content}  {DIM}(as of {then[:10]}){RESET}")
    for episode in kitchen.query_episodes(entities=["flour"]).results:
        say("kitchen-agent", f"{episode.content}  {DIM}(today){RESET}")

    section("What the kitchen follows")
    skills = Client("kitchen-agent").skills("kitchen-procedures")
    for skill in skills.list_skills():
        say("kitchen-agent", f"{skill.skill_name}: {skill.description}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bakery's memory and look at it.")
    parser.add_argument("--export", metavar="FILE.html", help="also write a self-contained snapshot of every vault")
    args = parser.parse_args()

    owner = Client("owner-agent")
    index_files()
    replay_store_facts(owner)
    replay_supplier_facts(owner)
    walk_through()

    section("Look at it")
    print(f"  {BOLD}ctxvault ui{RESET}  from this folder: the map of the six vaults and the three agents,")
    print("  then open store-facts and drag the time cursor back through the year.")
    if args.export:
        from ctxvault.ui import server
        note = ("A snapshot of the bakery example: three agents, six vaults, every kind of memory, one year "
                "of a small shop. Hover a vault or an agent on the map, open store-facts, then drag the time "
                "cursor in Over time.")
        path = server.export(Path(args.export), note=note)
        print(f"  Snapshot written to {path}")
    print("")

if __name__ == "__main__":
    main()
