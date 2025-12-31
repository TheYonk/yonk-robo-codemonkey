"""Configuration management for CodeGraph MCP.

Loads settings from environment variables using python-dotenv.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        # Database
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/codegraph"
        )

        # Schema isolation (one schema per repo)
        self.schema_prefix = os.getenv("SCHEMA_PREFIX", "codegraph_")
        self.use_schemas = os.getenv("USE_SCHEMAS", "true").lower() == "true"

        # Embeddings
        self.embeddings_provider: Literal["ollama", "vllm"] = os.getenv(
            "EMBEDDINGS_PROVIDER", "ollama"
        )
        self.embeddings_model = os.getenv("EMBEDDINGS_MODEL", "snowflake-arctic-embed2:latest")
        self.embeddings_base_url = os.getenv("EMBEDDINGS_BASE_URL", "http://localhost:11434")
        self.embeddings_dimension = int(os.getenv("EMBEDDINGS_DIMENSION", "1024"))
        self.max_chunk_length = int(os.getenv("MAX_CHUNK_LENGTH", "8192"))
        self.embedding_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

        # vLLM specific
        self.vllm_base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
        self.vllm_api_key = os.getenv("VLLM_API_KEY", "local-key")

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


# Global settings instance
settings = Settings()


def get_schema_name(repo_name: str) -> str:
    """Get schema name for a repository.

    Args:
        repo_name: Repository name

    Returns:
        Schema name (e.g., 'codegraph_legacy1')
    """
    if not settings.use_schemas:
        return "public"

    # Sanitize repo name for use in schema name
    safe_name = repo_name.lower().replace("-", "_").replace(" ", "_")
    # Remove any characters that aren't alphanumeric or underscore
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")

    return f"{settings.schema_prefix}{safe_name}"
