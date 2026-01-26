"""
API routes for settings management.

Allows viewing and updating configuration for:
- Embeddings (provider, model, base URL, API key)
- LLM (deep and small models)
- Database connection
- General settings
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# Paths to config files
PROJECT_ROOT = Path(__file__).resolve().parents[4]
ENV_FILE = PROJECT_ROOT / ".env"
DAEMON_CONFIG = PROJECT_ROOT / "config" / "robomonkey-daemon.yaml"


# ============ Pydantic Models ============

class EmbeddingsSettings(BaseModel):
    """Embeddings configuration."""
    provider: str = Field(..., description="Provider: ollama, vllm, or openai")
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="Provider base URL")
    api_key: Optional[str] = Field(default=None, description="API key (for vllm/openai)")
    dimension: int = Field(default=1536, description="Embedding dimension")


class LLMModelSettings(BaseModel):
    """Single LLM model configuration."""
    provider: str = Field(..., description="Provider: ollama, openai, or vllm")
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="Provider base URL")
    api_key: Optional[str] = Field(default=None, description="API key")
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=32000, ge=100)


class LLMSettings(BaseModel):
    """LLM configuration for deep and small models."""
    deep: LLMModelSettings
    small: LLMModelSettings


class DatabaseSettings(BaseModel):
    """Database configuration."""
    url: str = Field(..., description="PostgreSQL connection URL")


class AllSettings(BaseModel):
    """All settings combined."""
    embeddings: EmbeddingsSettings
    llm: LLMSettings
    database: DatabaseSettings


class UpdateEmbeddingsRequest(BaseModel):
    """Request to update embeddings settings."""
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    dimension: Optional[int] = None


class UpdateLLMRequest(BaseModel):
    """Request to update LLM settings."""
    model_type: str = Field(..., description="'deep' or 'small'")
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ============ Helper Functions ============

def read_env_file() -> dict[str, str]:
    """Read .env file into a dictionary."""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    # Remove quotes if present
                    value = value.strip('"').strip("'")
                    env_vars[key.strip()] = value
    return env_vars


def write_env_file(env_vars: dict[str, str]):
    """Write dictionary back to .env file, preserving comments."""
    lines = []
    existing_keys = set()

    # Read existing file to preserve comments and order
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('#') or not stripped:
                    lines.append(line.rstrip('\n'))
                elif '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    existing_keys.add(key)
                    if key in env_vars:
                        lines.append(f'{key}={env_vars[key]}')
                    else:
                        lines.append(line.rstrip('\n'))

    # Add any new keys
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f'{key}={value}')

    with open(ENV_FILE, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def read_daemon_config() -> dict:
    """Read daemon YAML config."""
    if DAEMON_CONFIG.exists():
        with open(DAEMON_CONFIG) as f:
            return yaml.safe_load(f) or {}
    return {}


def write_daemon_config(config: dict):
    """Write daemon YAML config."""
    DAEMON_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(DAEMON_CONFIG, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def mask_api_key(key: Optional[str]) -> Optional[str]:
    """Mask API key for display, showing only last 4 chars."""
    if not key or len(key) < 8:
        return key
    return f"{'*' * (len(key) - 4)}{key[-4:]}"


def get_embeddings_settings() -> EmbeddingsSettings:
    """Get current embeddings settings from .env."""
    env = read_env_file()
    return EmbeddingsSettings(
        provider=env.get('EMBEDDINGS_PROVIDER', 'ollama'),
        model=env.get('EMBEDDINGS_MODEL', 'nomic-embed-text'),
        base_url=env.get('EMBEDDINGS_BASE_URL', 'http://localhost:11434'),
        api_key=env.get('VLLM_API_KEY') or env.get('OPENAI_API_KEY'),
        dimension=int(env.get('EMBEDDINGS_DIMENSION', '1536')),
    )


def get_llm_settings() -> LLMSettings:
    """Get current LLM settings from daemon config."""
    config = read_daemon_config()
    llm = config.get('llm', {})

    deep = llm.get('deep', {})
    small = llm.get('small', {})

    return LLMSettings(
        deep=LLMModelSettings(
            provider=deep.get('provider', 'ollama'),
            model=deep.get('model', 'llama3.2'),
            base_url=deep.get('base_url', 'http://localhost:11434'),
            api_key=deep.get('api_key'),
            temperature=deep.get('temperature', 0.3),
            max_tokens=deep.get('max_tokens', 64000),
        ),
        small=LLMModelSettings(
            provider=small.get('provider', 'ollama'),
            model=small.get('model', 'llama3.2'),
            base_url=small.get('base_url', 'http://localhost:11434'),
            api_key=small.get('api_key'),
            temperature=small.get('temperature', 0.3),
            max_tokens=small.get('max_tokens', 32000),
        ),
    )


def get_database_settings() -> DatabaseSettings:
    """Get current database settings."""
    env = read_env_file()
    return DatabaseSettings(
        url=env.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5436/robomonkey'),
    )


# ============ API Endpoints ============

@router.get("/")
async def get_all_settings() -> dict[str, Any]:
    """Get all current settings."""
    embeddings = get_embeddings_settings()
    llm = get_llm_settings()
    database = get_database_settings()

    return {
        "embeddings": {
            "provider": embeddings.provider,
            "model": embeddings.model,
            "base_url": embeddings.base_url,
            "api_key_masked": mask_api_key(embeddings.api_key),
            "has_api_key": bool(embeddings.api_key),
            "dimension": embeddings.dimension,
        },
        "llm": {
            "deep": {
                "provider": llm.deep.provider,
                "model": llm.deep.model,
                "base_url": llm.deep.base_url,
                "api_key_masked": mask_api_key(llm.deep.api_key),
                "has_api_key": bool(llm.deep.api_key),
                "temperature": llm.deep.temperature,
                "max_tokens": llm.deep.max_tokens,
            },
            "small": {
                "provider": llm.small.provider,
                "model": llm.small.model,
                "base_url": llm.small.base_url,
                "api_key_masked": mask_api_key(llm.small.api_key),
                "has_api_key": bool(llm.small.api_key),
                "temperature": llm.small.temperature,
                "max_tokens": llm.small.max_tokens,
            },
        },
        "database": {
            "url_masked": re.sub(r'://[^@]+@', '://***:***@', database.url),
        },
        "config_paths": {
            "env_file": str(ENV_FILE),
            "daemon_config": str(DAEMON_CONFIG),
        },
    }


@router.put("/embeddings")
async def update_embeddings(request: UpdateEmbeddingsRequest) -> dict[str, Any]:
    """Update embeddings settings."""
    env = read_env_file()

    if request.provider is not None:
        env['EMBEDDINGS_PROVIDER'] = request.provider
    if request.model is not None:
        env['EMBEDDINGS_MODEL'] = request.model
    if request.base_url is not None:
        env['EMBEDDINGS_BASE_URL'] = request.base_url
    if request.api_key is not None:
        # Store in appropriate key based on provider
        provider = request.provider or env.get('EMBEDDINGS_PROVIDER', 'ollama')
        if provider == 'openai':
            env['OPENAI_API_KEY'] = request.api_key
        else:
            env['VLLM_API_KEY'] = request.api_key
    if request.dimension is not None:
        env['EMBEDDINGS_DIMENSION'] = str(request.dimension)

    write_env_file(env)

    return {
        "status": "updated",
        "message": "Embeddings settings updated. Restart services to apply changes.",
        "settings": {
            "provider": env.get('EMBEDDINGS_PROVIDER'),
            "model": env.get('EMBEDDINGS_MODEL'),
            "base_url": env.get('EMBEDDINGS_BASE_URL'),
            "dimension": env.get('EMBEDDINGS_DIMENSION'),
        },
    }


@router.put("/llm")
async def update_llm(request: UpdateLLMRequest) -> dict[str, Any]:
    """Update LLM settings."""
    if request.model_type not in ('deep', 'small'):
        raise HTTPException(status_code=400, detail="model_type must be 'deep' or 'small'")

    config = read_daemon_config()

    if 'llm' not in config:
        config['llm'] = {}
    if request.model_type not in config['llm']:
        config['llm'][request.model_type] = {}

    llm_config = config['llm'][request.model_type]

    if request.provider is not None:
        llm_config['provider'] = request.provider
    if request.model is not None:
        llm_config['model'] = request.model
    if request.base_url is not None:
        llm_config['base_url'] = request.base_url
    if request.api_key is not None:
        llm_config['api_key'] = request.api_key
    if request.temperature is not None:
        llm_config['temperature'] = request.temperature
    if request.max_tokens is not None:
        llm_config['max_tokens'] = request.max_tokens

    write_daemon_config(config)

    return {
        "status": "updated",
        "message": f"LLM {request.model_type} settings updated. Restart daemon to apply changes.",
        "settings": {
            "model_type": request.model_type,
            "provider": llm_config.get('provider'),
            "model": llm_config.get('model'),
            "base_url": llm_config.get('base_url'),
            "temperature": llm_config.get('temperature'),
            "max_tokens": llm_config.get('max_tokens'),
        },
    }


@router.put("/database")
async def update_database(url: str) -> dict[str, Any]:
    """Update database URL."""
    env = read_env_file()
    env['DATABASE_URL'] = url
    write_env_file(env)

    return {
        "status": "updated",
        "message": "Database URL updated. Restart services to apply changes.",
    }


@router.post("/test/embeddings")
async def test_embeddings() -> dict[str, Any]:
    """Test embeddings connection."""
    settings = get_embeddings_settings()

    try:
        if settings.provider == 'ollama':
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.base_url}/api/embeddings",
                    json={"model": settings.model, "prompt": "test"}
                )
                if resp.status_code == 200:
                    embedding = resp.json().get('embedding', [])
                    return {
                        "status": "success",
                        "message": f"Connected to Ollama. Embedding dimension: {len(embedding)}",
                        "dimension": len(embedding),
                    }
                return {"status": "error", "message": f"Ollama returned {resp.status_code}: {resp.text}"}

        else:  # vllm or openai
            import httpx
            headers = {"Content-Type": "application/json"}
            if settings.api_key:
                headers["Authorization"] = f"Bearer {settings.api_key}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.base_url}/v1/embeddings",
                    headers=headers,
                    json={"model": settings.model, "input": "test"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embedding = data.get('data', [{}])[0].get('embedding', [])
                    return {
                        "status": "success",
                        "message": f"Connected to {settings.provider}. Embedding dimension: {len(embedding)}",
                        "dimension": len(embedding),
                    }
                return {"status": "error", "message": f"API returned {resp.status_code}: {resp.text}"}

    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


@router.post("/test/llm/{model_type}")
async def test_llm(model_type: str) -> dict[str, Any]:
    """Test LLM connection."""
    if model_type not in ('deep', 'small'):
        raise HTTPException(status_code=400, detail="model_type must be 'deep' or 'small'")

    llm = get_llm_settings()
    settings = llm.deep if model_type == 'deep' else llm.small

    try:
        if settings.provider == 'ollama':
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.base_url}/api/generate",
                    json={"model": settings.model, "prompt": "Say 'OK' if you can read this.", "stream": False}
                )
                if resp.status_code == 200:
                    response_text = resp.json().get('response', '')[:100]
                    return {
                        "status": "success",
                        "message": f"Connected to Ollama model '{settings.model}'",
                        "response_preview": response_text,
                    }
                return {"status": "error", "message": f"Ollama returned {resp.status_code}: {resp.text}"}

        else:  # openai or vllm
            import httpx
            headers = {"Content-Type": "application/json"}
            if settings.api_key:
                headers["Authorization"] = f"Bearer {settings.api_key}"

            # Build request payload
            payload = {
                "model": settings.model,
                "messages": [{"role": "user", "content": "Say 'OK' if you can read this."}],
            }

            # Check if we're calling actual OpenAI vs an OpenAI-compatible API
            is_actual_openai = "api.openai.com" in settings.base_url.lower()

            if is_actual_openai:
                # OpenAI uses max_completion_tokens for all models now
                # Use configured max_tokens for test (or 1000 as fallback)
                payload["max_completion_tokens"] = settings.max_tokens or 1000
                # Reasoning models (o1*, o3*) don't support temperature
                model_lower = (settings.model or "").lower()
                is_reasoning_model = model_lower.startswith("o1") or model_lower.startswith("o3")
                # Don't add temperature for reasoning models
            else:
                # OpenAI-compatible APIs use standard parameters
                payload["max_tokens"] = settings.max_tokens or 1000

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get('choices', [{}])[0].get('message', {}).get('content', '')[:100]
                    # Check if we got a response
                    if response_text:
                        msg = f"Connected to {settings.provider} model '{settings.model}'"
                    else:
                        msg = f"Connected to {settings.provider} model '{settings.model}' (empty response - model may need different prompting)"
                    return {
                        "status": "success",
                        "message": msg,
                        "response_preview": response_text or "(empty)",
                    }
                return {"status": "error", "message": f"API returned {resp.status_code}: {resp.text[:200]}"}

    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


@router.get("/providers")
async def get_available_providers() -> dict[str, Any]:
    """Get list of available providers and common models."""
    return {
        "embeddings": {
            "providers": [
                {"id": "ollama", "name": "Ollama (Local)", "default_url": "http://localhost:11434"},
                {"id": "vllm", "name": "vLLM (Local)", "default_url": "http://localhost:8000"},
                {"id": "openai", "name": "OpenAI / Compatible", "default_url": "https://api.openai.com"},
            ],
            "common_models": {
                "ollama": ["nomic-embed-text", "mxbai-embed-large", "all-minilm"],
                "vllm": ["all-mpnet-base-v2", "bge-large-en-v1.5"],
                "openai": ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"],
            },
        },
        "llm": {
            "providers": [
                {"id": "ollama", "name": "Ollama (Local)", "default_url": "http://localhost:11434"},
                {"id": "openai", "name": "OpenAI / Compatible", "default_url": "https://api.openai.com"},
                {"id": "vllm", "name": "vLLM (Local)", "default_url": "http://localhost:8000"},
            ],
            "common_models": {
                "ollama": ["llama3.2", "llama3.1", "codellama", "qwen2.5-coder", "mistral"],
                "openai": ["gpt-5.2-codex", "gpt-5.2", "gpt-5.2-pro", "gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o", "o3", "o1"],
                "vllm": ["mistralai/Mistral-7B-Instruct-v0.2", "meta-llama/Llama-3-8b-chat-hf"],
            },
        },
    }
