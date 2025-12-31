"""
Database Architecture Report Generator

Generates comprehensive reports about database schema, stored routines,
and application database calls.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any
import asyncpg
from datetime import datetime

from codegraph_mcp.db_introspect.schema_extractor import extract_db_schema, DBSchema
from codegraph_mcp.db_introspect.routine_analyzer import analyze_routine
from codegraph_mcp.db_introspect.app_call_discoverer import discover_db_calls


@dataclass
class DBReportResult:
    """Result of DB report generation."""
    cached: bool
    report_json: dict[str, Any]
    report_text: str
    updated_at: datetime
    content_hash: str


async def generate_db_architecture_report(
    repo_id: str,
    target_db_url: str,
    database_url: str,
    regenerate: bool = False,
    schemas: list[str] | None = None,
    max_routines: int = 50,
    max_app_calls: int = 100
) -> DBReportResult:
    """
    Generate comprehensive database architecture report.

    Args:
        repo_id: Repository UUID
        target_db_url: Connection string for target database to analyze
        database_url: CodeGraph database connection string
        regenerate: Force regeneration even if cached
        schemas: List of schema names to analyze (None = all non-system schemas)
        max_routines: Maximum routines to include in top lists
        max_app_calls: Maximum app calls to include

    Returns:
        DBReportResult with cached flag, JSON, markdown, timestamp, and hash
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Calculate content hash for caching
        content_hash = await _calculate_content_hash(conn, repo_id, target_db_url, schemas or [])

        # Check for cached report
        if not regenerate:
            cached = await conn.fetchrow(
                """
                SELECT d.content, d.created_at
                FROM document d
                WHERE d.repo_id = $1
                  AND d.type = 'DB_REPORT'
                  AND d.source = 'GENERATED'
                  AND d.metadata->>'content_hash' = $2
                ORDER BY d.created_at DESC
                LIMIT 1
                """,
                repo_id, content_hash
            )
            if cached:
                report_json = json.loads(cached['content'])
                report_text = _generate_markdown(report_json)
                return DBReportResult(
                    cached=True,
                    report_json=report_json,
                    report_text=report_text,
                    updated_at=cached['created_at'],
                    content_hash=content_hash
                )

        # Generate new report
        report_data = await _generate_report_data(
            conn, repo_id, target_db_url, schemas, max_routines, max_app_calls
        )
        report_data['metadata'] = {
            'generated_at': datetime.utcnow().isoformat(),
            'content_hash': content_hash,
            'repo_id': repo_id
        }

        report_text = _generate_markdown(report_data)

        # Store report as document
        await _store_report(conn, repo_id, report_data, report_text, content_hash)

        return DBReportResult(
            cached=False,
            report_json=report_data,
            report_text=report_text,
            updated_at=datetime.utcnow(),
            content_hash=content_hash
        )
    finally:
        await conn.close()


async def _calculate_content_hash(
    conn: asyncpg.Connection,
    repo_id: str,
    target_db_url: str,
    schemas: list[str]
) -> str:
    """Calculate content hash for caching based on DB fingerprint."""
    # Get target DB version and object count as fingerprint
    target_conn = await asyncpg.connect(dsn=target_db_url)
    try:
        version = await target_conn.fetchval("SELECT version()")

        schema_filter = "AND n.nspname = ANY($1::text[])" if schemas else "AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
        params = [schemas] if schemas else []

        # Count tables
        table_count = await target_conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p') {schema_filter}
            """,
            *params
        )

        # Count functions
        func_count = await target_conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            WHERE p.prokind IN ('f', 'p') {schema_filter}
            """,
            *params
        )

        # Get last modified time of any file in repo
        last_file_mtime = await conn.fetchval(
            "SELECT MAX(mtime) FROM file WHERE repo_id = $1",
            repo_id
        )

        fingerprint = f"{version}:{table_count}:{func_count}:{last_file_mtime}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()
    finally:
        await target_conn.close()


async def _generate_report_data(
    conn: asyncpg.Connection,
    repo_id: str,
    target_db_url: str,
    schemas: list[str] | None,
    max_routines: int,
    max_app_calls: int
) -> dict[str, Any]:
    """Generate report data structure."""
    # Extract DB schema
    db_schema = await extract_db_schema(target_db_url, schemas)

    # Analyze routines
    routine_analyses = []
    for func in db_schema.functions[:max_routines]:
        analysis = analyze_routine(func)
        routine_analyses.append({
            'name': func['name'],
            'schema': func['schema'],
            'language': func['language'],
            'loc': analysis.loc,
            'complexity': analysis.complexity,
            'security_definer': analysis.security_definer,
            'has_dynamic_sql': analysis.has_dynamic_sql,
            'risks': analysis.risks,
            'deprecated_features': analysis.deprecated_features
        })

    # Discover app DB calls
    app_calls = await _discover_app_calls(conn, repo_id, max_app_calls)

    # Build report structure
    report = {
        'db_overview': _build_db_overview(db_schema),
        'schema_map': _build_schema_map(db_schema),
        'objects_inventory': _build_objects_inventory(db_schema),
        'stored_routines': _build_routines_summary(routine_analyses),
        'risk_analysis': _build_risk_analysis(db_schema, routine_analyses),
        'app_db_calls': _build_app_calls_summary(app_calls),
        'migration_info': _build_migration_info(db_schema)
    }

    return report


def _build_db_overview(schema: DBSchema) -> dict[str, Any]:
    """Build database overview section."""
    return {
        'version': schema.version,
        'database': schema.database,
        'extensions': [
            {'name': ext['name'], 'version': ext['version']}
            for ext in schema.extensions
        ],
        'schemas': sorted([s['name'] for s in schema.schemas]),
        'object_counts': {
            'tables': len(schema.tables),
            'views': len(schema.views),
            'materialized_views': len([v for v in schema.views if v.get('is_materialized')]),
            'functions': len(schema.functions),
            'triggers': len(schema.triggers),
            'sequences': len(schema.sequences),
            'types': len(schema.types),
            'enums': len(schema.enums)
        }
    }


def _build_schema_map(schema: DBSchema) -> dict[str, Any]:
    """Build schema map with tables grouped by schema."""
    schema_groups = {}

    for table in schema.tables:
        schema_name = table['schema']
        if schema_name not in schema_groups:
            schema_groups[schema_name] = []

        # Count relationships
        fk_count = len([c for c in table.get('constraints', []) if c['type'] == 'FOREIGN KEY'])
        referenced_by = sum(1 for t in schema.tables
                           for c in t.get('constraints', [])
                           if c['type'] == 'FOREIGN KEY' and c.get('referenced_table') == table['name'])

        schema_groups[schema_name].append({
            'name': table['name'],
            'row_estimate': table.get('row_estimate', 0),
            'columns': len(table['columns']),
            'foreign_keys': fk_count,
            'referenced_by': referenced_by
        })

    # Sort tables by row estimate
    for schema_name in schema_groups:
        schema_groups[schema_name].sort(key=lambda t: t['row_estimate'], reverse=True)

    return {
        'schemas': schema_groups,
        'total_relationships': sum(
            len([c for c in t.get('constraints', []) if c['type'] == 'FOREIGN KEY'])
            for t in schema.tables
        )
    }


def _build_objects_inventory(schema: DBSchema) -> dict[str, Any]:
    """Build inventory of database objects."""
    return {
        'views': [
            {
                'name': v['name'],
                'schema': v['schema'],
                'is_materialized': v.get('is_materialized', False)
            }
            for v in schema.views[:50]
        ],
        'functions': [
            {
                'name': f['name'],
                'schema': f['schema'],
                'language': f['language'],
                'return_type': f.get('return_type', 'void'),
                'volatility': f.get('volatility', 'VOLATILE'),
                'security_definer': f.get('security_definer', False)
            }
            for f in schema.functions[:50]
        ],
        'triggers': [
            {
                'name': t['name'],
                'schema': t['schema'],
                'table': t['table'],
                'enabled': t.get('enabled', True)
            }
            for t in schema.triggers[:50]
        ],
        'sequences': [
            {
                'name': s['name'],
                'schema': s['schema'],
                'owned_by': s.get('owned_by')
            }
            for s in schema.sequences[:50]
        ],
        'enums': [
            {
                'name': e['name'],
                'schema': e['schema'],
                'values': e.get('values', [])
            }
            for e in schema.enums[:50]
        ]
    }


def _build_routines_summary(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    """Build stored routines summary."""
    # Sort by complexity
    by_complexity = sorted(analyses, key=lambda a: a['complexity'], reverse=True)[:20]

    # Find risky routines
    risky = [a for a in analyses if a['risks'] or a['deprecated_features']][:20]

    # Count by language
    by_language = {}
    for a in analyses:
        lang = a['language']
        by_language[lang] = by_language.get(lang, 0) + 1

    # Count security definer
    security_definer_count = sum(1 for a in analyses if a['security_definer'])
    dynamic_sql_count = sum(1 for a in analyses if a['has_dynamic_sql'])

    return {
        'total': len(analyses),
        'by_language': by_language,
        'security_definer_count': security_definer_count,
        'dynamic_sql_count': dynamic_sql_count,
        'top_by_complexity': by_complexity,
        'risky_routines': risky
    }


def _build_risk_analysis(schema: DBSchema, analyses: list[dict[str, Any]]) -> dict[str, Any]:
    """Build risk and compatibility analysis."""
    risks = []

    # Check for deprecated features
    for analysis in analyses:
        if analysis['deprecated_features']:
            risks.append({
                'type': 'deprecated_feature',
                'severity': 'medium',
                'routine': f"{analysis['schema']}.{analysis['name']}",
                'details': ', '.join(analysis['deprecated_features'])
            })

    # Check for security issues
    for analysis in analyses:
        if analysis['risks']:
            for risk in analysis['risks']:
                risks.append({
                    'type': 'security_risk',
                    'severity': 'high' if 'injection' in risk.lower() else 'medium',
                    'routine': f"{analysis['schema']}.{analysis['name']}",
                    'details': risk
                })

    # Check for triggers (can impact performance)
    if len(schema.triggers) > 10:
        risks.append({
            'type': 'performance',
            'severity': 'low',
            'details': f"{len(schema.triggers)} triggers defined - review for performance impact"
        })

    return {
        'total_risks': len(risks),
        'risks': sorted(risks, key=lambda r: {'high': 0, 'medium': 1, 'low': 2}[r['severity']])
    }


async def _discover_app_calls(
    conn: asyncpg.Connection,
    repo_id: str,
    max_calls: int
) -> list[dict[str, Any]]:
    """Discover application database calls from indexed files."""
    files = await conn.fetch(
        """
        SELECT id, path, language
        FROM file
        WHERE repo_id = $1
          AND language IN ('javascript', 'typescript', 'python', 'go', 'java')
        ORDER BY mtime DESC
        """,
        repo_id
    )

    all_calls = []

    for file_row in files:
        file_path = file_row['path']
        language = file_row['language']

        # Read file content from chunks
        chunks = await conn.fetch(
            """
            SELECT content
            FROM chunk
            WHERE file_id = $1
            ORDER BY start_line
            """,
            file_row['id']
        )

        if not chunks:
            continue

        content = '\n'.join(chunk['content'] for chunk in chunks)

        # Discover calls
        calls = discover_db_calls(file_path, content, language)

        for call in calls[:max_calls]:
            all_calls.append({
                'file_path': call.file_path,
                'language': call.language,
                'framework': call.framework,
                'call_type': call.call_type,
                'sql_snippet': call.sql_snippet[:200] if call.sql_snippet else None,
                'line': call.line,
                'tags': call.tags
            })

        if len(all_calls) >= max_calls:
            break

    return all_calls[:max_calls]


def _build_app_calls_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Build application database calls summary."""
    # Group by language
    by_language = {}
    for call in calls:
        lang = call['language']
        if lang not in by_language:
            by_language[lang] = {'count': 0, 'frameworks': set(), 'call_types': set()}
        by_language[lang]['count'] += 1
        by_language[lang]['frameworks'].add(call['framework'])
        by_language[lang]['call_types'].add(call['call_type'])

    # Convert sets to lists for JSON serialization
    for lang in by_language:
        by_language[lang]['frameworks'] = sorted(by_language[lang]['frameworks'])
        by_language[lang]['call_types'] = sorted(by_language[lang]['call_types'])

    # Group by framework
    by_framework = {}
    for call in calls:
        fw = call['framework']
        by_framework[fw] = by_framework.get(fw, 0) + 1

    # Find migration calls
    migration_calls = [c for c in calls if 'migrations' in c['tags']]

    # Find DDL operations
    ddl_calls = [c for c in calls if 'ddl' in c['tags']]

    return {
        'total': len(calls),
        'by_language': by_language,
        'by_framework': by_framework,
        'migration_calls': len(migration_calls),
        'ddl_calls': len(ddl_calls),
        'sample_calls': calls[:20]
    }


def _build_migration_info(schema: DBSchema) -> dict[str, Any]:
    """Build migration framework information."""
    return {
        'migration_tables': [
            {'name': t['name'], 'schema': t['schema']}
            for t in schema.migration_tables
        ],
        'detected_frameworks': list(set(
            t.get('framework', 'unknown')
            for t in schema.migration_tables
        ))
    }


def _generate_markdown(report: dict[str, Any]) -> str:
    """Generate markdown version of the report."""
    lines = []

    lines.append("# Database Architecture Report\n")

    # Metadata
    if 'metadata' in report:
        meta = report['metadata']
        lines.append(f"**Generated:** {meta.get('generated_at', 'N/A')}\n")

    # DB Overview
    lines.append("## Database Overview\n")
    overview = report['db_overview']
    lines.append(f"**Version:** {overview['version']}\n")
    lines.append(f"**Database:** {overview['database']}\n")
    lines.append(f"**Schemas:** {', '.join(overview['schemas'])}\n")

    if overview['extensions']:
        lines.append("\n### Extensions\n")
        for ext in overview['extensions']:
            lines.append(f"- {ext['name']} ({ext['version']})")
        lines.append("")

    lines.append("### Object Counts\n")
    counts = overview['object_counts']
    for obj_type, count in counts.items():
        lines.append(f"- {obj_type}: {count}")
    lines.append("")

    # Schema Map
    lines.append("## Schema Map\n")
    schema_map = report['schema_map']
    lines.append(f"**Total Foreign Key Relationships:** {schema_map['total_relationships']}\n")

    for schema_name, tables in schema_map['schemas'].items():
        lines.append(f"\n### Schema: {schema_name}\n")
        lines.append("| Table | Rows (est) | Columns | FKs | Referenced By |")
        lines.append("|-------|------------|---------|-----|---------------|")
        for table in tables[:20]:
            lines.append(
                f"| {table['name']} | {table['row_estimate']:,} | "
                f"{table['columns']} | {table['foreign_keys']} | {table['referenced_by']} |"
            )
        if len(tables) > 20:
            lines.append(f"\n*...and {len(tables) - 20} more tables*\n")
        lines.append("")

    # Stored Routines
    lines.append("## Stored Routines Summary\n")
    routines = report['stored_routines']
    lines.append(f"**Total Functions/Procedures:** {routines['total']}\n")
    lines.append(f"**Security Definer Count:** {routines['security_definer_count']}")
    lines.append(f"**Dynamic SQL Count:** {routines['dynamic_sql_count']}\n")

    lines.append("### By Language\n")
    for lang, count in routines['by_language'].items():
        lines.append(f"- {lang}: {count}")
    lines.append("")

    if routines['top_by_complexity']:
        lines.append("### Most Complex Routines\n")
        lines.append("| Routine | Language | Complexity | LOC | Security Definer |")
        lines.append("|---------|----------|------------|-----|------------------|")
        for r in routines['top_by_complexity'][:10]:
            sd = "✓" if r['security_definer'] else ""
            lines.append(
                f"| {r['schema']}.{r['name']} | {r['language']} | "
                f"{r['complexity']} | {r['loc']} | {sd} |"
            )
        lines.append("")

    if routines['risky_routines']:
        lines.append("### Risky Routines\n")
        for r in routines['risky_routines'][:10]:
            lines.append(f"\n**{r['schema']}.{r['name']}** ({r['language']})")
            if r['risks']:
                lines.append("- **Risks:**")
                for risk in r['risks']:
                    lines.append(f"  - {risk}")
            if r['deprecated_features']:
                lines.append("- **Deprecated:**")
                for dep in r['deprecated_features']:
                    lines.append(f"  - {dep}")
        lines.append("")

    # Risk Analysis
    lines.append("## Risk & Compatibility Analysis\n")
    risk_analysis = report['risk_analysis']
    lines.append(f"**Total Risks Identified:** {risk_analysis['total_risks']}\n")

    if risk_analysis['risks']:
        lines.append("### Risks\n")
        for risk in risk_analysis['risks'][:20]:
            severity_badge = {
                'high': '🔴 HIGH',
                'medium': '🟡 MEDIUM',
                'low': '🟢 LOW'
            }.get(risk['severity'], risk['severity'])

            lines.append(f"\n**{severity_badge}** - {risk['type']}")
            if 'routine' in risk:
                lines.append(f"- **Routine:** {risk['routine']}")
            lines.append(f"- **Details:** {risk['details']}")
        lines.append("")

    # App DB Calls
    lines.append("## Application Database Calls\n")
    app_calls = report['app_db_calls']
    lines.append(f"**Total Calls Discovered:** {app_calls['total']}")
    lines.append(f"**Migration Calls:** {app_calls['migration_calls']}")
    lines.append(f"**DDL Calls:** {app_calls['ddl_calls']}\n")

    lines.append("### By Language\n")
    for lang, info in app_calls['by_language'].items():
        lines.append(f"\n**{lang}** ({info['count']} calls)")
        lines.append(f"- Frameworks: {', '.join(info['frameworks'])}")
        lines.append(f"- Call Types: {', '.join(info['call_types'])}")
    lines.append("")

    if app_calls['by_framework']:
        lines.append("### By Framework\n")
        for fw, count in sorted(app_calls['by_framework'].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {fw}: {count}")
        lines.append("")

    # Migration Info
    lines.append("## Migration Information\n")
    migration = report['migration_info']
    if migration['detected_frameworks']:
        lines.append(f"**Detected Frameworks:** {', '.join(migration['detected_frameworks'])}\n")

    if migration['migration_tables']:
        lines.append("### Migration Tables\n")
        for table in migration['migration_tables']:
            lines.append(f"- {table['schema']}.{table['name']}")
        lines.append("")

    return '\n'.join(lines)


async def _store_report(
    conn: asyncpg.Connection,
    repo_id: str,
    report_json: dict[str, Any],
    report_text: str,
    content_hash: str
) -> None:
    """Store report as document."""
    metadata = {
        'content_hash': content_hash,
        'type': 'db_architecture_report',
        'generated_at': datetime.utcnow().isoformat()
    }

    await conn.execute(
        """
        INSERT INTO document (repo_id, type, source, title, content, metadata, fts)
        VALUES ($1, 'DB_REPORT', 'GENERATED', $2, $3, $4, to_tsvector('simple', $5))
        """,
        repo_id,
        f"Database Architecture Report",
        json.dumps(report_json),
        json.dumps(metadata),
        report_text
    )
