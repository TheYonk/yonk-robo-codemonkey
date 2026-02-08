"""Generate portable TaskDefinition objects for arbitrary repositories.

Instead of YAML task files (which are tied to specific repos), this module
generates generic Q&A tasks that work on any codebase.  The generated tasks
cover three tiers:

- Tier 1 Understand (3 tasks): project overview, tech stack, architecture
- Tier 2 Review    (3 tasks): code quality, error handling, testing approach
- Tier 3 Discover  (3 tasks): entry points, configuration, data flow
"""
from __future__ import annotations

from .task_model import (
    TaskDefinition,
    TaskDifficulty,
    TaskCategory,
    TaskSetup,
    TaskEval,
)

# ── Tier 1: Understand ───────────────────────────────────────────

_UNDERSTAND_TASKS = [
    {
        "suffix": "project-overview",
        "name": "Project Overview",
        "prompt": (
            "Tell me about this project. What does it do, what's the tech stack, "
            "how is it organized, and what are the main entry points?\n\n"
            "Examine the repository structure, configuration files (setup.cfg, "
            "pyproject.toml, setup.py, package.json, go.mod, Cargo.toml, etc.), "
            "and top-level source directories. Identify the purpose of the project, "
            "the core technologies and runtime dependencies it relies on, how the "
            "source tree is laid out, and the primary entry points a developer or "
            "user would interact with.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "project purpose",
            "tech stack and dependencies",
            "directory structure",
            "main entry points",
        ],
        "rubric_weights": {
            "project purpose": 0.30,
            "tech stack and dependencies": 0.25,
            "directory structure": 0.25,
            "main entry points": 0.20,
        },
        "tags": ["understanding", "project-overview"],
    },
    {
        "suffix": "tech-stack",
        "name": "Technology Stack Analysis",
        "prompt": (
            "Identify all key dependencies and external libraries used by this "
            "project. Explain what role each major dependency plays and why it "
            "was likely chosen.\n\n"
            "Look at dependency manifests (requirements.txt, pyproject.toml, "
            "package.json, go.mod, Cargo.toml, pom.xml, etc.), import statements "
            "in source files, and any infrastructure configuration. Group "
            "dependencies by purpose (core framework, database, testing, build, "
            "etc.).\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "dependency identification",
            "role explanation",
            "grouping by purpose",
            "technology choices rationale",
        ],
        "rubric_weights": {
            "dependency identification": 0.30,
            "role explanation": 0.30,
            "grouping by purpose": 0.20,
            "technology choices rationale": 0.20,
        },
        "tags": ["understanding", "tech-stack"],
    },
    {
        "suffix": "architecture",
        "name": "Architecture Overview",
        "prompt": (
            "Describe the module architecture of this project. Identify the major "
            "layers, components, and design patterns used.\n\n"
            "Trace how the codebase is decomposed into modules or packages. "
            "Identify architectural layers (e.g., presentation, business logic, "
            "data access), key abstractions (interfaces, base classes, protocols), "
            "and any design patterns (MVC, repository, pub/sub, middleware, etc.). "
            "Explain how modules depend on each other.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "module decomposition",
            "architectural layers",
            "design patterns",
            "dependency relationships",
        ],
        "rubric_weights": {
            "module decomposition": 0.30,
            "architectural layers": 0.25,
            "design patterns": 0.25,
            "dependency relationships": 0.20,
        },
        "tags": ["understanding", "architecture"],
    },
]

# ── Tier 2: Review ───────────────────────────────────────────────

_REVIEW_TASKS = [
    {
        "suffix": "review-quality",
        "name": "Code Quality Review",
        "prompt": (
            "Review this codebase for code quality. Evaluate naming conventions, "
            "consistency, readability, and adherence to language idioms.\n\n"
            "Examine a representative sample of source files. Assess variable and "
            "function naming, code formatting consistency, use of language-specific "
            "idioms, documentation quality, and any code smells or anti-patterns. "
            "Provide specific file references for your observations.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "naming conventions",
            "consistency assessment",
            "language idioms",
            "specific file references",
        ],
        "rubric_weights": {
            "naming conventions": 0.25,
            "consistency assessment": 0.25,
            "language idioms": 0.25,
            "specific file references": 0.25,
        },
        "tags": ["review", "code-quality"],
    },
    {
        "suffix": "review-errors",
        "name": "Error Handling Review",
        "prompt": (
            "Review the error handling approach across this codebase. Identify "
            "patterns used, potential gaps, and areas for improvement.\n\n"
            "Look at how exceptions/errors are raised, caught, and propagated. "
            "Check for bare except clauses, swallowed errors, missing error "
            "context, inconsistent error handling strategies, and boundary "
            "validation. Note both strengths and weaknesses with specific "
            "file and line references.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "error patterns identified",
            "gap analysis",
            "boundary validation",
            "specific references",
        ],
        "rubric_weights": {
            "error patterns identified": 0.30,
            "gap analysis": 0.25,
            "boundary validation": 0.25,
            "specific references": 0.20,
        },
        "tags": ["review", "error-handling"],
    },
    {
        "suffix": "review-testing",
        "name": "Testing Approach Review",
        "prompt": (
            "Review the testing approach of this project. Evaluate test "
            "coverage strategy, test organization, fixture usage, and "
            "testing patterns.\n\n"
            "Examine the test directory structure, test frameworks in use, "
            "how fixtures and test data are managed, mocking strategies, "
            "integration vs unit test balance, and whether critical code "
            "paths have adequate coverage. Identify strengths and gaps.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "test organization",
            "framework and patterns",
            "fixture management",
            "coverage assessment",
        ],
        "rubric_weights": {
            "test organization": 0.25,
            "framework and patterns": 0.25,
            "fixture management": 0.25,
            "coverage assessment": 0.25,
        },
        "tags": ["review", "testing"],
    },
]

# ── Tier 3: Discover ─────────────────────────────────────────────

_DISCOVER_TASKS = [
    {
        "suffix": "discover-entry",
        "name": "Entry Points Discovery",
        "prompt": (
            "Find and explain all the main entry points to this application. "
            "Trace how a user, client, or external system first interacts "
            "with this code.\n\n"
            "Look for CLI entry points (console_scripts, __main__.py, main() "
            "functions), web endpoints (routes, handlers, controllers), API "
            "definitions, and any public-facing interfaces. For each entry "
            "point, explain what it does and how it connects to the rest of "
            "the system.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "entry point identification",
            "entry point explanation",
            "connection to system internals",
            "completeness",
        ],
        "rubric_weights": {
            "entry point identification": 0.30,
            "entry point explanation": 0.25,
            "connection to system internals": 0.25,
            "completeness": 0.20,
        },
        "tags": ["discover", "entry-points"],
    },
    {
        "suffix": "discover-config",
        "name": "Configuration Discovery",
        "prompt": (
            "Find and explain how configuration is managed in this project. "
            "Identify all configuration sources, how they are loaded, and "
            "how they affect runtime behavior.\n\n"
            "Look for environment variables, configuration files (YAML, TOML, "
            "INI, JSON), settings classes or modules, default values, and "
            "configuration validation. Explain the configuration hierarchy "
            "and how different environments (dev, test, prod) are handled.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "configuration sources",
            "loading mechanism",
            "environment handling",
            "validation and defaults",
        ],
        "rubric_weights": {
            "configuration sources": 0.30,
            "loading mechanism": 0.25,
            "environment handling": 0.25,
            "validation and defaults": 0.20,
        },
        "tags": ["discover", "configuration"],
    },
    {
        "suffix": "discover-dataflow",
        "name": "Data Flow Analysis",
        "prompt": (
            "Trace the main data flow through this application from input "
            "to output. Identify how data enters the system, how it is "
            "transformed, and where it ends up.\n\n"
            "Pick the primary use case of this application and follow the "
            "data path: external input (HTTP request, CLI args, file input) "
            "through validation, processing/transformation, storage, and "
            "response/output. Identify the key functions and classes involved "
            "at each stage.\n\n"
            "Do not modify any files. Provide a clear, structured answer."
        ),
        "rubric": [
            "data ingestion path",
            "transformation steps",
            "storage mechanism",
            "key functions identified",
        ],
        "rubric_weights": {
            "data ingestion path": 0.25,
            "transformation steps": 0.25,
            "storage mechanism": 0.25,
            "key functions identified": 0.25,
        },
        "tags": ["discover", "data-flow"],
    },
]

# ── Tier 4: Deep Review (Heavy Tasks) ────────────────────────────

_DEEP_REVIEW_TASKS = [
    {
        "suffix": "comprehensive-summary",
        "name": "Comprehensive Project Summary",
        "prompt": (
            "Perform a thorough review of this entire project and provide a "
            "comprehensive summary. This should be a detailed analysis that "
            "would help a new developer get up to speed quickly.\n\n"
            "Your summary should cover:\n"
            "1. **Project Purpose**: What problem does this solve? Who are the users?\n"
            "2. **Architecture Overview**: Major components, how they interact, key abstractions\n"
            "3. **Technology Stack**: All languages, frameworks, databases, external services\n"
            "4. **Code Organization**: Directory structure, module responsibilities, naming conventions\n"
            "5. **Key Workflows**: Most important user flows and how they're implemented\n"
            "6. **Data Model**: Core entities, relationships, storage approach\n"
            "7. **API Surface**: Public interfaces, endpoints, commands\n"
            "8. **Dependencies**: Critical external dependencies and why they're used\n"
            "9. **Build/Deploy**: How to build, test, and deploy the project\n"
            "10. **Notable Patterns**: Design patterns, idioms, conventions used\n\n"
            "Read as many files as needed to be thorough. Reference specific file paths "
            "and line numbers. Do not modify any files."
        ),
        "rubric": [
            "project purpose and users",
            "architecture and components",
            "technology stack completeness",
            "code organization explanation",
            "key workflows identified",
            "data model coverage",
            "API surface documentation",
            "dependency analysis",
            "build/deploy instructions",
            "patterns and conventions",
        ],
        "rubric_weights": {
            "project purpose and users": 0.10,
            "architecture and components": 0.15,
            "technology stack completeness": 0.10,
            "code organization explanation": 0.10,
            "key workflows identified": 0.15,
            "data model coverage": 0.10,
            "API surface documentation": 0.10,
            "dependency analysis": 0.05,
            "build/deploy instructions": 0.05,
            "patterns and conventions": 0.10,
        },
        "tags": ["deep-review", "comprehensive", "onboarding"],
    },
    {
        "suffix": "security-audit",
        "name": "Security Audit",
        "prompt": (
            "Perform a security audit of this codebase. Identify potential "
            "vulnerabilities, security anti-patterns, and areas of concern.\n\n"
            "Check for:\n"
            "1. **Input Validation**: Are user inputs properly validated and sanitized?\n"
            "2. **Authentication/Authorization**: How are users authenticated? Are permissions checked?\n"
            "3. **Secrets Management**: Are API keys, passwords, tokens handled securely?\n"
            "4. **SQL Injection**: Are database queries parameterized?\n"
            "5. **XSS Vulnerabilities**: Is output properly escaped in HTML contexts?\n"
            "6. **CSRF Protection**: Are state-changing operations protected?\n"
            "7. **Dependency Vulnerabilities**: Are there known-vulnerable dependencies?\n"
            "8. **Error Handling**: Do errors leak sensitive information?\n"
            "9. **Logging**: Is sensitive data being logged?\n"
            "10. **File Operations**: Are there path traversal or file inclusion risks?\n"
            "11. **Cryptography**: Are modern, secure algorithms used correctly?\n"
            "12. **Configuration**: Are debug modes, default credentials, or insecure defaults present?\n\n"
            "For each issue found, provide:\n"
            "- File path and line number\n"
            "- Severity (Critical/High/Medium/Low)\n"
            "- Description of the vulnerability\n"
            "- Recommended fix\n\n"
            "Do not modify any files. Be thorough but avoid false positives."
        ),
        "rubric": [
            "input validation issues",
            "auth/authz analysis",
            "secrets handling",
            "injection vulnerabilities",
            "XSS/CSRF checks",
            "dependency security",
            "error handling review",
            "file operation safety",
            "severity ratings",
            "actionable recommendations",
        ],
        "rubric_weights": {
            "input validation issues": 0.12,
            "auth/authz analysis": 0.12,
            "secrets handling": 0.10,
            "injection vulnerabilities": 0.12,
            "XSS/CSRF checks": 0.10,
            "dependency security": 0.08,
            "error handling review": 0.08,
            "file operation safety": 0.08,
            "severity ratings": 0.10,
            "actionable recommendations": 0.10,
        },
        "tags": ["deep-review", "security", "audit"],
    },
    {
        "suffix": "documentation-freshness",
        "name": "Documentation Freshness Review",
        "prompt": (
            "Review the documentation in this project and assess whether it is "
            "up to date with the actual code.\n\n"
            "Analyze:\n"
            "1. **README accuracy**: Does the README reflect current project state?\n"
            "2. **Code comments**: Are inline comments accurate or stale?\n"
            "3. **API documentation**: Do docstrings match function signatures and behavior?\n"
            "4. **Configuration docs**: Are config options documented correctly?\n"
            "5. **Architecture docs**: Do diagrams/descriptions match the code?\n"
            "6. **Installation instructions**: Would they work for a new developer?\n"
            "7. **Examples**: Do code examples still work?\n"
            "8. **CHANGELOG**: Is it maintained? Does it match recent commits?\n\n"
            "For each documentation issue, provide:\n"
            "- Location (file path, section)\n"
            "- What the docs say\n"
            "- What the code actually does\n"
            "- Recommended update\n\n"
            "Rate overall documentation health as: Excellent/Good/Fair/Poor/Critical.\n"
            "Do not modify any files."
        ),
        "rubric": [
            "README accuracy",
            "code comment freshness",
            "API documentation accuracy",
            "configuration documentation",
            "architecture documentation",
            "installation instructions",
            "example code validity",
            "overall health rating",
        ],
        "rubric_weights": {
            "README accuracy": 0.15,
            "code comment freshness": 0.10,
            "API documentation accuracy": 0.15,
            "configuration documentation": 0.10,
            "architecture documentation": 0.15,
            "installation instructions": 0.15,
            "example code validity": 0.10,
            "overall health rating": 0.10,
        },
        "tags": ["deep-review", "documentation", "freshness"],
    },
    {
        "suffix": "prioritization",
        "name": "What Should We Focus On Next?",
        "prompt": (
            "Based on a thorough review of this codebase, recommend what the "
            "team should focus on next. Prioritize improvements that would have "
            "the highest impact.\n\n"
            "Consider:\n"
            "1. **Technical Debt**: What shortcuts or workarounds need addressing?\n"
            "2. **Code Quality**: What areas need refactoring or cleanup?\n"
            "3. **Testing Gaps**: What areas lack test coverage?\n"
            "4. **Performance**: What might become bottlenecks at scale?\n"
            "5. **Security**: What security improvements are most urgent?\n"
            "6. **Developer Experience**: What makes the codebase hard to work with?\n"
            "7. **Missing Features**: What capabilities seem incomplete?\n"
            "8. **Dependencies**: What needs updating or replacing?\n\n"
            "Provide a prioritized list of 5-10 recommendations, each with:\n"
            "- Priority (P0/P1/P2)\n"
            "- Effort estimate (Small/Medium/Large)\n"
            "- Impact description\n"
            "- Specific files/areas to address\n"
            "- Suggested approach\n\n"
            "Focus on actionable, specific improvements. Do not modify any files."
        ),
        "rubric": [
            "technical debt identification",
            "code quality assessment",
            "testing gap analysis",
            "performance concerns",
            "security priorities",
            "developer experience",
            "prioritization rationale",
            "effort estimates",
            "actionable specificity",
        ],
        "rubric_weights": {
            "technical debt identification": 0.12,
            "code quality assessment": 0.12,
            "testing gap analysis": 0.12,
            "performance concerns": 0.10,
            "security priorities": 0.12,
            "developer experience": 0.10,
            "prioritization rationale": 0.12,
            "effort estimates": 0.10,
            "actionable specificity": 0.10,
        },
        "tags": ["deep-review", "prioritization", "roadmap"],
    },
]

# ── Category mapping ─────────────────────────────────────────────

_TIER_MAP = {
    "understand": (_UNDERSTAND_TASKS, TaskCategory.UNDERSTAND),
    "review": (_REVIEW_TASKS, TaskCategory.REVIEW),
    "discover": (_DISCOVER_TASKS, TaskCategory.DISCOVER),
    "deep": (_DEEP_REVIEW_TASKS, TaskCategory.REVIEW),
}


def generate_generic_tasks(
    repo_name: str,
    commit: str = "HEAD",
    tiers: list[str] | None = None,
) -> list[TaskDefinition]:
    """Generate portable Q&A tasks for an arbitrary repository.

    Args:
        repo_name: Name of the target repository (used in task IDs).
        commit: Git commit to reset to before each run (default HEAD).
        tiers: Which tiers to include. None means all three
               (understand, review, discover). Pass e.g. ["understand"]
               to generate only tier-1 tasks.

    Returns:
        List of TaskDefinition objects ready for the orchestrator.
    """
    selected_tiers = tiers or list(_TIER_MAP.keys())
    tasks: list[TaskDefinition] = []

    for tier_name in selected_tiers:
        tier_info = _TIER_MAP.get(tier_name)
        if not tier_info:
            continue
        task_defs, category = tier_info

        for t in task_defs:
            task_id = f"generic-{repo_name}-{t['suffix']}"
            tasks.append(
                TaskDefinition(
                    id=task_id,
                    name=t["name"],
                    difficulty=TaskDifficulty.SIMPLE,
                    category=category,
                    target_repo=repo_name,
                    prompt=t["prompt"],
                    setup=TaskSetup(commit=commit, branch="validate/baseline"),
                    eval=TaskEval(
                        hallucination_check=True,
                        llm_judge=True,
                        rubric=list(t["rubric"]),
                        rubric_weights=dict(t["rubric_weights"]),
                        min_detail_level="moderate",
                        factual_grounding=True,
                    ),
                    task_type="qa",
                    tags=list(t["tags"]) + [repo_name],
                    expected_turns_range=(1, 5),
                )
            )

    return tasks
