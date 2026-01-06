"""Configuration management for RoboMonkey."""
# Import from sibling config.py module
import sys
from pathlib import Path

# Add parent directory to path to import sibling modules
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# Import settings from config.py (sibling module)
from yonk_code_robomonkey.config_settings import settings, Settings, get_schema_name

# Import daemon config classes
from .daemon import (
    DaemonConfig,
    DatabaseConfig,
    EmbeddingsConfig,
    SummariesConfig,
    WorkersConfig,
    WatchingConfig,
    MonitoringConfig,
    LoggingConfig,
    DevModeConfig,
    load_daemon_config,
)

__all__ = [
    # Daemon config
    "DaemonConfig",
    "DatabaseConfig",
    "EmbeddingsConfig",
    "SummariesConfig",
    "WorkersConfig",
    "WatchingConfig",
    "MonitoringConfig",
    "LoggingConfig",
    "DevModeConfig",
    "load_daemon_config",
    # Legacy settings (from config.py)
    "settings",
    "Settings",
    "get_schema_name",
]
