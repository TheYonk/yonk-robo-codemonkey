"""Background worker for document validity scoring.

Periodically checks documentation and scores validity against the codebase.
"""
from __future__ import annotations
import asyncio
import asyncpg
import logging
from datetime import datetime
from typing import Any

from yonk_code_robomonkey.config import DaemonConfig
from yonk_code_robomonkey.db.schema_manager import list_repo_schemas, schema_context
from yonk_code_robomonkey.doc_validity import queries
from yonk_code_robomonkey.doc_validity.validator import validate_document
from yonk_code_robomonkey.doc_validity.scorer import (
    calculate_validity_score,
    store_validity_score,
    get_status
)

logger = logging.getLogger(__name__)


async def doc_validity_worker(config: DaemonConfig) -> None:
    """Background worker for document validity scoring.

    Runs on interval specified by config.doc_validity.check_interval_minutes.
    Checks documents against the codebase and calculates validity scores.

    Args:
        config: Daemon configuration
    """
    logger.info("Doc validity worker started")
    logger.info(f"Doc validity scoring: {'enabled' if config.doc_validity.enabled else 'disabled'}")
    logger.info(f"Check interval: {config.doc_validity.check_interval_minutes} minutes")
    logger.info(f"LLM validation: {'enabled' if config.doc_validity.use_llm_validation else 'disabled'}")

    while True:
        try:
            if not config.doc_validity.enabled:
                logger.debug("Doc validity scoring disabled, sleeping...")
                await asyncio.sleep(60)
                continue

            # Get all repositories
            conn = await asyncpg.connect(dsn=config.database.control_dsn)

            try:
                repos = await list_repo_schemas(conn)
                logger.info(f"Checking {len(repos)} repositories for doc validity...")

                total_stats = {
                    "repos_checked": len(repos),
                    "docs_validated": 0,
                    "issues_found": 0,
                    "errors": 0
                }

                # Process each repository
                for repo in repos:
                    repo_name = repo['repo_name']
                    repo_id = repo['repo_id']
                    schema_name = repo['schema_name']

                    logger.info(f"Processing repository: {repo_name} (schema: {schema_name})")

                    async with schema_context(conn, schema_name):
                        # Get current validity stats
                        try:
                            stats = await queries.get_validity_stats(conn, repo_id)
                            logger.info(
                                f"  Current validity - Total docs: {stats['total_docs']}, "
                                f"Validated: {stats['validated_docs']}, "
                                f"Avg score: {stats['avg_score']}"
                            )
                        except Exception as e:
                            logger.warning(f"  Could not get stats: {e}")
                            stats = {"total_docs": 0, "validated_docs": 0}

                        # Find documents needing validation
                        docs_to_validate = await queries.get_documents_needing_validation(
                            conn,
                            repo_id,
                            limit=config.doc_validity.batch_size
                        )

                        logger.info(f"  Found {len(docs_to_validate)} documents needing validation")

                        if not docs_to_validate:
                            logger.info(f"  No validation needed for {repo_name}")
                            continue

                        # Validate documents in batch
                        for doc in docs_to_validate:
                            try:
                                doc_id = str(doc['id'])
                                doc_path = doc.get('path', 'unknown')
                                doc_type = _get_doc_type(doc_path)

                                # Validate the document
                                validation_result = await validate_document(
                                    document_id=doc_id,
                                    repo_id=repo_id,
                                    conn=conn,
                                    doc_type=doc_type,
                                    content=doc.get('content'),
                                    max_references=config.doc_validity.max_references_per_doc
                                )

                                # Calculate score
                                score = await calculate_validity_score(
                                    document_id=doc_id,
                                    repo_id=repo_id,
                                    conn=conn,
                                    validation_result=validation_result,
                                    doc_updated=doc.get('updated_at'),
                                    weights={
                                        'reference': config.doc_validity.reference_weight,
                                        'embedding': config.doc_validity.embedding_weight,
                                        'freshness': config.doc_validity.freshness_weight,
                                    }
                                )

                                # Store the score
                                await store_validity_score(conn, score, repo_id)

                                total_stats["docs_validated"] += 1
                                total_stats["issues_found"] += len(score.issues)

                                logger.debug(
                                    f"    Validated {doc_path}: score={score.score}, "
                                    f"status={score.status}, issues={len(score.issues)}"
                                )

                            except Exception as e:
                                logger.error(f"    Error validating {doc.get('path', doc['id'])}: {e}")
                                total_stats["errors"] += 1

                        # Log summary for this repo
                        logger.info(
                            f"  Validated {len(docs_to_validate)} docs, "
                            f"found {total_stats['issues_found']} issues"
                        )

            finally:
                await conn.close()

            # Log overall stats
            logger.info(
                f"Doc validity cycle complete: "
                f"{total_stats['docs_validated']} docs validated, "
                f"{total_stats['issues_found']} issues found, "
                f"{total_stats['errors']} errors, "
                f"{total_stats['repos_checked']} repos checked"
            )

            # Sleep until next check
            sleep_seconds = config.doc_validity.check_interval_minutes * 60
            next_check = datetime.now().replace(microsecond=0)
            next_check = next_check.replace(
                second=0,
                minute=(next_check.minute + config.doc_validity.check_interval_minutes) % 60
            )
            logger.info(f"Next doc validity check at {next_check} (sleeping {sleep_seconds}s)")
            await asyncio.sleep(sleep_seconds)

        except Exception as e:
            logger.error(f"Error in doc validity worker: {e}", exc_info=True)
            # Sleep a bit before retrying
            await asyncio.sleep(60)


def _get_doc_type(path: str) -> str:
    """Determine document type from file path."""
    path_lower = path.lower()
    if path_lower.endswith('.rst'):
        return 'rst'
    elif path_lower.endswith('.adoc') or path_lower.endswith('.asciidoc'):
        return 'asciidoc'
    else:
        return 'markdown'


async def validate_document_once(
    document_id: str,
    repo_id: str,
    config: DaemonConfig,
    schema_name: str | None = None
) -> dict[str, Any]:
    """Validate a single document on-demand.

    Useful for MCP tool calls to get immediate validation.

    Args:
        document_id: Document UUID
        repo_id: Repository UUID
        config: Daemon configuration
        schema_name: Schema name (if known)

    Returns:
        Dict with validation results
    """
    conn = await asyncpg.connect(dsn=config.database.control_dsn)

    try:
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get document
        doc = await queries.get_document_by_id(conn, document_id)
        if not doc:
            return {
                "success": False,
                "error": "Document not found"
            }

        doc_type = _get_doc_type(doc.get('path', ''))

        # Validate
        validation_result = await validate_document(
            document_id=document_id,
            repo_id=repo_id,
            conn=conn,
            doc_type=doc_type,
            content=doc.get('content'),
            max_references=config.doc_validity.max_references_per_doc
        )

        # Calculate score
        score = await calculate_validity_score(
            document_id=document_id,
            repo_id=repo_id,
            conn=conn,
            validation_result=validation_result,
            doc_updated=doc.get('updated_at'),
            weights={
                'reference': config.doc_validity.reference_weight,
                'embedding': config.doc_validity.embedding_weight,
                'freshness': config.doc_validity.freshness_weight,
            }
        )

        # Store the score
        await store_validity_score(conn, score, repo_id)

        return {
            "success": True,
            "document_id": document_id,
            "path": doc.get('path'),
            "title": doc.get('title'),
            "score": score.score,
            "status": score.status,
            "component_scores": {
                "reference": round(score.reference_score, 2),
                "embedding": round(score.embedding_score, 2),
                "freshness": round(score.freshness_score, 2),
                "llm": score.llm_score
            },
            "references_checked": score.references_checked,
            "references_valid": score.references_valid,
            "related_code_chunks": score.related_code_chunks,
            "issues": [
                {
                    "type": issue.issue_type,
                    "severity": issue.severity,
                    "reference": issue.reference_text,
                    "line": issue.reference_line,
                    "expected_type": issue.expected_type,
                    "found_match": issue.found_match,
                    "similarity": issue.found_similarity,
                    "suggestion": issue.suggestion
                }
                for issue in score.issues
            ],
            "validated_at": score.validated_at.isoformat() if score.validated_at else None
        }

    finally:
        await conn.close()


async def run_validity_check_once(
    config: DaemonConfig,
    repo_name: str | None = None
) -> dict[str, Any]:
    """Run validity check once for all repos or a specific repo.

    Useful for CLI commands to trigger manual validation.

    Args:
        config: Daemon configuration
        repo_name: Optional specific repo to process (if None, processes all repos)

    Returns:
        Dict with validation results
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
                # Find all documents needing validation (no time limit)
                docs_to_validate = await queries.get_documents_needing_validation(
                    conn, repo_id, limit=500
                )

                repo_result = {
                    "repo_name": repo_name,
                    "docs_validated": 0,
                    "issues_found": 0,
                    "errors": 0,
                    "avg_score": 0.0
                }

                scores = []

                for doc in docs_to_validate:
                    try:
                        doc_id = str(doc['id'])
                        doc_type = _get_doc_type(doc.get('path', ''))

                        validation_result = await validate_document(
                            document_id=doc_id,
                            repo_id=repo_id,
                            conn=conn,
                            doc_type=doc_type,
                            content=doc.get('content'),
                            max_references=config.doc_validity.max_references_per_doc
                        )

                        score = await calculate_validity_score(
                            document_id=doc_id,
                            repo_id=repo_id,
                            conn=conn,
                            validation_result=validation_result,
                            doc_updated=doc.get('updated_at'),
                            weights={
                                'reference': config.doc_validity.reference_weight,
                                'embedding': config.doc_validity.embedding_weight,
                                'freshness': config.doc_validity.freshness_weight,
                            }
                        )

                        await store_validity_score(conn, score, repo_id)

                        repo_result["docs_validated"] += 1
                        repo_result["issues_found"] += len(score.issues)
                        scores.append(score.score)

                    except Exception as e:
                        logger.error(f"Error validating doc: {e}")
                        repo_result["errors"] += 1

                if scores:
                    repo_result["avg_score"] = round(sum(scores) / len(scores), 1)

                results.append(repo_result)

        return {
            "success": True,
            "repos_processed": len(results),
            "results": results
        }

    finally:
        await conn.close()
