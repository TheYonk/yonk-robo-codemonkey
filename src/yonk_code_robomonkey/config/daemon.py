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
    count: int = Field(2, ge=1, le=16, description="Number of worker processes")
    enabled_job_types: list[str] = Field(
        default_factory=lambda: ["EMBED_REPO", "EMBED_MISSING", "INDEX_REPO", "WATCH_REPO"],
        description="Job types to process"
    )


class WatchingConfig(BaseModel):
    """File system watching configuration."""
    enabled: bool = Field(True, description="Enable file watching")
    debounce_seconds: int = Field(2, ge=1, le=60, description="Debounce delay")
    ignore_patterns: list[str] = Field(
        default_factory=lambda: ["*.pyc", "__pycache__", ".git", "node_modules", ".venv"],
        description="Patterns to ignore"
    )


class MonitoringConfig(BaseModel):
    """Monitoring and health check configuration."""
    heartbeat_interval: int = Field(30, ge=5, le=300, description="Heartbeat interval (seconds)")
    dead_threshold: int = Field(120, ge=30, le=600, description="Dead threshold (seconds)")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO", description="Log level")


class DevModeConfig(BaseModel):
    """Development mode configuration."""
    enabled: bool = Field(False, description="Enable dev mode")
    auto_reload: bool = Field(False, description="Auto-reload on code changes")
    verbose: bool = Field(False, description="Verbose logging")


class DaemonConfig(BaseModel):
    """Complete daemon configuration."""
    database: DatabaseConfig
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    watching: WatchingConfig = Field(default_factory=WatchingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
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
