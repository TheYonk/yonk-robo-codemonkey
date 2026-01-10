"""Background worker for auto-summary generation.

Periodically checks for files, symbols, and modules that need summaries
and generates them in batches.
"""
from __future__ import annotations
import asyncio
import asyncpg
import logging
from datetime import datetime
from typing import Dict, Any

from yonk_code_robomonkey.config import DaemonConfig
from yonk_code_robomonkey.db.schema_manager import list_repo_schemas, schema_context
from yonk_code_robomonkey.summaries.queries import (
    find_files_needing_summaries,
    find_symbols_needing_summaries,
    find_modules_needing_summaries,
    get_summary_stats
)
from yonk_code_robomonkey.summaries.batch_generator import (
    generate_file_summaries_batch,
    generate_symbol_summaries_batch,
    generate_module_summaries_batch
)

logger = logging.getLogger(__name__)


async def summary_worker(config: DaemonConfig) -> None:
    """Background worker for auto-summary generation.

    Runs on interval specified by config.summaries.check_interval_minutes.
    Checks for files/symbols/modules that need summaries and generates them in batches.

    Args:
        config: Daemon configuration
    """
    logger.info("Summary worker started")
    logger.info(f"Auto-summary generation: {'enabled' if config.summaries.enabled else 'disabled'}")
    logger.info(f"Check interval: {config.summaries.check_interval_minutes} minutes")
    logger.info(f"LLM provider: {config.summaries.provider}, model: {config.summaries.model}")

    while True:
        try:
            if not config.summaries.enabled:
                logger.debug("Summary generation disabled, sleeping...")
                await asyncio.sleep(60)
                continue

            # Get all repositories
            conn = await asyncpg.connect(dsn=config.database.control_dsn)

            try:
                repos = await list_repo_schemas(conn)
                logger.info(f"Checking {len(repos)} repositories for summaries...")

                total_stats = {
                    "repos_checked": len(repos),
                    "files_summarized": 0,
                    "symbols_summarized": 0,
                    "modules_summarized": 0,
                    "errors": 0
                }

                # Process each repository
                for repo in repos:
                    repo_name = repo['repo_name']
                    repo_id = repo['repo_id']
                    schema_name = repo['schema_name']

                    logger.info(f"Processing repository: {repo_name} (schema: {schema_name})")

                    # Get summary stats
                    async with schema_context(conn, schema_name):
                        stats = await get_summary_stats(conn, repo_id)
                        logger.info(
                            f"  Current coverage - Files: {stats['files']['coverage_pct']}%, "
                            f"Symbols: {stats['symbols']['coverage_pct']}%, "
                            f"Modules: {stats['modules']['coverage_pct']}%"
                        )

                        # Find entities needing summaries
                        files_to_summarize = await find_files_needing_summaries(
                            conn,
                            repo_id,
                            config.summaries.check_interval_minutes,
                            limit=100
                        )

                        symbols_to_summarize = await find_symbols_needing_summaries(
                            conn,
                            repo_id,
                            config.summaries.check_interval_minutes,
                            limit=200
                        )

                        modules_to_summarize = await find_modules_needing_summaries(
                            conn,
                            repo_id,
                            config.summaries.check_interval_minutes,
                            limit=50
                        )

                        logger.info(
                            f"  Found {len(files_to_summarize)} files, "
                            f"{len(symbols_to_summarize)} symbols, "
                            f"{len(modules_to_summarize)} modules needing summaries"
                        )

                        if not files_to_summarize and not symbols_to_summarize and not modules_to_summarize:
                            logger.info(f"  No summaries needed for {repo_name}")
                            continue

                        # Generate summaries in batches (uses unified LLM client with "small" model)
                        if files_to_summarize:
                            file_ids = [f['file_id'] for f in files_to_summarize]
                            file_result = await generate_file_summaries_batch(
                                file_ids=file_ids,
                                database_url=config.database.control_dsn,
                                batch_size=config.summaries.batch_size,
                                schema_name=schema_name
                            )
                            total_stats["files_summarized"] += file_result.success
                            total_stats["errors"] += file_result.failed
                            logger.info(
                                f"  File summaries: {file_result.success} success, "
                                f"{file_result.failed} failed, {file_result.total} total"
                            )

                        if symbols_to_summarize:
                            symbol_ids = [s['symbol_id'] for s in symbols_to_summarize]
                            symbol_result = await generate_symbol_summaries_batch(
                                symbol_ids=symbol_ids,
                                database_url=config.database.control_dsn,
                                batch_size=config.summaries.batch_size,
                                schema_name=schema_name
                            )
                            total_stats["symbols_summarized"] += symbol_result.success
                            total_stats["errors"] += symbol_result.failed
                            logger.info(
                                f"  Symbol summaries: {symbol_result.success} success, "
                                f"{symbol_result.failed} failed, {symbol_result.total} total"
                            )

                        if modules_to_summarize:
                            module_result = await generate_module_summaries_batch(
                                modules=modules_to_summarize,
                                repo_id=repo_id,
                                database_url=config.database.control_dsn,
                                batch_size=min(config.summaries.batch_size, 5),  # Smaller batches for modules
                                schema_name=schema_name
                            )
                            total_stats["modules_summarized"] += module_result.success
                            total_stats["errors"] += module_result.failed
                            logger.info(
                                f"  Module summaries: {module_result.success} success, "
                                f"{module_result.failed} failed, {module_result.total} total"
                            )

            finally:
                await conn.close()

            # Log overall stats
            logger.info(
                f"Summary generation cycle complete: "
                f"{total_stats['files_summarized']} files, "
                f"{total_stats['symbols_summarized']} symbols, "
                f"{total_stats['modules_summarized']} modules, "
                f"{total_stats['errors']} errors, "
                f"{total_stats['repos_checked']} repos checked"
            )

            # Sleep until next check
            sleep_seconds = config.summaries.check_interval_minutes * 60
            next_check = datetime.now().replace(microsecond=0)
            next_check = next_check.replace(
                second=0,
                minute=(next_check.minute + config.summaries.check_interval_minutes) % 60
            )
            logger.info(f"Next summary check at {next_check} (sleeping {sleep_seconds}s)")
            await asyncio.sleep(sleep_seconds)

        except Exception as e:
            logger.error(f"Error in summary worker: {e}", exc_info=True)
            # Sleep a bit before retrying
            await asyncio.sleep(60)


async def run_summary_generation_once(config: DaemonConfig, repo_name: str | None = None) -> Dict[str, Any]:
    """Run summary generation once for all repos or a specific repo.

    Useful for CLI commands to trigger manual summary generation.

    Args:
        config: Daemon configuration
        repo_name: Optional specific repo to process (if None, processes all repos)

    Returns:
        Dict with generation results
    """
    conn = await asyncpg.connect(dsn=config.database.control_dsn)

    try:
        # Get repositories to process
        if repo_name:
            from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name)
            repos = [{
                'repo_name': repo_name,
                'repo_id': repo_id,
                'schema_name': schema_name
            }]
        else:
            repos = await list_repo_schemas(conn)

        results = []

        for repo in repos:
            repo_name = repo['repo_name']
            repo_id = repo['repo_id']
            schema_name = repo['schema_name']

            async with schema_context(conn, schema_name):
                # Find all entities (no time limit)
                files_to_summarize = await find_files_needing_summaries(
                    conn, repo_id, check_interval_minutes=999999, limit=1000
                )
                symbols_to_summarize = await find_symbols_needing_summaries(
                    conn, repo_id, check_interval_minutes=999999, limit=5000
                )
                modules_to_summarize = await find_modules_needing_summaries(
                    conn, repo_id, check_interval_minutes=999999, limit=500
                )

                repo_result = {
                    "repo_name": repo_name,
                    "files": 0,
                    "symbols": 0,
                    "modules": 0,
                    "errors": 0
                }

                # Generate summaries (uses unified LLM client with "small" model)
                if files_to_summarize:
                    file_ids = [f['file_id'] for f in files_to_summarize]
                    file_result = await generate_file_summaries_batch(
                        file_ids=file_ids,
                        database_url=config.database.control_dsn,
                        batch_size=config.summaries.batch_size,
                        schema_name=schema_name
                    )
                    repo_result["files"] = file_result.success
                    repo_result["errors"] += file_result.failed

                if symbols_to_summarize:
                    symbol_ids = [s['symbol_id'] for s in symbols_to_summarize]
                    symbol_result = await generate_symbol_summaries_batch(
                        symbol_ids=symbol_ids,
                        database_url=config.database.control_dsn,
                        batch_size=config.summaries.batch_size,
                        schema_name=schema_name
                    )
                    repo_result["symbols"] = symbol_result.success
                    repo_result["errors"] += symbol_result.failed

                if modules_to_summarize:
                    module_result = await generate_module_summaries_batch(
                        modules=modules_to_summarize,
                        repo_id=repo_id,
                        database_url=config.database.control_dsn,
                        batch_size=5,
                        schema_name=schema_name
                    )
                    repo_result["modules"] = module_result.success
                    repo_result["errors"] += module_result.failed

                results.append(repo_result)

        return {
            "success": True,
            "repos_processed": len(results),
            "results": results
        }

    finally:
        await conn.close()
