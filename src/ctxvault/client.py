"""Vaults from Python, in the same process.

The CLI, the HTTP API and the MCP server are three doors to one vault layer.
This is the fourth, for code that can hold the vault itself: a script, a
test, a pipeline, an agent that owns its memory. No server to start, no port,
no JSON in between. The vault is opened from disk and its methods are called
directly, returning the same typed models the API serializes.

    from ctxvault import Client

    memory = Client(agent="briefing-bot")
    facts = memory.episodic("account-memory")
    facts.write_episode("Sarah Klein is the main contact", entities=["Sarah Klein"])
    facts.query_episodes(entities=["Sarah Klein"]).results

The agent name plays the part the X-CtxVault-Agent header plays over HTTP: a
restricted vault opens only for an agent attached to it, and opens for anyone
when it is public. Vaults are found by name in the registry the CLI writes,
the project's .ctxvault first and then ~/.ctxvault, so what `ctxvault vaults`
lists is what this client can open.

One process at a time. A vault is a SQLite file or a Chroma directory, and
both are built for a single writer. Two processes that must share a vault,
an agent writing while a consolidation job reads, talk to one server; this
client is for the process that owns the vault.
"""

from ctxvault.core import vault_router
from ctxvault.core.exceptions import VaultAccessDeniedError, VaultTypeNotValidError
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.core.vaults.skill import SkillVault
from ctxvault.models.vaults import VaultType


class Client:
    """Opens vaults by name on behalf of one agent.

    `vault` returns whatever type the name resolves to; `semantic`, `skills`
    and `episodic` return the one type their caller expects, or fail before
    a method call would. The registry operations (`init`, `purge`, `attach`,
    `detach`, `make_public`, `vaults`) mirror the CLI commands of the same
    name and, like them, are not gated by the agent.
    """

    def __init__(self, agent: str | None = None):
        self.agent = agent

    # --- registry -------------------------------------------------------------

    def vaults(self) -> list[dict]:
        """Every registered vault, local ones first, as `ctxvault vaults` shows them."""
        return vault_router.list_vaults()

    def init(
        self,
        name: str,
        vault_type: str | VaultType = VaultType.SEMANTIC,
        *,
        restricted: bool = False,
        path: str | None = None,
        global_vault: bool = False,
        embedding_model: str | None = None,
    ) -> str:
        """Creates and registers a vault; returns its directory."""
        vault_path, _ = vault_router.init_vault(
            vault_name=name,
            vault_type=vault_type,
            restricted=restricted,
            path=path,
            global_vault=global_vault,
            embedding_model=embedding_model,
        )
        return vault_path

    def purge(self, name: str) -> None:
        """Deletes a vault's directory and forgets its registration."""
        vault_router.purge_vault(vault_name=name)

    def attach(self, name: str, agent: str) -> None:
        """Lets an agent into a vault, making the vault restricted if it was not."""
        vault_router.attach_agent(vault_name=name, agent_name=agent)

    def detach(self, name: str, agent: str) -> None:
        vault_router.detach_agent(vault_name=name, agent_name=agent)

    def make_public(self, name: str) -> None:
        vault_router.make_public(vault_name=name)

    # --- opening --------------------------------------------------------------

    def vault(self, name: str) -> SemanticVault | SkillVault | EpisodicVault:
        """The vault of that name, if this client's agent may use it."""
        vault = vault_router.open_vault(name)
        if not vault.is_agent_authorized(agent_name=self.agent):
            raise VaultAccessDeniedError(
                f"Agent '{self.agent}' is not authorized to access vault '{name}'."
            )
        return vault

    def semantic(self, name: str) -> SemanticVault:
        return self._open_as(name, VaultType.SEMANTIC)

    def skills(self, name: str) -> SkillVault:
        return self._open_as(name, VaultType.SKILL)

    def episodic(self, name: str) -> EpisodicVault:
        return self._open_as(name, VaultType.EPISODIC)

    def _open_as(self, name: str, expected: VaultType):
        vault = self.vault(name)
        actual = vault.config.get("type", VaultType.SEMANTIC.value)
        if actual != expected.value:
            raise VaultTypeNotValidError(
                f"Vault '{name}' is {actual}, not {expected.value}."
            )
        return vault
