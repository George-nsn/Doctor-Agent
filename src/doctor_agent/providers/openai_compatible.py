from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from doctor_agent.providers.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    LLMUsage,
    ProviderConfig,
)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Generic Provider for any OpenAI-compatible Chat Completions API endpoint."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        key_env_names: tuple[str, ...] = ("OPENAI_API_KEY", "API_KEY"),
        base_env_names: tuple[str, ...] = ("OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_API_BASE"),
        model_env_names: tuple[str, ...] = ("OPENAI_MODEL", "LLM_MODEL"),
    ) -> None:
        super().__init__(config)
        self.key_env_names = key_env_names
        self.base_env_names = base_env_names
        self.model_env_names = model_env_names

    @property
    def name(self) -> str:
        return "openai_compatible"

    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def get_api_key(self) -> str | None:
        if self.config.api_key:
            return self.config.api_key
        for name in self.key_env_names:
            val = os.getenv(name)
            if val:
                return val.strip()
        return None

    def get_base_url(self) -> str:
        if self.config.base_url:
            return self.config.base_url.rstrip("/")
        for name in self.base_env_names:
            val = os.getenv(name)
            if val:
                return val.strip().rstrip("/")
        return self.default_base_url.rstrip("/")

    def get_model(self) -> str:
        if self.config.model:
            return self.config.model
        for name in self.model_env_names:
            val = os.getenv(name)
            if val:
                return val.strip()
        return self.default_model

    def is_configured(self) -> bool:
        return bool(self.get_api_key())

    def _build_url(self) -> str:
        base = self.get_base_url()
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _build_headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "doctor-agent/0.2.0 (Medical RAG)",
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    def _build_payload(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.get_model(),
            "messages": [msg.to_dict() for msg in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        for k, v in kwargs.items():
            if v is not None and k not in payload:
                payload[k] = v
        return payload

    def _parse_response(self, data: dict[str, Any], raw_model: str) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Empty choices in response from {self.name}: {data}")
        first_choice = choices[0]
        msg = first_choice.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            # In case of multipart content blocks
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        finish_reason = first_choice.get("finish_reason")
        usage_data = data.get("usage")
        usage = LLMUsage.from_dict(usage_data)
        actual_model = data.get("model") or raw_model

        return LLMResponse(
            text=str(content).strip(),
            model=str(actual_model),
            provider=self.name,
            usage=usage,
            finish_reason=str(finish_reason) if finish_reason else None,
            raw=data,
        )

    def generate(
        self,
        messages: list[LLMMessage] | str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        api_key = self.get_api_key()
        if not api_key:
            raise RuntimeError(
                f"Missing API key for provider '{self.name}'. "
                f"Please set one of environment variables: {', '.join(self.key_env_names)}"
            )

        norm_messages = self.normalize_messages(messages, system=system)
        url = self._build_url()
        headers = self._build_headers(api_key)
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        req_timeout = timeout if timeout is not None else self.config.timeout
        target_model = self.get_model()

        payload = self._build_payload(norm_messages, temperature=temp, max_tokens=tokens, **kwargs)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=req_timeout) as resp:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                return self._parse_response(data, raw_model=target_model)
        except HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {err.code} error from {self.name} ({url}): {err_body}"
            ) from err
        except URLError as err:
            raise RuntimeError(
                f"Connection error to {self.name} ({url}): {err.reason}"
            ) from err

    async def agenerate(
        self,
        messages: list[LLMMessage] | str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await asyncio.to_thread(
            self.generate,
            messages=messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
