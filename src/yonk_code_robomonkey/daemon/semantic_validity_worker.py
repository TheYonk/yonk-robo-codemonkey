"""Background worker for semantic document validation.

Periodically extracts behavioral claims from documentation and verifies
them against actual code behavior to detect doc drift.
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
from yonk_code_robomonkey.doc_validity.claim_extractor import (
    BehavioralClaim,
    extract_and_store_claims
)
from yonk_code_robomonkey.doc_validity.claim_verifier import verify_and_store_claim
from yonk_code_robomonkey.doc_validity.scorer import calculate_semantic_score

logger = logging.getLogger(__name__)


async def semantic_validity_worker(config: DaemonConfig) -> None:
    """Background worker for semantic document validation.

    Runs on interval specified by config.doc_validity.semantic_check_interval_minutes.
    Extracts behavioral claims from docs and verifies them against code.

    Args:
        config: Daemon configuration
    """
    logger.info("Semantic validity worker started")
    logger.info(f"Semantic validation: {'enabled' if config.doc_validity.semantic_validation_enabled else 'disabled'}")
    logger.info(f"Check interval: {config.doc_validity.semantic_check_interval_minutes} minutes")
    logger.info(f"Max claims per doc: {config.doc_validity.max_claims_per_doc}")
    logger.info(f"Min structural score: {config.doc_validity.semantic_min_structural_score}")

    while True:
        try:
            if not config.doc_validity.semantic_validation_enabled:
                logger.debug("Semantic validation disabled, sleeping...")
                await asyncio.sleep(300)  # Check every 5 minutes if still disabled
                continue

            # Get all repositories
            conn = await asyncpg.connect(dsn=config.database.control_dsn)

            try:
                repos = await list_repo_schemas(conn)
                logger.info(f"Checking {len(repos)} repositories for semantic validation...")

                total_stats = {
                    "repos_checked": len(repos),
                    "docs_validated": 0,
                    "claims_extracted": 0,
                    "claims_verified": 0,
                    "drift_found": 0,
                    "errors": 0
                }

                # Process each repository
                for repo in repos:
                    repo_name = repo['repo_name']
                    repo_id = repo['repo_id']
                    schema_name = repo['schema_name']

                    logger.info(f"Processing repository: {repo_name} (schema: {schema_name})")

                    async with schema_context(conn, schema_name):
                        try:
                            # Get drift stats
                            drift_stats = await queries.get_drift_stats(conn, repo_id)
                            logger.info(
                                f"  Current drift - Open: {drift_stats['by_status']['open']}, "
                                f"High: {drift_stats['by_severity']['high']}, "
                                f"Critical: {drift_stats['by_severity']['critical']}"
                            )
                        except Exception as e:
                            logger.warning(f"  Could not get drift stats: {e}")
                            drift_stats = None

                        # Find documents needing semantic validation
                        docs_to_validate = await queries.get_documents_for_semantic_validation(
                            conn,
                            repo_id,
                            min_structural_score=config.doc_validity.semantic_min_structural_score,
                            limit=config.doc_validity.semantic_batch_size
                        )

                        logger.info(f"  Found {len(docs_to_validate)} documents needing semantic validation")

                        if not docs_to_validate:
                            logger.info(f"  No semantic validation needed for {repo_name}")
                            continue

                        # Process each document
                        for doc in docs_to_validate:
                            try:
                                doc_id = str(doc['id'])
                                doc_path = doc.get('path', 'unknown')
                                content = doc.get('content', '')

                                logger.info(f"    Processing: {doc_path}")

                                # Extract claims (uses unified LLM client with "deep" model)
                                extraction_result = await extract_and_store_claims(
                                    conn=conn,
                                    document_id=doc_id,
                                    content=content,
                                    repo_id=repo_id,
                                    max_claims=config.doc_validity.max_claims_per_doc,
                                    min_confidence=config.doc_validity.claim_min_confidence
                                )

                                if not extraction_result.success:
                                    logger.warning(f"      Extraction failed: {extraction_result.error}")
                                    total_stats["errors"] += 1
                                    continue

                                claims_extracted = len(extraction_result.claims)
                                total_stats["claims_extracted"] += claims_extracted
                                logger.info(f"      Extracted {claims_extracted} claims")

                                if claims_extracted == 0:
                                    # No claims - update semantic score as perfect
                                    await queries.update_validity_score_semantic(
                                        conn=conn,
                                        document_id=doc_id,
                                        semantic_score=1.0,
                                        claims_checked=0,
                                        claims_verified=0
                                    )
                                    total_stats["docs_validated"] += 1
                                    continue

                                # Verify each claim
                                claims_verified = 0
                                drift_count = 0

                                # Get fresh claims from DB
                                db_claims = await queries.get_claims_for_document(conn, doc_id)

                                for claim_record in db_claims:
                                    try:
                                        # Build BehavioralClaim for verification
                                        claim = BehavioralClaim(
                                            claim_text=claim_record.claim_text,
                                            topic=claim_record.topic,
                                            claim_line=claim_record.claim_line,
                                            claim_context=claim_record.claim_context,
                                            subject=claim_record.subject,
                                            condition=claim_record.condition,
                                            expected_value=claim_record.expected_value,
                                            value_type=claim_record.value_type,
                                            confidence=claim_record.extraction_confidence
                                        )

                                        # Verify (uses unified LLM client with "deep" model)
                                        result = await verify_and_store_claim(
                                            conn=conn,
                                            claim=claim,
                                            claim_id=claim_record.id,
                                            repo_id=repo_id,
                                            database_url=config.database.control_dsn,
                                            embeddings_provider=config.embeddings.provider,
                                            embeddings_model=config.embeddings.model,
                                            embeddings_base_url=_get_embeddings_url(config),
                                            embeddings_api_key=config.embeddings.vllm.api_key if config.embeddings.provider == "vllm" else "",
                                            schema_name=schema_name
                                        )

                                        total_stats["claims_verified"] += 1

                                        if result.verdict == "match":
                                            claims_verified += 1
                                        elif result.verdict == "mismatch":
                                            drift_count += 1
                                            total_stats["drift_found"] += 1

                                    except Exception as e:
                                        logger.error(f"      Error verifying claim: {e}")
                                        total_stats["errors"] += 1

                                # Calculate and update semantic score
                                semantic_score = calculate_semantic_score(
                                    claims_checked=len(db_claims),
                                    claims_verified=claims_verified
                                )

                                await queries.update_validity_score_semantic(
                                    conn=conn,
                                    document_id=doc_id,
                                    semantic_score=semantic_score,
                                    claims_checked=len(db_claims),
                                    claims_verified=claims_verified
                                )

                                total_stats["docs_validated"] += 1

                                logger.info(
                                    f"      Verified: {claims_verified}/{len(db_claims)} match, "
                                    f"{drift_count} drift, semantic_score={semantic_score:.2f}"
                                )

                            except Exception as e:
                                logger.error(f"    Error processing {doc.get('path', doc['id'])}: {e}")
                                total_stats["errors"] += 1

                        # Log summary for this repo
                        logger.info(
                            f"  Repo {repo_name}: {total_stats['docs_validated']} docs validated, "
                            f"{total_stats['drift_found']} drift issues found"
                        )

            finally:
                await conn.close()

            # Log overall stats
            logger.info(
                f"Semantic validation cycle complete: "
                f"{total_stats['docs_validated']} docs, "
                f"{total_stats['claims_extracted']} claims extracted, "
                f"{total_stats['claims_verified']} verified, "
                f"{total_stats['drift_found']} drift found, "
                f"{total_stats['errors']} errors"
            )

            # Sleep until next check
            sleep_seconds = config.doc_validity.semantic_check_interval_minutes * 60
            next_check = datetime.now().replace(microsecond=0)
            logger.info(f"Next semantic validation check in {sleep_seconds}s")
            await asyncio.sleep(sleep_seconds)

        except Exception as e:
            logger.error(f"Error in semantic validity worker: {e}", exc_info=True)
            # Sleep before retrying
            await asyncio.sleep(60)


def _get_embeddings_url(config: DaemonConfig) -> str:
    """Get embeddings provider URL from config."""
    if config.embeddings.provider == "ollama":
        return config.embeddings.ollama.base_url
    else:
        return config.embeddings.vllm.base_url


async def validate_document_semantically(
    document_id: str,
    repo_id: str,
    config: DaemonConfig,
    schema_name: str | None = None
) -> dict[str, Any]:
    """Validate a single document semantically on-demand.

    Useful for MCP tool calls to get immediate semantic validation.

    Args:
        document_id: Document UUID
        repo_id: Repository UUID
        config: Daemon configuration
        schema_name: Schema name (if known)

    Returns:
        Dict with semantic validation results
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

        content = doc.get('content', '')

        # Extract claims (uses unified LLM client with "deep" model)
        extraction_result = await extract_and_store_claims(
            conn=conn,
            document_id=document_id,
            content=content,
            repo_id=repo_id,
            max_claims=config.doc_validity.max_claims_per_doc,
            min_confidence=config.doc_validity.claim_min_confidence
        )

        if not extraction_result.success:
            return {
                "success": False,
                "error": f"Claim extraction failed: {extraction_result.error}"
            }

        claims_extracted = len(extraction_result.claims)

        if claims_extracted == 0:
            await queries.update_validity_score_semantic(
                conn=conn,
                document_id=document_id,
                semantic_score=1.0,
                claims_checked=0,
                claims_verified=0
            )
            return {
                "success": True,
                "document_id": document_id,
                "path": doc.get('path'),
                "claims_extracted": 0,
                "claims_verified": 0,
                "semantic_score": 1.0,
                "drift_issues": [],
                "why": "No behavioral claims found in document"
            }

        # Verify claims
        verification_results = []
        claims_verified = 0
        drift_issues = []

        db_claims = await queries.get_claims_for_document(conn, document_id)

        for claim_record in db_claims:
            claim = BehavioralClaim(
                claim_text=claim_record.claim_text,
                topic=claim_record.topic,
                claim_line=claim_record.claim_line,
                claim_context=claim_record.claim_context,
                subject=claim_record.subject,
                condition=claim_record.condition,
                expected_value=claim_record.expected_value,
                value_type=claim_record.value_type,
                confidence=claim_record.extraction_confidence
            )

            # Verify (uses unified LLM client with "deep" model)
            result = await verify_and_store_claim(
                conn=conn,
                claim=claim,
                claim_id=claim_record.id,
                repo_id=repo_id,
                database_url=config.database.control_dsn,
                embeddings_provider=config.embeddings.provider,
                embeddings_model=config.embeddings.model,
                embeddings_base_url=_get_embeddings_url(config),
                embeddings_api_key=config.embeddings.vllm.api_key if config.embeddings.provider == "vllm" else "",
                schema_name=schema_name
            )

            verification_results.append({
                "claim_text": claim.claim_text,
                "topic": claim.topic,
                "expected_value": claim.expected_value,
                "verdict": result.verdict,
                "confidence": result.confidence,
                "actual_value": result.actual_value,
                "reasoning": result.reasoning
            })

            if result.verdict == "match":
                claims_verified += 1
            elif result.verdict == "mismatch":
                drift_issues.append({
                    "claim_text": claim.claim_text,
                    "expected_value": claim.expected_value,
                    "actual_value": result.actual_value,
                    "suggested_fix": result.suggested_fix
                })

        # Calculate and update semantic score
        semantic_score = calculate_semantic_score(
            claims_checked=len(db_claims),
            claims_verified=claims_verified
        )

        await queries.update_validity_score_semantic(
            conn=conn,
            document_id=document_id,
            semantic_score=semantic_score,
            claims_checked=len(db_claims),
            claims_verified=claims_verified
        )

        return {
            "success": True,
            "document_id": document_id,
            "path": doc.get('path'),
            "claims_extracted": len(db_claims),
            "claims_verified": claims_verified,
            "semantic_score": round(semantic_score, 2),
            "drift_issues": drift_issues,
            "verification_results": verification_results,
            "why": f"Extracted {len(db_claims)} claims, {claims_verified} verified, {len(drift_issues)} drift issues found"
        }

    finally:
        await conn.close()
