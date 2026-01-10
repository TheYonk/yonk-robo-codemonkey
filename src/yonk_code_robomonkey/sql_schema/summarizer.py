"""LLM-powered summaries for SQL schema elements.

Generates human-readable descriptions for tables, columns, and routines
using local LLMs (Ollama/vLLM).

Uses the "small" LLM model by default for quick summaries.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from . import queries
from yonk_code_robomonkey.llm import call_llm, parse_json_response

logger = logging.getLogger(__name__)


# ============================================================================
# Prompts
# ============================================================================

TABLE_SUMMARY_PROMPT = """Analyze this database table and provide a concise description.

TABLE: {table_name}
SCHEMA: {schema_name}

COLUMNS:
{columns}

CONSTRAINTS:
{constraints}

COLUMN USAGE (where columns are referenced in code):
{usage_summary}

Based on the table structure and how it's used in the codebase, write a 1-2 sentence description of what this table stores and its purpose.

Return JSON:
{{
  "description": "brief description of the table's purpose",
  "column_descriptions": {{
    "column_name": "brief description of this column"
  }}
}}

Focus on business meaning, not technical details. Only describe columns that have unclear purposes.
JSON:"""

ROUTINE_SUMMARY_PROMPT = """Analyze this database routine and provide a concise description.

{routine_type}: {routine_name}
SCHEMA: {schema_name}

PARAMETERS:
{parameters}

{returns_section}

LANGUAGE: {language}

DEFINITION:
```sql
{definition}
```

Write a 1-2 sentence description of what this {routine_type_lower} does.

Return JSON:
{{
  "description": "brief description of the routine's purpose"
}}

JSON:"""


# ============================================================================
# Summary Generation
# ============================================================================

async def generate_table_summary(
    conn: asyncpg.Connection,
    table_metadata_id: str,
    repo_id: str,
) -> dict[str, Any]:
    """Generate LLM summary for a table.

    Uses the "small" LLM model (phi3.5) for quick summaries.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID
        repo_id: Repository UUID

    Returns:
        Dict with description and column_descriptions
    """
    # Get table metadata
    table = await queries.get_table_metadata(conn, repo_id, table_id=table_metadata_id)
    if not table:
        return {"error": "Table not found"}

    # Format columns
    columns = table.get("columns", [])
    columns_text = "\n".join(
        f"  - {c.get('name')}: {c.get('data_type')}"
        f"{' (PK)' if c.get('is_primary_key') else ''}"
        f"{' (FK)' if c.get('is_foreign_key') else ''}"
        f"{' NOT NULL' if not c.get('nullable', True) else ''}"
        for c in columns
    ) or "  (no columns)"

    # Format constraints
    constraints = table.get("constraints", []) or []
    constraints_text = "\n".join(
        f"  - {c.get('constraint_type')}: {', '.join(c.get('columns', []))}"
        for c in constraints
    ) or "  (none)"

    # Get column usage summary
    usage_stats = await queries.get_column_usage_stats(conn, table_metadata_id)
    usage_text = _format_usage_summary(usage_stats)

    # Build prompt
    prompt = TABLE_SUMMARY_PROMPT.format(
        table_name=table.get("table_name"),
        schema_name=table.get("schema_name") or "default",
        columns=columns_text,
        constraints=constraints_text,
        usage_summary=usage_text
    )

    # Call LLM using "small" model (phi3.5 for quick summaries)
    response = await call_llm(prompt, task_type="small")
    if not response:
        return {"error": "LLM call failed"}

    # Parse response
    result = parse_json_response(response)
    if not result:
        # Fallback: use raw response as description
        result = {"description": response[:500], "column_descriptions": {}}

    # Store in database
    await queries.update_table_description(
        conn=conn,
        table_id=table_metadata_id,
        description=result.get("description", ""),
        column_descriptions=result.get("column_descriptions")
    )

    return result


async def generate_routine_summary(
    conn: asyncpg.Connection,
    routine_id: str,
    repo_id: str,
) -> dict[str, Any]:
    """Generate LLM summary for a routine.

    Uses the "small" LLM model (phi3.5) for quick summaries.

    Args:
        conn: Database connection
        routine_id: Routine metadata UUID
        repo_id: Repository UUID

    Returns:
        Dict with description
    """
    # Get routine metadata
    routine = await queries.get_routine_metadata(conn, repo_id, routine_id=routine_id)
    if not routine:
        return {"error": "Routine not found"}

    # Format parameters
    params = routine.get("parameters", []) or []
    params_text = "\n".join(
        f"  - {p.get('name', 'unnamed')}: {p.get('data_type')} ({p.get('mode', 'IN')})"
        for p in params
    ) or "  (none)"

    # Format return type
    return_type = routine.get("return_type")
    returns_section = f"RETURNS: {return_type}" if return_type else ""

    # Build prompt
    routine_type = routine.get("routine_type", "FUNCTION")
    prompt = ROUTINE_SUMMARY_PROMPT.format(
        routine_type=routine_type,
        routine_type_lower=routine_type.lower(),
        routine_name=routine.get("routine_name"),
        schema_name=routine.get("schema_name") or "default",
        parameters=params_text,
        returns_section=returns_section,
        language=routine.get("language") or "unknown",
        definition=routine.get("create_statement", "")[:2000]  # Limit definition size
    )

    # Call LLM using "small" model (phi3.5 for quick summaries)
    response = await call_llm(prompt, task_type="small")
    if not response:
        return {"error": "LLM call failed"}

    # Parse response
    result = parse_json_response(response)
    if not result:
        result = {"description": response[:500]}

    # Store in database
    await queries.update_routine_description(
        conn=conn,
        routine_id=routine_id,
        description=result.get("description", "")
    )

    return result


async def generate_summaries_for_repo(
    conn: asyncpg.Connection,
    repo_id: str,
    max_tables: int = 50,
    max_routines: int = 50
) -> dict[str, Any]:
    """Generate summaries for all tables and routines in a repo.

    Uses the "small" LLM model (phi3.5) for quick summaries.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        max_tables: Max tables to summarize
        max_routines: Max routines to summarize

    Returns:
        Statistics dict
    """
    stats = {
        "tables_summarized": 0,
        "routines_summarized": 0,
        "errors": 0
    }

    # Get tables without summaries
    tables = await conn.fetch(
        """
        SELECT id FROM sql_table_metadata
        WHERE repo_id = $1 AND description IS NULL
        LIMIT $2
        """,
        repo_id, max_tables
    )

    for table in tables:
        try:
            await generate_table_summary(
                conn=conn,
                table_metadata_id=str(table["id"]),
                repo_id=repo_id,
            )
            stats["tables_summarized"] += 1
        except Exception as e:
            logger.warning(f"Failed to summarize table {table['id']}: {e}")
            stats["errors"] += 1

    # Get routines without summaries
    routines = await conn.fetch(
        """
        SELECT id FROM sql_routine_metadata
        WHERE repo_id = $1 AND description IS NULL
        LIMIT $2
        """,
        repo_id, max_routines
    )

    for routine in routines:
        try:
            await generate_routine_summary(
                conn=conn,
                routine_id=str(routine["id"]),
                repo_id=repo_id,
            )
            stats["routines_summarized"] += 1
        except Exception as e:
            logger.warning(f"Failed to summarize routine {routine['id']}: {e}")
            stats["errors"] += 1

    return stats


# ============================================================================
# Helper Functions
# ============================================================================

def _format_usage_summary(usage_stats: dict[str, Any]) -> str:
    """Format column usage stats for prompt."""
    columns = usage_stats.get("columns", [])
    if not columns:
        return "  (no usage found in codebase)"

    lines = []
    for col in columns[:10]:  # Limit to top 10 columns
        usage_types = col.get("usage_types", [])
        lines.append(
            f"  - {col.get('column_name')}: used in {col.get('usage_count', 0)} places "
            f"({', '.join(usage_types[:3])})"
        )

    return "\n".join(lines)
