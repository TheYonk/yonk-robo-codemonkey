"""Daemon configuration loading and validation.

Loads YAML configuration for the RoboMonkey daemon with full validation.
"""
from __future__ import annotations
import os
import yaml
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class DatabaseConfig(BaseModel):
    """Database configuration."""
    control_dsn: str = Field(..., description="Control schema database URL")
    schema_prefix: str = Field("robomonkey_", description="Schema prefix for repos")
    pool_size: int = Field(10, ge=1, le=50, description="Connection pool size")

    @field_validator("control_dsn")
    @classmethod
    def validate_dsn(cls, v: str) -> str:
        """Validate database URL format."""
        if not v.startswith("postgresql://"):
            raise ValueError("control_dsn must start with 'postgresql://'")
        return v


class OllamaConfig(BaseModel):
    """Ollama-specific configuration."""
    base_url: str = Field("http://localhost:11434", description="Ollama API URL")


class VLLMConfig(BaseModel):
    """vLLM-specific configuration."""
    base_url: str = Field("http://localhost:8000", description="vLLM API URL")
    api_key: str = Field("local-key", description="API key for vLLM")


class LLMModelConfig(BaseModel):
    """Configuration for a single LLM model."""
    provider: Literal["ollama", "vllm", "openai"] = Field("ollama", description="LLM provider: ollama, vllm, or openai")
    model: str = Field(..., description="Model name")
    base_url: str = Field("http://localhost:11434", description="API endpoint")
    api_key: str | None = Field(None, description="API key (required for openai, optional for vllm)")
    temperature: float = Field(0.3, ge=0, le=2, description="Temperature for generation")
    max_tokens: int = Field(2000, ge=100, le=128000, description="Max tokens to generate")


class LLMConfig(BaseModel):
    """Dual LLM configuration for deep vs small tasks.

    - deep: Heavy/complex tasks (code analysis, feature context, comprehensive reviews)
    - small: Light/simple tasks (summaries, classifications, quick answers)
    """
    deep: LLMModelConfig = Field(
        default_factory=lambda: LLMModelConfig(
            provider="ollama",
            model="qwen3-coder:30b",
            base_url="http://localhost:11434",
            temperature=0.3,
            max_tokens=4000
        ),
        description="Model for deep/complex tasks"
    )
    small: LLMModelConfig = Field(
        default_factory=lambda: LLMModelConfig(
            provider="ollama",
            model="phi3.5:3.8b",
            base_url="http://localhost:11434",
            temperature=0.3,
            max_tokens=1000
        ),
        description="Model for small/simple tasks"
    )

    def get_model(self, task_type: str = "small") -> LLMModelConfig:
        """Get the appropriate model config for a task type.

        Args:
            task_type: 'deep' for complex tasks, 'small' for simple tasks

        Returns:
            LLMModelConfig for the requested task type
        """
        if task_type == "deep":
            return self.deep
        return self.small


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration."""
    enabled: bool = Field(True, description="Enable embeddings generation")
    backfill_on_startup: bool = Field(True, description="Backfill missing embeddings on startup")
    provider: Literal["ollama", "vllm"] = Field("ollama", description="Embedding provider")
    model: str = Field("snowflake-arctic-embed2:latest", description="Model name")
    dimension: int = Field(1024, description="Embedding dimension")
    max_chunk_length: int = Field(8192, description="Max characters per chunk")
    batch_size: int = Field(100, description="Batch size for processing")
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    vllm: VLLMConfig = Field(default_factory=VLLMConfig)
    
    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, v: int) -> int:
        """Validate embedding dimension is reasonable."""
        if v < 128 or v > 4096:
            raise ValueError("dimension must be between 128 and 4096")
        return v
    
    def model_post_init(self, __context) -> None:
        """Validate provider-specific configuration."""
        if self.enabled:
            if self.provider == "ollama" and not self.ollama.base_url:
                raise ValueError("ollama.base_url required when provider=ollama")
            if self.provider == "vllm" and not self.vllm.base_url:
                raise ValueError("vllm.base_url required when provider=vllm")


class WorkersConfig(BaseModel):
    """Job workers configuration."""
    # Global concurrency limits
    global_max_concurrent: int = Field(4, ge=1, le=32, description="Global max concurrent jobs")
    max_concurrent_per_repo: int = Field(2, ge=1, le=8, description="Max concurrent jobs per repo")

    # Worker counts by type
    reindex_workers: int = Field(2, ge=1, le=16, description="Number of reindex workers")
    embed_workers: int = Field(2, ge=1, le=16, description="Number of embedding workers")
    docs_workers: int = Field(1, ge=1, le=8, description="Number of docs workers")

    # Polling configuration
    poll_interval_sec: int = Field(5, ge=1, le=60, description="Job polling interval (seconds)")

    # Legacy fields (for backward compatibility)
    count: int = Field(2, ge=1, le=16, description="Number of worker processes (deprecated)")
    enabled_job_types: list[str] = Field(
        default_factory=lambda: ["EMBED_REPO", "EMBED_MISSING", "INDEX_REPO", "WATCH_REPO"],
        description="Job types to process"
    )


class WatchingConfig(BaseModel):
    """File system watching configuration."""
    enabled: bool = Field(True, description="Enable file watching")
    debounce_seconds: int = Field(2, ge=1, le=60, description="Debounce delay")
    ignore_patterns: list[str] = Field(
        default_factory=lambda: ["*.pyc", "__pycache__", ".git", "node_modules", ".venv", "dist", "build", ".next"],
        description="Patterns to ignore"
    )
    code_extensions: list[str] = Field(
        default_factory=lambda: [
            ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java",
            ".ejs", ".hbs", ".handlebars", ".html", ".htm",
            ".vue", ".svelte", ".astro"
        ],
        description="File extensions to watch for code changes"
    )
    doc_extensions: list[str] = Field(
        default_factory=lambda: [".md", ".rst", ".adoc"],
        description="File extensions to watch for documentation changes"
    )


class MonitoringConfig(BaseModel):
    """Monitoring and health check configuration."""
    heartbeat_interval: int = Field(30, ge=5, le=300, description="Heartbeat interval (seconds)")
    dead_threshold: int = Field(120, ge=30, le=600, description="Dead threshold (seconds)")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO", description="Log level")


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO", description="Log level")
    format: str = Field(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string"
    )


class DevModeConfig(BaseModel):
    """Development mode configuration."""
    enabled: bool = Field(False, description="Enable dev mode")
    auto_reload: bool = Field(False, description="Auto-reload on code changes")
    verbose: bool = Field(False, description="Verbose logging")


class ReadOnlyConfig(BaseModel):
    """Per-type read-only settings to prevent overwrites."""
    summaries: bool = Field(False, description="Don't overwrite existing summaries")
    file_summaries: bool = Field(False, description="Don't overwrite file summaries")
    symbol_summaries: bool = Field(False, description="Don't overwrite symbol summaries")
    module_summaries: bool = Field(False, description="Don't overwrite module summaries")
    embeddings: bool = Field(False, description="Don't regenerate embeddings")


class SummariesConfig(BaseModel):
    """Auto-summary generation configuration."""
    enabled: bool = Field(True, description="Enable auto-summary generation")
    read_only: ReadOnlyConfig = Field(default_factory=ReadOnlyConfig, description="Per-type read-only settings")
    check_interval_minutes: int = Field(60, ge=1, le=1440, description="How often to check for changes (1-1440 minutes)")
    generate_on_index: bool = Field(False, description="Generate summaries immediately after indexing")
    provider: Literal["ollama", "vllm", "openai"] = Field("ollama", description="LLM provider")
    model: str = Field("qwen3-coder:30b", description="Model name for summaries")
    base_url: str = Field("http://localhost:11434", description="LLM endpoint")
    batch_size: int = Field(10, ge=1, le=100, description="Batch size for summary generation")

    @field_validator("check_interval_minutes")
    @classmethod
    def validate_check_interval(cls, v: int) -> int:
        """Validate check interval is within reasonable bounds."""
        if v < 1 or v > 1440:
            raise ValueError("check_interval_minutes must be between 1 and 1440 (24 hours)")
        return v


class DocValidityConfig(BaseModel):
    """Document validity scoring configuration."""
    enabled: bool = Field(True, description="Enable document validity scoring")
    check_interval_minutes: int = Field(120, ge=10, le=1440, description="Check interval (10-1440 minutes)")

    # Score weights (should sum to 1.0)
    reference_weight: float = Field(0.45, ge=0, le=1, description="Weight for reference validity")
    embedding_weight: float = Field(0.30, ge=0, le=1, description="Weight for embedding similarity")
    freshness_weight: float = Field(0.25, ge=0, le=1, description="Weight for freshness")

    # Thresholds
    stale_threshold: int = Field(50, ge=0, le=100, description="Score below which doc is considered stale")
    warning_threshold: int = Field(70, ge=0, le=100, description="Score below which to show warning")

    # LLM validation (optional)
    use_llm_validation: bool = Field(False, description="Use LLM for deep validation (expensive)")
    llm_provider: Literal["ollama", "vllm", "openai"] = Field("ollama", description="LLM provider for validation")
    llm_model: str = Field("qwen3-coder:30b", description="Model name for LLM validation")
    llm_base_url: str = Field("http://localhost:11434", description="LLM endpoint")
    llm_weight: float = Field(0.30, ge=0, le=1, description="Weight for LLM score when enabled")

    # Performance
    batch_size: int = Field(20, ge=1, le=100, description="Documents per validation batch")
    max_references_per_doc: int = Field(100, ge=10, le=500, description="Max references to extract per doc")

    # Semantic validation (behavioral claim verification)
    semantic_validation_enabled: bool = Field(False, description="Enable semantic validation (LLM-based)")
    semantic_check_interval_minutes: int = Field(360, ge=60, le=2880, description="Semantic check interval (60-2880 minutes)")
    max_claims_per_doc: int = Field(30, ge=5, le=100, description="Max behavioral claims to extract per doc")
    claim_min_confidence: float = Field(0.7, ge=0.5, le=1.0, description="Min confidence for claim extraction")
    semantic_batch_size: int = Field(5, ge=1, le=20, description="Documents per semantic validation batch")
    semantic_min_structural_score: int = Field(60, ge=0, le=100, description="Min structural score to run semantic validation")
    semantic_weight: float = Field(0.25, ge=0, le=1, description="Weight for semantic score when enabled")

    @field_validator("check_interval_minutes")
    @classmethod
    def validate_check_interval(cls, v: int) -> int:
        """Validate check interval is within reasonable bounds."""
        if v < 10 or v > 1440:
            raise ValueError("check_interval_minutes must be between 10 and 1440 (24 hours)")
        return v


class DaemonConfig(BaseModel):
    """Complete daemon configuration."""
    daemon_id: str = Field(default_factory=lambda: f"robomonkey-{os.getpid()}", description="Unique daemon ID")
    database: DatabaseConfig
    llm: LLMConfig = Field(default_factory=LLMConfig, description="Dual LLM configuration (deep + small)")
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    summaries: SummariesConfig = Field(default_factory=SummariesConfig)
    doc_validity: DocValidityConfig = Field(default_factory=DocValidityConfig)
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    watching: WatchingConfig = Field(default_factory=WatchingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    dev_mode: DevModeConfig = Field(default_factory=DevModeConfig)
    
    @classmethod
    def from_yaml(cls, path: str | Path) -> DaemonConfig:
        """Load configuration from YAML file.
        
        Args:
            path: Path to YAML configuration file
            
        Returns:
            Validated DaemonConfig instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If configuration is invalid
        """
        config_path = Path(path)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data:
            raise ValueError(f"Empty configuration file: {config_path}")
        
        try:
            return cls.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid configuration in {config_path}: {e}") from e
    
    @classmethod
    def from_env(cls, env_var: str = "ROBOMONKEY_CONFIG") -> DaemonConfig:
        """Load configuration from path in environment variable.
        
        Args:
            env_var: Environment variable name (default: ROBOMONKEY_CONFIG)
            
        Returns:
            Validated DaemonConfig instance
            
        Raises:
            ValueError: If env var not set or config invalid
        """
        config_path = os.getenv(env_var)
        
        if not config_path:
            # Try default path
            default_path = Path("config/robomonkey-daemon.yaml")
            if default_path.exists():
                return cls.from_yaml(default_path)
            raise ValueError(
                f"Environment variable {env_var} not set and default config not found at {default_path}"
            )
        
        return cls.from_yaml(config_path)
    
    def log_redacted(self) -> dict:
        """Get configuration dict with secrets redacted for logging.
        
        Returns:
            Dictionary with sensitive values redacted
        """
        config_dict = self.model_dump()
        
        # Redact secrets
        if "database" in config_dict and "control_dsn" in config_dict["database"]:
            dsn = config_dict["database"]["control_dsn"]
            # Redact password from DSN
            if "@" in dsn:
                parts = dsn.split("@")
                if ":" in parts[0]:
                    user_pass = parts[0].split(":")
                    config_dict["database"]["control_dsn"] = f"{user_pass[0]}:***@{parts[1]}"
        
        if "embeddings" in config_dict and "vllm" in config_dict["embeddings"]:
            if "api_key" in config_dict["embeddings"]["vllm"]:
                config_dict["embeddings"]["vllm"]["api_key"] = "***"
        
        return config_dict


def load_daemon_config(config_path: str | Path | None = None) -> DaemonConfig:
    """Load daemon configuration from file or environment.
    
    Args:
        config_path: Optional explicit path to config file
        
    Returns:
        Validated DaemonConfig instance
        
    Raises:
        ValueError: If configuration is invalid or not found
    """
    if config_path:
        return DaemonConfig.from_yaml(config_path)
    
    return DaemonConfig.from_env()
