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


class GeminiProvider(BaseLLMProvider):
    """Google Gemini REST LLM Provider (Gemini 1.5/2.0/2.5 Flash & Pro)."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        key_env_names: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"),
        base_env_names: tuple[str, ...] = ("GEMINI_API_BASE", "GOOGLE_API_BASE", "LLM_API_BASE"),
        model_env_names: tuple[str, ...] = ("GEMINI_MODEL", "GOOGLE_MODEL", "LLM_MODEL"),
    ) -> None:
        super().__init__(config)
        self.key_env_names = key_env_names
        self.base_env_names = base_env_names
        self.model_env_names = model_env_names

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return "gemini-2.5-flash"

    @property
    def default_base_url(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

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

    def _build_url(self, api_key: str) -> str:
        base = self.get_base_url()
        model = self.get_model()
        return f"{base}/models/{model}:generateContent?key={api_key}"

    def _build_payload(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        system_instructions = [msg.content for msg in messages if msg.role == "system"]
        contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_instructions:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_instructions)}]
            }

        return payload

    def _parse_response(self, data: dict[str, Any], raw_model: str) -> LLMResponse:
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"Empty candidates in response from Gemini: {data}")
        first_candidate = candidates[0]
        content_obj = first_candidate.get("content", {})
        parts = content_obj.get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        finish_reason = first_candidate.get("finishReason")

        usage_meta = data.get("usageMetadata", {})
        usage = LLMUsage(
            prompt_tokens=int(usage_meta.get("promptTokenCount", 0) or 0),
            completion_tokens=int(usage_meta.get("candidatesTokenCount", 0) or 0),
            total_tokens=int(usage_meta.get("totalTokenCount", 0) or 0),
        )

        return LLMResponse(
            text=text,
            model=data.get("modelVersion", raw_model),
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
        url = self._build_url(api_key)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "doctor-agent/0.2.0 (Medical RAG)",
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        req_timeout = timeout if timeout is not None else self.config.timeout
        target_model = self.get_model()

        payload = self._build_payload(norm_messages, temperature=temp, max_tokens=tokens)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=req_timeout) as resp:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                return self._parse_response(data, raw_model=target_model)
        except HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            # Mask API key in error url for safety
            safe_url = url.split("?key=")[0] + "?key=***"
            raise RuntimeError(
                f"HTTP {err.code} error from {self.name} ({safe_url}): {err_body}"
            ) from err
        except URLError as err:
            safe_url = url.split("?key=")[0] + "?key=***"
            raise RuntimeError(
                f"Connection error to {self.name} ({safe_url}): {err.reason}"
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
