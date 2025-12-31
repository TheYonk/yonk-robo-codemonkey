"""Main migration assessment orchestrator."""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any
import asyncpg
import hashlib
import json
import re

from codegraph_mcp.migration.ruleset import load_migration_rules, MigrationRuleset
from codegraph_mcp.migration.detector import detect_source_databases
from codegraph_mcp.db.schema_manager import schema_context


@dataclass
class MigrationFinding:
    """A single migration finding."""
    category: str
    severity: str
    title: str
    description: str
    evidence: list[dict[str, Any]]
    mapping: dict[str, Any]
    rule_id: str
    source_db: str


@dataclass
class MigrationAssessmentResult:
    """Complete migration assessment result."""
    score: int
    tier: str
    summary: str
    source_db: str
    target_db: str
    mode: str
    findings: list[MigrationFinding]
    report_markdown: str
    report_json: dict[str, Any]
    content_hash: str
    cached: bool
    created_at: datetime


async def assess_migration(
    repo_id: str,
    source_db: str,
    target_db: str,
    database_url: str,
    schema_name: str | None = None,
    connect: dict[str, Any] | None = None,
    regenerate: bool = False,
    top_k_evidence: int = 50
) -> MigrationAssessmentResult:
    """Perform comprehensive migration assessment.

    Args:
        repo_id: Repository UUID
        source_db: Source database type ('auto', 'oracle', 'sqlserver', 'mongodb', etc.)
        target_db: Target database type (default 'postgresql')
        database_url: CodeGraph database connection
        schema_name: Optional schema name for isolation
        connect: Optional live DB connection config
        regenerate: Force regeneration even if cached
        top_k_evidence: Maximum evidence items per finding

    Returns:
        MigrationAssessmentResult with score, findings, and reports
    """
    # Load ruleset
    ruleset = load_migration_rules()

    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Use schema context if provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Auto-detect source DB if needed
        detected_dbs = []
        if source_db == "auto":
            detected_dbs = await detect_source_databases(repo_id, database_url, ruleset, schema_name)
            if detected_dbs:
                source_db = detected_dbs[0].db_type
            else:
                source_db = "unknown"

        # Determine mode
        mode = "live_introspect" if connect else "repo_only"

        # Calculate content hash for caching
        content_hash = await _calculate_content_hash(
            conn, repo_id, source_db, target_db, mode, ruleset.content_hash
        )

        # Check for cached assessment
        if not regenerate:
            cached = await conn.fetchrow(
                """
                SELECT id, score, tier, summary, report_markdown, report_json, created_at
                FROM migration_assessment
                WHERE repo_id = $1
                  AND source_db = $2
                  AND target_db = $3
                  AND content_hash = $4
                ORDER BY created_at DESC
                LIMIT 1
                """,
                repo_id, source_db, target_db, content_hash
            )

            if cached:
                # Load findings
                findings_rows = await conn.fetch(
                    """
                    SELECT category, severity, title, description, evidence, mapping, rule_id, source_db
                    FROM migration_finding
                    WHERE assessment_id = $1
                    """,
                    cached['id']
                )

                findings = [
                    MigrationFinding(
                        category=row['category'],
                        severity=row['severity'],
                        title=row['title'],
                        description=row['description'],
                        evidence=row['evidence'] or [],
                        mapping=row['mapping'] or {},
                        rule_id=row['rule_id'] or '',
                        source_db=row['source_db']
                    )
                    for row in findings_rows
                ]

                return MigrationAssessmentResult(
                    score=cached['score'],
                    tier=cached['tier'],
                    summary=cached['summary'],
                    source_db=source_db,
                    target_db=target_db,
                    mode=mode,
                    findings=findings,
                    report_markdown=cached['report_markdown'],
                    report_json=cached['report_json'],
                    content_hash=content_hash,
                    cached=True,
                    created_at=cached['created_at']
                )
        else:
            # If regenerate=True, delete any existing assessment with the same content_hash
            await conn.execute(
                """
                DELETE FROM migration_assessment
                WHERE repo_id = $1
                  AND source_db = $2
                  AND target_db = $3
                  AND content_hash = $4
                """,
                repo_id, source_db, target_db, content_hash
            )

        # Generate new assessment
        findings = await _generate_findings(
            conn, repo_id, source_db, ruleset, top_k_evidence
        )

        # Calculate score
        score, tier = _calculate_score(findings, ruleset)

        # Generate reports
        report_json, report_markdown = await _generate_reports(
            conn, repo_id, source_db, target_db, mode, score, tier,
            findings, detected_dbs, ruleset
        )

        # Create summary
        summary = _generate_summary(score, tier, findings)

        # Store assessment
        assessment_id = await conn.fetchval(
            """
            INSERT INTO migration_assessment (
                repo_id, source_db, target_db, mode, score, tier,
                summary, report_markdown, report_json, content_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            repo_id, source_db, target_db, mode, score, tier,
            summary, report_markdown, json.dumps(report_json), content_hash
        )

        # Store findings
        for finding in findings:
            await conn.execute(
                """
                INSERT INTO migration_finding (
                    assessment_id, category, source_db, severity, title,
                    description, evidence, mapping, rule_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                assessment_id, finding.category, finding.source_db,
                finding.severity, finding.title, finding.description,
                json.dumps(finding.evidence), json.dumps(finding.mapping),
                finding.rule_id
            )

        # Store as searchable document
        await conn.execute(
            """
            INSERT INTO document (repo_id, type, source, title, content, fts)
            VALUES ($1, 'MIGRATION_REPORT', 'GENERATED', $2, $3, to_tsvector('simple', $4))
            """,
            repo_id,
            f"Migration Assessment: {source_db} to {target_db}",
            report_markdown,
            report_markdown
        )

        return MigrationAssessmentResult(
            score=score,
            tier=tier,
            summary=summary,
            source_db=source_db,
            target_db=target_db,
            mode=mode,
            findings=findings,
            report_markdown=report_markdown,
            report_json=report_json,
            content_hash=content_hash,
            cached=False,
            created_at=datetime.utcnow()
        )

    finally:
        await conn.close()


async def _calculate_content_hash(
    conn: asyncpg.Connection,
    repo_id: str,
    source_db: str,
    target_db: str,
    mode: str,
    ruleset_hash: str
) -> str:
    """Calculate content hash for caching."""
    # Get repo index state
    state = await conn.fetchrow(
        "SELECT last_indexed_at, file_count, symbol_count FROM repo_index_state WHERE repo_id = $1",
        repo_id
    )

    fingerprint = f"{repo_id}:{source_db}:{target_db}:{mode}:{ruleset_hash}"
    if state:
        fingerprint += f":{state['last_indexed_at']}:{state['file_count']}:{state['symbol_count']}"

    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


async def _generate_findings(
    conn: asyncpg.Connection,
    repo_id: str,
    source_db: str,
    ruleset: MigrationRuleset,
    top_k_evidence: int
) -> list[MigrationFinding]:
    """Generate findings by applying rules to repo code."""
    findings = []
    rules = ruleset.get_rules_for_db(source_db)

    for rule in rules:
        # Search for pattern in chunks
        matches = await conn.fetch(
            """
            SELECT c.id, c.file_id, c.start_line, c.end_line, c.content, f.path, f.language
            FROM chunk c
            JOIN file f ON f.id = c.file_id
            WHERE c.repo_id = $1
              AND c.content ~* $2
            LIMIT $3
            """,
            repo_id, rule.pattern, top_k_evidence
        )

        if matches:
            evidence = []
            for match in matches:
                # Extract excerpt
                lines = match['content'].split('\n')
                excerpt = '\n'.join(lines[:5])  # First 5 lines

                evidence.append({
                    'path': match['path'],
                    'line_start': match['start_line'],
                    'line_end': match['end_line'],
                    'excerpt': excerpt[:500],  # Limit length
                    'language': match['language']
                })

            findings.append(MigrationFinding(
                category=rule.category,
                severity=rule.severity,
                title=rule.title,
                description=rule.description,
                evidence=evidence,
                mapping=rule.mapping,
                rule_id=rule.id,
                source_db=rule.source_db or source_db
            ))

    return findings


def _calculate_score(findings: list[MigrationFinding], ruleset: MigrationRuleset) -> tuple[int, str]:
    """Calculate migration score based on findings."""
    total_score = 0.0

    # Group by category
    category_scores = {}

    for finding in findings:
        severity_weight = ruleset.severity_weights.get(finding.severity, 0)
        category_mult = ruleset.category_multipliers.get(finding.category, 1.0)

        # Each finding contributes based on severity and evidence count
        evidence_factor = min(len(finding.evidence) / 10.0, 2.0)  # Cap at 2x
        finding_score = severity_weight * category_mult * evidence_factor

        category_scores[finding.category] = category_scores.get(finding.category, 0) + finding_score

    # Sum all category scores
    total_score = sum(category_scores.values())

    # Normalize to 0-100
    score = min(100, int(total_score))

    # Determine tier
    tier = ruleset.get_tier(score)

    return score, tier


async def _generate_reports(
    conn: asyncpg.Connection,
    repo_id: str,
    source_db: str,
    target_db: str,
    mode: str,
    score: int,
    tier: str,
    findings: list[MigrationFinding],
    detected_dbs: list,
    ruleset: MigrationRuleset
) -> tuple[dict[str, Any], str]:
    """Generate JSON and Markdown reports."""
    # JSON report
    report_json = {
        'summary': {
            'source_db': source_db,
            'target_db': target_db,
            'score': score,
            'tier': tier,
            'total_findings': len(findings),
            'mode': mode
        },
        'detected_dbs': [
            {'db_type': d.db_type, 'confidence': d.confidence, 'evidence': d.evidence[:3]}
            for d in detected_dbs
        ] if detected_dbs else [],
        'findings_by_severity': _group_by_severity(findings),
        'findings_by_category': _group_by_category(findings),
        'top_blockers': _get_top_blockers(findings, 10),
        'migration_approaches': _suggest_approaches(score, tier, findings),
        'next_steps': _generate_next_steps(findings)
    }

    # Markdown report
    markdown = _generate_markdown_report(
        source_db, target_db, score, tier, findings, detected_dbs, report_json
    )

    return report_json, markdown


def _generate_summary(score: int, tier: str, findings: list[MigrationFinding]) -> str:
    """Generate executive summary."""
    critical_count = sum(1 for f in findings if f.severity == 'critical')
    high_count = sum(1 for f in findings if f.severity == 'high')

    summary = f"Migration complexity: {tier.upper()} (score: {score}/100). "
    summary += f"Found {len(findings)} issues: {critical_count} critical, {high_count} high severity. "

    if tier == "low":
        summary += "Straightforward migration with mostly mechanical changes."
    elif tier == "medium":
        summary += "Moderate complexity requiring careful planning and testing."
    elif tier == "high":
        summary += "Significant refactoring needed across multiple areas."
    else:
        summary += "Major undertaking requiring substantial architecture changes."

    return summary


def _group_by_severity(findings: list[MigrationFinding]) -> dict[str, int]:
    """Group findings by severity."""
    groups = {}
    for finding in findings:
        groups[finding.severity] = groups.get(finding.severity, 0) + 1
    return groups


def _group_by_category(findings: list[MigrationFinding]) -> dict[str, int]:
    """Group findings by category."""
    groups = {}
    for finding in findings:
        groups[finding.category] = groups.get(finding.category, 0) + 1
    return groups


def _get_top_blockers(findings: list[MigrationFinding], limit: int) -> list[dict[str, Any]]:
    """Get top blocking issues."""
    # Sort by severity (critical > high > medium > low)
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}

    sorted_findings = sorted(findings, key=lambda f: (severity_order.get(f.severity, 99), -len(f.evidence)))

    return [
        {
            'title': f.title,
            'severity': f.severity,
            'category': f.category,
            'description': f.description,
            'evidence_count': len(f.evidence)
        }
        for f in sorted_findings[:limit]
    ]


def _suggest_approaches(score: int, tier: str, findings: list[MigrationFinding]) -> list[dict[str, str]]:
    """Suggest migration approaches based on complexity."""
    approaches = []

    if score < 30:
        approaches.append({
            'name': 'Big Bang Migration',
            'description': 'Migrate entire application at once - complexity is manageable',
            'recommended': True
        })
    else:
        approaches.append({
            'name': 'Phased Migration',
            'description': 'Migrate in phases with dual-running period',
            'recommended': True
        })

    approaches.append({
        'name': 'Strangler Pattern',
        'description': 'Gradually replace old system service-by-service',
        'recommended': score > 50
    })

    return approaches


def _generate_next_steps(findings: list[MigrationFinding]) -> list[str]:
    """Generate next steps checklist."""
    steps = [
        "Review all critical and high severity findings",
        "Estimate effort for each category of changes",
        "Identify stored procedures that need rewriting",
        "Plan database schema migration strategy",
        "Set up test environment with PostgreSQL",
        "Create proof-of-concept for complex migrations",
        "Develop rollback plan"
    ]

    return steps


def _generate_markdown_report(
    source_db: str,
    target_db: str,
    score: int,
    tier: str,
    findings: list[MigrationFinding],
    detected_dbs: list,
    report_json: dict[str, Any]
) -> str:
    """Generate Markdown report."""
    lines = []

    lines.append(f"# Migration Assessment: {source_db.title()} to {target_db.title()}\n")
    lines.append(f"**Score:** {score}/100")
    lines.append(f"**Tier:** {tier.upper()}")
    lines.append(f"**Total Findings:** {len(findings)}\n")

    # Executive summary
    lines.append("## Executive Summary\n")
    by_severity = report_json['findings_by_severity']
    lines.append(f"- **Critical:** {by_severity.get('critical', 0)}")
    lines.append(f"- **High:** {by_severity.get('high', 0)}")
    lines.append(f"- **Medium:** {by_severity.get('medium', 0)}")
    lines.append(f"- **Low:** {by_severity.get('low', 0)}\n")

    # Detected DBs
    if detected_dbs:
        lines.append("## Detected Databases\n")
        for db in detected_dbs:
            lines.append(f"- **{db.db_type}** (confidence: {db.confidence:.0%})")
            for evidence in db.evidence[:3]:
                lines.append(f"  - {evidence}")
        lines.append("")

    # Top blockers
    lines.append("## Top Migration Blockers\n")
    for i, blocker in enumerate(report_json['top_blockers'][:5], 1):
        lines.append(f"{i}. **{blocker['title']}** ({blocker['severity']})")
        lines.append(f"   - {blocker['description']}")
        lines.append(f"   - Found in {blocker['evidence_count']} locations\n")

    # By category
    lines.append("## Findings by Category\n")
    by_category = report_json['findings_by_category']
    for category, count in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- **{category}:** {count}")
    lines.append("")

    # Recommended approach
    lines.append("## Recommended Migration Approach\n")
    for approach in report_json['migration_approaches']:
        if approach.get('recommended'):
            lines.append(f"### {approach['name']}")
            lines.append(f"{approach['description']}\n")

    # Next steps
    lines.append("## Next Steps\n")
    for step in report_json['next_steps']:
        lines.append(f"- [ ] {step}")

    return '\n'.join(lines)
