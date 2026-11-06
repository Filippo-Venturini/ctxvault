import pytest

from ctxvault import Client, EpisodicVault, SemanticVault, SkillVault, VaultType
from ctxvault.core.exceptions import (
    MissingAgentNameError,
    VaultAccessDeniedError,
    VaultNotFoundError,
    VaultTypeNotValidError,
)

# ── Opening by name ──────────────────────────────────────────────────────────

def test_vault_opens_as_the_class_its_type_calls_for(mock_vault_config, mock_skill_vault_config, mock_episodic_vault_config):
    memory = Client()

    assert isinstance(memory.vault("test_vault"), SemanticVault)
    assert isinstance(memory.vault("test_skill_vault"), SkillVault)
    assert isinstance(memory.vault("test_episodic_vault"), EpisodicVault)

def test_typed_accessors_refuse_another_type(mock_vault_config, mock_episodic_vault_config):
    memory = Client()

    assert isinstance(memory.semantic("test_vault"), SemanticVault)
    assert isinstance(memory.episodic("test_episodic_vault"), EpisodicVault)
    with pytest.raises(VaultTypeNotValidError, match="is semantic, not episodic"):
        memory.episodic("test_vault")
    with pytest.raises(VaultTypeNotValidError, match="is episodic, not skill"):
        memory.skills("test_episodic_vault")

def test_unknown_vault(mock_global_config):
    with pytest.raises(VaultNotFoundError):
        Client().vault("nowhere")

# ── Access control, as the HTTP header does it ───────────────────────────────

def test_restricted_vault_needs_an_attached_agent(mock_episodic_vault_config):
    memory = Client()
    memory.attach("test_episodic_vault", "keeper")

    with pytest.raises(MissingAgentNameError):
        memory.episodic("test_episodic_vault")
    with pytest.raises(VaultAccessDeniedError):
        Client(agent="stranger").episodic("test_episodic_vault")
    assert isinstance(Client(agent="keeper").episodic("test_episodic_vault"), EpisodicVault)

def test_public_again_after_make_public(mock_episodic_vault_config):
    memory = Client()
    memory.attach("test_episodic_vault", "keeper")
    memory.make_public("test_episodic_vault")

    assert isinstance(memory.episodic("test_episodic_vault"), EpisodicVault)

def test_detached_agent_is_out(mock_episodic_vault_config):
    memory = Client()
    memory.attach("test_episodic_vault", "keeper")
    memory.attach("test_episodic_vault", "other")
    memory.detach("test_episodic_vault", "keeper")

    with pytest.raises(VaultAccessDeniedError):
        Client(agent="keeper").episodic("test_episodic_vault")

# ── Registry ────────────────────────────────────────────────────────────────

def test_init_lists_and_purge_roundtrip(mock_global_config):
    memory = Client()

    path = memory.init("facts", "episodic", global_vault=True)
    listed = {v["name"]: v for v in memory.vaults()}

    assert listed["facts"]["type"] == VaultType.EPISODIC.value
    assert listed["facts"]["vault_path"] == path

    memory.purge("facts")
    assert "facts" not in {v["name"] for v in memory.vaults()}

def test_init_accepts_the_enum(mock_global_config):
    memory = Client()
    memory.init("procedures", VaultType.SKILL, global_vault=True)

    assert isinstance(memory.skills("procedures"), SkillVault)

# ── The same vault layer the server serves ──────────────────────────────────

def test_episodic_roundtrip_without_a_server(mock_episodic_vault_config):
    facts = Client().episodic("test_episodic_vault")

    first = facts.write_episode("Sarah Klein is the main contact", entities=["Sarah Klein"], salience=0.9)
    second = facts.supersede_episode(first.id, "Marco Rossi is the main contact", entities=["Marco Rossi"])

    current = facts.query_episodes(entities=["Marco Rossi"]).results
    assert [e.id for e in current] == [second.id]
    assert facts.get_episode(first.id).superseded_by == second.id
    assert [e.id for e in facts.history(second.id).chain] == [first.id, second.id]

def test_skill_roundtrip_without_a_server(mock_skill_vault_config, sample_skill_input):
    procedures = Client().skills("test_skill_vault")
    procedures.write_skill(sample_skill_input)

    assert procedures.read_skill("Deploy Service").instructions == sample_skill_input.instructions
    assert [s.skill_name for s in procedures.list_skills()] == ["Deploy Service"]

def test_semantic_query_without_a_server(mock_vault_config):
    documents = Client().semantic("test_vault")

    assert len(documents.query("test query").results) == 1
