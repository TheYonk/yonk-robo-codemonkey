"""Language detection by file extension.

Supports: Python, JavaScript, TypeScript, Go, Java, SQL
Also supports template engines and framework files that contain code in the target language.
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal

Language = Literal["python", "javascript", "typescript", "go", "java", "c", "sql", "unknown"]

# Extension to language mapping
EXTENSION_MAP: dict[str, Language] = {
    # Python
    ".py": "python",
    ".pyw": "python",  # Python Windows
    ".pyi": "python",  # Python type stubs

    # JavaScript (pure)
    ".js": "javascript",
    ".mjs": "javascript",  # ES modules
    ".cjs": "javascript",  # CommonJS
    ".jsx": "javascript",  # React JSX

    # JavaScript templates (HTML + JS in <script> tags)
    ".ejs": "javascript",  # EJS templates
    ".hbs": "javascript",  # Handlebars templates
    ".handlebars": "javascript",
    ".html": "javascript",  # HTML with embedded scripts
    ".htm": "javascript",
    ".vue": "javascript",  # Vue.js single-file components
    ".svelte": "javascript",  # Svelte components
    ".astro": "javascript",  # Astro components

    # TypeScript
    ".ts": "typescript",
    ".mts": "typescript",  # TypeScript modules
    ".cts": "typescript",  # TypeScript CommonJS
    ".tsx": "typescript",  # React TypeScript

    # Go
    ".go": "go",

    # Java
    ".java": "java",
    ".jsp": "java",  # JavaServer Pages

    # C
    ".c": "c",
    ".h": "c",

    # SQL and related
    ".sql": "sql",
    ".psql": "sql",
    ".pgsql": "sql",
    ".plsql": "sql",
    ".ddl": "sql",
    ".dml": "sql",
}


# Template extensions that need script extraction
TEMPLATE_EXTENSIONS = {
    ".ejs", ".hbs", ".handlebars", ".html", ".htm",
    ".vue", ".svelte", ".astro", ".jsp", ".erb"
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


def is_template_file(file_path: Path | str) -> bool:
    """Check if file is a template that needs script extraction.

    Args:
        file_path: Path to the file

    Returns:
        True if file is a template file (HTML-based with embedded code)
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    return ext in TEMPLATE_EXTENSIONS
