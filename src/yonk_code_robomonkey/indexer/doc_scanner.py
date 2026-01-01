"""Document scanner for finding documentation files.

Discovers README.md, docs/**/*.md, and other documentation files.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator


def scan_docs(repo_root: Path) -> Iterator[tuple[Path, str]]:
    """Scan repository for documentation files.

    Yields:
        Tuple of (file_path, doc_type) where doc_type is 'md', 'rst', 'adoc', or 'sql'
    """
    repo_root = repo_root.resolve()

    # Patterns to search for
    patterns = [
        "README.md",
        "readme.md",
        "README.rst",
        "readme.rst",
        "README.adoc",
        "readme.adoc",
        "**/*.md",
        "**/*.rst",
        "**/*.adoc",
        # SQL files as documentation (often contain schema definitions and migrations)
        "**/*.sql",
        "**/*.psql",
        "**/*.ddl",
    ]

    # Directories to exclude
    exclude_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
    }

    seen = set()

    for pattern in patterns:
        for file_path in repo_root.glob(pattern):
            # Skip if already processed
            if file_path in seen:
                continue

            # Skip if not a file
            if not file_path.is_file():
                continue

            # Skip if in excluded directory
            try:
                relative = file_path.relative_to(repo_root)
                if any(part in exclude_dirs for part in relative.parts):
                    continue
            except ValueError:
                continue

            # Determine doc type
            suffix = file_path.suffix.lower()
            if suffix == ".md":
                doc_type = "markdown"
            elif suffix == ".rst":
                doc_type = "restructuredtext"
            elif suffix == ".adoc":
                doc_type = "asciidoc"
            elif suffix in (".sql", ".psql", ".ddl"):
                doc_type = "sql"
            else:
                continue

            seen.add(file_path)
            yield (file_path, doc_type)
