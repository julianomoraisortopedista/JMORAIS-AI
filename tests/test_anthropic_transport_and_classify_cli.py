import json
from types import SimpleNamespace as NS

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from jmoraIs.application.support_classification import OUTPUT_JSON_SCHEMA, ProposalStatus
from jmoraIs.llm_gateway.anthropic_transport import FALLBACK_BETA, AnthropicMessagesTransport
from jmoraIs.llm_gateway.domain import (
    LLMProvider, LLMProviderFailure, LLMProviderTimeout, LLMRateLimited, ProviderRequest,
)
from scripts import classify_evidence
from tests.test_support_classification import QUOTE, abstract

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeMessages:
    def __init__(self, result):
        self.result, self.calls = result, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client(result):
    messages = FakeMessages(result)
    return NS(beta=NS(messages=messages)), messages


def message(text='{"direction":"SUPPORTING"}', stop="end_turn"):
    return NS(id="msg_1", model="claude-opus-5-5", stop_reason=stop,
              content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
              usage=NS(input_tokens=1200, output_tokens=300, cache_read_input_tokens=None))


def provider_request():
    return ProviderRequest("req-1", "claude-opus-5-5", "SYSTEM", '{"fields":[]}', 0.0, 7, 4000)


def test_transport_sends_governed_request_without_sampling_parameters():
    fake, messages = client(message())
    clock = iter([10.0, 10.25])
    result = AnthropicMessagesTransport(client=fake, json_schema=OUTPUT_JSON_SCHEMA, monotonic=lambda: next(clock)).send(
        LLMProvider.ANTHROPIC, provider_request())
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] == 4000 and call["system"] == "SYSTEM"
    assert call["messages"] == [{"role": "user", "content": '{"fields":[]}'}]
    assert "temperature" not in call and "seed" not in call and "thinking" not in call
    assert call["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_JSON_SCHEMA}}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert (result.output_text, result.input_tokens, result.output_tokens, result.cached_tokens, result.latency_ms) == (
        '{"direction":"SUPPORTING"}', 1200, 300, 0, 250)
    assert not result.refused and len(result.provider_metadata_hash) == 64


def test_refusal_is_returned_as_refused_without_text():
    fake, _ = client(message(text="partial", stop="refusal"))
    result = AnthropicMessagesTransport(client=fake).send(LLMProvider.ANTHROPIC, provider_request())
    assert result.refused and result.output_text == ""


def test_truncated_output_is_a_provider_failure():
    fake, _ = client(message(stop="max_tokens"))
    with pytest.raises(LLMProviderFailure):
        AnthropicMessagesTransport(client=fake).send(LLMProvider.ANTHROPIC, provider_request())


@pytest.mark.parametrize("error,expected", [
    (anthropic.RateLimitError("limit", response=httpx2.Response(429, request=REQ), body=None), LLMRateLimited),
    (anthropic.APITimeoutError(request=REQ), LLMProviderTimeout),
    (anthropic.APIConnectionError(request=REQ), LLMProviderFailure),
    (anthropic.AuthenticationError("bad key sk-ant-x", response=httpx2.Response(401, request=REQ), body=None), LLMProviderFailure),
])
def test_sdk_errors_map_to_gateway_errors_without_leaking_messages(error, expected):
    fake, _ = client(error)
    with pytest.raises(expected) as raised:
        AnthropicMessagesTransport(client=fake).send(LLMProvider.ANTHROPIC, provider_request())
    assert "sk-ant" not in str(raised.value)


class FakeTransport:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def send(self, provider, request):
        from tests.test_llm_gateway import response
        return response(output_text=self.outputs.pop(0))


class FakePubMed:
    def fetch_abstract(self, pmid):
        if pmid != "26488691":
            from jmoraIs.connect.pubmed import AbstractUnavailable
            raise AbstractUnavailable("no abstract published for this PMID")
        return abstract()


def run(outputs, answers, extra=(), tmp_path=None):
    service = classify_evidence.build_service("claude-opus-5-5", FakeTransport(outputs))
    lines, replies = [], iter(answers)
    argv = ["--claim", "Total knee replacement improves pain versus nonsurgical care",
            "--pmid", "26488691,99999999", "--reviewer", "CRM-SP-1", *extra]
    code = classify_evidence.main(argv, service=service, pubmed=FakePubMed(), read=lambda _: next(replies),
                                  write=lines.append)
    return code, "\n".join(lines)


def ai(direction="SUPPORTING", quote=QUOTE):
    return json.dumps({"direction": direction, "quote": quote, "rationale": "r"})


def test_without_credentials_nothing_is_sent():
    lines = []
    code = classify_evidence.main(["--claim", "x" * 20, "--pmid", "1", "--reviewer", "r"], write=lines.append, environ={})
    assert code == 2 and lines == [classify_evidence.NOT_CONFIGURED]


def test_accept_flow_shows_quote_and_writes_private_json(tmp_path):
    out = tmp_path / "decisions.json"
    code, text = run([ai()], ["a"], ("--out", str(out)))
    assert code == 0 and f'Quote: "{QUOTE}"' in text and "99999999: abstract unavailable" in text
    (record,) = json.loads(out.read_text())
    assert record["physician_decision"] == "ACCEPT" and record["final_direction"] == "SUPPORTING"
    assert record["reviewer"] == "CRM-SP-1" and record["model"] == "claude-opus-5-5"
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_override_requires_valid_direction_and_reason(tmp_path):
    out = tmp_path / "d.json"
    code, text = run([ai("NEUTRAL")], ["o", "WRONG", "", "o", "SUPPORTING", "Primary endpoint favours surgery"], ("--out", str(out)))
    assert "Invalid direction or empty reason." in text
    (record,) = json.loads(out.read_text())
    assert (record["ai_direction"], record["final_direction"], record["physician_decision"]) == ("NEUTRAL", "SUPPORTING", "OVERRIDE")


def test_ungrounded_proposal_is_auto_rejected(tmp_path):
    out = tmp_path / "d.json"
    code, text = run([ai(quote="Surgery is always better than anything else")], [], ("--out", str(out)))
    (record,) = json.loads(out.read_text())
    assert record["ai_status"] == ProposalStatus.UNGROUNDED.value and record["physician_decision"] == "REJECT"
    assert "quote is not a verbatim passage" in text


def test_model_configuration_detection():
    assert classify_evidence.model_configured({"ANTHROPIC_API_KEY": "x"})
    assert not classify_evidence.model_configured({})
