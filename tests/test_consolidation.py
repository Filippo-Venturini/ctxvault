import pytest
from pydantic import ValidationError

from ctxvault.consolidation import ChunkProvenance, Claim, ExternalProvenance, parse_claims

def claim(**overrides):
    data = {
        "subject": "Giuseppe",
        "statement": "Giuseppe lives in Mestre",
        "speaker": "Giuseppe",
        "kind": "first_party",
    }
    data.update(overrides)
    return data

class TestClaimSchema:
    def test_defaults(self):
        parsed = Claim.model_validate(claim())

        assert parsed.durability == "durable"
        assert parsed.confidence == 1.0
        assert parsed.valid_from is None
        assert parsed.valid_from_precision == "day"
        assert parsed.provenance is None

    def test_speaker_is_distinct_from_subject(self):
        parsed = Claim.model_validate(claim(
            subject="Maria",
            statement="Maria moved to Padova",
            kind="third_party",
        ))

        assert parsed.subject == "Maria"
        assert parsed.speaker == "Giuseppe"

    def test_kind_is_required(self):
        data = claim()
        del data["kind"]

        with pytest.raises(ValidationError):
            Claim.model_validate(data)

    @pytest.mark.parametrize("field", ["subject", "statement"])
    def test_blank_text_is_rejected(self, field):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(**{field: "   "}))

    @pytest.mark.parametrize("confidence", [-0.1, 1.5])
    def test_confidence_out_of_range_is_rejected(self, confidence):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(confidence=confidence))

    @pytest.mark.parametrize("value", ["2026-03-01", "2026-03-01T10:00:00+00:00", "2026-03-01T10:00:00Z"])
    def test_valid_from_accepts_iso(self, value):
        assert Claim.model_validate(claim(valid_from=value)).valid_from == value

    @pytest.mark.parametrize("value", ["March 2026", "last year", "2026-13-01"])
    def test_valid_from_rejects_free_text(self, value):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from=value))

    def test_imprecise_date_keeps_its_precision(self):
        parsed = Claim.model_validate(claim(valid_from="2026-03-01", valid_from_precision="month"))

        assert parsed.valid_from_precision == "month"

    def test_unknown_precision_is_rejected(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from_precision="week"))

class TestProvenance:
    def test_chunk_reference(self):
        parsed = Claim.model_validate(claim(provenance={
            "type": "chunk",
            "vault": "transcripts",
            "doc_id": "abc",
            "chunk_index": 3,
            "chunk_hash": "f00d",
        }))

        assert isinstance(parsed.provenance, ChunkProvenance)
        assert parsed.provenance.chunk_index == 3

    def test_external_source(self):
        parsed = Claim.model_validate(claim(provenance={
            "type": "external",
            "source": "telegram",
            "locator": "msg-42",
        }))

        assert isinstance(parsed.provenance, ExternalProvenance)
        assert parsed.provenance.locator == "msg-42"

    def test_chunk_reference_needs_its_hash(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(provenance={
                "type": "chunk",
                "vault": "transcripts",
                "doc_id": "abc",
                "chunk_index": 3,
            }))

    def test_unknown_provenance_type_is_rejected(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(provenance={"type": "rumour", "source": "x"}))

class TestParseClaims:
    def test_malformed_items_are_dropped(self):
        items = [
            claim(),
            claim(statement=""),
            claim(kind="hearsay"),
            "not a claim",
            None,
            claim(subject="Maria", statement="Maria moved to Padova", kind="third_party"),
        ]

        parsed = parse_claims(items)

        assert [c.statement for c in parsed] == ["Giuseppe lives in Mestre", "Maria moved to Padova"]

    def test_third_party_claims_can_be_switched_off(self):
        items = [
            claim(),
            claim(subject="Maria", statement="Maria moved to Padova", kind="third_party"),
        ]

        parsed = parse_claims(items, kinds=["first_party"])

        assert [c.subject for c in parsed] == ["Giuseppe"]

    def test_extra_keys_from_the_model_are_ignored(self):
        parsed = parse_claims([claim(reasoning="the speaker said so")])

        assert len(parsed) == 1

    def test_core_does_not_import_the_layer(self):
        import ctxvault

        assert "consolidation" not in ctxvault.__all__
