"""Comprehensive repository report generation.

Generates architecture reports including:
- Overview and tech stack
- Architecture map (modules, services, libraries)
- Key flows and entrypoints
- Data/storage layer
- Auth/security layer
- External integrations
- Observability
- Risks and hotspots
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
from collections import defaultdict
import hashlib
import json
import asyncpg


@dataclass
class ReportResult:
    """Result of report generation."""
    report_json: dict[str, Any]
    report_text: str
    content_hash: str
    cached: bool
    generated_at: str


async def generate_comprehensive_review(
    repo_id: str,
    database_url: str,
    regenerate: bool = False,
    max_modules: int = 25,
    max_files_per_module: int = 20,
    include_sections: list[str] | None = None
) -> ReportResult:
    """Generate a comprehensive architecture report for a repository.

    Args:
        repo_id: Repository UUID
        database_url: Database connection string
        regenerate: Force regeneration even if cached
        max_modules: Maximum modules to include
        max_files_per_module: Maximum files per module
        include_sections: Sections to include (default: all)

    Returns:
        ReportResult with JSON and markdown report
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Get repo info
        repo = await conn.fetchrow(
            "SELECT name, root_path FROM repo WHERE id = $1", repo_id
        )

        if not repo:
            raise ValueError(f"Repository not found: {repo_id}")

        # Calculate content hash for caching
        content_hash = await _calculate_content_hash(conn, repo_id)

        # Check for cached report
        if not regenerate:
            cached = await conn.fetchrow(
                "SELECT report_json, report_text, updated_at FROM repo_report WHERE repo_id = $1 AND content_hash = $2",
                repo_id, content_hash
            )

            if cached:
                return ReportResult(
                    report_json=cached["report_json"],
                    report_text=cached["report_text"],
                    content_hash=content_hash,
                    cached=True,
                    generated_at=str(cached["updated_at"])
                )

        # Generate new report
        report_data = await _generate_report_data(
            conn=conn,
            repo_id=repo_id,
            repo_name=repo["name"],
            max_modules=max_modules,
            max_files_per_module=max_files_per_module,
            include_sections=include_sections or [
                "overview", "architecture", "flows", "data",
                "auth", "observability", "risks"
            ]
        )

        # Convert to markdown
        report_text = _generate_markdown(report_data)

        # Store report
        await conn.execute(
            """
            INSERT INTO repo_report (repo_id, report_json, report_text, content_hash)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (repo_id)
            DO UPDATE SET
                report_json = EXCLUDED.report_json,
                report_text = EXCLUDED.report_text,
                content_hash = EXCLUDED.content_hash,
                updated_at = now()
            """,
            repo_id, json.dumps(report_data), report_text, content_hash
        )

        # Get updated_at
        updated_at = await conn.fetchval(
            "SELECT updated_at FROM repo_report WHERE repo_id = $1", repo_id
        )

        return ReportResult(
            report_json=report_data,
            report_text=report_text,
            content_hash=content_hash,
            cached=False,
            generated_at=str(updated_at)
        )

    finally:
        await conn.close()


async def _calculate_content_hash(conn: asyncpg.Connection, repo_id: str) -> str:
    """Calculate content hash for caching."""
    # Get index state
    index_state = await conn.fetchrow(
        "SELECT last_indexed_at, file_count, symbol_count FROM repo_index_state WHERE repo_id = $1",
        repo_id
    )

    # Get latest document update
    latest_doc = await conn.fetchval(
        "SELECT MAX(updated_at) FROM document WHERE repo_id = $1",
        repo_id
    )

    # Get latest summary update
    latest_summary = await conn.fetchval(
        """
        SELECT MAX(updated_at) FROM (
            SELECT MAX(fs.updated_at) as updated_at FROM file_summary fs
            JOIN file f ON f.id = fs.file_id
            WHERE f.repo_id = $1
            UNION ALL
            SELECT MAX(ms.updated_at) as updated_at FROM module_summary ms
            WHERE ms.repo_id = $1
        ) t
        """,
        repo_id
    )

    # Combine into hash input
    hash_input = f"{index_state or ''}{latest_doc or ''}{latest_summary or ''}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


async def _generate_report_data(
    conn: asyncpg.Connection,
    repo_id: str,
    repo_name: str,
    max_modules: int,
    max_files_per_module: int,
    include_sections: list[str]
) -> dict[str, Any]:
    """Generate structured report data."""
    report = {
        "repo_name": repo_name,
        "repo_id": repo_id,
        "sections": {}
    }

    # Overview section
    if "overview" in include_sections:
        report["sections"]["overview"] = await _generate_overview(conn, repo_id)

    # Tech stack
    if "overview" in include_sections:
        report["sections"]["tech_stack"] = await _generate_tech_stack(conn, repo_id)

    # Architecture map
    if "architecture" in include_sections:
        report["sections"]["architecture"] = await _generate_architecture_map(
            conn, repo_id, max_modules, max_files_per_module
        )

    # Key flows
    if "flows" in include_sections:
        report["sections"]["key_flows"] = await _generate_key_flows(conn, repo_id)

    # Data layer
    if "data" in include_sections:
        report["sections"]["data_layer"] = await _generate_data_layer(conn, repo_id)

    # Auth/security
    if "auth" in include_sections:
        report["sections"]["auth_security"] = await _generate_auth_security(conn, repo_id)

    # Observability
    if "observability" in include_sections:
        report["sections"]["observability"] = await _generate_observability(conn, repo_id)

    # Risks
    if "risks" in include_sections:
        report["sections"]["risks"] = await _generate_risks(conn, repo_id)

    return report


async def _generate_overview(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Generate overview section."""
    # Get README content
    readme = await conn.fetchrow(
        """
        SELECT title, content FROM document
        WHERE repo_id = $1 AND (path LIKE 'README%' OR path LIKE 'readme%')
        ORDER BY LENGTH(content) DESC
        LIMIT 1
        """,
        repo_id
    )

    # Get file counts by language
    lang_counts = await conn.fetch(
        """
        SELECT language, COUNT(*) as count
        FROM file
        WHERE repo_id = $1
        GROUP BY language
        ORDER BY count DESC
        """,
        repo_id
    )

    return {
        "description": readme["content"][:500] if readme else "No README found",
        "languages": [{"name": r["language"], "file_count": r["count"]} for r in lang_counts],
        "total_files": sum(r["count"] for r in lang_counts)
    }


async def _generate_tech_stack(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Infer tech stack from imports and tags."""
    # Get common imports/libraries
    imports = await conn.fetch(
        """
        SELECT dst.fqn, COUNT(*) as import_count
        FROM edge e
        JOIN symbol dst ON dst.id = e.dst_symbol_id
        WHERE e.repo_id = $1 AND e.type = 'IMPORTS'
        GROUP BY dst.fqn
        ORDER BY import_count DESC
        LIMIT 50
        """,
        repo_id
    )

    # Get tags
    tags = await conn.fetch(
        """
        SELECT t.name, COUNT(DISTINCT et.entity_id) as usage_count
        FROM entity_tag et
        JOIN tag t ON t.id = et.tag_id
        WHERE et.repo_id = $1
        GROUP BY t.name
        ORDER BY usage_count DESC
        """,
        repo_id
    )

    return {
        "frameworks": [r["fqn"].split(".")[0] for r in imports[:10]],
        "libraries": [r["fqn"] for r in imports[10:30]],
        "tags": [r["name"] for r in tags]
    }


async def _generate_architecture_map(
    conn: asyncpg.Connection,
    repo_id: str,
    max_modules: int,
    max_files_per_module: int
) -> dict[str, Any]:
    """Generate architecture map with modules."""
    # Get modules with summaries
    modules = await conn.fetch(
        """
        SELECT module_path, summary
        FROM module_summary
        WHERE repo_id = $1
        ORDER BY module_path
        LIMIT $2
        """,
        repo_id, max_modules
    )

    # For each module, get key files
    module_data = []
    for module in modules:
        module_path = module["module_path"]

        # Get files in this module
        files = await conn.fetch(
            """
            SELECT f.path, f.language, fs.summary
            FROM file f
            LEFT JOIN file_summary fs ON fs.file_id = f.id
            WHERE f.repo_id = $1 AND f.path LIKE $2
            ORDER BY f.path
            LIMIT $3
            """,
            repo_id, f"{module_path}%", max_files_per_module
        )

        # Get key symbols in this module
        symbols = await conn.fetch(
            """
            SELECT s.name, s.kind, s.fqn
            FROM symbol s
            JOIN file f ON f.id = s.file_id
            WHERE s.repo_id = $1 AND f.path LIKE $2
            ORDER BY s.name
            LIMIT 20
            """,
            repo_id, f"{module_path}%"
        )

        module_data.append({
            "path": module_path,
            "summary": module["summary"],
            "files": [{"path": f["path"], "language": f["language"], "summary": f["summary"]} for f in files],
            "key_symbols": [{"name": s["name"], "kind": s["kind"], "fqn": s["fqn"]} for s in symbols]
        })

    return {"modules": module_data}


async def _generate_key_flows(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Identify key flows from entrypoints."""
    # Identify entrypoints
    entrypoints = await conn.fetch(
        """
        SELECT s.id, s.name, s.fqn, f.path
        FROM symbol s
        JOIN file f ON f.id = s.file_id
        WHERE s.repo_id = $1
        AND (
            f.path LIKE '%main.%'
            OR f.path LIKE '%index.%'
            OR f.path LIKE '%app.%'
            OR f.path LIKE '%server.%'
            OR s.name LIKE '%main%'
            OR s.name LIKE '%Main%'
        )
        LIMIT 10
        """,
        repo_id
    )

    # For each entrypoint, get call graph (depth 2)
    flows = []
    for entry in entrypoints:
        callees = await conn.fetch(
            """
            WITH RECURSIVE calls AS (
                SELECT dst_symbol_id as symbol_id, 1 as depth
                FROM edge
                WHERE src_symbol_id = $1 AND type = 'CALLS'
                UNION ALL
                SELECT e.dst_symbol_id, c.depth + 1
                FROM edge e
                JOIN calls c ON c.symbol_id = e.src_symbol_id
                WHERE c.depth < 2 AND e.type = 'CALLS'
            )
            SELECT DISTINCT s.name, s.fqn, f.path, c.depth
            FROM calls c
            JOIN symbol s ON s.id = c.symbol_id
            JOIN file f ON f.id = s.file_id
            ORDER BY c.depth, s.name
            LIMIT 20
            """,
            entry["id"]
        )

        flows.append({
            "entrypoint": entry["fqn"],
            "file": entry["path"],
            "calls": [{"name": c["name"], "fqn": c["fqn"], "file": c["path"], "depth": c["depth"]} for c in callees]
        })

    return {"flows": flows}


async def _generate_data_layer(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Identify data/storage layer."""
    # Find database-related files via tags
    db_files = await conn.fetch(
        """
        SELECT DISTINCT f.path, fs.summary
        FROM entity_tag et
        JOIN tag t ON t.id = et.tag_id
        JOIN file f ON f.id = et.entity_id
        LEFT JOIN file_summary fs ON fs.file_id = f.id
        WHERE et.repo_id = $1 AND et.entity_type = 'file'
        AND t.name IN ('database', 'migrations', 'persistence')
        ORDER BY f.path
        LIMIT 20
        """,
        repo_id
    )

    return {
        "files": [{"path": f["path"], "summary": f["summary"]} for f in db_files]
    }


async def _generate_auth_security(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Identify auth/security layer."""
    auth_files = await conn.fetch(
        """
        SELECT DISTINCT f.path, fs.summary
        FROM entity_tag et
        JOIN tag t ON t.id = et.tag_id
        JOIN file f ON f.id = et.entity_id
        LEFT JOIN file_summary fs ON fs.file_id = f.id
        WHERE et.repo_id = $1 AND et.entity_type = 'file'
        AND t.name IN ('auth', 'security', 'authentication', 'authorization')
        ORDER BY f.path
        LIMIT 20
        """,
        repo_id
    )

    return {
        "files": [{"path": f["path"], "summary": f["summary"]} for f in auth_files]
    }


async def _generate_observability(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Identify observability layer."""
    obs_files = await conn.fetch(
        """
        SELECT DISTINCT f.path, fs.summary
        FROM entity_tag et
        JOIN tag t ON t.id = et.tag_id
        JOIN file f ON f.id = et.entity_id
        LEFT JOIN file_summary fs ON fs.file_id = f.id
        WHERE et.repo_id = $1 AND et.entity_type = 'file'
        AND t.name IN ('logging', 'metrics', 'monitoring')
        ORDER BY f.path
        LIMIT 20
        """,
        repo_id
    )

    return {
        "files": [{"path": f["path"], "summary": f["summary"]} for f in obs_files]
    }


async def _generate_risks(conn: asyncpg.Connection, repo_id: str) -> dict[str, Any]:
    """Identify risks and hotspots."""
    # Large files
    large_files = await conn.fetch(
        """
        SELECT f.path, LENGTH(STRING_AGG(c.content, '')) as size
        FROM file f
        JOIN chunk c ON c.file_id = f.id
        WHERE f.repo_id = $1
        GROUP BY f.id, f.path
        ORDER BY size DESC
        LIMIT 10
        """,
        repo_id
    )

    # High fan-in symbols (many callers)
    high_fanin = await conn.fetch(
        """
        SELECT s.fqn, COUNT(*) as caller_count
        FROM edge e
        JOIN symbol s ON s.id = e.dst_symbol_id
        WHERE e.repo_id = $1 AND e.type = 'CALLS'
        GROUP BY s.fqn
        ORDER BY caller_count DESC
        LIMIT 10
        """,
        repo_id
    )

    return {
        "large_files": [{"path": f["path"], "size": f["size"]} for f in large_files],
        "high_fanin_symbols": [{"fqn": s["fqn"], "caller_count": s["caller_count"]} for s in high_fanin]
    }


def _generate_markdown(report_data: dict[str, Any]) -> str:
    """Convert report data to markdown."""
    lines = []

    lines.append(f"# Architecture Report: {report_data['repo_name']}\n")

    sections = report_data.get("sections", {})

    # Overview
    if "overview" in sections:
        lines.append("## Overview\n")
        overview = sections["overview"]
        lines.append(overview.get("description", "No description available"))
        lines.append(f"\n**Total Files:** {overview.get('total_files', 0)}\n")
        lines.append("**Languages:**\n")
        for lang in overview.get("languages", []):
            lines.append(f"- {lang['name']}: {lang['file_count']} files\n")
        lines.append("")

    # Tech Stack
    if "tech_stack" in sections:
        lines.append("## Tech Stack\n")
        tech = sections["tech_stack"]
        if tech.get("frameworks"):
            lines.append("**Frameworks:**\n")
            for fw in tech["frameworks"]:
                lines.append(f"- {fw}\n")
        if tech.get("libraries"):
            lines.append("\n**Libraries:**\n")
            for lib in tech["libraries"][:10]:
                lines.append(f"- {lib}\n")
        lines.append("")

    # Architecture
    if "architecture" in sections:
        lines.append("## Architecture Map\n")
        arch = sections["architecture"]
        for module in arch.get("modules", [])[:10]:
            lines.append(f"### Module: {module['path']}\n")
            if module.get("summary"):
                lines.append(f"{module['summary']}\n")
            lines.append(f"\n**Files:** {len(module.get('files', []))}\n")
            lines.append(f"**Key Symbols:** {len(module.get('key_symbols', []))}\n")
            lines.append("")

    # Key Flows
    if "key_flows" in sections:
        lines.append("## Key Flows\n")
        flows = sections["key_flows"]
        for flow in flows.get("flows", [])[:5]:
            lines.append(f"### {flow['entrypoint']}\n")
            lines.append(f"**File:** {flow['file']}\n")
            if flow.get("calls"):
                lines.append("\n**Calls:**\n")
                for call in flow["calls"][:10]:
                    lines.append(f"- [{call['depth']}] {call['fqn']} ({call['file']})\n")
            lines.append("")

    # Data Layer
    if "data_layer" in sections:
        lines.append("## Data/Storage Layer\n")
        data = sections["data_layer"]
        for file in data.get("files", []):
            lines.append(f"- **{file['path']}**")
            if file.get("summary"):
                lines.append(f": {file['summary']}")
            lines.append("\n")
        lines.append("")

    # Auth/Security
    if "auth_security" in sections:
        lines.append("## Auth/Security Layer\n")
        auth = sections["auth_security"]
        for file in auth.get("files", []):
            lines.append(f"- **{file['path']}**")
            if file.get("summary"):
                lines.append(f": {file['summary']}")
            lines.append("\n")
        lines.append("")

    # Observability
    if "observability" in sections:
        lines.append("## Observability\n")
        obs = sections["observability"]
        for file in obs.get("files", []):
            lines.append(f"- **{file['path']}**")
            if file.get("summary"):
                lines.append(f": {file['summary']}")
            lines.append("\n")
        lines.append("")

    # Risks
    if "risks" in sections:
        lines.append("## Risks and Hotspots\n")
        risks = sections["risks"]
        if risks.get("large_files"):
            lines.append("### Large Files\n")
            for file in risks["large_files"][:5]:
                lines.append(f"- {file['path']} ({file['size']} chars)\n")
        if risks.get("high_fanin_symbols"):
            lines.append("\n### High Fan-in Symbols (Many Callers)\n")
            for sym in risks["high_fanin_symbols"][:5]:
                lines.append(f"- {sym['fqn']} ({sym['caller_count']} callers)\n")
        lines.append("")

    return "".join(lines)
