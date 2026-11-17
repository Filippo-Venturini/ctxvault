import hashlib
import subprocess
import sys

import pytest
from pydantic import ValidationError

from ctxvault.consolidation import ChunkProvenance, Claim, ExternalProvenance, parse_claims

HASH = hashlib.sha256(b"Mestre, since March.").hexdigest()

def claim(**overrides):
    data = {
        "subject": "Giuseppe",
        "statement": "Giuseppe lives in Mestre",
        "speaker": "Giuseppe",
        "kind": "first_party",
    }
    data.update(overrides)
    return data

def chunk(**overrides):
    data = {
        "type": "chunk",
        "vault": "transcripts",
        "doc_id": "abc",
        "chunk_index": 3,
        "chunk_hash": HASH,
    }
    data.update(overrides)
    return data

class TestClaimSchema:
    def test_defaults(self):
        parsed = Claim.model_validate(claim())

        assert parsed.durability == "durable"
        assert parsed.confidence is None
        assert parsed.valid_from is None
        assert parsed.valid_from_precision is None
        assert parsed.provenance == []

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

    def test_missing_confidence_is_not_read_as_certain(self):
        assert Claim.model_validate(claim()).confidence is None
        assert Claim.model_validate(claim(confidence=0.7)).confidence == 0.7

class TestValidFrom:
    @pytest.mark.parametrize("value", ["2026-03-01", "2026-03-01T10:00:00+00:00", "2026-03-01T10:00:00Z"])
    def test_accepts_iso(self, value):
        assert Claim.model_validate(claim(valid_from=value, valid_from_precision="day")).valid_from == value

    def test_naive_time_is_read_as_utc(self):
        parsed = Claim.model_validate(claim(valid_from="2026-03-01T10:00:00", valid_from_precision="day"))

        assert parsed.valid_from == "2026-03-01T10:00:00+00:00"

    @pytest.mark.parametrize("value", ["March 2026", "last year", "2026-13-01"])
    def test_rejects_free_text(self, value):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from=value, valid_from_precision="day"))

    def test_imprecise_date_keeps_its_precision(self):
        parsed = Claim.model_validate(claim(valid_from="2026-03-01", valid_from_precision="month"))

        assert parsed.valid_from_precision == "month"

    def test_precision_is_required_with_a_date(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from="2026-03-01"))

    def test_precision_without_a_date_is_rejected(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from_precision="month"))

    def test_unknown_precision_is_rejected(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(valid_from="2026-03-01", valid_from_precision="week"))

class TestProvenance:
    def test_chunk_reference(self):
        parsed = Claim.model_validate(claim(provenance=[chunk(path="sessions/2026-03-01.md")]))

        [reference] = parsed.provenance
        assert isinstance(reference, ChunkProvenance)
        assert reference.chunk_index == 3
        assert reference.path == "sessions/2026-03-01.md"

    def test_question_and_answer_in_two_chunks(self):
        parsed = Claim.model_validate(claim(provenance=[chunk(chunk_index=3), chunk(chunk_index=4)]))

        assert [p.chunk_index for p in parsed.provenance] == [3, 4]

    def test_mixed_sources(self):
        parsed = Claim.model_validate(claim(provenance=[
            chunk(),
            {"type": "external", "source": "telegram", "locator": "msg-42"},
        ]))

        assert isinstance(parsed.provenance[1], ExternalProvenance)
        assert parsed.provenance[1].locator == "msg-42"

    def test_chunk_reference_needs_its_hash(self):
        data = chunk()
        del data["chunk_hash"]

        with pytest.raises(ValidationError):
            Claim.model_validate(claim(provenance=[data]))

    @pytest.mark.parametrize("value", ["f00d", HASH.upper(), HASH[:-1] + "g"])
    def test_chunk_hash_must_be_a_sha256_hex_digest(self, value):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(provenance=[chunk(chunk_hash=value)]))

    def test_unknown_provenance_type_is_rejected(self):
        with pytest.raises(ValidationError):
            Claim.model_validate(claim(provenance=[{"type": "rumour", "source": "x"}]))

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

def test_core_does_not_import_the_layer():
    # In a fresh interpreter: this test module has already imported the layer.
    probe = "import sys, ctxvault; print('ctxvault.consolidation' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "False"
