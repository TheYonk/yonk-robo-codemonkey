from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from functools import lru_cache
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

# Common non-path extensions to skip (version numbers, domain names, etc.)
_SKIP_EXTENSIONS = frozenset({
    "com", "org", "net", "io", "dev", "ai", "app",  # domains
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",  # version numbers
})


def _build_repo_file_index(repo_dir: Path) -> tuple[set[str], set[str]]:
    """Build a set of basenames and relative paths for all files in repo.

    Returns:
        (basenames, relative_paths) — basenames is a set of filenames,
        relative_paths is a set of POSIX-style paths relative to repo_dir.
    """
    basenames: set[str] = set()
    relative_paths: set[str] = set()
    try:
        for f in repo_dir.rglob("*"):
            if not f.is_file():
                continue
            # Skip hidden dirs like .git
            parts = f.relative_to(repo_dir).parts
            if any(p.startswith(".") for p in parts[:-1]):
                continue
            rel = f.relative_to(repo_dir).as_posix()
            basenames.add(f.name)
            relative_paths.add(rel)
    except Exception as e:
        logger.warning("Failed to build repo file index: %s", e)
    return basenames, relative_paths


def _path_exists_in_repo(
    path_str: str,
    repo_dir: Path,
    basenames: set[str],
    relative_paths: set[str],
) -> bool:
    """Check if a mentioned file path exists anywhere in the repo tree.

    Checks in order:
    1. Exact path relative to repo root (original behavior)
    2. Suffix match — any repo path ending with the candidate
    3. Basename match — any file in the repo with the same filename
    """
    # 1. Exact path
    clean = path_str.lstrip("./")
    if clean in relative_paths:
        return True

    # 2. Suffix match (e.g., "flask/blueprints.py" matches "src/flask/blueprints.py")
    suffix = f"/{clean}"
    for rp in relative_paths:
        if rp.endswith(suffix):
            return True

    # 3. Basename match (e.g., "blueprints.py" matches any blueprints.py in the tree)
    basename = Path(path_str).name
    if basename in basenames:
        return True

    return False


def detect_file_hallucinations(
    text: str,
    repo_dir: Path,
) -> list[str]:
    """Find file paths mentioned in text that don't exist in the repo tree."""
    candidates = set(FILE_PATH_PATTERN.findall(text))
    basenames, relative_paths = _build_repo_file_index(repo_dir)
    hallucinated = []
    for path_str in candidates:
        # Skip obvious non-paths
        if path_str.startswith("http") or path_str.startswith("//"):
            continue
        # Skip common config / virtual files
        if path_str in (".env", "requirements.txt", "setup.py", "setup.cfg",
                        "pyproject.toml", "package.json", "Makefile"):
            continue
        # Skip likely non-path extensions (domains, version numbers)
        ext = path_str.rsplit(".", 1)[-1].lower() if "." in path_str else ""
        if ext in _SKIP_EXTENSIONS:
            continue
        # Only flag paths that look like project files
        if "/" not in path_str and not path_str.endswith(".py"):
            continue
        # Skip system/library headers (C/C++ includes not part of the project)
        if ext in ("h", "hpp") and "/" in path_str:
            # Paths like "utils/guc.h", "common/hmac.h" are typically system includes
            # Only flag .h files if the directory prefix exists in the repo
            dir_part = path_str.rsplit("/", 1)[0]
            if not any(rp.startswith(dir_part + "/") for rp in relative_paths):
                continue
        # Check against repo tree (exact, suffix, and basename matching)
        if not _path_exists_in_repo(path_str, repo_dir, basenames, relative_paths):
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
