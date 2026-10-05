"""Assemble the classification service with Claude behind the Canonical LLM Gateway."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Optional

from jmoraIs.application.support_classification import (
    OUTPUT_JSON_SCHEMA, SupportClassificationService, support_classification_prompt,
)
from jmoraIs.llm_gateway import CanonicalLLMGateway, LLMModel, LLMProvider, PromptGovernanceService
from jmoraIs.llm_gateway.infrastructure import (
    AnthropicProviderAdapter, InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository,
    InMemoryPromptAuditRepository, InMemoryPromptRepository,
)

DEFAULT_MODEL = "claude-opus-5-5"
# USD per million tokens (input, output).
MODEL_PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}


KEYCHAIN_SERVICE = "anthropic-api-key"


def keychain_api_key(run=None, platform=None) -> Optional[str]:
    """Read the key saved in the macOS Keychain (item "anthropic-api-key"); never logged."""
    import subprocess
    import sys
    if (platform or sys.platform) != "darwin":
        return None
    run = run or subprocess.run
    try:
        result = run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                     capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    # Tolerate whitespace and terminal bracketed-paste markers around a pasted key.
    value = (result.stdout or "").replace("\x1b[200~", "").replace("\x1b[201~", "").replace("^[[200~", "").replace("^[[201~", "")
    value = "".join(value.split())
    return value if result.returncode == 0 and value.startswith("sk-ant-") else None


def credentials_configured(environ, keychain=keychain_api_key) -> bool:
    return bool(environ.get("ANTHROPIC_API_KEY") or environ.get("ANTHROPIC_AUTH_TOKEN")
                or environ.get("ANTHROPIC_PROFILE") or keychain())


def build_service(model_id: str = DEFAULT_MODEL, transport=None) -> SupportClassificationService:
    clock = lambda: datetime.now(timezone.utc)
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=clock).register(support_classification_prompt(), created_by="jmorais")
    input_price, output_price = MODEL_PRICES.get(model_id, (0.0, 0.0))
    model = LLMModel(LLMProvider.ANTHROPIC, model_id, model_id, input_price, output_price, True, "MIP-10.1")
    if transport is None:
        from jmoraIs.llm_gateway.anthropic_transport import AnthropicMessagesTransport  # optional SDK
        env_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        transport = AnthropicMessagesTransport(json_schema=OUTPUT_JSON_SCHEMA,
                                               api_key=None if env_key else keychain_api_key())
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(),
                                  InMemoryLLMInvocationContextRepository(), (AnthropicProviderAdapter(transport),), clock=clock)
    return SupportClassificationService(gateway, prompt_version_id=version.prompt_version_id, model=model, clock=clock)
