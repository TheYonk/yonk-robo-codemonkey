"""Batch summary generation for files, symbols, and modules.

Processes entities in batches to generate summaries efficiently.
"""
from __future__ import annotations
import asyncio
import asyncpg
import logging
from typing import Dict, Any, List
from dataclasses import dataclass

from .generator import (
    generate_file_summary,
    generate_symbol_summary,
    generate_module_summary,
)

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a batch summary generation."""
    total: int
    success: int
    failed: int
    skipped: int
    errors: List[str]


async def generate_file_summaries_batch(
    file_ids: List[str],
    database_url: str,
    llm_provider: str,
    llm_model: str,
    llm_base_url: str,
    batch_size: int = 10,
    schema_name: str | None = None
) -> BatchResult:
    """Generate file summaries in batches.

    Args:
        file_ids: List of file UUIDs to summarize
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: LLM endpoint URL
        batch_size: Number of files to process per batch
        schema_name: Schema to use (if None, uses default)

    Returns:
        BatchResult with success/failure counts
    """
    conn = await asyncpg.connect(dsn=database_url)
    result = BatchResult(total=len(file_ids), success=0, failed=0, skipped=0, errors=[])

    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Process in batches
        for i in range(0, len(file_ids), batch_size):
            batch = file_ids[i:i + batch_size]
            logger.info(f"Processing file summary batch {i // batch_size + 1}: {len(batch)} files")

            for file_id in batch:
                try:
                    # Generate summary
                    summary_result = await generate_file_summary(
                        file_id=file_id,
                        database_url=database_url,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                        schema_name=schema_name
                    )

                    if summary_result.success and summary_result.summary:
                        # Store summary in database
                        await conn.execute(
                            """
                            INSERT INTO file_summary (file_id, summary)
                            VALUES ($1, $2)
                            ON CONFLICT (file_id)
                            DO UPDATE SET
                                summary = EXCLUDED.summary,
                                updated_at = now()
                            """,
                            file_id, summary_result.summary
                        )
                        result.success += 1
                        logger.debug(f"Generated file summary for {file_id}")
                    else:
                        result.failed += 1
                        error_msg = summary_result.error or "Unknown error"
                        result.errors.append(f"File {file_id}: {error_msg}")
                        logger.warning(f"Failed to generate file summary for {file_id}: {error_msg}")

                except Exception as e:
                    result.failed += 1
                    result.errors.append(f"File {file_id}: {str(e)}")
                    logger.error(f"Error generating file summary for {file_id}: {e}")

            # Small delay between batches to avoid overloading LLM
            if i + batch_size < len(file_ids):
                await asyncio.sleep(1)

    finally:
        await conn.close()

    logger.info(f"File summary batch complete: {result.success} success, {result.failed} failed, {result.total} total")
    return result


async def generate_symbol_summaries_batch(
    symbol_ids: List[str],
    database_url: str,
    llm_provider: str,
    llm_model: str,
    llm_base_url: str,
    batch_size: int = 10,
    schema_name: str | None = None
) -> BatchResult:
    """Generate symbol summaries in batches.

    Args:
        symbol_ids: List of symbol UUIDs to summarize
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: LLM endpoint URL
        batch_size: Number of symbols to process per batch
        schema_name: Schema to use (if None, uses default)

    Returns:
        BatchResult with success/failure counts
    """
    conn = await asyncpg.connect(dsn=database_url)
    result = BatchResult(total=len(symbol_ids), success=0, failed=0, skipped=0, errors=[])

    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Process in batches
        for i in range(0, len(symbol_ids), batch_size):
            batch = symbol_ids[i:i + batch_size]
            logger.info(f"Processing symbol summary batch {i // batch_size + 1}: {len(batch)} symbols")

            for symbol_id in batch:
                try:
                    # Generate summary
                    summary_result = await generate_symbol_summary(
                        symbol_id=symbol_id,
                        database_url=database_url,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                        schema_name=schema_name
                    )

                    if summary_result.success and summary_result.summary:
                        # Store summary in database
                        await conn.execute(
                            """
                            INSERT INTO symbol_summary (symbol_id, summary)
                            VALUES ($1, $2)
                            ON CONFLICT (symbol_id)
                            DO UPDATE SET
                                summary = EXCLUDED.summary,
                                updated_at = now()
                            """,
                            symbol_id, summary_result.summary
                        )
                        result.success += 1
                        logger.debug(f"Generated symbol summary for {symbol_id}")
                    else:
                        result.failed += 1
                        error_msg = summary_result.error or "Unknown error"
                        result.errors.append(f"Symbol {symbol_id}: {error_msg}")
                        logger.warning(f"Failed to generate symbol summary for {symbol_id}: {error_msg}")

                except Exception as e:
                    result.failed += 1
                    result.errors.append(f"Symbol {symbol_id}: {str(e)}")
                    logger.error(f"Error generating symbol summary for {symbol_id}: {e}")

            # Small delay between batches
            if i + batch_size < len(symbol_ids):
                await asyncio.sleep(1)

    finally:
        await conn.close()

    logger.info(f"Symbol summary batch complete: {result.success} success, {result.failed} failed, {result.total} total")
    return result


async def generate_module_summaries_batch(
    modules: List[Dict[str, Any]],
    repo_id: str,
    database_url: str,
    llm_provider: str,
    llm_model: str,
    llm_base_url: str,
    batch_size: int = 5,
    schema_name: str | None = None
) -> BatchResult:
    """Generate module summaries in batches.

    Args:
        modules: List of dicts with 'module_path' keys
        repo_id: Repository UUID
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: LLM endpoint URL
        batch_size: Number of modules to process per batch
        schema_name: Schema to use (if None, uses default)

    Returns:
        BatchResult with success/failure counts
    """
    conn = await asyncpg.connect(dsn=database_url)
    result = BatchResult(total=len(modules), success=0, failed=0, skipped=0, errors=[])

    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Process in batches
        for i in range(0, len(modules), batch_size):
            batch = modules[i:i + batch_size]
            logger.info(f"Processing module summary batch {i // batch_size + 1}: {len(batch)} modules")

            for module in batch:
                module_path = module['module_path']

                try:
                    # Generate summary
                    summary_result = await generate_module_summary(
                        repo_id=repo_id,
                        module_path=module_path,
                        database_url=database_url,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                        schema_name=schema_name
                    )

                    if summary_result.success and summary_result.summary:
                        # Store summary in database
                        await conn.execute(
                            """
                            INSERT INTO module_summary (repo_id, module_path, summary)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (repo_id, module_path)
                            DO UPDATE SET
                                summary = EXCLUDED.summary,
                                updated_at = now()
                            """,
                            repo_id, module_path, summary_result.summary
                        )
                        result.success += 1
                        logger.debug(f"Generated module summary for {module_path}")
                    else:
                        result.failed += 1
                        error_msg = summary_result.error or "Unknown error"
                        result.errors.append(f"Module {module_path}: {error_msg}")
                        logger.warning(f"Failed to generate module summary for {module_path}: {error_msg}")

                except Exception as e:
                    result.failed += 1
                    result.errors.append(f"Module {module_path}: {str(e)}")
                    logger.error(f"Error generating module summary for {module_path}: {e}")

            # Small delay between batches
            if i + batch_size < len(modules):
                await asyncio.sleep(1)

    finally:
        await conn.close()

    logger.info(f"Module summary batch complete: {result.success} success, {result.failed} failed, {result.total} total")
    return result
