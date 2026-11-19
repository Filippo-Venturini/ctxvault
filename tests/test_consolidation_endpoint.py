import json

import pytest
import requests

from ctxvault.consolidation import Claim, ConsolidationModel, ModelEndpointError, OpenAICompatibleModel, Prompts, consolidate
from ctxvault.consolidation import endpoint
from ctxvault.core import vault_router
from ctxvault.models.episodes import Episode

VAULT = "test_episodic_vault"
MARCH = "2026-03-10T09:00:00+00:00"
TURNS = [{"speaker": "Giuseppe", "text": "I moved to Mestre in March.", "at": MARCH}]
CLAIM = {"subject": "Giuseppe", "statement": "Giuseppe lives in Mestre", "speaker": "Giuseppe", "kind": "first_party"}

class Reply:
    def __init__(self, content=None, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"choices": [{"message": {"content": content}}]}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

@pytest.fixture
def server(monkeypatch):
    """Stands in for the endpoint: answers with what the test queued, and
    keeps what it was sent."""
    class Server:
        def __init__(self):
            self.replies = []
            self.calls = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append({"url": url, "body": json, "headers": headers, "timeout": timeout})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    fake = Server()
    monkeypatch.setattr(endpoint.requests, "post", fake.post)
    return fake

class TestWhereItMayGo:
    @pytest.mark.parametrize("url", [
        "http://localhost:11434/v1", "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1", "http://ollama.localhost/v1",
    ])
    def test_an_endpoint_on_this_machine_is_accepted(self, url):
        assert OpenAICompatibleModel("m", base_url=url).base_url == url

    @pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://192.168.1.20:11434/v1", "http://localhost.example.com/v1"])
    def test_an_endpoint_elsewhere_is_refused_unless_asked_for(self, url):
        with pytest.raises(ValueError, match="allow_remote"):
            OpenAICompatibleModel("m", base_url=url)

        assert OpenAICompatibleModel("m", base_url=url, allow_remote=True).base_url == url

class TestPrompts:
    def test_the_shipped_prompts_load_with_their_version(self):
        prompts = Prompts.load("en")

        assert prompts.version == "en-2"
        assert '"claims"' in prompts.extract and '"relation"' in prompts.relate

    def test_an_unknown_language_says_what_to_do(self):
        with pytest.raises(ValueError, match="from_dir"):
            Prompts.load("tlh")

    def test_prompts_of_your_own_come_from_a_directory(self, tmp_path):
        (tmp_path / "VERSION").write_text("mine-3\n")
        (tmp_path / "extract.md").write_text("Extract.")
        (tmp_path / "relate.md").write_text("Relate.")

        model = OpenAICompatibleModel("m", prompts=Prompts.from_dir(tmp_path))

        assert model.prompt_version == "mine-3"

    def test_a_directory_missing_a_file_is_refused(self, tmp_path):
        (tmp_path / "VERSION").write_text("mine-3")

        with pytest.raises(ValueError, match="extract.md"):
            Prompts.from_dir(tmp_path)

class TestTheRequest:
    def test_it_is_a_consolidation_model(self):
        assert isinstance(OpenAICompatibleModel("m"), ConsolidationModel)

    def test_extract_sends_the_prompt_and_the_dated_turns_at_temperature_zero(self, server):
        server.replies.append(Reply('{"claims": []}'))
        model = OpenAICompatibleModel("qwen2.5:7b")

        model.extract([endpoint.Turn(**TURNS[0])])

        (call,) = server.calls
        assert call["url"] == "http://localhost:11434/v1/chat/completions"
        assert call["body"]["model"] == "qwen2.5:7b"
        assert call["body"]["temperature"] == 0
        assert call["body"]["response_format"] == {"type": "json_object"}
        system, user = call["body"]["messages"]
        assert system == {"role": "system", "content": model.prompts.extract}
        assert user["content"] == f"0 [{MARCH}] Giuseppe: I moved to Mestre in March."
        assert call["headers"] == {}

    def test_relate_shows_the_claim_and_each_candidate_with_its_id(self, server):
        server.replies.append(Reply('{"relation": "new"}'))
        candidate = Episode(id="abc123", content="Giuseppe lives in Venezia", valid_from="2025-01-01T00:00:00+00:00", recorded_at="2025-01-01T00:00:00+00:00")

        OpenAICompatibleModel("m").relate(Claim.model_validate(CLAIM), [candidate])

        user = server.calls[0]["body"]["messages"][1]["content"]
        assert '"statement": "Giuseppe lives in Mestre"' in user
        assert '"id": "abc123"' in user and "Giuseppe lives in Venezia" in user

    def test_the_key_and_json_mode_are_optional(self, server):
        server.replies.append(Reply("{}"))

        OpenAICompatibleModel("m", api_key="secret", json_mode=False).extract([])

        (call,) = server.calls
        assert call["headers"] == {"Authorization": "Bearer secret"}
        assert "response_format" not in call["body"]

class TestTheAnswer:
    @pytest.mark.parametrize("content", [
        json.dumps({"claims": [CLAIM]}),
        json.dumps([CLAIM]),
        "```json\n" + json.dumps({"claims": [CLAIM]}) + "\n```",
        "Here are the claims:\n" + json.dumps({"claims": [CLAIM]}) + "\nLet me know if you need more.",
    ])
    def test_claims_are_read_bare_fenced_or_wrapped(self, server, content):
        server.replies.append(Reply(content))

        assert OpenAICompatibleModel("m").extract([]) == [CLAIM]

    @pytest.mark.parametrize("content", ["I found nothing.", "", '{"claims": "none"}', None])
    def test_an_answer_with_no_claims_in_it_is_no_claims(self, server, content):
        server.replies.append(Reply(content))

        assert OpenAICompatibleModel("m").extract([]) == []

    def test_a_relation_that_is_not_json_is_left_for_the_pipeline_to_refuse(self, server):
        server.replies.append(Reply("It replaces the first one."))

        assert OpenAICompatibleModel("m").relate(Claim.model_validate(CLAIM), []) is None

    @pytest.mark.parametrize("reply", [
        requests.ConnectionError("refused"),
        Reply(status_code=500, body={"error": "boom"}),
        Reply(body={"unexpected": True}),
    ])
    def test_an_endpoint_that_fails_raises(self, server, reply):
        server.replies.append(reply)

        with pytest.raises(ModelEndpointError):
            OpenAICompatibleModel("m").extract([])

class TestEndToEnd:
    def test_a_conversation_becomes_a_supersession_through_the_endpoint(self, server, mock_episodic_vault_config):
        vault = vault_router.open_vault(VAULT)
        venezia = vault.write_episode(
            "Giuseppe lives in Venezia", entities=["Giuseppe"],
            valid_from="2025-01-01T00:00:00+00:00", recorded_at="2025-01-01T00:00:00+00:00",
        )
        dated = {**CLAIM, "valid_from": "2026-03-01", "valid_from_precision": "month"}
        server.replies.append(Reply(json.dumps({"claims": [dated]})))
        server.replies.append(Reply(json.dumps({"relation": "replaces", "episode_id": venezia.id})))

        result = consolidate(vault, TURNS, OpenAICompatibleModel("qwen2.5:7b"))

        (operation,) = result.operations
        assert (operation.verb, operation.applied) == ("supersede_episode", True)
        assert (result.model, result.prompt_version) == ("qwen2.5:7b", "en-2")
        mestre = vault.get_episode(operation.episode_id)
        assert mestre.valid_from == "2026-03-01T00:00:00+00:00"
        assert mestre.metadata["model"] == "qwen2.5:7b" and mestre.metadata["prompt_version"] == "en-2"
        assert vault.get_episode(venezia.id).superseded_by == mestre.id

    def test_an_undated_turn_reaches_the_model_with_the_conversation_time(self, server, mock_episodic_vault_config):
        server.replies.append(Reply('{"claims": []}'))

        consolidate(vault_router.open_vault(VAULT), [{"speaker": "Giuseppe", "text": "I moved last March."}],
                    OpenAICompatibleModel("m"), at=MARCH)

        assert server.calls[0]["body"]["messages"][1]["content"] == f"0 [{MARCH}] Giuseppe: I moved last March."
