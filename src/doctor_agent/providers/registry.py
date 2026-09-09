from __future__ import annotations

import logging
import os
from typing import Any

from doctor_agent.providers.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    ProviderConfig,
)
from doctor_agent.providers.deepseek import DeepSeekProvider
from doctor_agent.providers.gemini import GeminiProvider
from doctor_agent.providers.glm import GLMProvider
from doctor_agent.providers.openai import OpenAIProvider
from doctor_agent.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

PROVIDER_CLASSES: dict[str, type[BaseLLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "glm": GLMProvider,
    "zhipu": GLMProvider,
    "zhipuai": GLMProvider,
    "bigmodel": GLMProvider,
    "openai": OpenAIProvider,
    "gpt": OpenAIProvider,
    "gemini": GeminiProvider,
    "google": GeminiProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


def register_provider(name: str, provider_cls: type[BaseLLMProvider]) -> None:
    """Register or override a provider class."""
    PROVIDER_CLASSES[name.lower()] = provider_cls


def get_provider(
    name: str | None = None,
    config: ProviderConfig | None = None,
    **kwargs: Any,
) -> BaseLLMProvider:
    """Get an instantiated LLM provider by name or from environment.

    If name is None, it reads from environment variable `MEDICAL_LLM_PROVIDER`.
    If still unset, it attempts to find any configured provider in priority order:
    deepseek -> glm -> openai -> gemini.
    """
    requested = name or os.getenv("MEDICAL_LLM_PROVIDER")

    if not requested:
        # Auto-detect first configured provider
        for candidate_name in ("deepseek", "glm", "openai", "gemini"):
            cls = PROVIDER_CLASSES[candidate_name]
            p = cls(config=config)
            if p.is_configured():
                return p
        # Default fallback to deepseek
        requested = "deepseek"

    canonical = requested.lower().strip()
    provider_cls = PROVIDER_CLASSES.get(canonical)
    if not provider_cls:
        available = ", ".join(sorted(PROVIDER_CLASSES.keys()))
        raise KeyError(
            f"Unknown LLM provider: '{requested}'. Available providers: {available}"
        )

    # Allow overriding config fields via kwargs
    if kwargs and not config:
        config = ProviderConfig(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
            model=kwargs.get("model"),
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", 1024),
            timeout=kwargs.get("timeout", 60),
            extra_headers=kwargs.get("extra_headers", {}),
        )

    return provider_cls(config=config)


def get_available_providers() -> list[str]:
    """Return a list of provider names that currently have API keys configured."""
    available: list[str] = []
    seen_classes: set[type[BaseLLMProvider]] = set()
    for name, cls in PROVIDER_CLASSES.items():
        if cls in seen_classes:
            continue
        seen_classes.add(cls)
        try:
            p = cls()
            if p.is_configured():
                available.append(p.name)
        except Exception:
            continue
    return available


def parse_provider_chain(chain_spec: list[str] | str | None = None) -> list[str]:
    """Parse a provider sequence from argument or environment."""
    if isinstance(chain_spec, list):
        return [p.strip().lower() for p in chain_spec if p.strip()]

    if isinstance(chain_spec, str) and chain_spec.strip():
        return [p.strip().lower() for p in chain_spec.split(",") if p.strip()]

    # From environment
    env_chain = os.getenv("MEDICAL_LLM_PROVIDERS")
    if env_chain:
        return [p.strip().lower() for p in env_chain.split(",") if p.strip()]

    single_provider = os.getenv("MEDICAL_LLM_PROVIDER")
    if single_provider:
        return [single_provider.strip().lower()]

    # If nothing configured, check which ones have keys in priority order
    discovered = get_available_providers()
    if discovered:
        return discovered

    return ["deepseek", "glm", "openai", "gemini"]


def execute_with_failover(
    prompt: str | list[LLMMessage],
    system: str | None = None,
    provider_names: list[str] | str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
    timeout: int = 60,
    **kwargs: Any,
) -> tuple[LLMResponse | None, dict[str, Any]]:
    """Execute LLM generation with multi-provider failover chaining.

    Tries providers in order. If one fails (e.g. rate limit, connection error, timeout),
    it logs the diagnostic and seamlessly falls over to the next configured provider.
    Returns (response, metadata).
    """
    chain = parse_provider_chain(provider_names)
    attempts: list[dict[str, Any]] = []

    for prov_name in chain:
        try:
            provider = get_provider(prov_name)
        except Exception as exc:
            attempts.append({
                "provider": prov_name,
                "status": "initialization_failed",
                "error": str(exc),
            })
            continue

        if not provider.is_configured():
            attempts.append({
                "provider": prov_name,
                "status": "skipped",
                "reason": "missing_api_key",
            })
            continue

        try:
            response = provider.generate(
                prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                **kwargs,
            )
            return response, {
                "used": True,
                "provider": provider.name,
                "model": response.model,
                "usage": response.usage.to_dict(),
                "attempts": attempts,
            }
        except Exception as exc:
            logger.warning("Provider '%s' failed: %s; trying next in chain", prov_name, exc)
            attempts.append({
                "provider": prov_name,
                "status": "call_failed",
                "error": type(exc).__name__,
                "detail": str(exc),
            })

    return None, {
        "used": False,
        "reason": "all_providers_failed_or_unconfigured",
        "attempts": attempts,
    }


async def aexecute_with_failover(
    prompt: str | list[LLMMessage],
    system: str | None = None,
    provider_names: list[str] | str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
    timeout: int = 60,
    **kwargs: Any,
) -> tuple[LLMResponse | None, dict[str, Any]]:
    """Asynchronously execute LLM generation with multi-provider failover chaining."""
    chain = parse_provider_chain(provider_names)
    attempts: list[dict[str, Any]] = []

    for prov_name in chain:
        try:
            provider = get_provider(prov_name)
        except Exception as exc:
            attempts.append({
                "provider": prov_name,
                "status": "initialization_failed",
                "error": str(exc),
            })
            continue

        if not provider.is_configured():
            attempts.append({
                "provider": prov_name,
                "status": "skipped",
                "reason": "missing_api_key",
            })
            continue

        try:
            response = await provider.agenerate(
                prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                **kwargs,
            )
            return response, {
                "used": True,
                "provider": provider.name,
                "model": response.model,
                "usage": response.usage.to_dict(),
                "attempts": attempts,
            }
        except Exception as exc:
            logger.warning("Provider '%s' async failed: %s; trying next in chain", prov_name, exc)
            attempts.append({
                "provider": prov_name,
                "status": "call_failed",
                "error": type(exc).__name__,
                "detail": str(exc),
            })

    return None, {
        "used": False,
        "reason": "all_providers_failed_or_unconfigured",
        "attempts": attempts,
    }
