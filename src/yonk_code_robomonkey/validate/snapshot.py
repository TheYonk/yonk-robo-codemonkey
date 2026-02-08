"""Database snapshot and restore for validation schemas.

Allows quick reset between test runs instead of re-indexing.
Snapshots are stored in ~/.robomonkey/validate/snapshots/{repo_name}.sql
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from yonk_code_robomonkey.config_settings import settings, get_schema_name


def _snapshots_dir() -> Path:
    """Get the snapshots directory."""
    d = Path.home() / ".robomonkey" / "validate" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot_path(repo_name: str) -> Path:
    """Get path to a repo's snapshot file."""
    return _snapshots_dir() / f"{repo_name}.sql"


def _parse_db_url(url: str) -> dict:
    """Parse DATABASE_URL into components for pg_dump/psql."""
    # postgresql://user:pass@host:port/dbname
    import re
    match = re.match(
        r"postgresql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<dbname>.+)",
        url
    )
    if not match:
        raise ValueError(f"Cannot parse DATABASE_URL: {url}")
    return match.groupdict()


async def snapshot_schema(repo_name: str, container: str = "robomonkey-postgres") -> Path:
    """Create a snapshot of a repo's schema.

    Args:
        repo_name: Name of the repo to snapshot
        container: Docker container name running PostgreSQL

    Returns:
        Path to the snapshot file
    """
    schema_name = get_schema_name(repo_name)
    snapshot_file = _snapshot_path(repo_name)
    db = _parse_db_url(settings.database_url)

    print(f"  Creating snapshot of {schema_name}...")

    # Use docker exec to run pg_dump inside the container (avoids version mismatch)
    env = {"PGPASSWORD": db["password"]}

    cmd = [
        "docker", "exec", "-e", f"PGPASSWORD={db['password']}", container,
        "pg_dump",
        "-U", db["user"],
        "-d", db["dbname"],
        "-n", schema_name,
        "--no-owner",
        "--no-privileges",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

    # Write output to file
    snapshot_file.write_bytes(stdout)

    size_kb = snapshot_file.stat().st_size / 1024
    print(f"  Snapshot saved: {snapshot_file} ({size_kb:.1f} KB)")

    return snapshot_file


async def restore_schema(repo_name: str, container: str = "robomonkey-postgres") -> None:
    """Restore a repo's schema from snapshot.

    Args:
        repo_name: Name of the repo to restore
        container: Docker container name running PostgreSQL
    """
    schema_name = get_schema_name(repo_name)
    snapshot_file = _snapshot_path(repo_name)

    if not snapshot_file.exists():
        raise FileNotFoundError(f"No snapshot found for {repo_name}: {snapshot_file}")

    db = _parse_db_url(settings.database_url)

    print(f"  Restoring {schema_name} from snapshot...")

    # First drop the existing schema using docker exec
    drop_cmd = [
        "docker", "exec", "-e", f"PGPASSWORD={db['password']}", container,
        "psql", "-U", db["user"], "-d", db["dbname"],
        "-c", f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE;',
    ]

    proc = await asyncio.create_subprocess_exec(
        *drop_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Pipe snapshot content to psql via docker exec
    restore_cmd = [
        "docker", "exec", "-i", "-e", f"PGPASSWORD={db['password']}", container,
        "psql", "-U", db["user"], "-d", db["dbname"],
    ]

    proc = await asyncio.create_subprocess_exec(
        *restore_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=snapshot_file.read_bytes())

    if proc.returncode != 0:
        raise RuntimeError(f"psql restore failed: {stderr.decode()}")

    print(f"  Restored {schema_name} from snapshot")


async def list_snapshots() -> list[dict]:
    """List all available snapshots.

    Returns:
        List of dicts with repo_name, path, size_kb, modified
    """
    snapshots = []
    for f in _snapshots_dir().glob("*.sql"):
        stat = f.stat()
        snapshots.append({
            "repo_name": f.stem,
            "path": str(f),
            "size_kb": stat.st_size / 1024,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return sorted(snapshots, key=lambda x: x["repo_name"])


async def delete_snapshot(repo_name: str) -> bool:
    """Delete a snapshot file.

    Args:
        repo_name: Name of the repo whose snapshot to delete

    Returns:
        True if deleted, False if not found
    """
    snapshot_file = _snapshot_path(repo_name)
    if snapshot_file.exists():
        snapshot_file.unlink()
        print(f"  Deleted snapshot: {snapshot_file}")
        return True
    return False
