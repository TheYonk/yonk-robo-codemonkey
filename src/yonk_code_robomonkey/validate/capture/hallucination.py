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
