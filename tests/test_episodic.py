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

class TestEntityListing:
    def test_lists_every_entity_with_counts(self, mock_episodic_vault_config):
        write("Giuseppe walks the dog", entities=["Giuseppe", "Briciola"])
        write("Briciola had her shots", entities=["Briciola"])
        write("The daughter called from Japan", entities=["Chiara", "Japan"])

        entities = vault_router.list_entities(vault_name=VAULT)
        counts = {e.entity_norm: e.episode_count for e in entities}

        assert counts == {"giuseppe": 1, "briciola": 2, "chiara": 1, "japan": 1}

    def test_ordered_by_how_often_mentioned(self, mock_episodic_vault_config):
        write("one", entities=["Briciola"])
        write("two", entities=["Briciola"])
        write("three", entities=["Chiara"])

        entities = vault_router.list_entities(vault_name=VAULT)

        assert [e.entity_norm for e in entities] == ["briciola", "chiara"]

    def test_surface_spelling_is_stable_across_casings(self, mock_episodic_vault_config):
        write("one", entities=["Briciola"])
        write("two", entities=["briciola"])

        entities = vault_router.list_entities(vault_name=VAULT)

        assert len(entities) == 1
        assert entities[0].entity == "Briciola"
        assert entities[0].episode_count == 2

    def test_closed_episodes_drop_out_unless_asked_for(self, mock_episodic_vault_config):
        episode = write("Giuseppe has a dog", entities=["Giuseppe", "Briciola"])
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id)
        write("Giuseppe walks every morning", entities=["Giuseppe"])

        open_only = {e.entity_norm for e in vault_router.list_entities(vault_name=VAULT)}
        everything = {
            e.entity_norm
            for e in vault_router.list_entities(vault_name=VAULT, include_closed=True)
        }

        assert open_only == {"giuseppe"}
        assert everything == {"giuseppe", "briciola"}

    def test_valid_at_reads_the_vocabulary_of_a_past_moment(self, mock_episodic_vault_config):
        write("Giuseppe lived in Mestre", entities=["Mestre"],
              valid_from="2020-01-01T00:00:00+00:00", valid_to="2023-01-01T00:00:00+00:00")
        write("Giuseppe lives in Padova", entities=["Padova"],
              valid_from="2023-01-01T00:00:00+00:00")

        then = vault_router.list_entities(vault_name=VAULT, valid_at="2021-06-01T00:00:00+00:00")
        now = vault_router.list_entities(vault_name=VAULT)

        assert [e.entity_norm for e in then] == ["mestre"]
        assert [e.entity_norm for e in now] == ["padova"]

    def test_min_episodes_drops_the_long_tail(self, mock_episodic_vault_config):
        write("one", entities=["Briciola"])
        write("two", entities=["Briciola"])
        write("three", entities=["Chiara"])

        entities = vault_router.list_entities(vault_name=VAULT, min_episodes=2)

        assert [e.entity_norm for e in entities] == ["briciola"]

    def test_empty_vault_lists_nothing(self, mock_episodic_vault_config):
        assert vault_router.list_entities(vault_name=VAULT) == []

    def test_listing_is_complete_past_any_query_limit(self, mock_episodic_vault_config):
        """The reason this operation exists.

        A query ranks and truncates, so deriving the vocabulary from its
        results silently loses whatever falls past the limit. Enumerating
        must not.
        """
        for n in range(250):
            write(f"fact {n}", entities=[f"entity{n:03d}"], salience=n / 250)

        from_query = {
            e for match in query(order_by="salience", limit=200) for e in match.entities
        }
        from_listing = {e.entity for e in vault_router.list_entities(vault_name=VAULT)}

        assert len(from_query) == 200
        assert len(from_listing) == 250
        assert from_query < from_listing

class TestEntityListingEndpoint:
    """The route carries a literal segment where episode ids also live.

    /episodes/entities must not be read as /episodes/{episode_id} with the id
    "entities", which is what happens if the two are registered in the wrong
    order.
    """

    def test_endpoint_lists_entities(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)

        write("Giuseppe walks the dog", entities=["Giuseppe", "Briciola"])
        write("Briciola had her shots", entities=["Briciola"])

        response = client.get("/ctxvault/episodes/entities", params={"vault_name": VAULT})

        assert response.status_code == 200
        body = response.json()
        assert body["vault_name"] == VAULT
        assert body["total"] == 2
        assert [e["entity_norm"] for e in body["entities"]] == ["briciola", "giuseppe"]
        assert body["entities"][0]["episode_count"] == 2

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

def days_from_now(days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def confirm(episode_id, **kwargs):
    return vault_router.confirm_episode(vault_name=VAULT, episode_id=episode_id, **kwargs)

def dispute(episode_id, other_id, **kwargs):
    return vault_router.dispute_episodes(vault_name=VAULT, episode_id=episode_id, other_id=other_id, **kwargs)

class TestConfirmation:
    def test_a_new_episode_is_unconfirmed(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")

        assert episode.confirmed_count == 0
        assert episode.last_confirmed_at is None

    def test_confirming_attests_without_changing_the_statement(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee", entities=["Giuseppe"], metadata={"topic": "habits"})

        confirm(episode.id)
        confirmed = confirm(episode.id, source="conversation")

        assert confirmed.confirmed_count == 2
        assert confirmed.last_confirmed_at is not None
        assert confirmed.content == episode.content
        assert confirmed.valid_from == episode.valid_from
        assert confirmed.metadata == {"topic": "habits"}
        assert confirmed.is_open
        assert vault_router.episode_stats(vault_name=VAULT)["total"] == 1

    def test_the_latest_attestation_is_reported_whatever_the_order(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee", valid_from="2026-01-01T00:00:00+00:00")

        confirm(episode.id, at="2026-03-01T00:00:00+00:00")
        confirmed = confirm(episode.id, at="2026-02-01T00:00:00+00:00")

        assert confirmed.confirmed_count == 2
        assert confirmed.last_confirmed_at == "2026-03-01T00:00:00+00:00"

    def test_known_at_reads_how_well_attested_it_was_then(self, mock_episodic_vault_config):
        """Attestations are events, not a counter, so a past instant reads
        the standing a belief had then and not the one it has now."""
        # `known_at` is transaction time, and the episode is recorded now, so
        # the instant to look back from has to lie after now: the
        # attestations are placed in the days ahead and read from between.
        episode = write("Giuseppe likes coffee")
        first, between, second = (days_from_now(10), days_from_now(20), days_from_now(40))
        confirm(episode.id, at=first)
        confirm(episode.id, at=second)

        then = query(known_at=between, valid_at=between)
        now = query(known_at=days_from_now(60), valid_at=days_from_now(60))

        assert len(then) == 1
        assert (then[0].confirmed_count, then[0].last_confirmed_at) == (1, first)
        assert (now[0].confirmed_count, now[0].last_confirmed_at) == (2, second)

    def test_confirming_before_the_start_is_refused(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee", valid_from="2026-03-01T00:00:00+00:00")

        with pytest.raises(ValueError):
            confirm(episode.id, at="2026-01-01T00:00:00+00:00")

    def test_a_closed_episode_cannot_be_confirmed(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id)

        with pytest.raises(EpisodeAlreadyClosedError):
            confirm(episode.id)

    def test_missing_episode_raises(self, mock_episodic_vault_config):
        with pytest.raises(EpisodeNotFoundError):
            confirm("nope")

    def test_endpoint_confirms(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        episode = write("Giuseppe likes coffee")

        response = client.post(f"/ctxvault/episodes/{episode.id}/confirm", json={"vault_name": VAULT})

        assert response.status_code == 200
        assert response.json()["episode"]["confirmed_count"] == 1

class TestDispute:
    def test_both_sides_stay_open_and_point_at_each_other(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre", entities=["Giuseppe"])
        padova = write("Giuseppe lives in Padova", entities=["Giuseppe"])

        dispute(mestre.id, padova.id, note="he said both this month")

        a = vault_router.get_episode(vault_name=VAULT, episode_id=mestre.id)
        b = vault_router.get_episode(vault_name=VAULT, episode_id=padova.id)
        assert a.disputed_with == [padova.id] and a.disputed
        assert b.disputed_with == [mestre.id] and b.disputed
        assert a.is_open and b.is_open
        assert {e.id for e in query(entities=["Giuseppe"])} == {mestre.id, padova.id}

    def test_a_dispute_is_not_a_belief_event(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")

        disputed = dispute(mestre.id, padova.id)

        assert disputed.content == mestre.content
        assert disputed.valid_from == mestre.valid_from
        assert disputed.recorded_at == mestre.recorded_at
        assert disputed.metadata == {}
        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 2, "open": 2, "closed": 0}

    def test_recording_the_same_pair_twice_is_harmless(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")

        dispute(mestre.id, padova.id)
        again = dispute(padova.id, mestre.id)

        assert again.disputed_with == [mestre.id]

    def test_superseding_one_side_settles_it(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        dispute(mestre.id, padova.id)

        vault_router.supersede_episode(vault_name=VAULT, episode_id=mestre.id, content="Giuseppe lives in Padova now")

        survivor = vault_router.get_episode(vault_name=VAULT, episode_id=padova.id)
        assert survivor.disputed_with == []
        assert not survivor.disputed

    def test_invalidating_one_side_settles_it(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        dispute(mestre.id, padova.id)

        vault_router.invalidate_episode(vault_name=VAULT, episode_id=padova.id)

        assert not vault_router.get_episode(vault_name=VAULT, episode_id=mestre.id).disputed

    def test_known_at_hides_a_dispute_noticed_later(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        dispute(mestre.id, padova.id, at=days_from_now(30))

        before = query(known_at=days_from_now(10), valid_at=days_from_now(10))
        after = query(known_at=days_from_now(60), valid_at=days_from_now(60))

        assert len(before) == 2 and not any(e.disputed for e in before)
        assert len(after) == 2 and all(e.disputed for e in after)

    def test_the_query_can_keep_only_what_is_unsettled(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        coffee = write("Giuseppe likes coffee")
        dispute(mestre.id, padova.id)

        assert {e.id for e in query(disputed=True)} == {mestre.id, padova.id}
        assert [e.id for e in query(disputed=False)] == [coffee.id]

    def test_a_closed_episode_cannot_be_disputed(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=mestre.id)

        with pytest.raises(EpisodeAlreadyClosedError):
            dispute(padova.id, mestre.id)

    def test_an_episode_cannot_dispute_itself(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")

        with pytest.raises(ValueError):
            dispute(mestre.id, mestre.id)

    def test_missing_episode_raises(self, mock_episodic_vault_config):
        mestre = write("Giuseppe lives in Mestre")

        with pytest.raises(EpisodeNotFoundError):
            dispute(mestre.id, "nope")

    def test_endpoint_disputes(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")

        response = client.post(
            f"/ctxvault/episodes/{mestre.id}/dispute",
            json={"vault_name": VAULT, "other_id": padova.id},
        )

        assert response.status_code == 200
        assert response.json()["episode"]["disputed_with"] == [padova.id]

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

    def test_a_v1_file_is_migrated_on_open(self, mock_episodic_vault_config):
        """A vault written before attestations and disputes existed opens,
        gains the tables, and reads its old rows as unconfirmed and
        undisputed."""
        db_path = mock_episodic_vault_config / "episodes.db"
        sqlite_store.close_connections()

        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('schema_version', '1');
            CREATE TABLE episodes (
                id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT,
                confidence REAL NOT NULL DEFAULT 1.0, salience REAL NOT NULL DEFAULT 0.5,
                occurred_at TEXT, valid_from TEXT NOT NULL, valid_to TEXT,
                recorded_at TEXT NOT NULL, invalidated_at TEXT,
                superseded_by TEXT REFERENCES episodes(id),
                recall_count INTEGER NOT NULL DEFAULT 0, last_recalled_at TEXT,
                metadata TEXT NOT NULL DEFAULT '{}', embedding BLOB
            );
            CREATE TABLE episode_entities (
                episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                entity TEXT NOT NULL, entity_norm TEXT NOT NULL,
                PRIMARY KEY (episode_id, entity_norm)
            );
            INSERT INTO episodes (id, content, valid_from, recorded_at)
            VALUES ('old1', 'Written under schema v1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
        """)
        conn.commit()
        conn.close()

        old = vault_router.get_episode(vault_name=VAULT, episode_id="old1")
        assert old.confirmed_count == 0
        assert old.last_confirmed_at is None
        assert old.disputed_with == []

        assert confirm("old1").confirmed_count == 1
        new = write("Written under schema v2")
        assert dispute("old1", new.id).disputed_with == [new.id]

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
