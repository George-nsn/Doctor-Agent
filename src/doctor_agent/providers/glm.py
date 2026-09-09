from __future__ import annotations

from doctor_agent.providers.base import ProviderConfig
from doctor_agent.providers.openai_compatible import OpenAICompatibleProvider


class GLMProvider(OpenAICompatibleProvider):
    """Zhipu AI / GLM Provider (GLM-4, GLM-4-Flash, GLM-4-Plus)."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(
            config=config,
            key_env_names=("ZHIPUAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY", "API_KEY"),
            base_env_names=("ZHIPUAI_API_BASE", "GLM_API_BASE", "LLM_API_BASE"),
            model_env_names=("GLM_MODEL", "ZHIPU_MODEL", "LLM_MODEL"),
        )

    @property
    def name(self) -> str:
        return "glm"

    @property
    def default_model(self) -> str:
        return "glm-4-flash"

    @property
    def default_base_url(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"
