"""Anthropic Messages API transport for the Canonical LLM Gateway (optional extra).

Used only behind `AnthropicProviderAdapter`; the gateway keeps prompt governance,
human-review policy, audit and classification. Credentials are resolved by the
official SDK from the environment (ANTHROPIC_API_KEY or an `ant auth login`
profile) and never enter DTOs, prompts or audit records.

Claude Opus 5.5 rejects sampling parameters, so `temperature`/`seed` from the
ProviderRequest are not sent; determinism comes from structured output instead.
"""
from __future__ import annotations

from hashlib import sha256
import time
from typing import Any, Callable, Optional

from .domain import LLMProviderFailure, LLMProviderTimeout, LLMRateLimited, ProviderRequest, ProviderResponse

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicMessagesTransport:
    def __init__(self, *, client: Any = None, json_schema: Optional[dict] = None, effort: str = "low",
                 monotonic: Callable[[], float] = time.monotonic):
        if client is None:
            import anthropic  # optional dependency: pip install '.[anthropic]'
            client = anthropic.Anthropic(timeout=120.0, max_retries=2)
        self._client = client
        self._json_schema = json_schema
        self._effort = effort
        self._monotonic = monotonic

    def send(self, provider, request: ProviderRequest) -> ProviderResponse:
        import anthropic
        output_config: dict[str, Any] = {"effort": self._effort}
        if self._json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": self._json_schema}
        started = self._monotonic()
        try:
            message = self._client.beta.messages.create(
                model=request.model_id,
                max_tokens=request.max_output_tokens,
                system=request.system_prompt,
                messages=[{"role": "user", "content": request.canonical_payload}],
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMRateLimited("anthropic rate limited") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMProviderTimeout("anthropic timeout") from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            # No provider message text is propagated: it may echo request content.
            raise LLMProviderFailure(f"anthropic request failed: {type(exc).__name__}") from exc
        latency_ms = max(0, int((self._monotonic() - started) * 1000))
        refused = message.stop_reason == "refusal"
        text = "" if refused else "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        if not refused and message.stop_reason == "max_tokens":
            raise LLMProviderFailure("anthropic output truncated at max_tokens")
        usage = message.usage
        cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        metadata = sha256(f"{message.id}|{message.model}|{message.stop_reason}".encode()).hexdigest()
        return ProviderResponse(message.id, text, int(usage.input_tokens), int(usage.output_tokens), cached,
                                latency_ms, metadata, refused)
