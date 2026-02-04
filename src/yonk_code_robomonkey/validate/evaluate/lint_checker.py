from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class LintResult:
    lint_errors: int = 0
    type_errors: int = 0
    lint_output: str = ""
    type_output: str = ""

async def check_lint(files: list[str], working_dir: Path) -> int:
    """Run ruff on specified files, return error count."""
    if not files:
        return 0
    cmd = ["python", "-m", "ruff", "check", "--quiet"] + files
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    # Count non-empty output lines
    return sum(1 for line in stdout.decode().strip().split("\n") if line.strip())

async def check_types(files: list[str], working_dir: Path) -> int:
    """Run mypy on specified files, return error count."""
    if not files:
        return 0
    cmd = ["python", "-m", "mypy", "--no-error-summary", "--ignore-missing-imports"] + files
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    lines = [l for l in stdout.decode().strip().split("\n") if l.strip() and ": error:" in l]
    return len(lines)

async def run_lint_checks(files: list[str], working_dir: Path) -> LintResult:
    """Run both lint and type checks."""
    lint_count, type_count = await asyncio.gather(
        check_lint(files, working_dir),
        check_types(files, working_dir),
    )
    return LintResult(lint_errors=lint_count, type_errors=type_count)
