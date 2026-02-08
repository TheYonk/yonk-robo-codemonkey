"""Prep phase generator for dynamic task creation.

Uses an LLM to analyze a repository and generate context-aware validation tasks
tailored to the specific codebase, its structure, and technologies.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from .task_model import (
    TaskDefinition,
    TaskDifficulty,
    TaskCategory,
    TaskSetup,
    TaskEval,
)

# Default LLM settings for prep phase
PREP_PHASE_MODEL = os.getenv("PREP_PHASE_MODEL", "gpt-4o-mini")
PREP_PHASE_PROVIDER = os.getenv("PREP_PHASE_PROVIDER", "openai")


async def _get_repo_overview(repo_path: Path) -> dict[str, Any]:
    """Gather key information about the repository structure.

    Args:
        repo_path: Path to the repository

    Returns:
        Dict with repo metadata (files, languages, config files, etc.)
    """
    overview = {
        "languages": set(),
        "config_files": [],
        "entry_points": [],
        "test_files": [],
        "doc_files": [],
        "directories": [],
        "total_files": 0,
        "sample_files": [],  # Sample of source files for context
    }

    # Language detection by extension
    lang_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript/React",
        ".jsx": "JavaScript/React",
        ".go": "Go",
        ".java": "Java",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".php": "PHP",
        ".c": "C",
        ".cpp": "C++",
        ".cs": "C#",
        ".swift": "Swift",
        ".kt": "Kotlin",
    }

    # Config files to look for
    config_patterns = [
        "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt",
        "package.json", "package-lock.json", "yarn.lock",
        "go.mod", "go.sum",
        "Cargo.toml", "Cargo.lock",
        "pom.xml", "build.gradle",
        "Gemfile",
        "docker-compose.yml", "Dockerfile*",
        "*.yaml", "*.yml", "*.toml", "*.ini", "*.cfg",
        ".env*",
    ]

    # Entry point patterns
    entry_patterns = [
        "__main__.py", "main.py", "app.py", "server.py",
        "index.js", "index.ts", "main.go", "main.rs",
    ]

    try:
        for item in repo_path.rglob("*"):
            if item.is_file():
                # Skip hidden and common ignore patterns
                parts = item.relative_to(repo_path).parts
                if any(p.startswith(".") for p in parts):
                    continue
                if any(p in ["node_modules", "__pycache__", "venv", ".venv", "dist", "build"] for p in parts):
                    continue

                overview["total_files"] += 1
                ext = item.suffix.lower()

                # Detect language
                if ext in lang_map:
                    overview["languages"].add(lang_map[ext])

                # Detect config files
                name = item.name.lower()
                for pattern in config_patterns:
                    if pattern.startswith("*"):
                        if name.endswith(pattern[1:]):
                            overview["config_files"].append(str(item.relative_to(repo_path)))
                            break
                    elif name == pattern.lower() or name.startswith(pattern.split("*")[0].lower()):
                        overview["config_files"].append(str(item.relative_to(repo_path)))
                        break

                # Detect entry points
                if item.name in entry_patterns:
                    overview["entry_points"].append(str(item.relative_to(repo_path)))

                # Detect test files
                if "test" in str(item.relative_to(repo_path)).lower():
                    overview["test_files"].append(str(item.relative_to(repo_path)))

                # Detect doc files
                if ext in [".md", ".rst", ".adoc", ".txt"] and name not in ["license", "licence"]:
                    overview["doc_files"].append(str(item.relative_to(repo_path)))

                # Sample some source files for context (limit to 20)
                if ext in lang_map and len(overview["sample_files"]) < 20:
                    overview["sample_files"].append(str(item.relative_to(repo_path)))

            elif item.is_dir():
                # Track top-level directories
                rel = item.relative_to(repo_path)
                if len(rel.parts) == 1 and not rel.name.startswith("."):
                    if rel.name not in ["node_modules", "__pycache__", "venv", ".venv"]:
                        overview["directories"].append(rel.name)
    except Exception:
        pass  # Best effort

    # Convert sets to lists for JSON serialization
    overview["languages"] = list(overview["languages"])

    # Limit lists for context window management
    overview["config_files"] = overview["config_files"][:20]
    overview["test_files"] = overview["test_files"][:20]
    overview["doc_files"] = overview["doc_files"][:20]

    return overview


def _build_prep_prompt(overview: dict[str, Any], repo_name: str) -> str:
    """Build the LLM prompt for generating tasks.

    Args:
        overview: Repository overview from _get_repo_overview
        repo_name: Name of the repository

    Returns:
        Prompt string for the LLM
    """
    return f"""You are a code review expert. Analyze this repository overview and generate 5-7 targeted validation tasks.

Repository: {repo_name}
Languages: {', '.join(overview['languages']) or 'Unknown'}
Total Files: {overview['total_files']}
Top-Level Directories: {', '.join(overview['directories'])}

Config Files:
{chr(10).join('- ' + f for f in overview['config_files'][:10])}

Entry Points:
{chr(10).join('- ' + f for f in overview['entry_points'][:5]) or '- None detected'}

Test Files (sample):
{chr(10).join('- ' + f for f in overview['test_files'][:5]) or '- None detected'}

Documentation:
{chr(10).join('- ' + f for f in overview['doc_files'][:5]) or '- None detected'}

Sample Source Files:
{chr(10).join('- ' + f for f in overview['sample_files'][:10])}

---

Generate 5-7 validation tasks that are SPECIFIC to this codebase. Each task should:
1. Reference actual files or directories from the overview
2. Be achievable by reading the codebase (no modifications)
3. Test understanding of this specific project's patterns

Output JSON array with this structure:
```json
[
  {{
    "suffix": "short-id",
    "name": "Task Name",
    "prompt": "Detailed prompt that references actual files/patterns from this repo...",
    "rubric": ["rubric item 1", "rubric item 2", "rubric item 3", "rubric item 4"],
    "rubric_weights": {{"rubric item 1": 0.25, "rubric item 2": 0.25, "rubric item 3": 0.25, "rubric item 4": 0.25}},
    "category": "understand|review|discover",
    "tags": ["tag1", "tag2"]
  }}
]
```

Categories:
- understand: Learning about project structure, purpose, dependencies
- review: Evaluating code quality, patterns, potential issues
- discover: Finding specific behaviors, data flows, entry points

Make prompts detailed (2-3 paragraphs) and reference specific files from the overview.
The rubric items should be weighted to sum to 1.0.

Output ONLY the JSON array, no other text."""


async def _call_llm_for_tasks(prompt: str) -> list[dict]:
    """Call the LLM to generate tasks.

    Uses OpenAI-compatible API (works with OpenAI, vLLM, local endpoints).

    Args:
        prompt: The prep phase prompt

    Returns:
        List of task dicts from the LLM
    """
    # Get provider settings
    provider = PREP_PHASE_PROVIDER.lower()
    model = PREP_PHASE_MODEL

    # Determine base URL and API key
    if provider == "openai":
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
        api_key = os.getenv("OPENAI_API_KEY", "")
    elif provider == "vllm":
        base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
        api_key = os.getenv("VLLM_API_KEY", "")
    else:
        base_url = os.getenv("PREP_PHASE_BASE_URL", "http://localhost:8000")
        api_key = os.getenv("PREP_PHASE_API_KEY", "")

    # Import httpx for async HTTP calls
    try:
        import httpx
    except ImportError:
        print("  Warning: httpx not available, skipping LLM prep phase")
        return []

    # Build request
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4000,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

            # Try parsing the whole content
            return json.loads(content)

    except Exception as e:
        print(f"  Warning: LLM prep phase failed: {e}")
        return []


def _convert_to_task_definitions(
    raw_tasks: list[dict],
    repo_name: str,
    commit: str = "HEAD",
) -> list[TaskDefinition]:
    """Convert raw LLM output to TaskDefinition objects.

    Args:
        raw_tasks: List of task dicts from LLM
        repo_name: Target repository name
        commit: Git commit for setup

    Returns:
        List of TaskDefinition objects
    """
    tasks = []

    # Category mapping
    category_map = {
        "understand": TaskCategory.UNDERSTAND,
        "review": TaskCategory.REVIEW,
        "discover": TaskCategory.DISCOVER,
    }

    for i, t in enumerate(raw_tasks):
        try:
            suffix = t.get("suffix", f"dynamic-{i}")
            category_str = t.get("category", "understand").lower()
            category = category_map.get(category_str, TaskCategory.UNDERSTAND)

            rubric = t.get("rubric", ["completeness", "accuracy", "detail", "clarity"])
            rubric_weights = t.get("rubric_weights", {r: 1.0/len(rubric) for r in rubric})

            task_id = f"prep-{repo_name}-{suffix}"

            tasks.append(
                TaskDefinition(
                    id=task_id,
                    name=t.get("name", f"Dynamic Task {i+1}"),
                    difficulty=TaskDifficulty.SIMPLE,
                    category=category,
                    target_repo=repo_name,
                    prompt=t.get("prompt", ""),
                    setup=TaskSetup(commit=commit, branch="validate/baseline"),
                    eval=TaskEval(
                        hallucination_check=True,
                        llm_judge=True,
                        rubric=list(rubric),
                        rubric_weights=rubric_weights,
                        min_detail_level="moderate",
                        factual_grounding=True,
                    ),
                    task_type="qa",
                    tags=list(t.get("tags", [])) + [repo_name, "prep-phase"],
                    expected_turns_range=(1, 5),
                )
            )
        except Exception as e:
            print(f"  Warning: Failed to convert task {i}: {e}")
            continue

    return tasks


async def generate_prep_tasks(
    repo_path: Path,
    repo_name: str,
    commit: str = "HEAD",
) -> list[TaskDefinition]:
    """Run the prep phase to generate dynamic tasks for a repository.

    This function:
    1. Scans the repository to gather structural information
    2. Calls an LLM to generate targeted validation tasks
    3. Converts the LLM output to TaskDefinition objects

    Args:
        repo_path: Path to the cloned repository
        repo_name: Name of the repository (used in task IDs)
        commit: Git commit to reset to for each task

    Returns:
        List of dynamically generated TaskDefinition objects
    """
    print(f"  Running prep phase for '{repo_name}'...")

    # Step 1: Gather repo overview
    overview = await _get_repo_overview(repo_path)
    print(f"  Scanned {overview['total_files']} files, {len(overview['languages'])} languages detected")

    # Step 2: Build prompt and call LLM
    prompt = _build_prep_prompt(overview, repo_name)
    raw_tasks = await _call_llm_for_tasks(prompt)

    if not raw_tasks:
        print("  No prep tasks generated (LLM unavailable or failed)")
        return []

    print(f"  LLM generated {len(raw_tasks)} dynamic tasks")

    # Step 3: Convert to TaskDefinitions
    tasks = _convert_to_task_definitions(raw_tasks, repo_name, commit)
    print(f"  Created {len(tasks)} validated TaskDefinitions")

    return tasks


def get_prep_phase_status() -> dict[str, Any]:
    """Get current prep phase configuration status.

    Returns:
        Dict with provider, model, and availability info
    """
    return {
        "provider": PREP_PHASE_PROVIDER,
        "model": PREP_PHASE_MODEL,
        "base_url": os.getenv(f"{PREP_PHASE_PROVIDER.upper()}_BASE_URL", "not set"),
        "api_key_set": bool(os.getenv(f"{PREP_PHASE_PROVIDER.upper()}_API_KEY")),
    }
