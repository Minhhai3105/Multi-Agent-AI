"""Check the configured LLM provider BEFORE running workflows.

Run it where the backend runs - inside the Docker container:

    docker compose run --rm app python scripts/check_llm_connection.py
    # or, while the stack is up:
    docker compose exec app python scripts/check_llm_connection.py

For LLM_PROVIDER=openai_compatible (e.g. CLIProxyAPI) it:
  1. calls GET {LLM_BASE_URL}/models and prints the available model ids,
  2. checks that LLM_MODEL is one of them,
  3. sends one tiny chat completion and prints the latency and reply.
The API key is never printed (only whether it is set and its length).
Exit code 0 = ready, 1 = not ready (with a hint about the likely cause).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.integrations.llm_client import (  # noqa: E402
    GeminiLLMClient,
    LLMError,
    LLMRequest,
    OpenAICompatibleLLMClient,
)

HINTS = {
    "provider_error": "Không tới được gateway. Proxy có đang chạy không? Trong Docker phải dùng "
                      "http://host.docker.internal:8317/v1 thay cho 127.0.0.1.",
    "config_error": "Thiếu cấu hình hoặc API key bị từ chối - kiểm tra LLM_BASE_URL / LLM_API_KEY trong .env.",
    "invalid_request": "Sai đường dẫn (Base URL phải kết thúc bằng /v1) hoặc tên model không có trong /v1/models.",
    "rate_limit": "Gateway báo hết quota hoặc gọi quá nhanh - đợi một lúc rồi thử lại.",
    "timeout": "Gateway trả lời quá chậm - tăng LLM_TIMEOUT_SECONDS (model thinking nên đặt 120).",
}


def ping(client, model: str, timeout: float, max_tokens: int) -> None:
    started = time.perf_counter()
    result = client.generate(
        LLMRequest(
            system_prompt="Bạn là trợ lý kiểm tra kết nối.",
            user_prompt="Trả lời đúng một từ: OK",
            model=model,
            temperature=0,
            max_output_tokens=max_tokens,
        ),
        timeout=timeout,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    print(f"[OK] chat completion: model={result.model} · {elapsed} ms · trả lời: {result.text[:80]!r}")


def main() -> int:
    s = get_settings()
    provider = s.effective_llm_provider
    print(f"LLM_PROVIDER (hiệu lực): {provider}")
    try:
        if provider == "openai_compatible":
            key_info = f"có ({len(s.llm_api_key)} ký tự)" if s.llm_api_key else "CHƯA ĐẶT"
            print(f"LLM_BASE_URL : {s.llm_base_url or 'CHƯA ĐẶT'}")
            print(f"LLM_API_KEY  : {key_info}")
            print(f"LLM_MODEL    : {s.llm_model}")
            client = OpenAICompatibleLLMClient(s.llm_base_url or "", s.llm_api_key, s.llm_model)
            models = client.list_models(timeout=15)
            print(f"[OK] GET /models: {len(models)} model")
            for m in models:
                print(f"     - {m}{'   <== LLM_MODEL' if m == s.llm_model else ''}")
            if s.llm_model not in models:
                print(f"[LỖI] LLM_MODEL='{s.llm_model}' không có trong danh sách trên - sửa LLM_MODEL trong .env.")
                return 1
            ping(client, s.llm_model, s.llm_timeout_seconds, s.llm_max_output_tokens)
        elif provider == "gemini":
            print(f"GEMINI_MODEL : {s.gemini_model}")
            ping(GeminiLLMClient(s.gemini_api_key or "", s.gemini_base_url, s.gemini_model),
                 s.gemini_model, s.llm_timeout_seconds, s.llm_max_output_tokens)
        else:
            print("Đang dùng LLM mô phỏng (mock) - không cần kết nối ra ngoài.")
    except LLMError as exc:
        print(f"[LỖI] {exc.kind}: {exc.message}")
        print(f"      Gợi ý: {HINTS.get(exc.kind, '')}")
        return 1
    print("Sẵn sàng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
