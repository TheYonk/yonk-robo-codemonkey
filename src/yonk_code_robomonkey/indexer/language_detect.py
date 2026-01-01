"""Language detection by file extension.

Supports: Python, JavaScript, TypeScript, Go, Java, SQL
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal

Language = Literal["python", "javascript", "typescript", "go", "java", "sql", "unknown"]

# Extension to language mapping
EXTENSION_MAP: dict[str, Language] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    # SQL and related
    ".sql": "sql",
    ".psql": "sql",
    ".pgsql": "sql",
    ".plsql": "sql",
    ".ddl": "sql",
    ".dml": "sql",
}


def detect_language(file_path: Path | str) -> Language:
    """Detect language from file extension.

    Args:
        file_path: Path to the file

    Returns:
        Language identifier or "unknown"
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    return EXTENSION_MAP.get(ext, "unknown")
