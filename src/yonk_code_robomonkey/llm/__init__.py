"""Unified LLM client with dual model support.

Provides easy access to deep (qwen3) and small (phi) models.

Usage:
    from yonk_code_robomonkey.llm import call_llm, get_llm_config

    # Simple task (uses phi)
    response = await call_llm("Summarize this: ...", task_type="small")

    # Complex task (uses qwen3)
    response = await call_llm("Analyze this codebase: ...", task_type="deep")

    # Get config for direct use
    config = get_llm_config("deep")
    print(f"Using model: {config['model']}")
"""
from .client import (
    TaskType,
    set_llm_config,
    get_llm_config,
    call_llm,
    call_llm_json,
    parse_json_response,
    call_deep_llm,
    call_small_llm,
)

__all__ = [
    "TaskType",
    "set_llm_config",
    "get_llm_config",
    "call_llm",
    "call_llm_json",
    "parse_json_response",
    "call_deep_llm",
    "call_small_llm",
]
