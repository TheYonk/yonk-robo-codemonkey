"""Repository scanner with .gitignore support.

Walks directory tree and yields files, respecting .gitignore patterns.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator
import pathspec

from .language_detect import detect_language


def scan_repo(
    repo_root: Path | str,
    ignore_file: str = ".gitignore"
) -> Iterator[tuple[Path, str]]:
    """Scan repository for source files, honoring .gitignore.

    Args:
        repo_root: Root directory of the repository
        ignore_file: Name of ignore file (default: .gitignore)

    Yields:
        Tuples of (file_path, language) for each source file
    """
    repo_root = Path(repo_root).resolve()

    if not repo_root.exists():
        raise FileNotFoundError(f"Repository path not found: {repo_root}")

    if not repo_root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {repo_root}")

    # Load .gitignore patterns
    gitignore_path = repo_root / ignore_file
    spec = None

    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8") as f:
            patterns = f.read()
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns.splitlines())

    # Walk directory tree
    for file_path in _walk_directory(repo_root, spec, repo_root):
        language = detect_language(file_path)

        # Only yield files with known languages
        if language != "unknown":
            yield (file_path, language)


def _walk_directory(
    directory: Path,
    spec: pathspec.PathSpec | None,
    repo_root: Path
) -> Iterator[Path]:
    """Recursively walk directory, applying gitignore filters.

    Args:
        directory: Directory to walk
        spec: PathSpec for gitignore patterns
        repo_root: Repository root for relative path calculation

    Yields:
        File paths that should be indexed
    """
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        # Skip directories we can't read
        return

    for entry in entries:
        # Skip hidden files/directories (except .gitignore itself)
        if entry.name.startswith(".") and entry.name != ".gitignore":
            continue

        # Calculate relative path for gitignore matching
        try:
            rel_path = entry.relative_to(repo_root)
        except ValueError:
            # Entry is not relative to repo_root, skip it
            continue

        # Check if path matches gitignore patterns
        if spec and spec.match_file(str(rel_path)):
            continue

        if entry.is_file():
            yield entry
        elif entry.is_dir():
            # Recursively walk subdirectories
            yield from _walk_directory(entry, spec, repo_root)
