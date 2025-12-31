"""Daemon configuration with YAML loading and validation."""

from __future__ import annotations
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml
import os


class DatabaseConfig(BaseModel):
    """Database configuration."""
    control_dsn: str = Field(
        ...,
        description="Connection string for control database (codegraph_control schema)"
    )
    pool_size: int = Field(default=10, ge=1, le=100)
    pool_timeout: int = Field(default=30, ge=1)


class OllamaConfig(BaseModel):
    """Ollama embedding provider configuration."""
    base_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="nomic-embed-text")
    timeout: int = Field(default=60, ge=1)
    batch_size: int = Field(default=32, ge=1, le=128)


class VLLMConfig(BaseModel):
    """vLLM OpenAI-compatible embedding provider configuration."""
    base_url: str = Field(default="http://localhost:8000")
    model: str = Field(...)
    api_key: str = Field(default="local-key")
    timeout: int = Field(default=60, ge=1)
    batch_size: int = Field(default=32, ge=1, le=128)


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration."""
    enabled: bool = Field(default=True)
    provider: Literal["ollama", "vllm"] = Field(default="ollama")
    dimension: int = Field(default=1536, ge=128)
    backfill_on_startup: bool = Field(
        default=False,
        description="Enqueue EMBED_MISSING jobs for all repos on daemon startup"
    )

    # Provider-specific configs
    ollama: Optional[OllamaConfig] = None
    vllm: Optional[VLLMConfig] = None

    @model_validator(mode='after')
    def validate_provider_config(self):
        """Ensure provider-specific config exists when enabled."""
        if not self.enabled:
            return self

        if self.provider == "ollama" and self.ollama is None:
            raise ValueError("embeddings.ollama config required when provider=ollama")
        if self.provider == "vllm" and self.vllm is None:
            raise ValueError("embeddings.vllm config required when provider=vllm")

        return self


class LLMConfig(BaseModel):
    """LLM configuration for summaries."""
    enabled: bool = Field(default=False)
    provider: Literal["ollama", "vllm"] = Field(default="ollama")
    model: str = Field(default="llama3.2:3b")
    base_url: str = Field(default="http://localhost:11434")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=1)


class WorkersConfig(BaseModel):
    """Worker pool configuration."""
    reindex_workers: int = Field(default=2, ge=1, le=16)
    embed_workers: int = Field(default=2, ge=1, le=16)
    docs_workers: int = Field(default=1, ge=1, le=8)
    summary_workers: int = Field(default=1, ge=0, le=8)

    max_concurrent_per_repo: int = Field(
        default=2,
        ge=1,
        description="Max concurrent jobs per repo (prevents thrashing)"
    )
    global_max_concurrent: int = Field(
        default=8,
        ge=1,
        description="Global max concurrent jobs across all repos"
    )

    poll_interval_sec: int = Field(default=5, ge=1, le=60)
    heartbeat_interval_sec: int = Field(default=30, ge=10, le=300)


class WatcherConfig(BaseModel):
    """File system watcher configuration."""
    enabled: bool = Field(default=True)
    debounce_ms: int = Field(default=500, ge=100, le=5000)
    ignore_patterns: list[str] = Field(default_factory=lambda: [
        "*.pyc",
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".DS_Store",
        "*.swp",
        "*.swo",
        ".vscode",
        ".idea",
    ])


class JobsConfig(BaseModel):
    """Job queue configuration."""
    claim_batch_size: int = Field(default=10, ge=1, le=100)
    max_retries: int = Field(default=5, ge=0)
    retry_backoff_base_sec: int = Field(default=60, ge=1)
    cleanup_retention_days: int = Field(default=7, ge=1)


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file: Optional[str] = None  # If set, log to file
    json_logs: bool = Field(default=False)


class DaemonConfig(BaseModel):
    """Root daemon configuration."""
    daemon_id: str = Field(
        default_factory=lambda: f"daemon-{os.getpid()}",
        description="Unique identifier for this daemon instance"
    )

    database: DatabaseConfig
    embeddings: EmbeddingsConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Feature flags
    enable_summaries: bool = Field(default=False)
    enable_tag_rules_sync: bool = Field(default=True)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DaemonConfig":
        """Load configuration from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    @classmethod
    def from_env(cls) -> "DaemonConfig":
        """Load configuration from environment variable CODEGRAPH_CONFIG."""
        config_path = os.getenv("CODEGRAPH_CONFIG", "config/codegraph-daemon.yaml")
        return cls.from_yaml(config_path)

    def log_effective_config(self, logger):
        """Log effective configuration (redacting secrets)."""
        config_dict = self.model_dump()

        # Redact secrets
        if "database" in config_dict and "control_dsn" in config_dict["database"]:
            dsn = config_dict["database"]["control_dsn"]
            if "@" in dsn:
                # Mask password in DSN
                parts = dsn.split("@")
                before_at = parts[0]
                if ":" in before_at:
                    user_pass = before_at.split("//")[-1]
                    if ":" in user_pass:
                        user = user_pass.split(":")[0]
                        config_dict["database"]["control_dsn"] = f"postgresql://{user}:***@{parts[1]}"

        if "vllm" in config_dict.get("embeddings", {}) and config_dict["embeddings"]["vllm"]:
            if "api_key" in config_dict["embeddings"]["vllm"]:
                config_dict["embeddings"]["vllm"]["api_key"] = "***"

        logger.info("Effective daemon configuration:")
        logger.info(f"  Daemon ID: {config_dict['daemon_id']}")
        logger.info(f"  Database: {config_dict['database']['control_dsn']}")
        logger.info(f"  Embeddings: {config_dict['embeddings']['enabled']} ({config_dict['embeddings']['provider']})")
        logger.info(f"  Workers: reindex={config_dict['workers']['reindex_workers']}, "
                   f"embed={config_dict['workers']['embed_workers']}, "
                   f"docs={config_dict['workers']['docs_workers']}")
        logger.info(f"  Watcher: {config_dict['watcher']['enabled']}")


def get_default_config_path() -> Path:
    """Get default config path."""
    # Try relative to project root
    project_root = Path(__file__).parents[3]
    default_path = project_root / "config" / "codegraph-daemon.yaml"

    return default_path


def validate_config(config: DaemonConfig) -> list[str]:
    """Validate configuration and return list of warnings/errors."""
    warnings = []

    # Check database connectivity (would need actual connection test)
    if not config.database.control_dsn.startswith("postgresql://"):
        warnings.append("database.control_dsn should start with postgresql://")

    # Check embeddings
    if config.embeddings.enabled:
        if config.embeddings.provider == "ollama" and config.embeddings.ollama:
            if "localhost" in config.embeddings.ollama.base_url:
                warnings.append("Ollama using localhost - ensure service is running")
        elif config.embeddings.provider == "vllm" and config.embeddings.vllm:
            if "localhost" in config.embeddings.vllm.base_url:
                warnings.append("vLLM using localhost - ensure service is running")

    # Check worker counts
    total_workers = (
        config.workers.reindex_workers +
        config.workers.embed_workers +
        config.workers.docs_workers +
        config.workers.summary_workers
    )
    if total_workers > config.workers.global_max_concurrent:
        warnings.append(
            f"Total worker count ({total_workers}) exceeds global_max_concurrent "
            f"({config.workers.global_max_concurrent})"
        )

    return warnings
