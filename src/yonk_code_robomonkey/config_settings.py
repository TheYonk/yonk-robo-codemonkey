"""Configuration management for RoboMonkey.

Loads settings from environment variables using python-dotenv.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load .env file
load_dotenv()


# =============================================================================
# Model-Aware Chunk Configuration
# =============================================================================

# Model-specific maximum input lengths (conservative estimates in characters)
# These represent safe limits that account for tokenizer overhead
MODEL_CHUNK_LIMITS: dict[str, int] = {
    # Sentence-transformers models (small context windows)
    "all-MiniLM-L6-v2": 1000,
    "all-MiniLM-L12-v2": 1000,
    "paraphrase-MiniLM-L6-v2": 500,
    "all-mpnet-base-v2": 1500,
    "all-distilroberta-v1": 2000,
    "multi-qa-MiniLM-L6-cos-v1": 2000,

    # OpenAI models (large context windows)
    "text-embedding-3-small": 30000,
    "text-embedding-3-large": 30000,
    "text-embedding-ada-002": 30000,

    # Ollama/local models
    "nomic-embed-text": 30000,
    "snowflake-arctic-embed2": 2000,
    "snowflake-arctic-embed2:latest": 2000,
    "mxbai-embed-large": 2000,

    # Default for unknown models
    "_default": 2000,
}


@dataclass
class ChunkConfig:
    """Configuration for chunking based on embedding model limits.

    Attributes:
        max_chars: Maximum characters per chunk (model's hard limit)
        target_chars: Target chunk size (70% of max for safety margin)
        overlap_chars: Overlap between chunks (10% of target)
        min_chars: Minimum viable chunk size (10% of max)
    """
    max_chars: int
    target_chars: int
    overlap_chars: int
    min_chars: int

    @classmethod
    def for_model(cls, model_name: str) -> "ChunkConfig":
        """Create chunk configuration optimized for a specific embedding model.

        Args:
            model_name: Name of the embedding model (e.g., "text-embedding-3-small")

        Returns:
            ChunkConfig with appropriate sizes for the model
        """
        # Normalize model name for lookup
        model_lower = model_name.lower()
        base_name = model_name.split(":")[0].lower()  # Strip :latest, :v2, etc.

        # Find matching limit
        max_chars = MODEL_CHUNK_LIMITS.get("_default", 2000)

        for key, limit in MODEL_CHUNK_LIMITS.items():
            if key == "_default":
                continue
            key_lower = key.lower()
            if key_lower == base_name or key_lower == model_lower or key_lower in model_lower:
                max_chars = limit
                break

        # Calculate optimal chunk sizes
        # Target is 70% of max to leave room for variation
        target_chars = int(max_chars * 0.7)
        # Min is 10% of max
        min_chars = max(100, int(max_chars * 0.1))
        # Overlap is 10% of target
        overlap_chars = int(target_chars * 0.1)

        return cls(
            max_chars=max_chars,
            target_chars=target_chars,
            overlap_chars=overlap_chars,
            min_chars=min_chars,
        )


def get_chunk_config_for_model(model_name: str) -> dict[str, int]:
    """Get chunk configuration as a dictionary for a specific model.

    Convenience function that returns chunking parameters as a dict.

    Args:
        model_name: Name of the embedding model

    Returns:
        Dict with max_chars, target_chars, overlap_chars, min_chars
    """
    config = ChunkConfig.for_model(model_name)
    return {
        "max_chars": config.max_chars,
        "target_chars": config.target_chars,
        "overlap_chars": config.overlap_chars,
        "min_chars": config.min_chars,
    }


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        # Database
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/robomonkey"
        )

        # Schema isolation (one schema per repo)
        self.schema_prefix = os.getenv("SCHEMA_PREFIX", "robomonkey_")
        self.use_schemas = os.getenv("USE_SCHEMAS", "true").lower() == "true"

        # Embeddings
        # Provider: "ollama", "vllm", or "openai" (for OpenAI-compatible APIs including local embedding service)
        self.embeddings_provider: Literal["ollama", "vllm", "openai"] = os.getenv(
            "EMBEDDINGS_PROVIDER", "ollama"
        )
        self.embeddings_model = os.getenv("EMBEDDINGS_MODEL", "snowflake-arctic-embed2:latest")
        self.embeddings_base_url = os.getenv("EMBEDDINGS_BASE_URL", "http://localhost:11434")
        self.embeddings_dimension = int(os.getenv("EMBEDDINGS_DIMENSION", "1024"))
        self.embedding_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

        # Chunk configuration - model-aware with optional override
        self._chunk_config = ChunkConfig.for_model(self.embeddings_model)
        # Allow explicit override via MAX_CHUNK_LENGTH env var
        max_chunk_override = os.getenv("MAX_CHUNK_LENGTH")
        if max_chunk_override:
            self.max_chunk_length = int(max_chunk_override)
        else:
            self.max_chunk_length = self._chunk_config.max_chars

        # vLLM specific
        self.vllm_base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
        self.vllm_api_key = os.getenv("VLLM_API_KEY", "local-key")

        # Resolved embeddings API key (picks the right key based on provider)
        if self.embeddings_provider == "openai":
            self.embeddings_api_key = os.getenv("OPENAI_API_KEY", "")
        elif self.embeddings_provider == "vllm":
            self.embeddings_api_key = self.vllm_api_key
        else:
            self.embeddings_api_key = ""

        # Resolved embeddings base URL (handles provider-specific routing)
        if self.embeddings_provider == "vllm" and self.embeddings_base_url == "http://localhost:11434":
            # Override default ollama URL with vLLM URL
            self.embeddings_base_url = self.vllm_base_url

        # LLM for summaries and text generation
        self.llm_model = os.getenv("LLM_MODEL", "qwen3-coder:30b")
        self.llm_base_url = os.getenv("LLM_BASE_URL", self.embeddings_base_url)  # Defaults to embeddings URL

        # Repo scanning
        self.repo_root = os.getenv("REPO_ROOT", "")
        self.ignore_file = os.getenv("IGNORE_FILE", ".gitignore")
        self.watch_mode = os.getenv("WATCH_MODE", "false").lower() == "true"

        # Search parameters
        self.vector_top_k = int(os.getenv("VECTOR_TOP_K", "30"))
        self.fts_top_k = int(os.getenv("FTS_TOP_K", "30"))
        self.final_top_k = int(os.getenv("FINAL_TOP_K", "12"))

        # Context packing
        self.context_budget_tokens = int(os.getenv("CONTEXT_BUDGET_TOKENS", "12000"))
        self.graph_depth = int(os.getenv("GRAPH_DEPTH", "2"))

        # Default repository for MCP server
        self.default_repo = os.getenv("DEFAULT_REPO", "")

    @property
    def chunk_config(self) -> ChunkConfig:
        """Get the chunk configuration for the current embedding model."""
        return self._chunk_config

    def get_chunk_config(self) -> dict[str, int]:
        """Get chunk configuration as a dictionary."""
        return {
            "max_chars": self._chunk_config.max_chars,
            "target_chars": self._chunk_config.target_chars,
            "overlap_chars": self._chunk_config.overlap_chars,
            "min_chars": self._chunk_config.min_chars,
        }


# Global settings instance
settings = Settings()


def get_schema_name(repo_name: str) -> str:
    """Get schema name for a repository.

    Args:
        repo_name: Repository name

    Returns:
        Schema name (e.g., 'robomonkey_legacy1')
    """
    if not settings.use_schemas:
        return "public"

    # Sanitize repo name for use in schema name
    safe_name = repo_name.lower().replace("-", "_").replace(" ", "_")
    # Remove any characters that aren't alphanumeric or underscore
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")

    return f"{settings.schema_prefix}{safe_name}"
