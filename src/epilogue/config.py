"""Model and runtime configuration.

Epilogue is provider-agnostic thanks to the Strands model abstraction.
Amazon Bedrock is the default (and what the AgentCore deployment uses);
Anthropic, Gemini, OpenAI, Ollama, and LiteLLM are one environment variable
away — useful for local development and for judges without an AWS account
handy. Gemini deserves a special mention: Google AI Studio keys have a free
tier, so the full live demo can be experienced at zero cost.

    EPILOGUE_MODEL_PROVIDER = bedrock | anthropic | gemini | openai | ollama | litellm
    EPILOGUE_MODEL_ID       = provider-specific model id (optional, sane defaults)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_MODEL_IDS = {
    # Claude Sonnet — strong tool use at agent-friendly cost. Override via EPILOGUE_MODEL_ID.
    "bedrock": os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "anthropic": "claude-sonnet-4-5",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1",
    "ollama": "qwen3:8b",
    "litellm": "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}


def data_dir() -> Path:
    return Path(os.environ.get("EPILOGUE_DATA_DIR", "data"))


def db_path() -> Path:
    return data_dir() / "epilogue.db"


@lru_cache(maxsize=1)
def make_model():
    """Build the configured Strands model. Imported lazily so optional provider
    packages are only required when actually selected."""
    provider = os.environ.get("EPILOGUE_MODEL_PROVIDER", "bedrock").lower()
    model_id = os.environ.get("EPILOGUE_MODEL_ID") or DEFAULT_MODEL_IDS.get(provider)

    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        return BedrockModel(
            model_id=model_id,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            temperature=0.4,
        )
    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(model_id=model_id, max_tokens=4096, params={"temperature": 0.4})
    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        return GeminiModel(
            client_args={"api_key": api_key} if api_key else None,
            model_id=model_id,
            params={"temperature": 0.4},
        )
    if provider == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(model_id=model_id, params={"temperature": 0.4})
    if provider == "ollama":
        from strands.models.ollama import OllamaModel

        return OllamaModel(
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            model_id=model_id,
        )
    if provider == "litellm":
        from strands.models.litellm import LiteLLMModel

        return LiteLLMModel(model_id=model_id, params={"temperature": 0.4})
    raise ValueError(f"Unknown EPILOGUE_MODEL_PROVIDER: {provider!r}")
