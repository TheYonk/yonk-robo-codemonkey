"""Job processors for different job types."""

from __future__ import annotations
import asyncpg
import logging
from pathlib import Path
from typing import Any
import asyncio

from yonk_code_robomonkey.daemon.queue import Job
from yonk_code_robomonkey.config.daemon import DaemonConfig
from yonk_code_robomonkey.db.vector_indexes import (
    get_embedding_counts,
    rebuild_schema_indexes,
    should_rebuild_indexes,
)

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

        # Run full index (check payload for force flag)
        import json
        payload = job.payload if isinstance(job.payload, dict) else json.loads(job.payload) if job.payload else {}
        force = payload.get("force", False)
        stats = await index_repository(
            repo_path=repo_path,
            repo_name=job.repo_name,
            database_url=self.config.database.control_dsn,
            force=force
        )

        logger.info(f"FULL_INDEX complete for {job.repo_name}: {stats}")


class ReindexFileProcessor(JobProcessor):
    """Processor for REINDEX_FILE jobs."""

    async def process(self, job: Job) -> None:
        """Reindex a single file."""
        import json
        payload = job.payload if isinstance(job.payload, dict) else json.loads(job.payload) if job.payload else {}
        file_path = payload.get("path")
        op = payload.get("op", "UPSERT")

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
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )
        finally:
            await conn.close()

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name} in schema {schema_name}")

        # Import reindexer
        from yonk_code_robomonkey.indexer.reindexer import reindex_file

        # Reindex the file
        await reindex_file(
            repo_id=str(repo_id),
            abs_path=abs_path,
            op=op,
            database_url=self.config.database.control_dsn,
            repo_root=repo_root,
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
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )
        finally:
            await conn.close()

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name} in schema {schema_name}")

        # Import reindexer
        from yonk_code_robomonkey.indexer.reindexer import reindex_file

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
    """Processor for EMBED_MISSING jobs.

    Supports payload overrides for embedding configuration:
        - model: Override the embedding model (e.g., "all-MiniLM-L6-v2")
        - provider: Override the provider ("ollama", "vllm", "openai")
        - base_url: Override the embedding service URL
        - batch_size: Override batch size for embedding requests

    If not specified in payload, falls back to global config defaults.
    """

    async def process(self, job: Job) -> None:
        """Generate embeddings for chunks/docs missing them."""
        logger.info(f"Processing EMBED_MISSING for {job.repo_name}")

        if not self.config.embeddings.enabled:
            logger.warning("Embeddings disabled, skipping EMBED_MISSING job")
            return

        # Parse payload for optional overrides
        import json
        payload = job.payload if isinstance(job.payload, dict) else json.loads(job.payload) if job.payload else {}

        # Get embedding settings from payload or fall back to config defaults
        use_provider = payload.get("provider", self.config.embeddings.provider)
        use_model = payload.get("model", self.config.embeddings.model)
        use_batch_size = payload.get("batch_size", self.config.embeddings.batch_size)

        # Determine base_url and api_key based on provider (payload can override base_url)
        if use_provider == "ollama":
            default_base_url = self.config.embeddings.ollama.base_url
            api_key = ""
        elif use_provider == "vllm":
            default_base_url = self.config.embeddings.vllm.base_url
            api_key = self.config.embeddings.vllm.api_key
        else:  # openai (includes local embedding service)
            default_base_url = self.config.embeddings.openai.base_url
            api_key = self.config.embeddings.openai.api_key

        use_base_url = payload.get("base_url", default_base_url)

        # Log effective settings (helpful for debugging)
        if payload.get("model") or payload.get("provider"):
            logger.info(
                f"Using payload overrides - provider: {use_provider}, model: {use_model}, "
                f"base_url: {use_base_url}"
            )
        else:
            logger.debug(f"Using default config - provider: {use_provider}, model: {use_model}")

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

        # Get embedding counts BEFORE processing (for auto-rebuild decision)
        before_counts = {}
        if self.config.embeddings.auto_rebuild_indexes:
            async with self.control_pool.acquire() as conn:
                before_counts = await get_embedding_counts(conn, schema_name)
            logger.debug(f"Embedding counts before: {before_counts}")

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

        # Generate embeddings with effective settings
        stats = await embed_repo(
            repo_id=None,  # Will be looked up by name
            repo_name=job.repo_name,
            database_url=self.config.database.control_dsn,
            schema_name=schema_name,
            embeddings_provider=use_provider,
            embeddings_model=use_model,
            embeddings_base_url=use_base_url,
            embeddings_api_key=api_key,
            only_missing=True,
            batch_size=use_batch_size,
            max_chunk_length=self.config.embeddings.max_chunk_length
        )

        logger.info(f"EMBED_MISSING complete for {job.repo_name} (model={use_model}): {stats}")

        # Auto-rebuild vector indexes if enabled and threshold exceeded
        if self.config.embeddings.auto_rebuild_indexes:
            async with self.control_pool.acquire() as conn:
                after_counts = await get_embedding_counts(conn, schema_name)
            logger.debug(f"Embedding counts after: {after_counts}")

            should_rebuild, reason = await should_rebuild_indexes(
                before_counts,
                after_counts,
                self.config.embeddings.rebuild_change_threshold
            )

            if should_rebuild:
                logger.info(f"Auto-rebuilding vector indexes for {schema_name}: {reason}")
                async with self.control_pool.acquire() as conn:
                    rebuild_results = await rebuild_schema_indexes(
                        conn=conn,
                        schema_name=schema_name,
                        index_type=self.config.embeddings.rebuild_index_type,
                        lists=None,  # Auto-calculate based on row count
                        m=self.config.embeddings.rebuild_hnsw_m,
                        ef_construction=self.config.embeddings.rebuild_hnsw_ef_construction
                    )
                rebuilt_count = sum(1 for r in rebuild_results if r.get("status") == "rebuilt")
                logger.info(f"Auto-rebuild complete: {rebuilt_count} indexes rebuilt")
            else:
                logger.debug(f"Skipping index rebuild: {reason}")


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
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )
        finally:
            await conn.close()

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
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )
        finally:
            await conn.close()

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


class SummarizeFilesProcessor(JobProcessor):
    """Processor for SUMMARIZE_FILES jobs - generates file summaries in batch."""

    async def process(self, job: Job) -> None:
        """Generate summaries for files without summaries."""
        logger.info(f"Processing SUMMARIZE_FILES for {job.repo_name}")

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

        # Get repo_id and files without summaries
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

            # Get files that don't have summaries yet
            rows = await conn.fetch(
                """
                SELECT f.id
                FROM file f
                LEFT JOIN file_summary fs ON f.id = fs.file_id
                WHERE fs.file_id IS NULL
                  AND f.language IS NOT NULL
                  AND f.language NOT IN ('binary', 'image', 'unknown')
                ORDER BY f.path
                LIMIT 500
                """
            )
            file_ids = [str(row['id']) for row in rows]

        finally:
            await conn.close()

        if not file_ids:
            logger.info(f"No files need summaries for {job.repo_name}")
            return

        logger.info(f"Generating summaries for {len(file_ids)} files in {job.repo_name}")

        # Import batch generator
        from yonk_code_robomonkey.summaries.batch_generator import generate_file_summaries_batch

        # Generate summaries in batches
        result = await generate_file_summaries_batch(
            file_ids=file_ids,
            database_url=self.config.database.control_dsn,
            batch_size=5,  # Small batches to avoid overloading LLM
            schema_name=schema_name
        )

        logger.info(
            f"SUMMARIZE_FILES complete for {job.repo_name}: "
            f"{result.success} success, {result.failed} failed, {result.total} total"
        )


class SummarizeSymbolsProcessor(JobProcessor):
    """Processor for SUMMARIZE_SYMBOLS jobs - generates symbol summaries in batch."""

    async def process(self, job: Job) -> None:
        """Generate summaries for symbols without summaries."""
        logger.info(f"Processing SUMMARIZE_SYMBOLS for {job.repo_name}")

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

        # Get symbols without summaries
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

            # Get symbols that don't have summaries yet
            # Prioritize functions and classes over variables
            rows = await conn.fetch(
                """
                SELECT s.id
                FROM symbol s
                LEFT JOIN symbol_summary ss ON s.id = ss.symbol_id
                WHERE ss.symbol_id IS NULL
                  AND s.kind IN ('function', 'method', 'class', 'interface')
                ORDER BY
                    CASE s.kind
                        WHEN 'class' THEN 1
                        WHEN 'interface' THEN 2
                        WHEN 'function' THEN 3
                        WHEN 'method' THEN 4
                        ELSE 5
                    END,
                    s.fqn
                LIMIT 500
                """
            )
            symbol_ids = [str(row['id']) for row in rows]

        finally:
            await conn.close()

        if not symbol_ids:
            logger.info(f"No symbols need summaries for {job.repo_name}")
            return

        logger.info(f"Generating summaries for {len(symbol_ids)} symbols in {job.repo_name}")

        # Import batch generator
        from yonk_code_robomonkey.summaries.batch_generator import generate_symbol_summaries_batch

        # Generate summaries in batches
        result = await generate_symbol_summaries_batch(
            symbol_ids=symbol_ids,
            database_url=self.config.database.control_dsn,
            batch_size=5,  # Small batches to avoid overloading LLM
            schema_name=schema_name
        )

        logger.info(
            f"SUMMARIZE_SYMBOLS complete for {job.repo_name}: "
            f"{result.success} success, {result.failed} failed, {result.total} total"
        )


class RegenerateSummaryProcessor(JobProcessor):
    """Processor for REGENERATE_SUMMARY jobs."""

    async def process(self, job: Job) -> None:
        """Regenerate comprehensive summary for a repository."""
        logger.info(f"Processing REGENERATE_SUMMARY for {job.repo_name}")

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
        conn = await asyncpg.connect(dsn=self.config.database.control_dsn)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                job.repo_name
            )
        finally:
            await conn.close()

        if not repo_id:
            raise ValueError(f"Repo ID not found for {job.repo_name}")

        # Import summary generator
        from yonk_code_robomonkey.reports.generator import generate_comprehensive_review

        # Generate comprehensive review summary
        result = await generate_comprehensive_review(
            repo_id=str(repo_id),
            database_url=self.config.database.control_dsn,
            regenerate=True,  # Force regeneration
            max_modules=25,
            max_files_per_module=20,
            schema_name=schema_name
        )

        logger.info(
            f"REGENERATE_SUMMARY complete for {job.repo_name}: "
            f"cached={result.cached}, hash={result.content_hash[:8]}"
        )


# Registry of processors
PROCESSORS: dict[str, type[JobProcessor]] = {
    "FULL_INDEX": FullIndexProcessor,
    "REINDEX_FILE": ReindexFileProcessor,
    "REINDEX_MANY": ReindexManyProcessor,
    "EMBED_MISSING": EmbedMissingProcessor,
    "DOCS_SCAN": DocsScanProcessor,
    "TAG_RULES_SYNC": TagRulesSyncProcessor,
    "SUMMARIZE_FILES": SummarizeFilesProcessor,
    "SUMMARIZE_SYMBOLS": SummarizeSymbolsProcessor,
    "REGENERATE_SUMMARY": RegenerateSummaryProcessor,
}


def get_processor(job_type: str, config: DaemonConfig, pool: asyncpg.Pool) -> JobProcessor:
    """Get processor instance for job type."""
    processor_class = PROCESSORS.get(job_type)
    if not processor_class:
        raise ValueError(f"Unknown job type: {job_type}")

    return processor_class(config, pool)
