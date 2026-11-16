"""OpenAI-compatible LLM adapter (CLIProxyAPI / any /chat/completions gateway).

Uses httpx.MockTransport so no real gateway or key is needed. Covers the wire format,
error normalisation (connection, authentication, model, quota, server, timeout,
malformed and empty replies), secret hygiene, and the interaction with the one
automatic retry of AgentStepExecutor (QA-1).
"""
from __future__ import annotations

import dataclasses
import json
import socket

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.integrations.llm_client import (
    FaultInjectingLLMClient,
    LLMError,
    LLMRequest,
    OpenAICompatibleLLMClient,
    build_llm_client,
    resolve_model,
)
from app.models import StepRun, WorkflowRun
from app.repositories.database import SessionLocal
from app.services.step_executors import DONE, FAILED, AgentStepExecutor

BASE = "http://host.docker.internal:8317/v1"
KEY = "sk-test-client-access-key-0123456789"
REQ = LLMRequest(system_prompt="sys", user_prompt="Xin chào", model="default", temperature=0.2, max_output_tokens=512)


def ok_body(text="Xin chào từ gateway", model="gemini-3.8-flash-high"):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }


def client_with(handler, default_model="gemini-3.8-flash-high", key=KEY, base=BASE):
    return OpenAICompatibleLLMClient(base, key, default_model, transport=httpx.MockTransport(handler))


def test_request_uses_openai_wire_format_and_bearer_key():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body())

    result = client_with(handler).generate(REQ, timeout=10)
    assert seen["url"] == f"{BASE}/chat/completions"
    assert KEY not in seen["url"]  # key travels in the header only
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"]
    assert body["model"] == "gemini-3.8-flash-high"  # Agent model 'default' -> LLM_MODEL
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "Xin chào"
    assert body["temperature"] == 0.2 and body["max_tokens"] == 512 and body["stream"] is False
    assert result.text == "Xin chào từ gateway" and result.provider == "openai_compatible"
    assert result.usage == {"prompt_tokens": 12, "output_tokens": 5, "total_tokens": 17}


def test_explicit_agent_model_and_unlimited_tokens():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ok_body(model="gemini-2.5-pro"))

    req = dataclasses.replace(REQ, model="gemini-2.5-pro", max_output_tokens=0)
    client_with(handler).generate(req, timeout=10)
    assert seen["model"] == "gemini-2.5-pro"
    assert "max_tokens" not in seen  # 0 = let the gateway decide (thinking models)


def test_content_as_list_of_parts_is_supported():
    body = ok_body()
    body["choices"][0]["message"]["content"] = [{"type": "text", "text": "Phần 1. "}, {"type": "text", "text": "Phần 2."}]
    result = client_with(lambda r: httpx.Response(200, json=body)).generate(REQ, timeout=10)
    assert result.text == "Phần 1. Phần 2."


def test_list_models():
    def handler(request):
        assert request.url.path.endswith("/v1/models")
        return httpx.Response(200, json={"object": "list", "data": [{"id": "gemini-3.8-flash-high"}, {"id": "gemini-2.5-pro"}]})

    assert client_with(handler).list_models() == ["gemini-2.5-pro", "gemini-3.8-flash-high"]


@pytest.mark.parametrize(
    "status,kind,fragment",
    [
        (401, "config_error", "LLM_API_KEY"),
        (403, "config_error", "LLM_API_KEY"),
        (404, "invalid_request", "/v1/models"),
        (400, "invalid_request", "HTTP 400"),
        (429, "rate_limit", "429"),
        (500, "provider_error", "HTTP 500"),
        (503, "provider_error", "HTTP 503"),
    ],
)
def test_http_errors_are_normalised(status, kind, fragment):
    handler = lambda r: httpx.Response(status, json={"error": {"message": f"upstream says {status}"}})  # noqa: E731
    with pytest.raises(LLMError) as err:
        client_with(handler).generate(REQ, timeout=10)
    assert err.value.kind == kind
    assert fragment in err.value.message
    assert KEY not in str(err.value)


def test_connection_refused_on_real_socket():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens on this port any more
    client = OpenAICompatibleLLMClient(f"http://127.0.0.1:{port}/v1", KEY, "m")
    with pytest.raises(LLMError) as err:
        client.generate(REQ, timeout=3)
    assert err.value.kind == "provider_error"
    assert f"127.0.0.1:{port}" in err.value.message and "host.docker.internal" in err.value.message
    assert KEY not in str(err.value)


def test_connect_error_and_timeout_from_transport():
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(LLMError) as err:
        client_with(refuse).generate(REQ, timeout=5)
    assert err.value.kind == "provider_error"
    with pytest.raises(LLMError) as err:
        client_with(slow).generate(REQ, timeout=5)
    assert err.value.kind == "timeout" and "5s" in err.value.message


@pytest.mark.parametrize("base,key,missing", [("", KEY, "LLM_BASE_URL"), (BASE, "", "LLM_API_KEY"), (BASE, None, "LLM_API_KEY")])
def test_missing_configuration_fails_without_network(base, key, missing):
    def never(request):  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    with pytest.raises(LLMError) as err:
        client_with(never, key=key, base=base).generate(REQ, timeout=5)
    assert err.value.kind == "config_error" and missing in err.value.message


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"choices": []}, "định dạng"),
        ({"unexpected": True}, "định dạng"),
        ({"choices": [{"finish_reason": "length", "message": {"content": ""}}]}, "finish_reason=length"),
        ({"choices": [{"finish_reason": "stop", "message": {"content": None}}]}, "rỗng"),
    ],
)
def test_malformed_or_empty_replies(payload, fragment):
    with pytest.raises(LLMError) as err:
        client_with(lambda r: httpx.Response(200, json=payload)).generate(REQ, timeout=5)
    assert err.value.kind == "provider_error" and fragment in err.value.message


def test_non_json_reply():
    with pytest.raises(LLMError) as err:
        client_with(lambda r: httpx.Response(200, text="<html>proxy login page</html>")).generate(REQ, timeout=5)
    assert err.value.kind == "provider_error"


def test_resolve_model():
    assert resolve_model("default", "x") == "x"
    assert resolve_model("", "x") == "x"
    assert resolve_model(None, "x") == "x"
    assert resolve_model(" gemini-2.5-pro ", "x") == "gemini-2.5-pro"


def test_factory_selects_adapter_from_settings():
    base = get_settings()
    s = dataclasses.replace(base, llm_provider="openai_compatible", llm_base_url=BASE + "/", llm_api_key=KEY,
                            llm_model="gemini-3.8-flash-high", demo_mode=True)
    client = build_llm_client(s)
    assert isinstance(client, FaultInjectingLLMClient)  # fault injection still wraps it (QA-1 demo)
    inner = client.inner
    assert isinstance(inner, OpenAICompatibleLLMClient)
    assert inner.target == BASE and inner.default_model == "gemini-3.8-flash-high"
    assert s.effective_llm_provider == "openai_compatible"
    assert dataclasses.replace(base, llm_provider="auto", gemini_api_key=None).effective_llm_provider == "mock"
    assert isinstance(base, Settings)


# --------------------------------------------------------------------------- with the executor (QA-1)
class Sequence:
    """Transport that replays a list of responses/exceptions and counts calls."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, request):
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


def run_agent_step(client):
    settings = dataclasses.replace(get_settings(), llm_timeout_seconds=5)
    executor = AgentStepExecutor(client, settings)
    with SessionLocal() as db:
        run = WorkflowRun(id=0, initial_input={"request": "Viết slogan"}, started_by=1)
        step = StepRun(id=0, agent_id=4, step_order=1, step_type="agent")
        return executor.execute(db, run, step, {"initial_input": run.initial_input, "previous_output": None})


def test_transient_gateway_error_is_retried_once_then_succeeds(client):
    seq = Sequence(httpx.Response(503, json={"error": {"message": "busy"}}), httpx.Response(200, json=ok_body("Slogan hay")))
    result = run_agent_step(OpenAICompatibleLLMClient(BASE, KEY, "gemini-3.8-flash-high", transport=httpx.MockTransport(seq)))
    assert result.status == DONE and result.retry_count == 1 and seq.calls == 2
    assert result.output["provider"] == "openai_compatible" and result.output["text"] == "Slogan hay"


def test_authentication_error_is_not_retried(client):
    seq = Sequence(httpx.Response(401, json={"error": {"message": "invalid key"}}))
    result = run_agent_step(OpenAICompatibleLLMClient(BASE, KEY, "m", transport=httpx.MockTransport(seq)))
    assert result.status == FAILED and result.retry_count == 0 and seq.calls == 1  # C6: no wasted call
    assert result.error.startswith("config_error") and KEY not in result.error


def test_unreachable_gateway_fails_after_exactly_one_retry(client):
    calls = {"n": 0}

    def refuse(request):
        calls["n"] += 1
        raise httpx.ConnectError("Connection refused", request=request)

    result = run_agent_step(OpenAICompatibleLLMClient(BASE, KEY, "m", transport=httpx.MockTransport(refuse)))
    assert result.status == FAILED and result.retry_count == 1 and calls["n"] == 2
    assert "host.docker.internal:8317" in result.error


def test_empty_model_is_a_configuration_error_without_network():
    def never(request):  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    with pytest.raises(LLMError) as err:
        client_with(never, default_model="").generate(REQ, timeout=5)  # Agent model 'default' + LLM_MODEL=''
    assert err.value.kind == "config_error" and "LLM_MODEL" in err.value.message


def test_empty_env_values_do_not_produce_empty_models(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("GEMINI_MODEL", "")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.llm_model == ""  # explicit: the adapter then raises config_error
        assert s.gemini_model == "gemini-2.5-flash"  # Gemini keeps a sensible default
    finally:
        get_settings.cache_clear()
