from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    total: int = 0
    output: str = ""

async def run_tests(test_paths: list[str], working_dir: Path) -> TestResult:
    """Run pytest on specified test files and capture results."""
    if not test_paths:
        return TestResult()

    cmd = ["python", "-m", "pytest", "--tb=short", "-q", "--no-header"]
    cmd.extend(test_paths)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode()

    # Parse pytest summary line: "5 passed, 2 failed, 1 error"
    passed = failed = errors = 0
    for line in output.split("\n"):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            import re
            m_pass = re.search(r'(\d+) passed', line)
            m_fail = re.search(r'(\d+) failed', line)
            m_err = re.search(r'(\d+) error', line)
            if m_pass: passed = int(m_pass.group(1))
            if m_fail: failed = int(m_fail.group(1))
            if m_err: errors = int(m_err.group(1))

    return TestResult(
        passed=passed, failed=failed, errors=errors,
        total=passed + failed + errors, output=output,
    )
