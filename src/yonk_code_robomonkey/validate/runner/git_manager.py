"""Git state management for reproducible benchmark runs."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GitManager:
    """Manage git state for reproducible benchmark runs."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.repo_dir,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def reset_to_commit(self, commit: str) -> None:
        """Reset repo to exact commit (detached HEAD)."""
        rc, _, err = await self._run_git("checkout", commit, "--detach")
        if rc != 0:
            raise RuntimeError(f"git checkout failed: {err}")
        # Reset tracked files to commit state
        rc, _, err = await self._run_git("reset", "--hard")
        if rc != 0:
            raise RuntimeError(f"git reset failed: {err}")
        # Clean untracked files but preserve common development artifacts
        rc, _, err = await self._run_git(
            "clean", "-fdx",
            "--exclude=.venv",
            "--exclude=.env",
            "--exclude=node_modules",
        )
        if rc != 0:
            raise RuntimeError(f"git clean failed: {err}")

    async def is_clean(self) -> bool:
        """Check if working tree is clean."""
        rc, stdout, _ = await self._run_git("status", "--porcelain")
        return rc == 0 and stdout.strip() == ""

    async def verify_clean(self) -> None:
        """Assert working tree is clean, raise if not."""
        if not await self.is_clean():
            raise RuntimeError(f"Repo {self.repo_dir} has uncommitted changes")

    async def get_diff_stats(self) -> dict:
        """Get diff statistics after a run."""
        rc, stdout, _ = await self._run_git("diff", "--stat")
        rc2, stdout2, _ = await self._run_git("diff", "--numstat")
        added = removed = 0
        files_changed = []
        for line in stdout2.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 3:
                a = int(parts[0]) if parts[0] != "-" else 0
                r = int(parts[1]) if parts[1] != "-" else 0
                added += a
                removed += r
                files_changed.append(parts[2])
        return {
            "lines_added": added,
            "lines_removed": removed,
            "files_changed": files_changed,
        }
