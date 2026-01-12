"""Unified LLM client with dual model support.

Provides easy access to deep (qwen3) and small (phi) models for different task types.

Task Type Guidelines:
- deep: Complex code analysis, feature context, comprehensive reviews, verification
- small: Quick summaries, table/routine descriptions, classifications, simple Q&A

Usage:
    from yonk_code_robomonkey.llm import get_llm_config, call_llm

    # Get config for task type
    config = get_llm_config("deep")  # or "small"

    # Call LLM directly
    response = await call_llm(prompt, task_type="small")
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

# Task type alias
TaskType = Literal["deep", "small"]

# Default configurations (used when daemon config not available)
DEFAULT_DEEP_CONFIG = {
    "provider": "ollama",
    "model": os.getenv("LLM_DEEP_MODEL", "qwen3-coder:30b"),
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434"),
    "temperature": 0.3,
    "max_tokens": 4000,
}

DEFAULT_SMALL_CONFIG = {
    "provider": "ollama",
    "model": os.getenv("LLM_SMALL_MODEL", "phi3.5:3.8b"),
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434"),
    "temperature": 0.3,
    "max_tokens": 1000,
}

# Global config cache (set by daemon on startup)
_llm_config: dict[str, Any] | None = None


def set_llm_config(config: dict[str, Any]) -> None:
    """Set the global LLM configuration.

    Called by daemon on startup to inject the loaded config.

    Args:
        config: LLM config dict with 'deep' and 'small' keys
    """
    global _llm_config
    _llm_config = config
    logger.info(
        f"LLM config set: deep={config.get('deep', {}).get('model')}, "
        f"small={config.get('small', {}).get('model')}"
    )


def get_llm_config(task_type: TaskType = "small") -> dict[str, Any]:
    """Get LLM configuration for a task type.

    Args:
        task_type: 'deep' for complex tasks, 'small' for simple tasks

    Returns:
        Dict with provider, model, base_url, temperature, max_tokens
    """
    if _llm_config:
        if task_type == "deep":
            return _llm_config.get("deep", DEFAULT_DEEP_CONFIG)
        return _llm_config.get("small", DEFAULT_SMALL_CONFIG)

    # Fall back to defaults
    if task_type == "deep":
        return DEFAULT_DEEP_CONFIG
    return DEFAULT_SMALL_CONFIG


async def call_llm(
    prompt: str,
    task_type: TaskType = "small",
    timeout: float = 120.0,
    config_override: dict[str, Any] | None = None
) -> str | None:
    """Call LLM to generate text.

    Args:
        prompt: Prompt to send
        task_type: 'deep' or 'small' to select model
        timeout: Request timeout in seconds
        config_override: Optional config to override defaults

    Returns:
        Generated text or None on error
    """
    config = config_override or get_llm_config(task_type)

    provider = config.get("provider", "ollama")
    model = config.get("model")
    base_url = config.get("base_url", "http://localhost:11434")
    temperature = config.get("temperature", 0.3)
    max_tokens = config.get("max_tokens", 2000)

    logger.debug(f"Calling {provider}/{model} (task_type={task_type})")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if provider == "ollama":
                response = await client.post(
                    f"{base_url.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens
                        }
                    }
                )
                response.raise_for_status()
                return response.json().get("response", "")

            elif provider == "vllm":
                api_key = config.get("api_key") or os.getenv("VLLM_API_KEY", "local-key")
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "prompt": prompt,
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    }
                )
                response.raise_for_status()
                choices = response.json().get("choices", [])
                if choices:
                    return choices[0].get("text", "")

            elif provider == "openai":
                # OpenAI-compatible chat completions API
                # Also works with Azure OpenAI, Together.ai, Groq, etc.
                api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY", "")
                if not api_key:
                    logger.error("OpenAI API key not configured (set api_key in config or OPENAI_API_KEY env var)")
                    return None
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    }
                )
                response.raise_for_status()
                choices = response.json().get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")

    except Exception as e:
        logger.warning(f"LLM call failed ({provider}/{model}): {e}")

    return None


async def call_llm_json(
    prompt: str,
    task_type: TaskType = "small",
    timeout: float = 120.0
) -> dict[str, Any] | list | None:
    """Call LLM and parse JSON response.

    Args:
        prompt: Prompt to send (should ask for JSON output)
        task_type: 'deep' or 'small'
        timeout: Request timeout

    Returns:
        Parsed JSON or None on error
    """
    response = await call_llm(prompt, task_type, timeout)
    if not response:
        return None

    return parse_json_response(response)


def parse_json_response(text: str) -> dict[str, Any] | list | None:
    """Parse JSON from LLM response.

    Handles various LLM output formats:
    - Direct JSON
    - JSON in markdown code blocks
    - JSON with surrounding text

    Args:
        text: Raw LLM response

    Returns:
        Parsed JSON or None
    """
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object or array
    for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    return None


# Convenience functions for specific task types
async def call_deep_llm(prompt: str, timeout: float = 180.0) -> str | None:
    """Call the deep (complex) LLM model."""
    return await call_llm(prompt, task_type="deep", timeout=timeout)


async def call_small_llm(prompt: str, timeout: float = 60.0) -> str | None:
    """Call the small (simple) LLM model."""
    return await call_llm(prompt, task_type="small", timeout=timeout)
