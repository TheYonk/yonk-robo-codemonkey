# Phase 5: Hallucination Detection

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 4 (RunResult, tool calls)
> **Produces:** File, symbol, and import hallucination checks

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/capture/hallucination.py` | Hallucination detection |
| `tests/test_validate_hallucination.py` | Tests for this phase |

---

## Design

Three types of hallucination to detect:

1. **File hallucinations:** AI references files that don't exist on disk
2. **Symbol hallucinations:** AI references functions/classes that don't exist in the codebase
3. **Import hallucinations:** AI writes import statements that can't resolve

### Inputs

- `diff_text`: The git diff the AI produced
- `conversation_text`: The AI's response text
- `repo_dir`: The target repository directory
- `database_url` + `repo_id` (optional): For symbol lookup via RoboMonkey's index

### Strategy

- **Files:** Regex extract paths from conversation and diff, check `os.path.exists()`
- **Symbols:** Regex extract function/class names from the diff's added lines, check against repo with `grep` or RoboMonkey's symbol table
- **Imports:** Parse added import lines from diff, try `importlib.util.find_spec()` for stdlib, check file existence for relative imports

```python
# hallucination.py
from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class HallucinationReport:
    """Results of hallucination detection."""
    hallucinated_files: list[str] = field(default_factory=list)
    hallucinated_symbols: list[str] = field(default_factory=list)
    hallucinated_imports: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.hallucinated_files) + len(self.hallucinated_symbols) + len(self.hallucinated_imports)

# Pattern: paths like src/foo/bar.py or ./foo/bar.py
FILE_PATH_PATTERN = re.compile(r'(?:^|[\s"`\'(])([a-zA-Z0-9_./-]+\.[a-zA-Z]{1,5})(?:[\s"`\'),;:]|$)')

# Pattern: Python import lines
IMPORT_PATTERN = re.compile(r'^[+]\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', re.MULTILINE)

def detect_file_hallucinations(
    text: str,
    repo_dir: Path,
) -> list[str]:
    """Find file paths mentioned in text that don't exist."""
    candidates = set(FILE_PATH_PATTERN.findall(text))
    hallucinated = []
    for path_str in candidates:
        # Skip obvious non-paths
        if path_str.startswith("http") or path_str.startswith("//"):
            continue
        # Check relative to repo
        full = repo_dir / path_str
        if not full.exists() and path_str not in (".env", "requirements.txt"):
            # Only flag paths that look like project files
            if "/" in path_str or path_str.endswith(".py"):
                hallucinated.append(path_str)
    return hallucinated

def detect_import_hallucinations(
    diff_text: str,
    repo_dir: Path,
) -> list[str]:
    """Find import statements in diff that can't resolve."""
    hallucinated = []
    for match in IMPORT_PATTERN.finditer(diff_text):
        module = match.group(1) or match.group(2)
        if not module:
            continue
        # Check if it's a stdlib/installed module
        try:
            import importlib.util
            if importlib.util.find_spec(module.split(".")[0]):
                continue
        except (ModuleNotFoundError, ValueError):
            pass
        # Check if it's a local module
        parts = module.replace(".", "/")
        if (repo_dir / f"{parts}.py").exists():
            continue
        if (repo_dir / parts / "__init__.py").exists():
            continue
        hallucinated.append(module)
    return hallucinated

def detect_symbol_hallucinations(
    diff_text: str,
    repo_dir: Path,
) -> list[str]:
    """Find function/class references in diff that don't exist in repo.

    Simple approach: extract identifiers from added lines, check if they
    appear anywhere in the repo source files. More sophisticated checking
    against RoboMonkey's symbol table can be added later.
    """
    # Extract identifiers from added lines that look like function/class usage
    added_lines = [line[1:] for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++")]

    # Find called functions: name( pattern
    call_pattern = re.compile(r'(\b[A-Z]\w+)\(')  # ClassName( pattern
    called = set()
    for line in added_lines:
        called.update(call_pattern.findall(line))

    if not called:
        return []

    # Check each against repo source files
    hallucinated = []
    all_source = ""
    for py_file in repo_dir.rglob("*.py"):
        try:
            all_source += py_file.read_text(errors="ignore")
        except Exception:
            continue

    for name in called:
        # Skip common builtins
        if name in ("Exception", "ValueError", "TypeError", "RuntimeError",
                     "KeyError", "IndexError", "AttributeError", "FileNotFoundError",
                     "Path", "Optional", "Any", "Dict", "List", "Set", "Tuple",
                     "True", "False", "None", "MagicMock", "AsyncMock"):
            continue
        if f"class {name}" not in all_source and f"def {name}" not in all_source:
            hallucinated.append(name)

    return hallucinated

async def check_hallucinations(
    diff_text: str,
    conversation_text: str,
    repo_dir: Path,
) -> HallucinationReport:
    """Run all hallucination checks."""
    return HallucinationReport(
        hallucinated_files=detect_file_hallucinations(conversation_text, repo_dir),
        hallucinated_imports=detect_import_hallucinations(diff_text, repo_dir),
        hallucinated_symbols=detect_symbol_hallucinations(diff_text, repo_dir),
    )
```

## Tests

```python
# tests/test_validate_hallucination.py
import pytest
from pathlib import Path
from yonk_code_robomonkey.validate.capture.hallucination import (
    detect_file_hallucinations,
    detect_import_hallucinations,
    detect_symbol_hallucinations,
    check_hallucinations,
    HallucinationReport,
)

def test_detect_real_file(tmp_path):
    """No hallucination for files that exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    result = detect_file_hallucinations("check src/main.py", tmp_path)
    assert result == []

def test_detect_fake_file(tmp_path):
    """Detect file path that doesn't exist."""
    result = detect_file_hallucinations("look at src/nonexistent.py for details", tmp_path)
    assert "src/nonexistent.py" in result

def test_detect_valid_import(tmp_path):
    """No hallucination for valid stdlib import."""
    diff = "+import json\n+import os"
    result = detect_import_hallucinations(diff, tmp_path)
    assert result == []

def test_detect_fake_import(tmp_path):
    """Detect import that can't resolve."""
    diff = "+from totally_fake_module import something"
    result = detect_import_hallucinations(diff, tmp_path)
    assert "totally_fake_module" in result

def test_detect_valid_symbol(tmp_path):
    """No hallucination for class that exists in repo."""
    (tmp_path / "models.py").write_text("class MyModel:\n    pass\n")
    diff = "+obj = MyModel()"
    result = detect_symbol_hallucinations(diff, tmp_path)
    assert "MyModel" not in result

def test_detect_fake_symbol(tmp_path):
    """Detect class reference that doesn't exist."""
    (tmp_path / "models.py").write_text("class RealModel:\n    pass\n")
    diff = "+obj = FakeModel()"
    result = detect_symbol_hallucinations(diff, tmp_path)
    assert "FakeModel" in result

def test_clean_code_zero_hallucinations(tmp_path):
    """Zero hallucinations for correct code referencing real files."""
    (tmp_path / "app.py").write_text("class App:\n    pass\n")
    text = "The App class in app.py handles this."
    result = detect_file_hallucinations(text, tmp_path)
    assert result == []

@pytest.mark.asyncio
async def test_check_hallucinations_combined(tmp_path):
    """Full check returns combined report."""
    (tmp_path / "real.py").write_text("class Real:\n    pass\n")
    diff = "+from fake_lib import stuff\n+obj = Fake()"
    text = "See src/missing.py"
    report = await check_hallucinations(diff, text, tmp_path)
    assert report.total > 0
    assert isinstance(report, HallucinationReport)
```

## Done When

- [ ] File hallucination detection works (real files pass, fake files caught)
- [ ] Import hallucination detection works (stdlib passes, fake modules caught)
- [ ] Symbol hallucination detection works (existing classes pass, fake ones caught)
- [ ] Combined `check_hallucinations()` returns unified report
- [ ] All tests pass: `pytest tests/test_validate_hallucination.py -v`
- [ ] Commit: `feat(validate): add hallucination detection for files, imports, symbols`
