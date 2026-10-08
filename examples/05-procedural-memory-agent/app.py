"""
LangChain + CtxVault Procedural Memory Demo

One agent, two vaults — semantic knowledge and communication skills.

The agent retrieves factual context from a semantic vault and applies
procedural communication skills from a skill vault. The skills are
invisible to the user — they shape how the agent writes, not what
it writes about.

Semantic vault: company knowledge, team metrics, project updates
Skill vault:    communication procedures (weekly update, newsletter, FAQ)

The same facts, written three different ways — because three different
skills were applied.

Integration via MCP.

Run:
    python app.py

Requires:
    OPENAI_API_KEY environment variable
"""

import json
import os
import time
import asyncio
import subprocess
import requests
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR      = Path(__file__).parent
KNOWLEDGE_VAULT = "company-knowledge"
SKILLS_VAULT    = "comms-skills"

# ANSI colors
RESET   = "\033[0m"
BOLD    = "\033[1m"
GREY    = "\033[90m"
WHITE   = "\033[97m"
BLUE    = "\033[94m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
DIM     = "\033[2m"

# =====================================================================
# Helpers
# =====================================================================

def divider(char="─", width=68):
    print(f"{GREY}{char * width}{RESET}")

def section(title: str):
    print()
    divider("═")
    print(f"{BOLD}{WHITE}  {title}{RESET}")
    divider("═")
    print()

def step(label: str, message: str, color: str = GREY):
    print(f"  {color}{BOLD}[{label}]{RESET} {message}")

def info(message: str):
    print(f"  {DIM}{message}{RESET}")

# =====================================================================
# Setup — index vaults via HTTP before starting MCP
# =====================================================================

def index_vaults():
    step("SETUP", "starting api to index vaults...", BLUE)

    os.chdir(BASE_DIR)

    proc = subprocess.Popen(
        ["uvicorn", "ctxvault.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(BASE_DIR)
    )

    for _ in range(30):
        try:
            requests.get("http://127.0.0.1:8000", timeout=1)
            break
        except:
            time.sleep(0.3)

    requests.put("http://127.0.0.1:8000/ctxvault/index",
        json={"vault_name": KNOWLEDGE_VAULT})
    step("SETUP", f"indexed {KNOWLEDGE_VAULT}", GREEN)

    requests.put("http://127.0.0.1:8000/ctxvault/index",
        json={"vault_name": SKILLS_VAULT})
    step("SETUP", f"indexed {SKILLS_VAULT}", GREEN)

    proc.terminate()
    proc.wait()
    print()

# =====================================================================
# Agent
# =====================================================================

AGENT_PREAMBLE = """Before writing anything, follow these steps in order:
1. Call list_vaults to see all available vaults
2. Call list_skills with vault_name="{skills_vault}" to see available skills
3. Identify the correct skill for this request
4. Call read_skill to load the skill instructions
5. Call query with vault_name="{knowledge_vault}" to retrieve relevant facts
6. Write the output following the skill instructions exactly

Request: """

SYSTEM_PROMPT = f"""You are an internal communications assistant for an engineering team.

You have access to two vaults via MCP tools:

- '{KNOWLEDGE_VAULT}': semantic vault with factual company information — team metrics,
  project updates, team structure. Use the query tool to retrieve relevant facts.

- '{SKILLS_VAULT}': skill vault with communication procedures. These procedures define
  exactly how you must write each type of communication — structure, tone, word limits,
  hard rules. They are not suggestions. You must follow them precisely.

Your workflow for every request:
1. Use list_skills on '{SKILLS_VAULT}' to identify the correct skill for this communication type
2. Use read_skill to load the skill instructions — read them carefully
3. Use query on '{KNOWLEDGE_VAULT}' to retrieve the facts you need
4. Produce the output following the skill instructions exactly

The skill instructions override your default writing style. If the skill says
no greetings, there are no greetings. If it says maximum 250 words, you stop at 250.
The user never sees the skill — they only see the output it produced."""


async def run_agent(requests_list: list[tuple[str, str]]):
    server_params = StdioServerParameters(
        command="ctxvault-mcp",
        args=[],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await load_mcp_tools(session)
            step("MCP", f"loaded {len(tools)} tools", CYAN)
            for t in tools:
                info(f"→ {t.name}")
            print()

            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            agent = create_agent(llm, tools=tools, system_prompt=SYSTEM_PROMPT)

            for label, request in requests_list:
                section(label)
                print(f"  {WHITE}{request}{RESET}\n")

                full_request = AGENT_PREAMBLE.format(
                    skills_vault=SKILLS_VAULT,
                    knowledge_vault=KNOWLEDGE_VAULT
                ) + request

                answer = ""
                async for chunk in agent.astream(
                    {"messages": [{"role": "user", "content": full_request}]},
                    stream_mode="updates"
                ):
                    if "model" in chunk:
                        for msg in chunk["model"]["messages"]:
                            if getattr(msg, "tool_calls", None):
                                for tc in msg.tool_calls:
                                    vault = tc.get("args", {}).get("vault_name", "")
                                    vault_label = f" [{vault}]" if vault else ""
                                    info(f"⤷ {tc['name']}{vault_label}")
                            elif msg.content:
                                answer = msg.content

                divider()
                print(f"\n{answer}\n")

# =====================================================================
# Main
# =====================================================================

def main():
    if not os.getenv("OPENAI_API_KEY"):
        print(f"\n  {YELLOW}error: OPENAI_API_KEY not set{RESET}\n")
        return

    index_vaults()

    section("COMMUNICATIONS AGENT — PROCEDURAL MEMORY DEMO")
    print(f"  {DIM}knowledge vault:  {KNOWLEDGE_VAULT}  (what to write about){RESET}")
    print(f"  {DIM}skill vault:      {SKILLS_VAULT}  (how to write it){RESET}")
    print()

    requests_list = [
        (
            "REQUEST 1: Weekly Update",
            "Write the weekly engineering update for stakeholders."
        ),
        (
            "REQUEST 2: Newsletter",
            "Write the engineering section for this month's company newsletter."
        ),
        (
            "REQUEST 3: FAQ",
            "Write FAQ answers for employees about the new engineers joining "
            "and the upcoming release freeze."
        ),
    ]

    asyncio.run(run_agent(requests_list))

    section("WHAT HAPPENED")
    print(f"  {DIM}Three requests, same knowledge vault, three different skills.{RESET}")
    print(f"  {DIM}The weekly update: structured, metric-heavy, under 250 words.{RESET}")
    print(f"  {DIM}The newsletter: warm, jargon-free, written for non-engineers.{RESET}")
    print(f"  {DIM}The FAQ: direct, self-contained answers, no filler.{RESET}")
    print()
    print(f"  {DIM}The skills were never shown to the user.{RESET}")
    print(f"  {DIM}They shaped the output — not the content, the form.{RESET}")
    print()

if __name__ == "__main__":
    main()