"""Daily rollup aggregation for metrics tables.

Uses INSERT ... ON CONFLICT DO UPDATE to incrementally update daily stats.
Called periodically by the daemon's metrics rollup loop.
"""
from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)


async def rollup_tool_stats(conn: asyncpg.Connection) -> int:
    """Roll up mcp_tool_metrics into mcp_tool_stats for today."""
    result = await conn.execute("""
        INSERT INTO robomonkey_control.mcp_tool_stats
            (tool_name, date, call_count, error_count, avg_duration_ms, p95_duration_ms, max_duration_ms)
        SELECT
            tool_name,
            created_at::date AS date,
            COUNT(*) AS call_count,
            COUNT(*) FILTER (WHERE status = 'error') AS error_count,
            AVG(duration_ms)::INT AS avg_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INT AS p95_duration_ms,
            MAX(duration_ms) AS max_duration_ms
        FROM robomonkey_control.mcp_tool_metrics
        WHERE created_at::date >= CURRENT_DATE - INTERVAL '1 day'
        GROUP BY tool_name, created_at::date
        ON CONFLICT (tool_name, date) DO UPDATE SET
            call_count = EXCLUDED.call_count,
            error_count = EXCLUDED.error_count,
            avg_duration_ms = EXCLUDED.avg_duration_ms,
            p95_duration_ms = EXCLUDED.p95_duration_ms,
            max_duration_ms = EXCLUDED.max_duration_ms,
            updated_at = now()
    """)
    count = int(result.split()[-1]) if result else 0
    logger.debug("Tool stats rollup: %d rows upserted", count)
    return count


async def rollup_llm_stats(conn: asyncpg.Connection) -> int:
    """Roll up llm_call_metrics into llm_call_stats for today."""
    result = await conn.execute("""
        INSERT INTO robomonkey_control.llm_call_stats
            (provider, model, task_type, date, call_count, error_count,
             total_prompt_tokens, total_completion_tokens, total_tokens,
             avg_duration_ms, p95_duration_ms, max_duration_ms)
        SELECT
            provider,
            model,
            task_type,
            created_at::date AS date,
            COUNT(*) AS call_count,
            COUNT(*) FILTER (WHERE status = 'error') AS error_count,
            COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            AVG(duration_ms)::INT AS avg_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INT AS p95_duration_ms,
            MAX(duration_ms) AS max_duration_ms
        FROM robomonkey_control.llm_call_metrics
        WHERE created_at::date >= CURRENT_DATE - INTERVAL '1 day'
        GROUP BY provider, model, task_type, created_at::date
        ON CONFLICT (provider, model, task_type, date) DO UPDATE SET
            call_count = EXCLUDED.call_count,
            error_count = EXCLUDED.error_count,
            total_prompt_tokens = EXCLUDED.total_prompt_tokens,
            total_completion_tokens = EXCLUDED.total_completion_tokens,
            total_tokens = EXCLUDED.total_tokens,
            avg_duration_ms = EXCLUDED.avg_duration_ms,
            p95_duration_ms = EXCLUDED.p95_duration_ms,
            max_duration_ms = EXCLUDED.max_duration_ms,
            updated_at = now()
    """)
    count = int(result.split()[-1]) if result else 0
    logger.debug("LLM stats rollup: %d rows upserted", count)
    return count


async def rollup_embedding_stats(conn: asyncpg.Connection) -> int:
    """Roll up embedding_call_metrics into embedding_call_stats for today."""
    result = await conn.execute("""
        INSERT INTO robomonkey_control.embedding_call_stats
            (provider, model, date, call_count, error_count,
             total_texts, total_chars, avg_duration_ms, p95_duration_ms, max_duration_ms)
        SELECT
            provider,
            model,
            created_at::date AS date,
            COUNT(*) AS call_count,
            COUNT(*) FILTER (WHERE status = 'error') AS error_count,
            SUM(text_count) AS total_texts,
            SUM(total_chars) AS total_chars,
            AVG(duration_ms)::INT AS avg_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INT AS p95_duration_ms,
            MAX(duration_ms) AS max_duration_ms
        FROM robomonkey_control.embedding_call_metrics
        WHERE created_at::date >= CURRENT_DATE - INTERVAL '1 day'
        GROUP BY provider, model, created_at::date
        ON CONFLICT (provider, model, date) DO UPDATE SET
            call_count = EXCLUDED.call_count,
            error_count = EXCLUDED.error_count,
            total_texts = EXCLUDED.total_texts,
            total_chars = EXCLUDED.total_chars,
            avg_duration_ms = EXCLUDED.avg_duration_ms,
            p95_duration_ms = EXCLUDED.p95_duration_ms,
            max_duration_ms = EXCLUDED.max_duration_ms,
            updated_at = now()
    """)
    count = int(result.split()[-1]) if result else 0
    logger.debug("Embedding stats rollup: %d rows upserted", count)
    return count


async def run_all_rollups(database_url: str) -> dict[str, int]:
    """Run all rollups using a single connection."""
    conn = await asyncpg.connect(database_url, timeout=10)
    try:
        tool = await rollup_tool_stats(conn)
        llm = await rollup_llm_stats(conn)
        embed = await rollup_embedding_stats(conn)
        return {"tool_stats": tool, "llm_stats": llm, "embedding_stats": embed}
    finally:
        await conn.close()
