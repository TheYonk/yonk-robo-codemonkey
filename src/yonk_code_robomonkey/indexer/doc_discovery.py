"""Auto-discovery of documentation files in repositories.

This module provides a higher-level interface for discovering documentation files
in repositories. It wraps the existing doc_scanner with configurable include/exclude
patterns for flexible doc discovery scenarios.
"""

import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Default patterns for doc discovery
DOC_INCLUDE_PATTERNS = [
    "README*",
    "CHANGELOG*",
    "*.md",
    "*.rst",
    "*.adoc",
    "docs/**/*.md",
    "docs/**/*.rst",
    "docs/**/*.pdf",
    "doc/**/*.md",
    "doc/**/*.pdf",
]

DOC_EXCLUDE_PATTERNS = [
    "node_modules/**",
    "vendor/**",
    ".git/**",
    "dist/**",
    "build/**",
    "__pycache__/**",
    "*.min.js",
    "*.bundle.js",
    ".venv/**",
    "venv/**",
]


def discover_repo_docs(
    repo_path: str | Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> Iterator[Path]:
    """Discover documentation files in a repository.

    Args:
        repo_path: Path to repository root
        include_patterns: Glob patterns to include (default: DOC_INCLUDE_PATTERNS)
        exclude_patterns: Glob patterns to exclude (default: DOC_EXCLUDE_PATTERNS)

    Yields:
        Path objects for each discovered doc file
    """
    repo_path = Path(repo_path)
    include_patterns = include_patterns or DOC_INCLUDE_PATTERNS
    exclude_patterns = exclude_patterns or DOC_EXCLUDE_PATTERNS

    # Collect all matching files
    seen = set()
    for pattern in include_patterns:
        for path in repo_path.glob(pattern):
            if path.is_file():
                rel_path = path.relative_to(repo_path)
                rel_str = str(rel_path)

                # Skip if excluded
                skip = False
                for exc in exclude_patterns:
                    # Simple check: if any component matches exclude pattern
                    if any(part in exc.replace("/**", "").replace("**", "")
                           for part in rel_path.parts):
                        skip = True
                        break

                if skip:
                    continue

                # Skip if already seen
                if rel_str in seen:
                    continue
                seen.add(rel_str)

                logger.debug(f"Discovered doc: {rel_path}")
                yield path

    logger.info(f"Discovered {len(seen)} documentation files in {repo_path}")
