"""Job processors for different job types."""

from __future__ import annotations
import asyncpg
import logging
from pathlib import Path
from typing import Any
import asyncio

from yonk_code_robomonkey.daemon.queue import Job
from yonk_code_robomonkey.config.daemon import DaemonConfig

logger = logging.getLogger(__name__)


class JobProcessor:
    """Base class for job processors."""

    def __init__(self, config: DaemonConfig, control_pool: asyncpg.Pool):
        self.config = config
        self.control_pool = control_pool

    async def process(self, job: Job) -> None:
        """Process a job. Must be implemented by subclasses."""
        raise NotImplementedError


class FullIndexProcessor(JobProcessor):
    """Processor for FULL_INDEX jobs."""

    async def process(self, job: Job) -> None:
        """Reindex entire repository."""
        logger.info(f"Processing FULL_INDEX for {job.repo_name}")

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name, root_path
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        repo_path = repo["root_path"]
        schema_name = repo["schema_name"]

        # Import indexer
        from yonk_code_robomonkey.indexer.indexer import index_repository

        # Run full index
        stats = await index_repository(
            repo_path=repo_path,
            repo_name=job.repo_name,
            database_url=self.config.database.control_dsn,
            force=False
        )

        logger.info(f"FULL_INDEX complete for {job.repo_name}: {stats}")


class ReindexFileProcessor(JobProcessor):
    """Processor for REINDEX_FILE jobs."""

    async def process(self, job: Job) -> None:
        """Reindex a single file."""
        file_path = job.payload.get("path")
        op = job.payload.get("op", "UPSERT")

        if not file_path:
            raise ValueError("REINDEX_FILE job missing 'path' in payload")

        logger.info(f"Processing REINDEX_FILE: {file_path} (op={op}) for {job.repo_name}")

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name, root_path
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        repo_root = Path(repo["root_path"])
        abs_path = repo_root / file_path
        schema_name = repo["schema_name"]

        # Get repo_id from the repo schema
        async with await asyncpg.connect(dsn=self.config.database.control_dsn) as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name} in schema {schema_name}")

        # Import reindexer
        from yonk_code_robomonkey.freshness.reindexer import reindex_file

        # Reindex the file
        await reindex_file(
            repo_id=str(repo_id),
            abs_path=str(abs_path),
            op=op,
            database_url=self.config.database.control_dsn,
            schema_name=schema_name
        )

        logger.info(f"REINDEX_FILE complete: {file_path}")


class ReindexManyProcessor(JobProcessor):
    """Processor for REINDEX_MANY jobs (batch file reindex)."""

    async def process(self, job: Job) -> None:
        """Reindex multiple files."""
        paths = job.payload.get("paths", [])

        if not paths:
            raise ValueError("REINDEX_MANY job missing 'paths' in payload")

        logger.info(f"Processing REINDEX_MANY: {len(paths)} files for {job.repo_name}")

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name, root_path
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        repo_root = Path(repo["root_path"])
        schema_name = repo["schema_name"]

        # Get repo_id from the repo schema
        async with await asyncpg.connect(dsn=self.config.database.control_dsn) as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name} in schema {schema_name}")

        # Import reindexer
        from yonk_code_robomonkey.freshness.reindexer import reindex_file

        # Process each file
        success_count = 0
        error_count = 0

        for path_info in paths:
            file_path = path_info.get("path")
            op = path_info.get("op", "UPSERT")

            try:
                abs_path = repo_root / file_path
                await reindex_file(
                    repo_id=str(repo_id),
                    abs_path=str(abs_path),
                    op=op,
                    database_url=self.config.database.control_dsn,
                    schema_name=schema_name
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to reindex {file_path}: {e}")
                error_count += 1

        logger.info(
            f"REINDEX_MANY complete: {success_count} succeeded, {error_count} failed"
        )

        if error_count > 0 and success_count == 0:
            raise Exception(f"All {len(paths)} files failed to reindex")


class EmbedMissingProcessor(JobProcessor):
    """Processor for EMBED_MISSING jobs."""

    async def process(self, job: Job) -> None:
        """Generate embeddings for chunks/docs missing them."""
        logger.info(f"Processing EMBED_MISSING for {job.repo_name}")

        if not self.config.embeddings.enabled:
            logger.warning("Embeddings disabled, skipping EMBED_MISSING job")
            return

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name, root_path
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        schema_name = repo["schema_name"]

        # Count missing embeddings
        async with self.control_pool.acquire() as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

            missing_chunks = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM chunk c
                LEFT JOIN chunk_embedding ce ON c.id = ce.chunk_id
                WHERE ce.chunk_id IS NULL
                """
            )

            missing_docs = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM document d
                LEFT JOIN document_embedding de ON d.id = de.document_id
                WHERE de.document_id IS NULL
                """
            )

        logger.info(
            f"Found {missing_chunks} chunks and {missing_docs} docs missing embeddings"
        )

        if missing_chunks == 0 and missing_docs == 0:
            logger.info("No missing embeddings, job complete")
            return

        # Import embedder
        from yonk_code_robomonkey.embeddings.embedder import embed_repo

        # Generate embeddings
        stats = await embed_repo(
            repo_id=None,  # Will be looked up by name
            repo_name=job.repo_name,
            database_url=self.config.database.control_dsn,
            schema_name=schema_name,
            embeddings_provider=self.config.embeddings.provider,
            embeddings_model=self.config.embeddings.model,
            embeddings_base_url=(
                self.config.embeddings.ollama.base_url
                if self.config.embeddings.provider == "ollama"
                else self.config.embeddings.vllm.base_url
            ),
            embeddings_api_key=(
                self.config.embeddings.vllm.api_key
                if self.config.embeddings.provider == "vllm"
                else ""
            ),
            only_missing=True,
            batch_size=self.config.embeddings.batch_size,
            max_chunk_length=self.config.embeddings.max_chunk_length
        )

        logger.info(f"EMBED_MISSING complete for {job.repo_name}: {stats}")


class DocsScanProcessor(JobProcessor):
    """Processor for DOCS_SCAN jobs."""

    async def process(self, job: Job) -> None:
        """Scan and ingest documentation files."""
        logger.info(f"Processing DOCS_SCAN for {job.repo_name}")

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name, root_path
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        repo_path = repo["root_path"]
        schema_name = repo["schema_name"]

        # Get repo_id from the repo schema
        async with await asyncpg.connect(dsn=self.config.database.control_dsn) as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name}")

        # Import doc ingester
        from yonk_code_robomonkey.indexer.doc_ingester import ingest_docs

        # Ingest docs
        stats = await ingest_docs(
            repo_id=str(repo_id),
            repo_path=repo_path,
            database_url=self.config.database.control_dsn,
            schema_name=schema_name
        )

        logger.info(f"DOCS_SCAN complete for {job.repo_name}: {stats}")


class TagRulesSyncProcessor(JobProcessor):
    """Processor for TAG_RULES_SYNC jobs."""

    async def process(self, job: Job) -> None:
        """Sync tag rules for a repository."""
        logger.info(f"Processing TAG_RULES_SYNC for {job.repo_name}")

        if not self.config.enable_tag_rules_sync:
            logger.warning("Tag rules sync disabled, skipping")
            return

        # Get repo info
        async with self.control_pool.acquire() as conn:
            repo = await conn.fetchrow(
                """
                SELECT name, schema_name
                FROM robomonkey_control.repo_registry
                WHERE name = $1
                """,
                job.repo_name
            )

        if not repo:
            raise ValueError(f"Repo not found: {job.repo_name}")

        schema_name = repo["schema_name"]

        # Get repo_id from the repo schema
        async with await asyncpg.connect(dsn=self.config.database.control_dsn) as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name}")

        # Import tag rules
        from yonk_code_robomonkey.tagging.rules import apply_tag_rules, seed_starter_tags

        # Seed starter tags if needed
        async with await asyncpg.connect(dsn=self.config.database.control_dsn) as conn:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            await seed_starter_tags(conn)

        # Apply tag rules
        stats = await apply_tag_rules(
            repo_id=str(repo_id),
            database_url=self.config.database.control_dsn,
            schema_name=schema_name
        )

        logger.info(f"TAG_RULES_SYNC complete for {job.repo_name}: {stats}")


# Registry of processors
PROCESSORS: dict[str, type[JobProcessor]] = {
    "FULL_INDEX": FullIndexProcessor,
    "REINDEX_FILE": ReindexFileProcessor,
    "REINDEX_MANY": ReindexManyProcessor,
    "EMBED_MISSING": EmbedMissingProcessor,
    "DOCS_SCAN": DocsScanProcessor,
    "TAG_RULES_SYNC": TagRulesSyncProcessor,
}


def get_processor(job_type: str, config: DaemonConfig, pool: asyncpg.Pool) -> JobProcessor:
    """Get processor instance for job type."""
    processor_class = PROCESSORS.get(job_type)
    if not processor_class:
        raise ValueError(f"Unknown job type: {job_type}")

    return processor_class(config, pool)
