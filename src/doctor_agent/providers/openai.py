from __future__ import annotations

from doctor_agent.providers.base import ProviderConfig
from doctor_agent.providers.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI Official LLM Provider (GPT-4o, GPT-4o-mini, GPT-4.1, etc.)."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(
            config=config,
            key_env_names=("OPENAI_API_KEY", "GPT_API_KEY", "API_KEY"),
            base_env_names=("OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_API_BASE"),
            model_env_names=("OPENAI_MODEL", "GPT_MODEL", "LLM_MODEL"),
        )

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"
