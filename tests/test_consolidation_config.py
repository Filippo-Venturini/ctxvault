import chromadb
import pytest

from ctxvault import Client
from ctxvault.consolidation import (
    Claim,
    ConsolidationConfig,
    consolidate,
    consolidate_session,
    facts_and_transcripts,
    facts_only,
    sources,
)
from ctxvault.core import vault_router
from ctxvault.core.exceptions import VaultAccessDeniedError, VaultTypeNotValidError
from ctxvault.storage import chroma_store

MARCH = "2026-03-10T09:00:00+00:00"

def claim(**overrides):
    data = {"subject": "Giuseppe", "statement": "Giuseppe lives in Mestre", "speaker": "Giuseppe", "kind": "first_party"}
    data.update(overrides)
    return data

class StubModel:
    name = "stub-model"
    prompt_version = "v0"

    def __init__(self, claims):
        self.claims = claims
        self.seen = None

    def extract(self, turns):
        self.seen = turns
        return self.claims

    def relate(self, claim, candidates):
        return {"relation": "new"}

def session(n, words=12):
    """n dated turns whose words are unique to each, long enough to span chunks."""
    return [
        {"speaker": "Giuseppe" if i % 2 == 0 else "assistant",
         "text": " ".join(f"t{i}w{j}" for j in range(words)),
         "at": f"2026-03-10T09:{i:02d}:00+00:00"}
        for i in range(n)
    ]

@pytest.fixture
def real_chroma(monkeypatch):
    monkeypatch.setattr(chroma_store, "PersistentClient", chromadb.PersistentClient)
    # small chunks, so a short session spans several: 30 words, 8 of overlap
    monkeypatch.setattr(
        "ctxvault.core.embedding.token_budget",
        lambda model_name=None: (lambda text: len(text.split()), 30, 8),
    )

def episodes(config):
    return vault_router.open_vault(config.facts_vault).query_episodes(limit=50).results

class TestConfig:
    def test_it_round_trips_through_a_file(self, tmp_path):
        config = ConsolidationConfig(facts_vault="f", transcripts_vault="t", kinds=["first_party"])
        config.save(tmp_path / "consolidation.json")
        assert ConsolidationConfig.load(tmp_path / "consolidation.json") == config

    def test_facts_only_is_the_default_and_unknown_keys_are_refused(self):
        assert ConsolidationConfig(facts_vault="f").transcripts_vault is None
        with pytest.raises(ValueError):
            ConsolidationConfig(facts_vault="f", transcript_vault="typo")

class TestPresets:
    def test_facts_only_creates_one_episodic_vault(self, mock_global_config):
        config = facts_only("assistant", global_vault=True)
        assert (config.facts_vault, config.transcripts_vault) == ("assistant-facts", None)
        assert {v["name"]: v["type"] for v in Client().vaults()} == {"assistant-facts": "episodic"}

    def test_facts_and_transcripts_creates_both(self, mock_global_config):
        config = facts_and_transcripts("assistant", global_vault=True, kinds=["first_party"])
        assert config.kinds == ["first_party"]
        assert {v["name"]: v["type"] for v in Client().vaults()} == {
            "assistant-facts": "episodic", "assistant-transcripts": "semantic",
        }

    def test_a_preset_run_twice_keeps_the_vaults_it_finds(self, mock_global_config):
        first = facts_and_transcripts("assistant", global_vault=True)
        assert facts_and_transcripts("assistant", global_vault=True) == first
        assert len(Client().vaults()) == 2

    def test_a_vault_of_the_wrong_type_is_not_taken_over(self, mock_global_config):
        Client().init("assistant-facts", "semantic", global_vault=True)
        with pytest.raises(VaultTypeNotValidError):
            facts_only("assistant", global_vault=True)

class TestFactsOnly:
    def test_nothing_but_the_facts_is_stored(self, mock_global_config):
        config = facts_only("assistant", global_vault=True)
        result = consolidate_session(config, session(2), StubModel([claim(turns=[0])]), at=MARCH)

        assert result.transcript is None
        [episode] = episodes(config)
        assert "provenance" not in episode.metadata
        assert episode.metadata["turns"] == [0]

    def test_a_named_source_becomes_external_provenance(self, mock_global_config):
        config = facts_only("assistant", global_vault=True)
        consolidate_session(config, session(2), StubModel([claim()]), session_id="thread-42", source="slack://C01")

        [episode] = episodes(config)
        assert episode.metadata["provenance"] == [{"type": "external", "source": "slack://C01", "locator": "thread-42"}]
        assert sources(episode) == []

    def test_the_facts_vault_must_be_episodic(self, mock_vault_config):
        with pytest.raises(VaultTypeNotValidError):
            consolidate_session(ConsolidationConfig(facts_vault="test_vault"), session(1), StubModel([claim()]))

    def test_kinds_come_from_the_config(self, mock_global_config):
        config = facts_only("assistant", global_vault=True, kinds=["first_party"])
        result = consolidate_session(config, session(1), StubModel([claim(), claim(kind="third_party", subject="Anna")]))
        assert (result.extracted, result.dropped, len(result.operations)) == (2, 1, 1)

class TestFactsAndTranscripts:
    def test_a_claim_points_at_the_chunks_its_turns_are_in(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        turns = session(8)
        result = consolidate_session(
            config, turns, StubModel([claim(turns=[0]), claim(statement="Giuseppe works in Venezia", turns=[6, 7])]),
            session_id="42",
        )

        written = result.transcript
        assert written.path == "sessions/42.txt" and written.chunks > 2
        first, second = sorted(episodes(config), key=lambda e: e.metadata["turns"])

        [resolved] = sources(first)
        assert resolved.state == "holds" and "t0w0" in resolved.text
        assert first.metadata["provenance"][0]["vault"] == "assistant-transcripts"

        texts = " ".join(r.text for r in sources(second))
        assert all(r.state == "holds" for r in sources(second))
        assert "t6w0" in texts and "t7w0" in texts
        # two turns in the same chunk are one reference, not two
        assert len(second.metadata["provenance"]) == len(set(written.turn_chunks[6:8]))

    def test_a_claim_that_names_no_turn_gets_no_reference(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        consolidate_session(config, session(4), StubModel([claim(), claim(statement="Giuseppe has a dog", turns=[99])]),
                            session_id="42")
        assert all("provenance" not in e.metadata and "turns" not in e.metadata for e in episodes(config))

    def test_a_bad_citation_does_not_cost_the_claim(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        result = consolidate_session(config, session(4), StubModel([claim(turns="the second one"), claim(
            statement="Giuseppe has a dog", turns=[1, "x", -3, 1])]), session_id="42")
        assert result.dropped == 0
        assert sorted(e.metadata.get("turns", []) for e in episodes(config)) == [[], [1]]

    def test_the_same_session_id_replaces_the_transcript(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        one = consolidate_session(config, session(4), StubModel([]), session_id="42")
        two = consolidate_session(config, session(6), StubModel([]), session_id="42")
        assert one.transcript.doc_id == two.transcript.doc_id
        assert len(Client().semantic("assistant-transcripts").list_documents()) == 1

    def test_an_edited_transcript_no_longer_backs_the_fact(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        consolidate_session(config, session(4), StubModel([claim(turns=[0])]), session_id="42")
        changed = session(4)
        changed[0]["text"] = "something else entirely"
        consolidate_session(config, changed, StubModel([]), session_id="42")

        fact = next(e for e in episodes(config) if e.metadata.get("turns") == [0])
        [resolved] = sources(fact)
        assert resolved.state == "changed" and resolved.text is None

    def test_an_undated_turn_is_written_with_the_given_conversation_time(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        result = consolidate_session(config, [{"speaker": "Giuseppe", "text": "I moved."}], StubModel([]),
                                     session_id="42", at=MARCH)
        assert result.transcript.session_started == MARCH

        undated = consolidate_session(config, [{"speaker": "Giuseppe", "text": "I moved."}], StubModel([]), session_id="43")
        assert undated.transcript.session_started is None

    def test_a_transcript_needs_a_usable_session_id(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        with pytest.raises(ValueError, match="needs a session_id"):
            consolidate_session(config, session(1), StubModel([]))
        for bad in ("../escape", "a/b", ".hidden", ""):
            with pytest.raises(ValueError):
                consolidate_session(config, session(1), StubModel([]), session_id=bad)
        assert Client().semantic("assistant-transcripts").list_documents() == []

    def test_a_dry_run_writes_no_transcript_and_no_fact(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        result = consolidate_session(config, session(4), StubModel([claim(turns=[0])]), session_id="42", dry_run=True)

        assert result.transcript is None and len(result.operations) == 1
        assert result.operations[0].claim.provenance == []
        assert episodes(config) == []
        assert Client().semantic("assistant-transcripts").list_documents() == []

    def test_a_restricted_vault_is_closed_to_another_agent(self, mock_global_config, real_chroma):
        config = facts_and_transcripts("assistant", global_vault=True)
        Client().attach("assistant-transcripts", "writer")
        Client().attach("assistant-facts", "writer")

        with pytest.raises(VaultAccessDeniedError):
            consolidate_session(config, session(2), StubModel([claim(turns=[0])]), session_id="42", agent="stranger")

        consolidate_session(config, session(2), StubModel([claim(turns=[0])]), session_id="42", agent="writer")
        [fact] = Client(agent="writer").episodic("assistant-facts").query_episodes(limit=5).results
        assert sources(fact, agent="writer")[0].state == "holds"
        assert sources(fact, agent="stranger")[0].state == "refused"

class TestTurnProvenance:
    def test_it_must_cover_every_turn(self, mock_episodic_vault_config):
        vault = vault_router.open_vault("test_episodic_vault")
        with pytest.raises(ValueError, match="turn_provenance"):
            consolidate(vault, session(2), StubModel([]), turn_provenance=[[]])

    def test_a_claim_without_turns_falls_back_to_the_general_provenance(self, mock_episodic_vault_config):
        vault = vault_router.open_vault("test_episodic_vault")
        general = [{"type": "external", "source": "whole-thread"}]
        by_turn = [[{"type": "external", "source": "thread", "locator": str(i)}] for i in range(2)]
        result = consolidate(vault, session(2), StubModel([claim(), claim(statement="Giuseppe has a dog", turns=[1])]),
                             provenance=general, turn_provenance=by_turn)

        loose, cited = [op.claim for op in result.operations]
        assert [p.source for p in loose.provenance] == ["whole-thread"]
        assert [(p.source, p.locator) for p in cited.provenance] == [("thread", "1")]

    def test_a_claim_keeps_the_provenance_it_came_with(self, mock_episodic_vault_config):
        vault = vault_router.open_vault("test_episodic_vault")
        own = [{"type": "external", "source": "the-model-said-so"}]
        result = consolidate(vault, session(1), StubModel([claim(turns=[0], provenance=own)]),
                             turn_provenance=[[{"type": "external", "source": "thread"}]])
        assert [p.source for p in result.operations[0].claim.provenance] == ["the-model-said-so"]

def test_the_schema_reads_turns():
    assert Claim.model_validate(claim(turns=[3, 1, 3])).turns == [1, 3]
    assert Claim.model_validate(claim()).turns == []
