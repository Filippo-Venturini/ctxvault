import json
import sqlite3

import pytest

from ctxvault.core import vault_router
from ctxvault.core.exceptions import (
    EpisodeAlreadyClosedError,
    EpisodeAlreadyOpenError,
    EpisodeNotFoundError,
    EpisodeSuccessorStillOpenError,
    EpisodeWasRevisedError,
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
        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 1, "open": 1, "closed": 0, "holding": 1, "disputes": 0}

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

    def test_an_end_recorded_later_was_not_yet_known_and_an_end_is_not_a_retraction(self, mock_episodic_vault_config):
        from ctxvault.core import vault_router as router
        from ctxvault.storage import sqlite_store
        episode = write("Giuseppe lives in Mestre", valid_from="2026-01-01T00:00:00+00:00")
        # recorded in January; the vault learns today that it ended in February
        conn = sqlite_store.get_connection(router.open_vault(VAULT).config)
        with conn:
            conn.execute("UPDATE episodes SET recorded_at = ? WHERE id = ?", ("2026-01-01T00:00:00+00:00", episode.id))
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, valid_to="2026-02-01T00:00:00+00:00")

        march = "2026-03-01T00:00:00+00:00"
        # as the vault stood in March, nothing had ended: the statement was open
        assert [e.id for e in query(valid_at=march, known_at=march)] == [episode.id]
        # as the vault stands today, it had ended in February
        assert query(valid_at=march) == []
        # and today the vault still holds that it was true in January: ended, not retracted
        january = "2026-01-15T00:00:00+00:00"
        assert [e.id for e in query(valid_at=january, known_at=days_from_now(1))] == [episode.id]

    def test_history_can_be_replayed_with_its_own_recording_times(self, mock_episodic_vault_config):
        from ctxvault.core import vault_router as router
        march, june, september = "2026-03-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"
        plan = write("On the Trial plan", valid_from=march, recorded_at=march)
        pro = router.supersede_episode(VAULT, plan.id, "On the Pro plan", at=june, valid_from=june)
        precise = router.revise_episode(VAULT, pro.id, "On the Pro plan, billed yearly", at=september)
        router.invalidate_episode(VAULT, precise.id, at="2026-10-01T00:00:00+00:00")

        assert plan.recorded_at == march and pro.recorded_at == june and precise.recorded_at == september
        assert router.get_episode(VAULT, plan.id).invalidated_at == june
        assert router.get_episode(VAULT, pro.id).invalidated_at == september
        assert router.get_episode(VAULT, precise.id).invalidated_at == "2026-10-01T00:00:00+00:00"
        # as the vault stood in July: the Pro plan, as first stated
        assert [e.id for e in query(valid_at="2026-07-01T00:00:00+00:00", known_at="2026-07-01T00:00:00+00:00")] == [pro.id]

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

def reopen(episode_id, **kwargs):
    return vault_router.reopen_episode(vault_name=VAULT, episode_id=episode_id, **kwargs)

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

class TestInvalidateEndpoint:
    def test_closing_before_the_start_is_a_client_error_not_a_crash(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        episode = write("Giuseppe likes coffee", valid_from="2026-03-01T00:00:00+00:00")

        response = client.post(
            f"/ctxvault/episodes/{episode.id}/invalidate",
            json={"vault_name": VAULT, "valid_to": "2026-01-01T00:00:00+00:00"},
        )

        assert response.status_code == 400
        assert "before" in response.json()["detail"]

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
        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 2, "open": 2, "closed": 0, "holding": 2, "disputes": 1}

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

        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 2, "open": 1, "closed": 1, "holding": 1, "disputes": 0}

    def test_the_distinct_values_of_a_metadata_key_can_be_listed(self, mock_episodic_vault_config):
        from ctxvault.core import vault_router as router
        write("Pill at 8", metadata={"card": "health"})
        closed = write("Lived in Mestre", metadata={"card": "home"})
        write("Likes coffee", metadata={"card": "habits", "tags": ["a", "b"]})
        write("Reads", metadata={"card": "habits"})
        write("No card")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=closed.id)

        now = router.list_metadata_values(VAULT, "card")
        everything = router.list_metadata_values(VAULT, "card", include_closed=True)

        assert [(v["value"], v["episode_count"]) for v in now] == [("habits", 2), ("health", 1)]
        assert [(v["value"], v["episode_count"]) for v in everything] == [("habits", 2), ("health", 1), ("home", 1)]
        assert router.list_metadata_values(VAULT, "tags") == [{"value": '["a","b"]', "episode_count": 1}]
        assert router.list_metadata_values(VAULT, "nothing") == []

    def test_stats_tell_open_rows_from_what_holds_now(self, mock_episodic_vault_config):
        # open is the row's own state; holding is what a default query returns
        write("Starts next century", valid_from="2099-01-01T00:00:00+00:00")
        a = write("Pill at 8")
        b = write("Pill in the evening")
        vault_router.dispute_episodes(vault_name=VAULT, episode_id=a.id, other_id=b.id)

        stats = vault_router.episode_stats(vault_name=VAULT)

        assert stats["open"] == 3 and stats["holding"] == 2 and stats["disputes"] == 1

    def test_the_whole_vault_can_be_read_without_the_scan_limit(self, mock_episodic_vault_config):
        from ctxvault.core import vault_router as router
        from ctxvault.storage import sqlite_store
        for i in range(3):
            write(f"fact {i}")
        vault = router.open_vault(VAULT)

        assert len(sqlite_store.select_episodes(vault.config, include_closed=True, scan_limit=2)) == 2
        assert len(sqlite_store.select_episodes(vault.config, include_closed=True, scan_limit=None)) == 3
        assert len(vault.all_episodes()) == 3
        assert len(vault.changes()) == 3                 # three recordings, nothing else yet

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
        # v3: the migrated row can be revised, and the revision keeps the attestation
        revised = vault_router.revise_episode(vault_name=VAULT, episode_id="old1",
                                              content="Written under schema v1, said better")
        assert revised.confirmed_count == 1
        assert vault_router.get_episode(vault_name=VAULT, episode_id="old1").revised_by == revised.id
        # v4: a revised original cannot be reopened; a merely closed
        # migrated row can, and the store now has episode_closures.
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=revised.id)
        with pytest.raises(EpisodeWasRevisedError) as raised:
            reopen("old1")
        assert revised.id in str(raised.value)
        temporary = write("a close to undo")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=temporary.id)
        restored = reopen(temporary.id)
        assert restored.is_open and restored.reopened_at is not None

        conn = sqlite3.connect(db_path)
        stored = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        assert int(stored) == sqlite_store.SCHEMA_VERSION
        assert "episode_closures" in tables

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

class TestRevise:
    """The world did not change, the wording did."""

    def test_a_revision_keeps_the_validity_and_the_attestations(self, mock_episodic_vault_config):
        first = write("Anna lives in Padova", entities=["Anna"], salience=0.7,
                      valid_from="2026-01-01T00:00:00+00:00", metadata={"card": "anna", "slot": "dove"})
        vault_router.confirm_episode(vault_name=VAULT, episode_id=first.id, at="2026-02-01T00:00:00+00:00")
        vault_router.confirm_episode(vault_name=VAULT, episode_id=first.id, at="2026-03-01T00:00:00+00:00")

        revised = vault_router.revise_episode(
            vault_name=VAULT, episode_id=first.id, content="Anna lives in Padova, in the Arcella")

        assert revised.valid_from == first.valid_from          # nothing changed in the world
        assert revised.valid_to is None and revised.is_open
        assert revised.confirmed_count == 2                      # what attested the fact attests its wording
        assert revised.last_confirmed_at == "2026-03-01T00:00:00+00:00"
        assert revised.entities == ["Anna"] and revised.salience == 0.7
        assert revised.metadata == {"card": "anna", "slot": "dove", "revision_of": first.id}

        original = vault_router.get_episode(vault_name=VAULT, episode_id=first.id)
        assert original.revised_by == revised.id
        assert original.superseded_by is None
        assert original.valid_to is None                         # still true in the world
        assert original.invalidated_at is not None               # no longer how the vault says it
        assert original.metadata["invalidation_reason"] == "revised"

    def test_only_the_revision_is_what_the_vault_states(self, mock_episodic_vault_config):
        first = write("Anna lives in Padova", entities=["Anna"])
        revised = vault_router.revise_episode(vault_name=VAULT, episode_id=first.id,
                                              content="Anna lives in Padova, in the Arcella")

        assert [e.id for e in query(entities=["Anna"])] == [revised.id]
        assert {e.id for e in query(entities=["Anna"], include_closed=True)} == {first.id, revised.id}
        # Before the revision was recorded, the original was the belief.
        before = query(entities=["Anna"], known_at=first.recorded_at)
        assert [e.id for e in before] == [first.id]
        assert vault_router.episode_stats(vault_name=VAULT) == {"total": 2, "open": 1, "closed": 1, "holding": 1, "disputes": 0}

    def test_an_open_dispute_follows_the_revision(self, mock_episodic_vault_config):
        bologna = write("Anna lives in Bologna", entities=["Anna"])
        padova = write("Anna lives in Padova", entities=["Anna"])
        vault_router.dispute_episodes(vault_name=VAULT, episode_id=bologna.id, other_id=padova.id)

        revised = vault_router.revise_episode(vault_name=VAULT, episode_id=padova.id,
                                              content="Anna lives in Padova, in the Arcella")

        assert revised.disputed_with == [bologna.id]
        assert vault_router.get_episode(vault_name=VAULT, episode_id=bologna.id).disputed_with == [revised.id]

    def test_the_history_walks_through_revisions_and_supersessions(self, mock_episodic_vault_config):
        first = write("Anna lives in Padova", entities=["Anna"], valid_from="2026-01-01T00:00:00+00:00")
        revised = vault_router.revise_episode(vault_name=VAULT, episode_id=first.id,
                                              content="Anna lives in Padova, in the Arcella")
        moved = vault_router.supersede_episode(vault_name=VAULT, episode_id=revised.id,
                                               content="Anna lives in Milan",
                                               valid_from="2026-09-01T00:00:00+00:00")

        chain = vault_router.episode_history(vault_name=VAULT, episode_id=first.id).chain
        assert [e.id for e in chain] == [first.id, revised.id, moved.id]
        assert [e.id for e in vault_router.episode_history(vault_name=VAULT, episode_id=moved.id).chain] == \
            [first.id, revised.id, moved.id]

    def test_a_closed_episode_cannot_be_revised(self, mock_episodic_vault_config):
        first = write("Anna lives in Padova")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=first.id)

        with pytest.raises(EpisodeAlreadyClosedError):
            vault_router.revise_episode(vault_name=VAULT, episode_id=first.id, content="Anna lives in Padova, Arcella")

    def test_endpoint_revises(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        episode = write("Giuseppe likes coffee", entities=["Giuseppe"])
        client.post(f"/ctxvault/episodes/{episode.id}/confirm", json={"vault_name": VAULT})

        response = client.post(f"/ctxvault/episodes/{episode.id}/revise",
                               json={"vault_name": VAULT, "content": "Giuseppe likes his coffee long"})

        assert response.status_code == 200
        body = response.json()["episode"]
        assert body["content"] == "Giuseppe likes his coffee long"
        assert body["confirmed_count"] == 1 and body["metadata"]["revision_of"] == episode.id
        again = client.post(f"/ctxvault/episodes/{episode.id}/revise",
                            json={"vault_name": VAULT, "content": "twice"})
        assert again.status_code == 409


class TestEmbeddingAfterTheFact:
    def test_a_vault_given_a_model_later_embeds_what_it_already_holds(self, mock_episodic_vault_config):
        from ctxvault.utils.config import set_embedding_model
        write("Giuseppe keeps bees on the hill behind the house", entities=["Giuseppe"])
        write("Giuseppe takes the bus to the market on Thursdays", entities=["Giuseppe"])
        config = vault_router.open_vault(VAULT).config
        assert all(sqlite_store.get_episode(config, e["id"], with_embedding=True)["embedding"] is None
                   for e in sqlite_store.episodes_without_embedding(config))
        with pytest.raises(UnsupportedVaultOperationError):
            vault_router.reindex_files(vault_name=VAULT)

        set_embedding_model(VAULT, "sentence-transformers/all-MiniLM-L6-v2")
        done, skipped = vault_router.reindex_files(vault_name=VAULT)
        assert len(done) == 2 and skipped == []
        assert sqlite_store.episodes_without_embedding(vault_router.open_vault(VAULT).config) == []

        # vectors from now on (the test environment stubs the model, so the
        # ordering is not asserted here; only that similarity is computed)
        results = query(text="honey and hives", entities=["Giuseppe"], order_by="relevance")
        assert len(results) == 2 and all(r.similarity is not None for r in results)
        # and a new episode is written with its vector at once
        new = write("Giuseppe sells honey at the market", entities=["Giuseppe"])
        assert sqlite_store.get_episode(vault_router.open_vault(VAULT).config, new.id, with_embedding=True)["embedding"]
class TestReopen:
    """A close can be undone without erasing it."""

    def test_an_invalidated_episode_becomes_current_again(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee", entities=["Giuseppe"])
        vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=episode.id, reason="the shop closed"
        )
        assert query() == []

        restored = reopen(episode.id, reason="it reopened")

        assert restored.is_open
        assert restored.valid_to is None
        assert restored.invalidated_at is None
        assert restored.reopened_at is not None
        assert restored.reopen_reason == "it reopened"
        assert "invalidation_reason" not in restored.metadata
        assert {e.id for e in query()} == {episode.id}

    def test_as_of_between_the_close_and_the_reopen_still_sees_it_closed(
        self, mock_episodic_vault_config
    ):
        written, closed, reopened = (
            days_from_now(-30),
            days_from_now(-20),
            days_from_now(-10),
        )
        episode = write("Giuseppe likes coffee", recorded_at=written, valid_from=written)
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, at=closed)
        reopen(episode.id, at=reopened)

        before = query(known_at=days_from_now(-25), valid_at=days_from_now(-25))
        during = query(known_at=days_from_now(-15), valid_at=days_from_now(-15))
        after = query(known_at=days_from_now(-5), valid_at=days_from_now(-5))

        assert [e.id for e in before] == [episode.id]
        assert before[0].invalidated_at is None and before[0].reopened_at is None
        assert during == []
        closed_as_of = query(known_at=days_from_now(-15), include_closed=True)
        assert [e.id for e in closed_as_of] == [episode.id]
        assert closed_as_of[0].invalidated_at == closed
        assert [e.id for e in after] == [episode.id]
        assert after[0].is_open and after[0].reopened_at == reopened

    def test_history_shows_the_reopen_and_keeps_the_successor(self, mock_episodic_vault_config):
        first = write("Sarah Klein is the main contact", entities=["Sarah"])
        second = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=first.id, content="Marco Rossi is the main contact"
        )
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=second.id)
        restored = reopen(first.id)

        chain = vault_router.episode_history(vault_name=VAULT, episode_id=first.id).chain
        assert [e.id for e in chain] == [first.id, second.id]
        assert chain[0].is_open and chain[0].reopened_at is not None
        assert not chain[1].is_open
        assert {e.id for e in query()} == {first.id}
        # The successor link is preserved for the history even though the
        # current row was cleared so default queries can see the original.
        assert restored.reopened_at is not None

    def test_reopening_fails_while_the_successor_is_current(self, mock_episodic_vault_config):
        first = write("Sarah Klein is the main contact")
        second = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=first.id, content="Marco Rossi is the main contact"
        )

        with pytest.raises(EpisodeSuccessorStillOpenError) as raised:
            reopen(first.id)
        assert second.id in str(raised.value)
        assert not vault_router.get_episode(vault_name=VAULT, episode_id=first.id).is_open
        assert vault_router.get_episode(vault_name=VAULT, episode_id=second.id).is_open

    def test_a_revised_original_cannot_be_reopened(
        self, mock_episodic_vault_config
    ):
        first = write("Anna lives in Padova")
        revision = vault_router.revise_episode(
            vault_name=VAULT, episode_id=first.id, content="Anna lives in Padova, in the Arcella"
        )

        with pytest.raises(EpisodeWasRevisedError) as raised:
            reopen(first.id)
        assert revision.id in str(raised.value)

        vault_router.invalidate_episode(vault_name=VAULT, episode_id=revision.id)
        with pytest.raises(EpisodeWasRevisedError) as raised:
            reopen(first.id)
        assert revision.id in str(raised.value)
        assert not vault_router.get_episode(vault_name=VAULT, episode_id=first.id).is_open
        chain = vault_router.episode_history(vault_name=VAULT, episode_id=first.id).chain
        assert [e.id for e in chain] == [first.id, revision.id]

    def test_reopening_an_open_episode_is_refused(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")
        with pytest.raises(EpisodeAlreadyOpenError):
            reopen(episode.id)

    def test_a_missing_episode_cannot_be_reopened(self, mock_episodic_vault_config):
        with pytest.raises(EpisodeNotFoundError):
            reopen("does-not-exist")

    def test_reopening_before_the_close_is_refused(self, mock_episodic_vault_config):
        episode = write(
            "Giuseppe likes coffee", recorded_at=days_from_now(-10), valid_from=days_from_now(-10)
        )
        vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=episode.id, at=days_from_now(-2)
        )
        with pytest.raises(ValueError, match="before the episode's close"):
            reopen(episode.id, at=days_from_now(-5))

    def test_a_settled_dispute_returns_once_the_closed_side_is_reopened(
        self, mock_episodic_vault_config
    ):
        mestre = write("Giuseppe lives in Mestre")
        padova = write("Giuseppe lives in Padova")
        dispute(mestre.id, padova.id)
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=padova.id)
        assert not vault_router.get_episode(vault_name=VAULT, episode_id=mestre.id).disputed

        restored = reopen(padova.id)

        assert restored.disputed_with == [mestre.id]
        assert vault_router.get_episode(vault_name=VAULT, episode_id=mestre.id).disputed_with == [
            padova.id
        ]
        assert {e.id for e in query(disputed=True)} == {mestre.id, padova.id}

    def test_as_of_during_the_settled_window_hides_the_dispute(self, mock_episodic_vault_config):
        written, closed, reopened = (
            days_from_now(-30),
            days_from_now(-20),
            days_from_now(-10),
        )
        mestre = write("Giuseppe lives in Mestre", recorded_at=written, valid_from=written)
        padova = write("Giuseppe lives in Padova", recorded_at=written, valid_from=written)
        dispute(mestre.id, padova.id, at=written)
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=padova.id, at=closed)
        reopen(padova.id, at=reopened)

        during = query(known_at=days_from_now(-15), valid_at=days_from_now(-15))
        after = query(known_at=days_from_now(-5), valid_at=days_from_now(-5))

        assert {e.id for e in during} == {mestre.id}
        assert not during[0].disputed
        assert {e.id for e in after} == {mestre.id, padova.id}
        assert all(e.disputed for e in after)

    def test_it_can_be_closed_again_and_the_open_window_stays_reconstructable(
        self, mock_episodic_vault_config
    ):
        written, closed, reopened, closed_again = (
            days_from_now(-40),
            days_from_now(-30),
            days_from_now(-20),
            days_from_now(-10),
        )
        episode = write("Giuseppe likes coffee", recorded_at=written, valid_from=written)
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, at=closed)
        reopen(episode.id, at=reopened)
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, at=closed_again)

        mid = query(known_at=days_from_now(-15), valid_at=days_from_now(-15))
        late = query(known_at=days_from_now(-5), valid_at=days_from_now(-5))

        assert [e.id for e in mid] == [episode.id] and mid[0].is_open
        assert late == []
        assert not vault_router.get_episode(vault_name=VAULT, episode_id=episode.id).is_open

    def test_the_http_endpoint_reopens_an_episode(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        episode = write("Giuseppe likes coffee")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id)

        response = client.post(
            f"/ctxvault/episodes/{episode.id}/reopen",
            json={"vault_name": VAULT, "reason": "false alarm"},
        )

        assert response.status_code == 200
        body = response.json()["episode"]
        assert body["invalidated_at"] is None
        assert body["reopened_at"] is not None


class TestReviewRegressions:
    """Bugs the maintainer reported on PR #48's reconstruction approach.

    These fail on the first reopen implementation and pass once known_at
    uses closure intervals and metadata comes from the row itself.
    """

    def test_known_at_before_a_never_reopened_close_keeps_row_metadata(
        self, mock_episodic_vault_config,
    ):
        from ctxvault.core import vault_router as router

        vault = router.open_vault(VAULT)
        written = sqlite_store.write_episode(
            vault.config,
            content="Likes coffee",
            metadata={"generated_by": "agent-x"},
            recorded_at="2026-01-01T00:00:00+00:00",
            valid_from="2026-01-01T00:00:00+00:00",
        )
        sqlite_store.invalidate_episode(
            vault.config,
            written["id"],
            valid_to="2026-06-01T00:00:00+00:00",
            at="2026-06-01T00:00:00+00:00",
        )

        as_of = sqlite_store.select_episodes(
            vault.config, known_at="2026-03-01T00:00:00+00:00",
        )

        assert len(as_of) == 1
        assert as_of[0]["metadata"]["generated_by"] == "agent-x"
        assert as_of[0]["invalidated_at"] is None
        assert as_of[0]["valid_to"] is None

    def test_scan_limit_is_applied_after_the_known_at_filter(
        self, mock_episodic_vault_config,
    ):
        # Five older episodes still open at T, then five newer ones closed
        # before T. ORDER BY valid_from DESC plus a SQL LIMIT of 5 before
        # the Python known_at filter returns nothing; the filter must
        # happen in SQL so the five older rows are kept.
        from ctxvault.core import vault_router as router

        vault = router.open_vault(VAULT)
        older = [
            sqlite_store.write_episode(
                vault.config,
                content=f"old {i}",
                valid_from=f"2026-01-0{i + 1}T00:00:00+00:00",
                recorded_at="2026-01-01T00:00:00+00:00",
            )
            for i in range(5)
        ]
        newer = [
            sqlite_store.write_episode(
                vault.config,
                content=f"new {i}",
                valid_from=f"2026-06-0{i + 1}T00:00:00+00:00",
                recorded_at="2026-01-01T00:00:00+00:00",
            )
            for i in range(5)
        ]
        for episode in newer:
            sqlite_store.invalidate_episode(
                vault.config, episode["id"], at="2026-06-15T00:00:00+00:00",
            )

        found = sqlite_store.select_episodes(
            vault.config,
            known_at="2026-07-01T00:00:00+00:00",
            scan_limit=5,
        )

        assert {e["id"] for e in found} == {e["id"] for e in older}
        assert all(e["invalidated_at"] is None for e in found)

    def test_a_written_in_valid_to_is_restored_on_reopen(
        self, mock_episodic_vault_config,
    ):
        episode = write(
            "The lease ends in December",
            recorded_at="2026-01-01T00:00:00+00:00",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-12-31T00:00:00+00:00",
        )
        vault_router.invalidate_episode(
            vault_name=VAULT,
            episode_id=episode.id,
            at="2026-06-01T00:00:00+00:00",
        )
        restored = reopen(episode.id)

        assert restored.valid_to == "2026-12-31T00:00:00+00:00"
        assert [e.id for e in query()] == [episode.id]

    def test_history_exposes_the_reopen_reason(self, mock_episodic_vault_config):
        first = write("Sarah Klein is the main contact")
        second = vault_router.supersede_episode(
            vault_name=VAULT, episode_id=first.id, content="Marco Rossi is the main contact"
        )
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=second.id)
        reopen(first.id, reason="the report was a false alarm")

        chain = vault_router.episode_history(vault_name=VAULT, episode_id=first.id).chain
        assert chain[0].reopen_reason == "the report was a false alarm"
        assert chain[0].reopened_at is not None

    def test_multiple_close_reopen_cycles_keep_each_interval(
        self, mock_episodic_vault_config
    ):
        written, closed, reopened, closed_again, reopened_again = (
            days_from_now(-50),
            days_from_now(-40),
            days_from_now(-30),
            days_from_now(-20),
            days_from_now(-10),
        )
        episode = write(
            "The lease ends in December",
            recorded_at=written,
            valid_from=written,
            valid_to="2026-12-31T00:00:00+00:00",
        )
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, at=closed)
        reopen(episode.id, at=reopened, reason="first undo")
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=episode.id, at=closed_again)
        restored = reopen(episode.id, at=reopened_again, reason="second undo")

        assert restored.valid_to == "2026-12-31T00:00:00+00:00"
        assert restored.reopen_reason == "second undo"
        during_first_close = query(known_at=days_from_now(-35), include_closed=True)
        assert during_first_close[0].invalidated_at == closed
        mid_open = query(known_at=days_from_now(-25), valid_at=days_from_now(-25))
        assert [e.id for e in mid_open] == [episode.id] and mid_open[0].is_open is False
        assert mid_open[0].valid_to == "2026-12-31T00:00:00+00:00"
        assert mid_open[0].reopen_reason == "first undo"
        during_second = query(known_at=days_from_now(-15), valid_at=days_from_now(-15))
        assert during_second == []
        after = query(known_at=days_from_now(-5), valid_at=days_from_now(-5))
        assert [e.id for e in after] == [episode.id]
        assert after[0].reopened_at == reopened_again
        assert after[0].reopen_reason == "second undo"

    def test_a_v3_closed_row_is_backfilled_with_a_null_prior_valid_to(
        self, mock_episodic_vault_config, tmp_path,
    ):
        """Closed rows from before closures existed get a closure whose
        prior_valid_to is NULL, because that earlier end was overwritten."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('schema_version', '3');
            CREATE TABLE episodes (
                id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT,
                confidence REAL NOT NULL DEFAULT 1.0, salience REAL NOT NULL DEFAULT 0.5,
                occurred_at TEXT, valid_from TEXT NOT NULL, valid_to TEXT,
                recorded_at TEXT NOT NULL, invalidated_at TEXT,
                superseded_by TEXT REFERENCES episodes(id),
                revised_by TEXT REFERENCES episodes(id),
                recall_count INTEGER NOT NULL DEFAULT 0, last_recalled_at TEXT,
                metadata TEXT NOT NULL DEFAULT '{}', embedding BLOB
            );
            CREATE TABLE episode_entities (
                episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                entity TEXT NOT NULL, entity_norm TEXT NOT NULL,
                PRIMARY KEY (episode_id, entity_norm)
            );
            INSERT INTO episodes (
                id, content, valid_from, valid_to, recorded_at, invalidated_at, metadata
            ) VALUES (
                'old-closed',
                'Was already closed under v3',
                '2026-01-01T00:00:00+00:00',
                '2026-06-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00',
                '2026-06-01T00:00:00+00:00',
                '{"generated_by": "agent-x", "invalidation_reason": "ended"}'
            );
        """)
        conn.commit()
        conn.close()

        config = {"db_path": str(db_path)}
        sqlite_store.close_connections()
        # Opening migrates v3 -> v4 and backfills the closure.
        as_of = sqlite_store.select_episodes(config, known_at="2026-03-01T00:00:00+00:00")
        assert len(as_of) == 1
        assert as_of[0]["metadata"]["generated_by"] == "agent-x"
        assert as_of[0]["invalidated_at"] is None

        conn = sqlite3.connect(db_path)
        closure = conn.execute(
            "SELECT prior_valid_to, valid_to, reason FROM episode_closures WHERE episode_id = 'old-closed'"
        ).fetchone()
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        conn.close()
        sqlite_store.close_connections()

        assert closure[0] is None  # prior_valid_to unknown for a legacy close
        assert closure[1] == "2026-06-01T00:00:00+00:00"
        assert closure[2] == "ended"
        assert int(version) == sqlite_store.SCHEMA_VERSION

        restored = sqlite_store.reopen_episode(config, "old-closed")
        # The written-in end cannot be restored: it was never kept.
        assert restored["valid_to"] is None
        assert restored["invalidated_at"] is None

    def test_http_refuses_to_reopen_a_revised_original(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient

        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        first = write("Anna lives in Padova")
        revision = vault_router.revise_episode(
            vault_name=VAULT, episode_id=first.id, content="Anna lives in Padova, in the Arcella"
        )
        vault_router.invalidate_episode(vault_name=VAULT, episode_id=revision.id)

        response = client.post(
            f"/ctxvault/episodes/{first.id}/reopen",
            json={"vault_name": VAULT},
        )
        assert response.status_code == 409
        assert revision.id in response.json()["detail"]

    def test_known_at_alone_filters_validity_at_now(self, mock_episodic_vault_config):
        # On dev, known_at alone means "recorded by then, that holds now".
        # valid_at is what moves the valid instant; known_at must not.
        from ctxvault.core import vault_router as router

        vault = router.open_vault(VAULT)
        ended = sqlite_store.write_episode(
            vault.config,
            content="held only in March",
            valid_from="2026-03-01T00:00:00+00:00",
            valid_to="2026-03-20T00:00:00+00:00",
            recorded_at="2026-03-01T00:00:00+00:00",
        )
        upcoming = sqlite_store.write_episode(
            vault.config,
            content="starts in April",
            valid_from="2026-04-01T00:00:00+00:00",
            recorded_at="2026-03-01T00:00:00+00:00",
        )

        found = sqlite_store.select_episodes(
            vault.config, known_at="2026-03-10T00:00:00+00:00",
        )
        assert {e["id"] for e in found} == {upcoming["id"]}

        then = sqlite_store.select_episodes(
            vault.config,
            known_at="2026-03-10T00:00:00+00:00",
            valid_at="2026-03-10T00:00:00+00:00",
        )
        assert {e["id"] for e in then} == {ended["id"]}

    def test_a_close_before_the_latest_reopen_is_refused(self, mock_episodic_vault_config):
        episode = write(
            "Giuseppe likes coffee",
            recorded_at="2026-01-01T00:00:00+00:00",
            valid_from="2026-01-01T00:00:00+00:00",
        )
        vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=episode.id, at="2026-03-01T00:00:00+00:00",
        )
        reopen(episode.id, at="2026-06-01T00:00:00+00:00")

        with pytest.raises(ValueError, match="reopened"):
            vault_router.invalidate_episode(
                vault_name=VAULT, episode_id=episode.id, at="2026-04-01T00:00:00+00:00",
            )
        assert vault_router.get_episode(vault_name=VAULT, episode_id=episode.id).is_open

        other = write(
            "Sarah is the contact",
            recorded_at="2026-01-01T00:00:00+00:00",
            valid_from="2026-01-01T00:00:00+00:00",
        )
        vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=other.id, at="2026-03-01T00:00:00+00:00",
        )
        reopen(other.id, at="2026-06-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="reopened"):
            vault_router.supersede_episode(
                vault_name=VAULT, episode_id=other.id,
                content="Marco is the contact",
                at="2026-04-01T00:00:00+00:00",
            )
        with pytest.raises(ValueError, match="reopened"):
            vault_router.revise_episode(
                vault_name=VAULT, episode_id=other.id,
                content="Sarah Klein is the contact",
                at="2026-04-01T00:00:00+00:00",
            )
        assert vault_router.get_episode(vault_name=VAULT, episode_id=other.id).is_open



class TestEventMetadata:
    def test_confirm_dispute_and_invalidate_store_and_return_metadata(self, mock_episodic_vault_config):
        coffee = write("Giuseppe likes coffee")
        tea = write("Giuseppe likes tea")
        run = {"run_id": "run-1", "model": "test-model", "prompt_version": "v3"}

        confirm(coffee.id, source="conversation", metadata=run)
        dispute(coffee.id, tea.id, note="he said both", metadata=run)
        vault_router.invalidate_episode(
            vault_name=VAULT, episode_id=tea.id, reason="settled", metadata=run
        )

        attestations = vault_router.open_vault(VAULT).attestations()
        disputes = vault_router.open_vault(VAULT).disputes()
        tea_history = vault_router.episode_history(vault_name=VAULT, episode_id=tea.id)
        coffee_history = vault_router.episode_history(vault_name=VAULT, episode_id=coffee.id)

        assert attestations == [{
            "episode_id": coffee.id,
            "at": attestations[0]["at"],
            "source": "conversation",
            "metadata": run,
        }]
        assert disputes[0]["metadata"] == run
        assert {disputes[0]["episode_a"], disputes[0]["episode_b"]} == {coffee.id, tea.id}
        assert coffee_history.attestations[0]["metadata"] == run
        assert coffee_history.disputes[0]["metadata"] == run
        assert tea_history.closures[0]["reason"] == "settled"
        assert tea_history.closures[0]["metadata"] == run
        # Event metadata stays on the event; it is not mixed into the episode row.
        assert "run_id" not in vault_router.get_episode(vault_name=VAULT, episode_id=tea.id).metadata

    def test_a_v4_vault_file_migrates_and_keeps_existing_events(self, tmp_path, monkeypatch):
        from ctxvault.storage import sqlite_store

        sqlite_store.close_connections()
        db = tmp_path / "episodes.db"
        config = {"db_path": str(db)}
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('schema_version', '4');
            CREATE TABLE episodes (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                salience REAL NOT NULL DEFAULT 0.5,
                occurred_at TEXT,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                recorded_at TEXT NOT NULL,
                invalidated_at TEXT,
                superseded_by TEXT,
                revised_by TEXT,
                recall_count INTEGER NOT NULL DEFAULT 0,
                last_recalled_at TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                embedding BLOB
            );
            CREATE TABLE episode_entities (
                episode_id TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_norm TEXT NOT NULL,
                PRIMARY KEY (episode_id, entity_norm)
            );
            CREATE TABLE episode_attestations (
                episode_id TEXT NOT NULL,
                at TEXT NOT NULL,
                source TEXT
            );
            CREATE TABLE episode_disputes (
                episode_a TEXT NOT NULL,
                episode_b TEXT NOT NULL,
                noticed_at TEXT NOT NULL,
                note TEXT,
                PRIMARY KEY (episode_a, episode_b)
            );
            CREATE TABLE episode_closures (
                episode_id TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                valid_to TEXT,
                prior_valid_to TEXT,
                superseded_by TEXT,
                revised_by TEXT,
                reason TEXT,
                reopened_at TEXT,
                reopen_reason TEXT,
                PRIMARY KEY (episode_id, closed_at)
            );
            INSERT INTO episodes (id, content, valid_from, recorded_at, metadata)
            VALUES ('e1', 'old fact', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '{}');
            INSERT INTO episode_attestations (episode_id, at, source)
            VALUES ('e1', '2026-01-02T00:00:00+00:00', 'carer');
            INSERT INTO episode_disputes (episode_a, episode_b, noticed_at, note)
            VALUES ('e1', 'e1', '2026-01-03T00:00:00+00:00', 'legacy');
            INSERT INTO episode_closures (
                episode_id, closed_at, valid_to, prior_valid_to,
                superseded_by, revised_by, reason, reopened_at, reopen_reason
            )
            VALUES ('e1', '2026-01-04T00:00:00+00:00', NULL, NULL, NULL, NULL, 'ended', NULL, NULL);
            """
        )
        conn.commit()
        conn.close()

        sqlite_store.get_connection(config)
        version = sqlite_store.get_connection(config).execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        attestations = sqlite_store.list_attestations(config)
        disputes = sqlite_store.list_disputes(config)
        closures = sqlite_store.list_closures(config)

        assert int(version) == sqlite_store.SCHEMA_VERSION
        assert attestations == [{
            "episode_id": "e1",
            "at": "2026-01-02T00:00:00+00:00",
            "source": "carer",
            "metadata": {},
        }]
        assert disputes[0]["metadata"] == {} and disputes[0]["note"] == "legacy"
        assert closures[0]["metadata"] == {} and closures[0]["reason"] == "ended"
        sqlite_store.close_connections()

    def test_episodes_can_be_queried_by_event_metadata(self, mock_episodic_vault_config):
        tagged = write("Giuseppe likes coffee")
        other = write("Giuseppe lives in Mestre")
        confirm(tagged.id, metadata={"run_id": "run-1"})
        confirm(other.id, metadata={"run_id": "run-2"})

        found = query(event_metadata_filters={"run_id": "run-1"}, include_closed=True)
        assert [e.id for e in found] == [tagged.id]

        # Keys must hold on the same event: a confirm with only run_id does
        # not match a filter that also asks for a model.
        assert query(event_metadata_filters={"run_id": "run-1", "model": "x"}) == []

    def test_a_revision_copies_attestation_metadata(self, mock_episodic_vault_config):
        episode = write("Giuseppe lives in Padova")
        confirm(episode.id, source="conversation", metadata={"run_id": "run-1"})
        revised = vault_router.revise_episode(
            vault_name=VAULT, episode_id=episode.id, content="Giuseppe lives in Padova, in the Arcella"
        )
        copied = [
            row for row in vault_router.open_vault(VAULT).attestations()
            if row["episode_id"] == revised.id
        ]
        assert copied[0]["metadata"] == {"run_id": "run-1"}
        assert copied[0]["source"] == "conversation"

    def test_omitted_event_metadata_is_an_empty_object(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")
        confirm(episode.id)
        assert vault_router.open_vault(VAULT).attestations()[0]["metadata"] == {}

    def test_a_duplicate_dispute_keeps_the_first_metadata(self, mock_episodic_vault_config):
        coffee = write("Giuseppe likes coffee")
        tea = write("Giuseppe likes tea")
        dispute(coffee.id, tea.id, metadata={"run_id": "first"})
        dispute(coffee.id, tea.id, metadata={"run_id": "second"})
        assert vault_router.open_vault(VAULT).disputes()[0]["metadata"] == {"run_id": "first"}

    def test_non_object_event_metadata_is_refused(self, mock_episodic_vault_config):
        episode = write("Giuseppe likes coffee")
        with pytest.raises(ValueError, match="JSON object"):
            confirm(episode.id, metadata=["run-1"])

    def test_endpoint_stores_confirm_metadata(self, mock_episodic_vault_config):
        from fastapi.testclient import TestClient
        from ctxvault.api.app import app, ctxvault_router

        app.include_router(ctxvault_router)
        client = TestClient(app)
        episode = write("Giuseppe likes coffee")

        response = client.post(
            f"/ctxvault/episodes/{episode.id}/confirm",
            json={"vault_name": VAULT, "source": "api", "metadata": {"run_id": "run-9"}},
        )
        assert response.status_code == 200

        history = client.get(
            f"/ctxvault/episodes/{episode.id}/history",
            params={"vault_name": VAULT},
        )
        assert history.status_code == 200
        body = history.json()
        assert body["attestations"][0]["metadata"] == {"run_id": "run-9"}
        assert body["attestations"][0]["source"] == "api"

        found = client.post(
            "/ctxvault/episodes/query",
            json={"vault_name": VAULT, "event_metadata_filters": {"run_id": "run-9"}},
        )
        assert found.status_code == 200
        assert [row["id"] for row in found.json()["results"]] == [episode.id]
