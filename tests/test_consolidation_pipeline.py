import pytest

from ctxvault.consolidation import Claim, ConsolidationModel, consolidate
from ctxvault.core import vault_router

VAULT = "test_episodic_vault"
MARCH = "2026-03-10T09:00:00+00:00"
JUNE = "2026-06-10T09:00:00+00:00"

TURNS = [{"speaker": "Giuseppe", "text": "I moved to Mestre in March.", "at": MARCH}]

def claim(**overrides):
    data = {
        "subject": "Giuseppe",
        "statement": "Giuseppe lives in Mestre",
        "speaker": "Giuseppe",
        "kind": "first_party",
    }
    data.update(overrides)
    return data

class StubModel:
    """A model that returns what the test scripted, and records what it was asked."""

    name = "stub-model"
    prompt_version = "v0"

    def __init__(self, claims, relation=None):
        self.claims = claims
        self.relation = relation
        self.asked: list[tuple[Claim, list[str]]] = []

    def extract(self, turns):
        return self.claims

    def relate(self, claim, candidates):
        self.asked.append((claim, [c.id for c in candidates]))
        if callable(self.relation):
            return self.relation(claim, candidates)
        return self.relation

def about_first(relation):
    return lambda claim, candidates: {"relation": relation, "episode_id": candidates[0].id}

@pytest.fixture
def vault(mock_episodic_vault_config):
    return vault_router.open_vault(VAULT)

@pytest.fixture
def venezia(vault):
    return vault.write_episode(
        "Giuseppe lives in Venezia", entities=["Giuseppe"],
        valid_from="2025-01-01T00:00:00+00:00", recorded_at="2025-01-01T00:00:00+00:00",
    )

def test_the_stub_satisfies_the_model_protocol():
    assert isinstance(StubModel([]), ConsolidationModel)

class TestNewClaims:
    def test_a_claim_about_nothing_on_file_is_written_without_asking_the_model(self, vault):
        model = StubModel([claim()])

        result = consolidate(vault, TURNS, model)

        (operation,) = result.operations
        assert (operation.verb, operation.relation, operation.applied) == ("write_episode", "new", True)
        assert model.asked == []
        episode = vault.get_episode(operation.episode_id)
        assert episode.content == "Giuseppe lives in Mestre"
        assert episode.entities == ["Giuseppe"]
        assert episode.source == "Giuseppe"

    def test_the_conversation_time_is_the_transaction_time_and_the_default_valid_from(self, vault):
        result = consolidate(vault, TURNS, StubModel([claim()]))

        episode = vault.get_episode(result.operations[0].episode_id)
        assert result.at == MARCH
        assert episode.recorded_at == MARCH
        assert episode.valid_from == MARCH

    def test_a_dated_claim_starts_holding_on_its_date(self, vault):
        model = StubModel([claim(valid_from="2026-03-01", valid_from_precision="month")])

        result = consolidate(vault, TURNS, model)

        episode = vault.get_episode(result.operations[0].episode_id)
        assert episode.valid_from == "2026-03-01T00:00:00+00:00"
        assert episode.recorded_at == MARCH
        assert episode.metadata["valid_from_precision"] == "month"

    def test_every_write_carries_the_run_the_model_and_the_prompt(self, vault):
        result = consolidate(vault, TURNS, StubModel([claim()]), run_id="run-1")

        episode = vault.get_episode(result.operations[0].episode_id)
        assert episode.metadata == {
            "run_id": "run-1", "model": "stub-model", "prompt_version": "v0",
            "claim_kind": "first_party", "durability": "durable",
        }

    def test_confidence_is_stored_only_when_the_model_stated_one(self, vault):
        model = StubModel([claim(), claim(subject="Maria", statement="Maria works in Padova", confidence=0.6)])

        unstated, stated = consolidate(vault, TURNS, model).operations

        assert vault.get_episode(unstated.episode_id).confidence == 1.0
        assert vault.get_episode(stated.episode_id).confidence == 0.6

class TestRelations:
    def test_the_model_is_shown_what_the_vault_holds_about_the_subject(self, vault, venezia):
        other = vault.write_episode("Maria works in Padova", entities=["Maria"])
        model = StubModel([claim()], relation={"relation": "new"})

        consolidate(vault, TURNS, model)

        ((asked, shown),) = model.asked
        assert asked.statement == "Giuseppe lives in Mestre"
        assert shown == [venezia.id]
        assert other.id not in shown

    def test_a_statement_close_in_wording_is_shown_even_under_another_name(self, vault):
        past = {"valid_from": "2025-01-01T00:00:00+00:00", "recorded_at": "2025-01-01T00:00:00+00:00"}
        full_name = vault.write_episode("Giuseppe Rossi lives in Venezia", entities=["Giuseppe Rossi"], **past)
        vault.write_episode("The bakery opens at seven", entities=["bakery"], **past)
        model = StubModel([claim()], relation={"relation": "new"})

        consolidate(vault, TURNS, model)

        ((_, shown),) = model.asked
        assert shown == [full_name.id]

    def test_confirms_records_an_attestation_and_writes_nothing(self, vault, venezia):
        model = StubModel([claim(statement="Giuseppe lives in Venezia")], relation=about_first("confirms"))

        result = consolidate(vault, TURNS, model, run_id="run-1")

        (operation,) = result.operations
        assert (operation.verb, operation.target_id, operation.episode_id) == ("confirm_episode", venezia.id, None)
        assert vault.get_episode(venezia.id).confirmed_count == 1
        assert vault.stats()["total"] == 1
        (attestation,) = vault.history(venezia.id).attestations
        assert attestation["at"] == MARCH
        assert attestation["metadata"]["run_id"] == "run-1"

    def test_replaces_supersedes_the_old_statement(self, vault, venezia):
        model = StubModel([claim()], relation=about_first("replaces"))

        result = consolidate(vault, TURNS, model, run_id="run-1")

        (operation,) = result.operations
        assert (operation.verb, operation.target_id) == ("supersede_episode", venezia.id)
        old = vault.get_episode(venezia.id)
        assert old.superseded_by == operation.episode_id
        assert old.valid_to == MARCH
        assert vault.get_episode(operation.episode_id).metadata["run_id"] == "run-1"
        (closure,) = vault.history(venezia.id).closures
        assert closure["metadata"]["run_id"] == "run-1"

    def test_refines_revises_without_changing_valid_time(self, vault, venezia):
        model = StubModel([claim(statement="Giuseppe lives in Venezia, in Cannaregio")], relation=about_first("refines"))

        result = consolidate(vault, TURNS, model)

        (operation,) = result.operations
        assert operation.verb == "revise_episode"
        assert vault.get_episode(venezia.id).revised_by == operation.episode_id
        revision = vault.get_episode(operation.episode_id)
        assert revision.valid_from == venezia.valid_from
        assert revision.entities == ["Giuseppe"]

    def test_contradicts_writes_the_statement_and_puts_the_two_in_dispute(self, vault, venezia):
        model = StubModel([claim()], relation=about_first("contradicts"))

        result = consolidate(vault, TURNS, model, run_id="run-1")

        write, dispute = result.operations
        assert (write.verb, dispute.verb) == ("write_episode", "dispute_episodes")
        assert dispute.target_id == venezia.id and dispute.episode_id == write.episode_id
        assert vault.get_episode(venezia.id).disputed_with == [write.episode_id]
        assert vault.get_episode(venezia.id).is_open
        (noticed,) = vault.history(venezia.id).disputes
        assert noticed["metadata"]["run_id"] == "run-1"

    def test_a_later_claim_sees_what_an_earlier_one_wrote(self, vault):
        model = StubModel(
            [claim(), claim(statement="Giuseppe lives in Mestre, near the station")],
            relation=about_first("refines"),
        )

        first, second = consolidate(vault, TURNS, model).operations

        assert first.verb == "write_episode"
        assert (second.verb, second.target_id) == ("revise_episode", first.episode_id)

    def test_a_claim_of_the_day_is_written_without_being_related(self, vault, venezia):
        model = StubModel(
            [claim(statement="Giuseppe had risotto for lunch", durability="of_the_day")],
            relation=about_first("replaces"),
        )

        (operation,) = consolidate(vault, TURNS, model).operations

        assert operation.verb == "write_episode"
        assert model.asked == []
        assert vault.get_episode(venezia.id).is_open
        assert vault.get_episode(operation.episode_id).metadata["durability"] == "of_the_day"

class TestUnusableAnswers:
    @pytest.mark.parametrize("answer", [
        None,
        "replaces",
        {"relation": "merges", "episode_id": "x"},
        {"relation": "replaces"},
    ])
    def test_a_relation_that_does_not_fit_is_read_as_new(self, vault, venezia, answer):
        (operation,) = consolidate(vault, TURNS, StubModel([claim()], relation=answer)).operations

        assert (operation.verb, operation.relation) == ("write_episode", "new")
        assert "did not fit" in operation.note
        assert vault.get_episode(venezia.id).is_open

    def test_an_episode_the_model_was_not_shown_is_never_acted_on(self, vault, venezia):
        hidden = vault.write_episode("Maria works in Padova", entities=["Maria"])
        model = StubModel([claim()], relation={"relation": "replaces", "episode_id": hidden.id})

        (operation,) = consolidate(vault, TURNS, model).operations

        assert operation.relation == "new"
        assert hidden.id in operation.note
        assert vault.get_episode(hidden.id).is_open

    def test_malformed_claims_are_dropped_and_counted(self, vault):
        model = StubModel([claim(), {"subject": "Giuseppe"}, "not a claim"])

        result = consolidate(vault, TURNS, model)

        assert (result.extracted, result.dropped, len(result.operations)) == (3, 2, 1)

    def test_extraction_that_is_not_a_list_yields_nothing(self, vault):
        result = consolidate(vault, TURNS, StubModel("I could not find any claims."))

        assert (result.extracted, result.operations) == (0, [])

    def test_a_verb_the_vault_refuses_is_reported_and_the_rest_goes_on(self, vault, venezia):
        # Superseding at a date before the old statement started is refused.
        model = StubModel(
            [claim(valid_from="2024-01-01", valid_from_precision="year"),
             claim(subject="Maria", statement="Maria works in Padova")],
            relation=about_first("replaces"),
        )

        refused, written = consolidate(vault, TURNS, model).operations

        assert refused.applied is False and "before the episode's valid_from" in refused.error
        assert vault.get_episode(venezia.id).is_open
        assert written.applied is True

class TestOptions:
    def test_dry_run_plans_the_same_operations_and_writes_nothing(self, vault, venezia):
        model = StubModel([claim()], relation=about_first("contradicts"))

        result = consolidate(vault, TURNS, model, dry_run=True)

        assert [(o.verb, o.target_id, o.applied) for o in result.operations] == [
            ("write_episode", None, False), ("dispute_episodes", venezia.id, False),
        ]
        assert vault.stats()["total"] == 1
        assert vault.get_episode(venezia.id).disputed_with == []

    def test_kinds_refuses_claims_about_third_parties(self, vault):
        model = StubModel([claim(), claim(subject="Maria", statement="Maria moved to Padova", kind="third_party")])

        result = consolidate(vault, TURNS, model, kinds=["first_party"])

        assert result.dropped == 1
        assert [o.claim.subject for o in result.operations] == ["Giuseppe"]

    def test_the_callers_provenance_goes_on_claims_that_have_none(self, vault):
        source = {"type": "external", "source": "session-42"}

        result = consolidate(vault, TURNS, StubModel([claim()]), provenance=[source])

        episode = vault.get_episode(result.operations[0].episode_id)
        assert episode.metadata["provenance"] == [source]

    def test_at_replays_a_conversation_in_its_own_time(self, vault, venezia):
        model = StubModel([claim()], relation=about_first("replaces"))

        consolidate(vault, [{"speaker": "Giuseppe", "text": "I moved."}], model, at=JUNE)

        assert vault.get_episode(venezia.id).invalidated_at == JUNE
        (still_venezia,) = vault.query_episodes(entities=["Giuseppe"], known_at=MARCH, valid_at=MARCH).results
        assert still_venezia.id == venezia.id

    def test_a_whole_run_is_one_query(self, vault, venezia):
        model = StubModel([claim()], relation=about_first("replaces"))

        consolidate(vault, TURNS, model, run_id="run-1")

        written = vault.query_episodes(metadata_filters={"run_id": "run-1"}, include_closed=True).results
        closed = vault.query_episodes(event_metadata_filters={"run_id": "run-1"}, include_closed=True).results
        assert [e.content for e in written] == ["Giuseppe lives in Mestre"]
        assert [e.id for e in closed] == [venezia.id]

    def test_no_turns_means_no_call_to_the_model(self, vault):
        class Unreachable(StubModel):
            def extract(self, turns):
                raise AssertionError("the model was called with nothing to read")

        assert consolidate(vault, [], Unreachable([])).operations == []
