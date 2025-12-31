"""Git-based incremental sync for changed files.

Uses git diff to identify changed files and reindex only those.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import asyncio
import re

from .reindexer import reindex_file


async def sync_from_git_diff(
    repo_id: str,
    repo_root: Path,
    base_ref: str,
    head_ref: str = "HEAD",
    database_url: str = None,
    generate_summaries: bool = False
) -> dict[str, any]:
    """Sync repository by analyzing git diff between two refs.

    Args:
        repo_id: Repository UUID
        repo_root: Repository root path
        base_ref: Base git ref (e.g., commit hash, branch name, tag)
        head_ref: Head git ref (default: HEAD)
        database_url: Database connection string
        generate_summaries: Whether to regenerate summaries

    Returns:
        Dictionary with sync results and stats
    """
    repo_root = repo_root.resolve()

    # Run git diff --name-status to get changed files
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", f"{base_ref}...{head_ref}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True
        )
        diff_output = result.stdout
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Git diff failed: {e.stderr}"
        }

    # Parse diff output
    changes = _parse_diff_output(diff_output, repo_root)

    if not changes:
        return {
            "success": True,
            "message": "No changes detected",
            "files_processed": 0
        }

    # Process changes
    stats = await _process_changes(
        repo_id=repo_id,
        repo_root=repo_root,
        changes=changes,
        database_url=database_url
    )

    return {
        "success": True,
        "base_ref": base_ref,
        "head_ref": head_ref,
        **stats
    }


async def sync_from_patch_file(
    repo_id: str,
    repo_root: Path,
    patch_file: Path,
    database_url: str,
    generate_summaries: bool = False
) -> dict[str, any]:
    """Sync repository by analyzing a patch file.

    Args:
        repo_id: Repository UUID
        repo_root: Repository root path
        patch_file: Path to patch file
        database_url: Database connection string
        generate_summaries: Whether to regenerate summaries

    Returns:
        Dictionary with sync results and stats
    """
    repo_root = repo_root.resolve()

    # Read patch file
    try:
        patch_content = patch_file.read_text()
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read patch file: {e}"
        }

    # Parse patch to extract changed files
    changes = _parse_patch_content(patch_content, repo_root)

    if not changes:
        return {
            "success": True,
            "message": "No changes detected in patch",
            "files_processed": 0
        }

    # Process changes
    stats = await _process_changes(
        repo_id=repo_id,
        repo_root=repo_root,
        changes=changes,
        database_url=database_url
    )

    return {
        "success": True,
        "patch_file": str(patch_file),
        **stats
    }


def _parse_diff_output(diff_output: str, repo_root: Path) -> list[tuple[str, Path]]:
    """Parse git diff --name-status output.

    Returns:
        List of (operation, file_path) tuples where operation is UPSERT or DELETE
    """
    changes = []

    for line in diff_output.strip().split("\n"):
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        status = parts[0]
        file_path = parts[1]

        # Handle rename/copy (R100, C100, etc.)
        if status.startswith("R") or status.startswith("C"):
            # Renamed/copied: old path deleted, new path added
            if len(parts) >= 3:
                old_path = parts[1]
                new_path = parts[2]
                changes.append(("DELETE", repo_root / old_path))
                changes.append(("UPSERT", repo_root / new_path))
        elif status == "D":
            # Deleted
            changes.append(("DELETE", repo_root / file_path))
        elif status in ("A", "M"):
            # Added or Modified
            changes.append(("UPSERT", repo_root / file_path))

    return changes


def _parse_patch_content(patch_content: str, repo_root: Path) -> list[tuple[str, Path]]:
    """Parse patch file content to extract changed files.

    Returns:
        List of (operation, file_path) tuples where operation is UPSERT or DELETE
    """
    changes = []

    # Extract file paths from diff headers
    # Matches: diff --git a/path b/path
    # Matches: --- a/path
    # Matches: +++ b/path
    # Matches: deleted file mode
    # Matches: new file mode

    current_file = None
    is_deletion = False
    is_addition = False

    for line in patch_content.split("\n"):
        # Check for diff header
        if line.startswith("diff --git"):
            match = re.search(r"diff --git a/(\S+) b/(\S+)", line)
            if match:
                old_path = match.group(1)
                new_path = match.group(2)
                current_file = new_path
                is_deletion = False
                is_addition = False

        # Check for deleted file
        elif line.startswith("deleted file mode"):
            is_deletion = True

        # Check for new file
        elif line.startswith("new file mode"):
            is_addition = True

        # Check for rename
        elif line.startswith("rename from"):
            match = re.search(r"rename from (\S+)", line)
            if match:
                old_path = match.group(1)
                changes.append(("DELETE", repo_root / old_path))

        elif line.startswith("rename to"):
            match = re.search(r"rename to (\S+)", line)
            if match:
                new_path = match.group(1)
                changes.append(("UPSERT", repo_root / new_path))
                current_file = None

        # Check for file headers
        elif line.startswith("---") or line.startswith("+++"):
            # Extract file path from --- a/path or +++ b/path
            if line.startswith("---"):
                match = re.search(r"--- a/(\S+)", line)
                if match and match.group(1) != "/dev/null":
                    current_file = match.group(1)
            elif line.startswith("+++"):
                match = re.search(r"\+\+\+ b/(\S+)", line)
                if match and match.group(1) != "/dev/null":
                    new_path = match.group(1)
                    if current_file and not is_deletion and not is_addition:
                        # Modified file
                        changes.append(("UPSERT", repo_root / new_path))
                    elif is_deletion:
                        changes.append(("DELETE", repo_root / current_file))
                    elif is_addition:
                        changes.append(("UPSERT", repo_root / new_path))

                    current_file = None
                    is_deletion = False
                    is_addition = False

    # Remove duplicates while preserving order
    seen = set()
    unique_changes = []
    for op, path in changes:
        key = (op, str(path))
        if key not in seen:
            seen.add(key)
            unique_changes.append((op, path))

    return unique_changes


async def _process_changes(
    repo_id: str,
    repo_root: Path,
    changes: list[tuple[str, Path]],
    database_url: str
) -> dict[str, any]:
    """Process a list of file changes.

    Args:
        repo_id: Repository UUID
        repo_root: Repository root path
        changes: List of (operation, file_path) tuples
        database_url: Database connection string

    Returns:
        Dictionary with processing stats
    """
    stats = {
        "files_processed": 0,
        "files_deleted": 0,
        "files_upserted": 0,
        "files_failed": 0,
        "total_symbols": 0,
        "total_chunks": 0,
        "total_edges": 0
    }

    for operation, file_path in changes:
        try:
            result = await reindex_file(
                repo_id=repo_id,
                abs_path=file_path,
                op=operation,
                database_url=database_url,
                repo_root=repo_root
            )

            if result["success"]:
                stats["files_processed"] += 1

                if operation == "DELETE":
                    stats["files_deleted"] += 1
                    print(f"  [DELETE] {result['path']}")
                else:  # UPSERT
                    stats["files_upserted"] += 1
                    stats["total_symbols"] += result.get("symbols", 0)
                    stats["total_chunks"] += result.get("chunks", 0)
                    stats["total_edges"] += result.get("edges", 0)
                    print(f"  [UPSERT] {result['path']} - {result.get('symbols', 0)} symbols")
            else:
                stats["files_failed"] += 1
                print(f"  [FAILED] {file_path}: {result.get('error', 'Unknown error')}")

        except Exception as e:
            stats["files_failed"] += 1
            print(f"  [ERROR] {file_path}: {e}")

    return stats
