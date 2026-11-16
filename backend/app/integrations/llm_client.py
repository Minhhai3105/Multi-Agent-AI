"""LLM Client - the ONLY adapter allowed to call the External LLM Provider (rule R4).

Interface contract (Architecture Design 5.4):
    LLMClient.generate(request, timeout) -> LLMResult
    Failure: raises LLMError with a normalised `kind`
    (timeout | rate_limit | provider_error | invalid_request | config_error);
    provider-specific exceptions never leave this module.

Implementations
    GeminiLLMClient          Google Gemini REST API (primary provider, C2).
    MockLLMClient            Offline provider for demos/tests without an API key.
    FaultInjectingLLMClient  Decorator that injects timeouts / provider errors so the
                             reliability scenario QA-1 can be demonstrated on demand
                             (risk R02 validation: "inject timeout/429 through a stub").
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.config import Settings


@dataclass
class LLMRequest:
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float = 0.3
    max_output_tokens: int = 1024


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    latency_ms: int
    usage: dict = field(default_factory=dict)


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


class LLMClient(Protocol):
    provider_name: str

    def generate(self, request: LLMRequest, timeout: float) -> LLMResult: ...


# --------------------------------------------------------------------------- Gemini
class GeminiLLMClient:
    provider_name = "gemini"

    def __init__(self, api_key: str, base_url: str, default_model: str):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    def _model(self, requested: str) -> str:
        return requested if requested.startswith("gemini") else self._default_model

    def generate(self, request: LLMRequest, timeout: float) -> LLMResult:
        model = self._model(request.model)
        url = f"{self._base_url}/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        started = time.perf_counter()
        try:
            # The key travels in a header, never in the URL, so it cannot leak into logs.
            response = httpx.post(
                url, json=body, headers={"x-goog-api-key": self._api_key}, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", f"Gemini did not answer within {timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError("provider_error", f"Cannot reach Gemini: {type(exc).__name__}") from exc

        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429:
            raise LLMError("rate_limit", "Gemini quota or rate limit exceeded (HTTP 429)")
        if response.status_code in (400, 404):
            raise LLMError("invalid_request", _short_error(response))
        if response.status_code in (401, 403):
            raise LLMError("config_error", "Gemini rejected the API key (check GEMINI_API_KEY)")
        if response.status_code >= 500:
            raise LLMError("provider_error", f"Gemini server error (HTTP {response.status_code})")
        if response.status_code != 200:
            raise LLMError("provider_error", _short_error(response))

        try:
            data = response.json()
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("provider_error", "Unexpected Gemini response format") from exc
        if not text:
            reason = candidate.get("finishReason", "unknown")
            raise LLMError("provider_error", f"Gemini returned no text (finishReason={reason})")
        usage = data.get("usageMetadata", {})
        return LLMResult(
            text=text,
            model=model,
            provider=self.provider_name,
            latency_ms=latency,
            usage={
                "prompt_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            },
        )


def _short_error(response: httpx.Response) -> str:
    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        message = response.text
    return f"HTTP {response.status_code}: {message[:200]}"


# --------------------------------------------------------------------------- Mock
class MockLLMClient:
    """Deterministic offline provider. Produces readable Vietnamese output that echoes
    the Agent role, the incoming context and any retrieved knowledge, so the multi-agent
    pipeline can be demonstrated without an API key or quota (C6)."""

    provider_name = "mock"

    def __init__(self, latency_ms: int = 800):
        self.latency_ms = latency_ms
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest, timeout: float) -> LLMResult:
        with self._lock:
            self.calls += 1
        delay = self.latency_ms / 1000.0
        if delay > timeout:
            time.sleep(timeout)
            raise LLMError("timeout", f"Mock provider exceeded timeout of {timeout:.0f}s")
        time.sleep(delay)
        return LLMResult(
            text=_mock_answer(request),
            model=request.model,
            provider=self.provider_name,
            latency_ms=self.latency_ms,
            usage={"prompt_tokens": len(request.user_prompt) // 4, "output_tokens": 120},
        )


def _first_sentences(text: str, limit: int = 2) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(sentences[:limit])[:400]


def _section(prompt: str, title: str) -> str:
    match = re.search(rf"### {title}\n(.*?)(?=\n### |\Z)", prompt, flags=re.S)
    return match.group(1).strip() if match else ""


def _mock_answer(request: LLMRequest) -> str:
    role = re.search(r"Vai trò: (.+)", request.system_prompt)
    role_name = role.group(1).strip() if role else "AI Agent"
    task_input = _section(request.user_prompt, "Yêu cầu ban đầu")
    previous = _section(request.user_prompt, "Kết quả của bước trước")
    knowledge = _section(request.user_prompt, "Tri thức tham khảo")

    lines = [f"[{role_name} – phản hồi mô phỏng]"]
    if knowledge:
        snippets = re.findall(r"\[Nguồn (\d+)\][^\n]*\n(.+?)(?=\n\[Nguồn |\Z)", knowledge, flags=re.S)
        if snippets:
            lines.append("Căn cứ tài liệu nội bộ:")
            for idx, body in snippets[:2]:
                lines.append(f"- {_first_sentences(body)} [Nguồn {idx}]")
    if previous:
        lines.append(f"Tiếp nhận kết quả bước trước: {_first_sentences(previous, 1)}")
    if task_input:
        lines.append(f"Xử lý yêu cầu: {_first_sentences(task_input, 2)}")
    lines.append(
        "Kết luận: đã hoàn thành phần việc theo vai trò được giao và chuyển kết quả cho bước tiếp theo."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- Fault injection
@dataclass
class FaultConfig:
    mode: str = "none"  # none | fail_next | fail_always | timeout_next
    remaining: int = 0
    kind: str = "provider_error"  # provider_error | rate_limit
    skip: int = 0  # let this many calls succeed before the fault starts (e.g. fail from step 2)
    injected_total: int = 0


class FaultInjectingLLMClient:
    """Decorator around any LLMClient. Enabled only when DEMO_MODE=true."""

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.provider_name = inner.provider_name
        self._config = FaultConfig()
        self._lock = threading.Lock()

    def configure(self, mode: str, count: int = 1, kind: str = "provider_error", skip: int = 0) -> FaultConfig:
        with self._lock:
            self._config = FaultConfig(
                mode=mode, remaining=max(count, 0), kind=kind, skip=max(skip, 0),
                injected_total=self._config.injected_total,
            )
            return FaultConfig(**vars(self._config))

    def status(self) -> FaultConfig:
        with self._lock:
            return FaultConfig(**vars(self._config))

    def _should_fail(self) -> str | None:
        with self._lock:
            cfg = self._config
            if cfg.mode != "none" and cfg.skip > 0:
                cfg.skip -= 1
                return None
            if cfg.mode == "fail_always":
                cfg.injected_total += 1
                return cfg.kind
            if cfg.mode in ("fail_next", "timeout_next") and cfg.remaining > 0:
                cfg.remaining -= 1
                cfg.injected_total += 1
                kind = "timeout" if cfg.mode == "timeout_next" else cfg.kind
                if cfg.remaining == 0:
                    cfg.mode = "none"
                return kind
            return None

    def generate(self, request: LLMRequest, timeout: float) -> LLMResult:
        kind = self._should_fail()
        if kind == "timeout":
            time.sleep(min(timeout, 1.0))
            raise LLMError("timeout", f"Injected timeout (LLM timeout is {timeout:.0f}s)")
        if kind == "rate_limit":
            raise LLMError("rate_limit", "Injected HTTP 429 rate limit")
        if kind:
            raise LLMError("provider_error", "Injected provider error (HTTP 503)")
        return self.inner.generate(request, timeout)


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.effective_llm_provider == "gemini":
        client: LLMClient = GeminiLLMClient(
            api_key=settings.gemini_api_key or "",
            base_url=settings.gemini_base_url,
            default_model=settings.gemini_model,
        )
    else:
        client = MockLLMClient(latency_ms=settings.mock_llm_latency_ms)
    if settings.demo_mode:
        client = FaultInjectingLLMClient(client)
    return client
