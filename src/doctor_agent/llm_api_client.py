from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from doctor_agent.common import PROJECT_ROOT

PROVIDER_ALIASES = {
    "openai": "openai",
    "gpt": "openai",
    "codex": "codex",
    "deepseek": "deepseek",
    "glm": "glm",
    "zhipu": "glm",
    "zhipuai": "glm",
    "bigmodel": "glm",
    "gemini": "gemini",
    "google": "gemini",
    "copilot": "github_models",
    "github": "github_models",
    "github_models": "github_models",
}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_style: str
    default_base_url: str
    default_model: str
    key_env_names: tuple[str, ...]
    base_env_names: tuple[str, ...]
    model_env_names: tuple[str, ...]


PROVIDERS = {
    "openai": ProviderConfig(
        name="openai",
        api_style="chat_completions",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        key_env_names=("OPENAI_API_KEY", "GPT_API_KEY", "API_KEY"),
        base_env_names=("OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_API_BASE"),
        model_env_names=("OPENAI_MODEL", "GPT_MODEL", "LLM_MODEL"),
    ),
    "glm": ProviderConfig(
        name="glm",
        api_style="chat_completions",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        key_env_names=("ZHIPUAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY", "API_KEY"),
        base_env_names=("ZHIPUAI_API_BASE", "GLM_API_BASE", "LLM_API_BASE"),
        model_env_names=("GLM_MODEL", "ZHIPU_MODEL", "LLM_MODEL"),
    ),
    "codex": ProviderConfig(
        name="codex",
        api_style="chat_completions",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5-codex",
        key_env_names=("CODEX_API_KEY", "OPENAI_API_KEY", "API_KEY"),
        base_env_names=("CODEX_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_API_BASE"),
        model_env_names=("CODEX_MODEL", "OPENAI_MODEL", "LLM_MODEL"),
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        api_style="chat_completions",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        key_env_names=("DEEPSEEK_API_KEY", "API_KEY"),
        base_env_names=("DEEPSEEK_API_BASE", "DEEPSEEK_BASE_URL", "LLM_API_BASE"),
        model_env_names=("DEEPSEEK_MODEL", "LLM_MODEL"),
    ),
    "gemini": ProviderConfig(
        name="gemini",
        api_style="gemini_generate_content",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-3.5-flash",
        key_env_names=("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"),
        base_env_names=("GEMINI_API_BASE", "GOOGLE_API_BASE", "LLM_API_BASE"),
        model_env_names=("GEMINI_MODEL", "GOOGLE_MODEL", "LLM_MODEL"),
    ),
    "github_models": ProviderConfig(
        name="github_models",
        api_style="chat_completions",
        default_base_url="https://models.github.ai/inference",
        default_model="openai/gpt-4.1-mini",
        key_env_names=("GITHUB_TOKEN", "GITHUB_MODELS_API_KEY", "COPILOT_API_KEY", "API_KEY"),
        base_env_names=("GITHUB_MODELS_API_BASE", "COPILOT_API_BASE", "LLM_API_BASE"),
        model_env_names=("GITHUB_MODELS_MODEL", "COPILOT_MODEL", "LLM_MODEL"),
    ),
}


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    provider = resolve_provider(args.provider)
    api_key = args.api_key or first_env(provider.key_env_names)
    base_url = normalize_base_url(args.base_url or first_env(provider.base_env_names) or provider.default_base_url)
    model = args.model or first_env(provider.model_env_names) or provider.default_model

    if not api_key and not args.dry_run:
        env_names = ", ".join(provider.key_env_names)
        raise SystemExit(f"Missing API key. Set one of: {env_names}, or pass --api-key.")

    request_plan = build_request_plan(
        provider=provider,
        base_url=base_url,
        api_key=api_key or "dry-run-key",
        model=model,
        prompt=args.prompt,
        system=args.system,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    if args.dry_run:
        print(json.dumps(mask_request_plan(request_plan), ensure_ascii=False, indent=2))
        return 0

    response = post_json(request_plan["url"], request_plan["headers"], request_plan["payload"], args.timeout)
    text = extract_text(provider.api_style, response)
    if args.raw:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


def call_llm_from_env(
    prompt: str,
    system: str,
    provider_name: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 600,
    timeout: int = 60,
) -> tuple[str | None, dict[str, Any]]:
    """Call configured LLM with multi-provider failover."""
    load_env_file(PROJECT_ROOT / ".env")
    from doctor_agent.providers import execute_with_failover

    chain_spec = (
        provider_name
        or os.getenv("MEDICAL_LLM_PROVIDERS")
        or os.getenv("MEDICAL_LLM_PROVIDER")
    )
    if not chain_spec:
        return None, {"used": False, "reason": "MEDICAL_LLM_PROVIDER_not_set"}

    response, meta = execute_with_failover(
        prompt=prompt,
        system=system,
        provider_names=chain_spec,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if response and response.text:
        return response.text, meta
    return None, meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call GPT/Codex/Gemini/DeepSeek/Copilot-compatible LLM APIs.")
    parser.add_argument("--provider", choices=sorted(PROVIDER_ALIASES), default="gpt")
    parser.add_argument("--model", help="Model name. Defaults are provider-specific and can be overridden by env vars.")
    parser.add_argument("--prompt", required=True, help="User prompt text.")
    parser.add_argument("--system", default="You are a helpful medical RAG engineering assistant.")
    parser.add_argument("--api-key", help="API key. Prefer environment variables or .env instead of this CLI option.")
    parser.add_argument("--base-url", help="Override provider base URL, useful for gateways or OpenAI-compatible proxies.")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env", help="Optional .env file to load before reading env vars.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="Print masked endpoint, headers, and payload without sending a request.")
    parser.add_argument("--raw", action="store_true", help="Print raw provider JSON instead of extracted text.")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_provider(provider_name: str) -> ProviderConfig:
    canonical = PROVIDER_ALIASES[provider_name]
    return PROVIDERS[canonical]


def first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_request_plan(
    provider: ProviderConfig,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    if provider.api_style == "gemini_generate_content":
        return build_gemini_request(base_url, api_key, model, prompt, system, temperature, max_tokens)
    return build_chat_completions_request(base_url, api_key, model, prompt, system, temperature, max_tokens)


def build_chat_completions_request(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    return {
        "url": f"{base_url}/chat/completions",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        "payload": payload,
    }


def build_gemini_request(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    return {
        "url": f"{base_url}/models/{model}:generateContent?key={api_key}",
        "headers": {"Content-Type": "application/json", "Accept": "application/json"},
        "payload": payload,
    }


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {error.code} from LLM API: {body}") from error
    except URLError as error:
        raise SystemExit(f"Failed to connect to LLM API: {error.reason}") from error


def extract_text(api_style: str, response: dict[str, Any]) -> str:
    if api_style == "gemini_generate_content":
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text_parts = [part.get("text", "") for part in parts if part.get("text")]
        return "".join(text_parts).strip()
    message = response.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return str(content).strip()


def mask_request_plan(request_plan: dict[str, Any]) -> dict[str, Any]:
    masked = json.loads(json.dumps(request_plan, ensure_ascii=False))
    headers = masked.get("headers", {})
    if "Authorization" in headers:
        headers["Authorization"] = "******"
    masked["url"] = mask_api_key_in_url(str(masked.get("url", "")))
    return masked


def mask_api_key_in_url(url: str) -> str:
    if "key=" not in url:
        return url
    prefix, _key = url.split("key=", 1)
    return f"{prefix}key=***"


if __name__ == "__main__":
    raise SystemExit(main())
