"""Metrics API endpoints for tool, LLM, and embedding usage data."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Query

from yonk_code_robomonkey.config import Settings

router = APIRouter()


async def _get_conn() -> asyncpg.Connection:
    settings = Settings()
    return await asyncpg.connect(dsn=settings.database_url, timeout=10)


def _safe_int(val) -> int | None:
    """Convert Decimal/float DB values to int for JSON serialization."""
    if val is None:
        return None
    return int(val)


@router.get("/overview")
async def metrics_overview():
    """Last-24h summary: tool calls, LLM tokens, embedding stats."""
    try:
        conn = await _get_conn()
        try:
            # Check if tables exist
            tables_exist = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'robomonkey_control'
                    AND table_name = 'mcp_tool_metrics'
                )
            """)
            if not tables_exist:
                return {
                    "enabled": False,
                    "message": "Metrics tables not created yet. Run 'robomonkey db init' or restart the daemon."
                }

            tool_row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_calls,
                    COUNT(*) FILTER (WHERE status = 'error') AS error_calls,
                    AVG(duration_ms)::INT AS avg_duration_ms
                FROM robomonkey_control.mcp_tool_metrics
                WHERE created_at > now() - INTERVAL '24 hours'
            """)

            llm_row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_calls,
                    COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    AVG(duration_ms)::INT AS avg_duration_ms
                FROM robomonkey_control.llm_call_metrics
                WHERE created_at > now() - INTERVAL '24 hours'
            """)

            embed_row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_calls,
                    COALESCE(SUM(text_count), 0) AS total_texts,
                    COALESCE(SUM(total_chars), 0) AS total_chars,
                    AVG(duration_ms)::INT AS avg_duration_ms
                FROM robomonkey_control.embedding_call_metrics
                WHERE created_at > now() - INTERVAL '24 hours'
            """)

            return {
                "enabled": True,
                "period": "24h",
                "tool_calls": {
                    "total": tool_row["total_calls"],
                    "errors": tool_row["error_calls"],
                    "avg_duration_ms": _safe_int(tool_row["avg_duration_ms"]),
                },
                "llm_calls": {
                    "total": llm_row["total_calls"],
                    "total_prompt_tokens": llm_row["total_prompt_tokens"],
                    "total_completion_tokens": llm_row["total_completion_tokens"],
                    "total_tokens": llm_row["total_tokens"],
                    "avg_duration_ms": _safe_int(llm_row["avg_duration_ms"]),
                },
                "embedding_calls": {
                    "total": embed_row["total_calls"],
                    "total_texts": embed_row["total_texts"],
                    "total_chars": embed_row["total_chars"],
                    "avg_duration_ms": _safe_int(embed_row["avg_duration_ms"]),
                },
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"enabled": False, "error": str(e)}


@router.get("/tools")
async def tool_metrics(days: int = Query(default=7, ge=1, le=90)):
    """Daily tool stats + recent calls."""
    try:
        conn = await _get_conn()
        try:
            # Daily stats from rollup table
            stats_rows = await conn.fetch("""
                SELECT tool_name, date::text, call_count, error_count,
                       avg_duration_ms, p95_duration_ms, max_duration_ms
                FROM robomonkey_control.mcp_tool_stats
                WHERE date >= CURRENT_DATE - ($1 || ' days')::INTERVAL
                ORDER BY date DESC, call_count DESC
            """, str(days))

            # Recent individual calls
            recent_rows = await conn.fetch("""
                SELECT tool_name, duration_ms, status, repo_context,
                       error_message, created_at::text
                FROM robomonkey_control.mcp_tool_metrics
                ORDER BY created_at DESC
                LIMIT 50
            """)

            return {
                "daily_stats": [dict(r) for r in stats_rows],
                "recent_calls": [dict(r) for r in recent_rows],
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


@router.get("/llm")
async def llm_metrics(days: int = Query(default=7, ge=1, le=90)):
    """Daily LLM stats by model."""
    try:
        conn = await _get_conn()
        try:
            stats_rows = await conn.fetch("""
                SELECT provider, model, task_type, date::text,
                       call_count, error_count,
                       total_prompt_tokens, total_completion_tokens, total_tokens,
                       avg_duration_ms, p95_duration_ms, max_duration_ms
                FROM robomonkey_control.llm_call_stats
                WHERE date >= CURRENT_DATE - ($1 || ' days')::INTERVAL
                ORDER BY date DESC, total_tokens DESC
            """, str(days))

            recent_rows = await conn.fetch("""
                SELECT provider, model, task_type,
                       prompt_tokens, completion_tokens, total_tokens,
                       tokens_estimated, duration_ms, status, caller,
                       error_message, created_at::text
                FROM robomonkey_control.llm_call_metrics
                ORDER BY created_at DESC
                LIMIT 50
            """)

            return {
                "daily_stats": [dict(r) for r in stats_rows],
                "recent_calls": [dict(r) for r in recent_rows],
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


@router.get("/embeddings")
async def embedding_metrics(days: int = Query(default=7, ge=1, le=90)):
    """Daily embedding stats."""
    try:
        conn = await _get_conn()
        try:
            stats_rows = await conn.fetch("""
                SELECT provider, model, date::text,
                       call_count, error_count,
                       total_texts, total_chars,
                       avg_duration_ms, p95_duration_ms, max_duration_ms
                FROM robomonkey_control.embedding_call_stats
                WHERE date >= CURRENT_DATE - ($1 || ' days')::INTERVAL
                ORDER BY date DESC, total_texts DESC
            """, str(days))

            recent_rows = await conn.fetch("""
                SELECT provider, model, text_count, total_chars,
                       duration_ms, status, error_message, created_at::text
                FROM robomonkey_control.embedding_call_metrics
                ORDER BY created_at DESC
                LIMIT 50
            """)

            return {
                "daily_stats": [dict(r) for r in stats_rows],
                "recent_calls": [dict(r) for r in recent_rows],
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


@router.post("/cleanup")
async def cleanup_metrics(retention_days: int = Query(default=30, ge=1, le=365)):
    """Clean up old granular metrics data."""
    try:
        conn = await _get_conn()
        try:
            result = await conn.fetchval(
                "SELECT robomonkey_control.cleanup_old_metrics($1)",
                retention_days
            )
            return {"status": "cleaned", "result": result}
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}
