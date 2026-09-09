from __future__ import annotations

from doctor_agent.providers.base import ProviderConfig
from doctor_agent.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek LLM Provider (DeepSeek-V3, DeepSeek-R1, etc.)."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(
            config=config,
            key_env_names=("DEEPSEEK_API_KEY", "API_KEY"),
            base_env_names=("DEEPSEEK_API_BASE", "DEEPSEEK_BASE_URL", "LLM_API_BASE"),
            model_env_names=("DEEPSEEK_MODEL", "LLM_MODEL"),
        )

    @property
    def name(self) -> str:
        return "deepseek"

    @property
    def default_model(self) -> str:
        return "deepseek-chat"

    @property
    def default_base_url(self) -> str:
        return "https://api.deepseek.com"
