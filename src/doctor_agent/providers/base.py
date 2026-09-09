from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMMessage:
        return cls(role=str(data.get("role", "user")), content=str(data.get("content", "")))

    @classmethod
    def system(cls, content: str) -> LLMMessage:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> LLMMessage:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> LLMMessage:
        return cls(role="assistant", content=content)


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LLMUsage:
        if not data:
            return cls()
        prompt = int(data.get("prompt_tokens", 0) or 0)
        completion = int(data.get("completion_tokens", 0) or 0)
        total = int(data.get("total_tokens", prompt + completion) or 0)
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "usage": self.usage.to_dict(),
            "finish_reason": self.finish_reason,
        }


@dataclass
class ProviderConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: int = 60
    extra_headers: dict[str, str] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    """Abstract Base Class for all LLM Providers in Doctor Agent."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        self.config = config or ProviderConfig()

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical provider identifier (e.g. 'deepseek', 'glm', 'openai', 'gemini')."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model name for this provider."""
        ...

    @property
    @abstractmethod
    def default_base_url(self) -> str:
        """Default Base API URL for this provider."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check whether the necessary API key or authentication is present."""
        ...

    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage] | str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronously generate response from the LLM."""
        ...

    @abstractmethod
    async def agenerate(
        self,
        messages: list[LLMMessage] | str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Asynchronously generate response from the LLM."""
        ...

    def normalize_messages(
        self, messages: list[LLMMessage] | str, system: str | None = None
    ) -> list[LLMMessage]:
        normalized: list[LLMMessage] = []
        if system:
            normalized.append(LLMMessage.system(system))
        if isinstance(messages, str):
            normalized.append(LLMMessage.user(messages))
        else:
            for msg in messages:
                if isinstance(msg, dict):
                    normalized.append(LLMMessage.from_dict(msg))
                else:
                    normalized.append(msg)
        return normalized
