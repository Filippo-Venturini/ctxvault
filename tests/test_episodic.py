import json
import sqlite3

import pytest

from ctxvault.core import vault_router
from ctxvault.core.exceptions import (
    EpisodeAlreadyClosedError,
    EpisodeNotFoundError,
    SchemaVersionError,
    UnsupportedVaultOperationError,
    VaultTypeNotValidError,
)
from ctxvault.core.indexer import _extract_agent_metadata
from ctxvault.storage import sqlite_store

VAULT = "test_episodic_vault"

def write(content, **kwargs):
    return vault_router.write_episode(vault_name=VAULT, content=content, **kwargs)

def query(**kwargs):
    return vault_router.query_episodes(vault_name=VAULT, **kwargs).results

class TestWriteAndRead:
    def test_roundtrip_keeps_every_field(self, mock_episodic_vault_config):
        episode = write(
            "Giuseppe has a dog named Briciola",
            entities=["Giuseppe", "Briciola"],
            source="conversation",
            salience=0.8,
            confidence=0.9,
            metadata={"topic": "pets"},
        )

        stored = vault_router.get_episode(vault_name=VAULT, episode_id=episode.id)

        assert stored.content == "Giuseppe has a dog named Briciola"
        assert stored.entities == ["Briciola", "Giuseppe"]
        assert stored.source == "conversation"
        assert stored.salience == 0.8
        assert stored.confidence == 0.9
        assert stored.metadata == {"topic": "pets"}

    def test_new_episode_is_open_on_both_axes(self, mock_episodic_vault_config):
        episode = write("Giuseppe lives in Mestre")

        assert episode.valid_to is None
        assert episode.invalidated_at is None
        assert episode.superseded_by is None
        assert episode.is_open

    def test_valid_from_defaults_to_occurrence(self, mock_episodic_vault_config):
        episode = write("The daughter visited", occurred_at="2026-03-01T10:00:00+00:00")

        assert episode.valid_from == "2026-03-01T10:00:00+00:00"

    def test_empty_content_is_rejected(self, mock_episodic_vault_config):
        with pytest.raises(ValueError):
            write("   ")

    def test_missing_episode_raises(self, mock_episodic_vault_config):
        with pytest.raises(EpisodeNotFoundError):
            vault_router.get_episode(vault_name=VAULT, episode_id="nope")

class TestValidity:
    def test_open_episodes_are_returned_by_default(self, mock_episodic_vault_config):
        write("Giuseppe has a dog named Briciola", entities=["Briciola"])

        assert len(query(entities=["Briciola"])) == 1

    def test_closed_episodes_are_hidden_but_not_deleted(self, mock_episodic_vault_config):
        episode = write("Giuseppe has a dog named Briciola", entities=["Briciola"])

        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, reason="the dog died")

        assert query(entities=["Briciola"]) == []
        assert len(query(entities=["Briciola"], include_closed=True)) == 1

        closed = vault_router.get_episode(vault_name=VAULT, episode_id=episode.id)
        assert closed.valid_to is not None
        assert closed.invalidated_at is not None
        assert closed.metadata["invalidation_reason"] == "the dog died"

    def test_closing_twice_is_refused(self, mock_episodic_vault_config):
        episode = write("Giuseppe has a dog")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id)

        with pytest.raises(EpisodeAlreadyClosedError):
            vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id)

    def test_explicit_valid_to_can_be_in_the_past(self, mock_episodic_vault_config):
        episode = write("Giuseppe has a dog", valid_from="2026-03-01T00:00:00+00:00")

        closed = vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=episode.id, valid_to="2026-07-12T00:00:00+00:00"
        )

        # The statement stopped being true in July; we only learned it now.
        assert closed.valid_to == "2026-07-12T00:00:00+00:00"
        assert closed.invalidated_at > closed.valid_to

class TestImpossibleWindows:
    def test_closing_before_the_start_is_refused(self, mock_episodic_vault_config):
        episode = write("Giuseppe has a dog", valid_from="2026-03-01T00:00:00+00:00")

        with pytest.raises(ValueError, match="cannot stop holding before it starts"):
            vault_router.invalidate_episode(
                vault_name=VAULT, episode_id=episode.id, valid_to="2026-01-01T00:00:00+00:00"
            )

        # The refusal leaves the episode untouched, not half-closed.
        assert vault_router.get_episode(vault_name=VAULT, episode_id=episode.id).valid_to is None

    def test_superseding_before_the_start_is_refused(self, mock_episodic_vault_config):
        episode = write("Anna studies in Bologna", valid_from="2026-03-01T00:00:00+00:00")

        with pytest.raises(ValueError, match="cannot stop holding before it starts"):
            vault_router.supersede_episode(
                vault_name=VAULT,
                episode_id=episode.id,
                content="Anna studies in Milan",
                valid_from="2026-01-01T00:00:00+00:00",
            )

        assert vault_router.get_episode(vault_name=VAULT, episode_id=episode.id).superseded_by is None
        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 1, "open": 1, "closed": 0}

class TestSupersede:
    def test_old_closes_exactly_where_new_opens(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna", entities=["Anna"], salience=0.7, valid_from="2026-01-01T00:00:00+00:00")

        second = vault_router.supersede_episode(
            vault_name=VAULT,
            episode_id=first.id,
            content="Anna studies in Milan",
            entities=["Anna"],
            valid_from="2026-09-01T00:00:00+00:00",
        )

        closed = vault_router.get_episode(vault_name=VAULT, episode_id=first.id)

        assert closed.valid_to == second.valid_from
        assert closed.superseded_by == second.id
        assert second.valid_to is None

    def test_salience_is_inherited_unless_overridden(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna", salience=0.7)

        inherited = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=first.id, content="Anna studies in Milan"
        )
        assert inherited.salience == 0.7

        overridden = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=inherited.id, content="Anna works in Milan", salience=0.2
        )
        assert overridden.salience == 0.2

    def test_entities_are_inherited_unless_overridden(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna", entities=["Anna"])

        inherited = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=first.id, content="Anna studies in Milan"
        )
        assert inherited.entities == ["Anna"]
        assert len(query(entities=["Anna"])) == 1

        replaced = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=inherited.id, content="Marco studies in Milan", entities=["Marco"]
        )
        assert replaced.entities == ["Marco"]

    def test_only_the_current_version_is_visible(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna", entities=["Anna"])
        vault_router.supersede_episode(vault_name=VAULT, episode_id=first.id, content="Anna studies in Milan", entities=["Anna"])

        results = query(entities=["Anna"])

        assert len(results) == 1
        assert results[0].content == "Anna studies in Milan"

    def test_superseding_a_closed_episode_is_refused(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna")
        vault_router.supersede_episode(vault_name=VAULT, episode_id=first.id, content="Anna studies in Milan")

        with pytest.raises(EpisodeAlreadyClosedError):
            vault_router.supersede_episode(vault_name=VAULT, episode_id=first.id, content="Anna studies in Rome")

    def test_history_returns_the_chain_oldest_first(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna")
        second = vault_router.supersede_episode(vault_name=VAULT, episode_id=first.id, content="Anna studies in Milan")
        third = vault_router.supersede_episode(vault_name=VAULT, episode_id=second.id, content="Anna works in Milan")

        # Asking from the middle still returns the whole chain.
        chain = vault_router.episode_history(vault_name=VAULT, episode_id=second.id).chain

        assert [e.id for e in chain] == [first.id, second.id, third.id]

class TestTimeTravel:
    def test_valid_at_recovers_what_was_true_then(self, mock_episodic_vault_config):
        first = write("Anna studies in Bologna", entities=["Anna"], valid_from="2026-01-01T00:00:00+00:00")
        vault_router.supersede_episode(
            vault_name=VAULT,
            episode_id=first.id,
            content="Anna studies in Milan",
            entities=["Anna"],
            valid_from="2026-09-01T00:00:00+00:00",
        )

        past = query(entities=["Anna"], valid_at="2026-05-01T00:00:00+00:00")
        present = query(entities=["Anna"])

        assert [e.content for e in past] == ["Anna studies in Bologna"]
        assert [e.content for e in present] == ["Anna studies in Milan"]

    def test_known_at_hides_what_had_not_been_recorded_yet(self, mock_episodic_vault_config):
        write("Giuseppe lives in Mestre", valid_from="2020-01-01T00:00:00+00:00")

        # True in the world back then, but this vault had not been told.
        assert query(valid_at="2021-01-01T00:00:00+00:00", known_at="2021-01-01T00:00:00+00:00") == []
        assert len(query(valid_at="2021-01-01T00:00:00+00:00")) == 1

class TestFiltersAndOrdering:
    def test_entity_match_ignores_case(self, mock_episodic_vault_config):
        write("Anna graduated", entities=["Anna"])

        assert len(query(entities=["anna"])) == 1
        assert query(entities=["marco"]) == []

    def test_source_and_confidence_filters(self, mock_episodic_vault_config):
        write("Reported by the daughter", source="daughter", confidence=0.9)
        write("Reported by the patient", source="patient", confidence=0.4)

        assert len(query(source="daughter")) == 1
        assert len(query(min_confidence=0.5)) == 1

    def test_metadata_filters(self, mock_episodic_vault_config):
        write("A health note", metadata={"visibility": "caregiver"})
        write("A family note", metadata={"visibility": "family"})

        results = query(metadata_filters={"visibility": "family"})

        assert [e.content for e in results] == ["A family note"]

    def test_order_by_salience(self, mock_episodic_vault_config):
        write("Minor detail", salience=0.1)
        write("What matters", salience=0.9)

        results = query(order_by="salience")

        assert results[0].content == "What matters"

    def test_relevance_falls_back_to_keywords_without_embeddings(self, mock_episodic_vault_config):
        write("Giuseppe worked as a railwayman in Mestre")
        write("The weather was good today")

        results = query(text="railwayman Mestre")

        assert results[0].content.startswith("Giuseppe worked")
        assert results[0].similarity > 0

    def test_composite_blends_the_three_signals(self, mock_episodic_vault_config):
        write("Old but important", salience=1.0, valid_from="2020-01-01T00:00:00+00:00")
        write("Recent and trivial", salience=0.0)

        results = query(order_by="composite", weights={"relevance": 0.0, "recency": 0.1, "salience": 1.0})

        assert results[0].content == "Old but important"

    def test_relevance_without_text_is_refused(self, mock_episodic_vault_config):
        with pytest.raises(ValueError):
            query(order_by="relevance")

    def test_unknown_order_is_refused(self, mock_episodic_vault_config):
        with pytest.raises(ValueError):
            query(order_by="whatever")

    def test_limit_is_honoured(self, mock_episodic_vault_config):
        for i in range(5):
            write(f"Episode {i}")

        assert len(query(limit=2)) == 2

class TestReinforcement:
    def test_recall_is_not_recorded_unless_asked(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")

        query()

        assert vault_router.get_episode(vault_name=VAULT, episode_id=episode.id).recall_count == 0

    def test_reinforce_bumps_the_counter(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")

        query(reinforce=True)

        refreshed = vault_router.get_episode(vault_name=VAULT, episode_id=episode.id)
        assert refreshed.recall_count == 1
        assert refreshed.last_recalled_at is not None

class TestVaultContract:
    def test_episodic_vault_refuses_file_indexing(self, mock_episodic_vault_config):
        with pytest.raises(UnsupportedVaultOperationError):
            vault_router.index_files(vault_name=VAULT)

    def test_semantic_vault_refuses_episodes(self, mock_vault_config):
        with pytest.raises(UnsupportedVaultOperationError):
            vault_router.write_episode(vault_name="test_vault", content="nope")

    def test_unknown_vault_type_fails_loudly(self, mock_vault_config, monkeypatch):
        monkeypatch.setattr(
            "ctxvault.core.vault_router.get_vault_config",
            lambda vault_name: {"type": "from-the-future", "vault_path": "/tmp/x", "db_path": None},
        )

        with pytest.raises(VaultTypeNotValidError):
            vault_router.query_episodes(vault_name="test_vault")

    def test_stats_count_open_and_closed(self, mock_episodic_vault_config):
        first = write("Still true")
        write("Also true")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=first.id)

        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 2, "open": 1, "closed": 1}

class TestSchemaVersioning:
    def test_version_is_stamped_on_creation(self, mock_episodic_vault_config):
        write("anything")
        db_path = mock_episodic_vault_config / "episodes.db"

        conn = sqlite3.connect(db_path)
        stored = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        conn.close()

        assert int(stored) == sqlite_store.SCHEMA_VERSION

    def test_a_newer_file_is_refused_instead_of_misread(self, mock_episodic_vault_config):
        write("anything")
        db_path = mock_episodic_vault_config / "episodes.db"
        sqlite_store.close_connections()

        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(sqlite_store.SCHEMA_VERSION + 1),))
        conn.commit()
        conn.close()

        with pytest.raises(SchemaVersionError):
            query()

class TestReindexMetadata:
    def test_agent_metadata_survives_a_reindex(self):
        metadatas = [{
            "doc_id": "1",
            "chunk_id": "1::0",
            "chunk_index": 0,
            "source": "notes.md",
            "filetype": ".md",
            "indexed_at": "2026-01-01T00:00:00+00:00",
            "generated_by": "agent-7",
            "topic": "pets",
        }]

        assert _extract_agent_metadata(metadatas) == {"generated_by": "agent-7", "topic": "pets"}

    def test_built_in_only_metadata_yields_nothing(self):
        assert _extract_agent_metadata([{"doc_id": "1", "chunk_index": 0, "source": "a", "filetype": ".md"}]) is None
