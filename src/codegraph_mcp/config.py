"""Configuration management for CodeGraph MCP.

Loads settings from environment variables using python-dotenv.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Literal


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        # Database
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/codegraph"
        )

        # Embeddings
        self.embeddings_provider: Literal["ollama", "vllm"] = os.getenv(
            "EMBEDDINGS_PROVIDER", "ollama"
        )
        self.embeddings_model = os.getenv("EMBEDDINGS_MODEL", "nomic-embed-text")
        self.embeddings_base_url = os.getenv("EMBEDDINGS_BASE_URL", "http://localhost:11434")

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
