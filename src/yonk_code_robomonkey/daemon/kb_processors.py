"""Job processors for KB (Knowledge Base) document jobs.

Handles document indexing, embedding, summarization, and feature extraction
through the daemon job queue system.
"""

from __future__ import annotations
import asyncio
import asyncpg
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from yonk_code_robomonkey.daemon.kb_queue import KBJob
from yonk_code_robomonkey.config.daemon import DaemonConfig
from yonk_code_robomonkey.config import Settings

logger = logging.getLogger(__name__)

# Model-specific max input lengths (in characters, approximate)
# These are conservative estimates to avoid silent truncation
EMBEDDING_MODEL_LIMITS = {
    # Sentence-transformers models
    "all-MiniLM-L6-v2": 1000,      # 256 tokens max
    "all-mpnet-base-v2": 1500,     # 384 tokens max
    "all-MiniLM-L12-v2": 1000,     # 256 tokens max
    "paraphrase-MiniLM-L6-v2": 512, # 128 tokens max
    "multi-qa-MiniLM-L6-cos-v1": 2000,  # 512 tokens max
    "all-distilroberta-v1": 2000,  # 512 tokens max

    # OpenAI models
    "text-embedding-3-small": 32000,  # 8191 tokens max
    "text-embedding-3-large": 32000,  # 8191 tokens max
    "text-embedding-ada-002": 32000,  # 8191 tokens max

    # Ollama/local models
    "nomic-embed-text": 32000,     # 8192 tokens max
    "snowflake-arctic-embed2": 2000,  # 512 tokens typically
    "mxbai-embed-large": 2000,     # 512 tokens typically

    # Default fallback
    "_default": 2000,
}


def get_model_max_chars(model_name: str) -> int:
    """Get the max input character length for an embedding model."""
    # Try exact match first
    if model_name in EMBEDDING_MODEL_LIMITS:
        return EMBEDDING_MODEL_LIMITS[model_name]

    # Try base name (without :tag)
    base_name = model_name.split(":")[0]
    if base_name in EMBEDDING_MODEL_LIMITS:
        return EMBEDDING_MODEL_LIMITS[base_name]

    # Try case-insensitive match
    model_lower = model_name.lower()
    for key, value in EMBEDDING_MODEL_LIMITS.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return value

    return EMBEDDING_MODEL_LIMITS["_default"]


async def detect_embedding_dimension(
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
) -> int:
    """Probe the embedding service to detect the actual embedding dimension."""
    from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed
    from yonk_code_robomonkey.embeddings.ollama import ollama_embed

    try:
        texts = ["test"]
        if provider == "ollama":
            embeddings = await ollama_embed(texts, model, base_url)
        else:
            embeddings = await vllm_embed(texts, model, base_url, api_key)

        if embeddings and len(embeddings) > 0:
            return len(embeddings[0])
    except Exception as e:
        logger.warning(f"Could not probe embedding dimension: {e}")

    # Return common defaults based on model name
    model_lower = model.lower()
    if "minilm" in model_lower:
        return 384
    if "mpnet" in model_lower:
        return 768
    if "ada" in model_lower or "text-embedding-3" in model_lower:
        return 1536
    if "arctic" in model_lower:
        return 1024

    return 768  # Safe default


async def embed_long_text(
    text: str,
    max_chars: int,
    embed_func,
    overlap_chars: int = 200,
) -> list[float]:
    """Embed a long text by chunking and averaging embeddings.

    For texts longer than max_chars:
    1. Split into overlapping segments
    2. Embed each segment
    3. Mean pool the embeddings

    This preserves information that would be lost by truncation.
    """
    if len(text) <= max_chars:
        embeddings = await embed_func([text])
        return embeddings[0]

    # Split into overlapping segments
    segments = []
    start = 0
    while start < len(text):
        end = start + max_chars
        segment = text[start:end]
        segments.append(segment)

        # Move start with overlap
        start = end - overlap_chars
        if start >= len(text) - overlap_chars:
            break

    if not segments:
        segments = [text[:max_chars]]

    logger.debug(f"Split {len(text)} char text into {len(segments)} segments for embedding")

    # Embed all segments
    all_embeddings = await embed_func(segments)

    # Mean pool
    if len(all_embeddings) == 1:
        return all_embeddings[0]

    dim = len(all_embeddings[0])
    pooled = [0.0] * dim
    for emb in all_embeddings:
        for i in range(dim):
            pooled[i] += emb[i]

    # Normalize
    n = len(all_embeddings)
    pooled = [x / n for x in pooled]

    return pooled


async def ensure_embedding_table_dimension(conn, dimension: int) -> bool:
    """Ensure the embedding tables have the correct dimension.

    Returns True if tables were recreated.
    """
    # Check current dimension using a simpler query
    type_info = await conn.fetchval("""
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'robomonkey_docs'
          AND c.relname = 'doc_chunk_embedding'
          AND a.attname = 'embedding'
    """)

    # Extract dimension from type string like "vector(768)"
    current_dim = None
    if type_info:
        import re
        match = re.search(r'vector\((\d+)\)', type_info)
        if match:
            current_dim = int(match.group(1))

    if current_dim == dimension:
        logger.debug(f"Embedding table dimension already {dimension}")
        return False

    logger.info(f"Adjusting embedding table dimension from {current_dim} to {dimension}")

    # Recreate tables with correct dimension
    await conn.execute(f"""
        DROP TABLE IF EXISTS robomonkey_docs.doc_chunk_embedding CASCADE;
        CREATE TABLE robomonkey_docs.doc_chunk_embedding (
            chunk_id UUID PRIMARY KEY REFERENCES robomonkey_docs.doc_chunk(id) ON DELETE CASCADE,
            embedding vector({dimension}),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        DROP TABLE IF EXISTS robomonkey_docs.doc_summary_embedding CASCADE;
        CREATE TABLE robomonkey_docs.doc_summary_embedding (
            summary_id UUID PRIMARY KEY REFERENCES robomonkey_docs.doc_summary(id) ON DELETE CASCADE,
            embedding vector({dimension}),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    return True


class KBJobProcessor:
    """Base class for KB job processors."""

    def __init__(self, config: DaemonConfig, control_pool: asyncpg.Pool):
        self.config = config
        self.control_pool = control_pool

    async def process(self, job: KBJob) -> None:
        """Process a job. Must be implemented by subclasses."""
        raise NotImplementedError


def _sanitize_text(text: str) -> str:
    """Remove null bytes and other problematic characters for PostgreSQL."""
    if not text:
        return text
    # Remove null bytes which cause "invalid byte sequence for encoding UTF8: 0x00"
    result = text.replace('\x00', '')
    # Keep printable chars (ord >= 32), tab (9), newline (10), carriage return (13)
    result = ''.join(c for c in result if ord(c) >= 32 or ord(c) in (9, 10, 13))
    # Ensure valid UTF-8
    try:
        result = result.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    except Exception:
        pass
    return result


class DocIndexProcessor(KBJobProcessor):
    """Processor for DOC_INDEX jobs - extract and chunk a document."""

    async def process(self, job: KBJob) -> None:
        """Process document indexing job."""
        file_path = job.file_path
        source_name = job.source_name
        payload = job.payload

        logger.info(f"Processing DOC_INDEX for {source_name}: {file_path}")

        if not file_path:
            raise ValueError("DOC_INDEX job missing file_path")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Get settings for database URL
        settings = Settings()

        # Get extractor based on file type
        from yonk_code_robomonkey.knowledge_base.extractors import get_extractor
        try:
            extractor = get_extractor(file_path)
        except ValueError as e:
            raise ValueError(f"Unsupported file type: {e}")

        # Connect to database
        conn = await asyncpg.connect(dsn=settings.database_url)

        try:
            # Get or create source record
            source_id = UUID(job.source_id) if job.source_id else None

            if not source_id:
                # Check if source exists by name
                existing = await conn.fetchrow("""
                    SELECT id, content_hash FROM robomonkey_docs.doc_source
                    WHERE name = $1
                """, source_name)

                content_hash = hashlib.sha256(path.read_bytes()).hexdigest()

                if existing:
                    if existing["content_hash"] == content_hash and not payload.get("force"):
                        logger.info(f"Document {source_name} unchanged, skipping")
                        return
                    # Delete old chunks for reindexing
                    await conn.execute("""
                        DELETE FROM robomonkey_docs.doc_chunk WHERE source_id = $1
                    """, existing["id"])
                    source_id = existing["id"]
                    await conn.execute("""
                        UPDATE robomonkey_docs.doc_source SET
                            status = 'processing',
                            file_path = $2,
                            content_hash = $3,
                            error_message = NULL,
                            stop_requested = FALSE,
                            updated_at = NOW()
                        WHERE id = $1
                    """, source_id, str(path), content_hash)
                else:
                    # Create new source
                    source_id = uuid4()
                    doc_type = payload.get("doc_type", "general")
                    description = payload.get("description")
                    version = payload.get("version")
                    metadata = payload.get("metadata", {})

                    await conn.execute("""
                        INSERT INTO robomonkey_docs.doc_source (
                            id, name, file_path, doc_type, description,
                            content_hash, version, metadata, status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, 'processing')
                    """,
                        source_id, source_name, str(path), doc_type,
                        description, content_hash, version,
                        json.dumps(metadata) if metadata else '{}'
                    )
            else:
                # Update existing source to processing
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET status = 'processing', stop_requested = FALSE, error_message = NULL
                    WHERE id = $1
                """, source_id)

            # Extract content
            logger.info(f"Extracting content from: {file_path}")
            extracted = await asyncio.to_thread(extractor.extract, file_path)

            # Chunk the document (using model-aware chunk sizes)
            from yonk_code_robomonkey.knowledge_base.chunker import DocumentChunker
            from yonk_code_robomonkey.knowledge_base.models import ChunkingConfig

            # Create chunking config based on embedding model
            if self.config.embeddings.enabled:
                chunk_config = ChunkingConfig.for_model(self.config.embeddings.model)
                logger.info(
                    f"Using model-aware chunking for {self.config.embeddings.model}: "
                    f"max={chunk_config.max_chunk_chars}, target={chunk_config.target_chunk_chars}"
                )
            else:
                chunk_config = ChunkingConfig()

            chunker = DocumentChunker(chunk_config)
            chunks = await asyncio.to_thread(chunker.chunk_document, extracted, str(source_id))
            total_chunks = len(chunks)

            # Get resume point if any
            resume_from = payload.get("resume_from_chunk", 0)

            # Update source with stats
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source SET
                    total_pages = $2,
                    total_chunks = CASE WHEN $4 = 0 THEN 0 ELSE total_chunks END,
                    chunks_expected = $3,
                    file_size_bytes = $5,
                    indexed_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
            """, source_id, extracted.total_pages, total_chunks, resume_from, path.stat().st_size)

            # Insert chunks in batches
            batch_size = 100
            chunks_inserted = resume_from
            chunks_to_process = chunks[resume_from:] if resume_from > 0 else chunks

            if resume_from > 0:
                logger.info(f"Resuming from chunk {resume_from}, {len(chunks_to_process)} remaining")

            for i in range(0, len(chunks_to_process), batch_size):
                # Check for stop signal
                stop_requested = await conn.fetchval("""
                    SELECT stop_requested FROM robomonkey_docs.doc_source WHERE id = $1
                """, source_id)

                if stop_requested:
                    logger.info(f"Stop requested for {source_name} at chunk {chunks_inserted}/{total_chunks}")
                    await conn.execute("""
                        UPDATE robomonkey_docs.doc_source
                        SET status = 'stopped', stop_requested = FALSE, updated_at = NOW()
                        WHERE id = $1
                    """, source_id)
                    return

                batch = chunks_to_process[i:i + batch_size]
                batch_success = 0

                for chunk in batch:
                    try:
                        safe_content = _sanitize_text(chunk.content)
                        safe_heading = _sanitize_text(chunk.heading) if chunk.heading else None
                        safe_section_path = [_sanitize_text(s) for s in (chunk.section_path or [])]

                        await conn.execute("""
                            INSERT INTO robomonkey_docs.doc_chunk (
                                id, source_id, content, content_hash,
                                section_path, heading, heading_level, page_number, chunk_index,
                                start_char, end_char, char_count, token_count_approx,
                                chunk_type, language, topics, oracle_constructs, epas_features, metadata
                            ) VALUES (
                                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19::jsonb
                            )
                            ON CONFLICT (id) DO NOTHING
                        """,
                            chunk.id, source_id, safe_content, chunk.content_hash,
                            safe_section_path, safe_heading, chunk.heading_level,
                            chunk.page_number, chunk.chunk_index,
                            chunk.start_char, chunk.end_char, chunk.char_count, chunk.token_count_approx,
                            chunk.chunk_type.value, chunk.language,
                            chunk.topics, chunk.oracle_constructs, chunk.epas_features,
                            json.dumps(chunk.metadata) if chunk.metadata else '{}'
                        )
                        batch_success += 1
                    except Exception as chunk_err:
                        logger.warning(f"Skipping chunk {chunk.chunk_index}: {chunk_err}")

                chunks_inserted += batch_success

                # Update progress
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET total_chunks = $2, updated_at = NOW()
                    WHERE id = $1
                """, source_id, chunks_inserted)

                if chunks_inserted % 500 == 0 or chunks_inserted == total_chunks:
                    logger.info(f"Progress: {chunks_inserted}/{total_chunks} chunks for {source_name}")

            logger.info(f"Indexed {chunks_inserted} chunks from {source_name}")

            # Update status to ready
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'ready', updated_at = NOW()
                WHERE id = $1
            """, source_id)

            # Queue follow-up jobs
            from yonk_code_robomonkey.daemon.kb_queue import KBJobQueue
            kb_queue = KBJobQueue(self.control_pool, self.config.daemon_id)

            # Queue embedding job
            if self.config.embeddings.enabled:
                await kb_queue.enqueue(
                    job_type="DOC_EMBED",
                    source_id=source_id,
                    source_name=source_name,
                    priority=4,
                    dedup_key=f"{source_name}:embed"
                )
                logger.info(f"Queued DOC_EMBED for {source_name}")

            # Queue feature extraction
            await kb_queue.enqueue(
                job_type="DOC_FEATURES",
                source_id=source_id,
                source_name=source_name,
                priority=3,
                dedup_key=f"{source_name}:features"
            )

            # Queue summarization
            await kb_queue.enqueue(
                job_type="DOC_SUMMARIZE",
                source_id=source_id,
                source_name=source_name,
                priority=2,
                dedup_key=f"{source_name}:summarize"
            )

        except Exception as e:
            logger.error(f"Error indexing {source_name}: {e}")
            if 'source_id' in locals() and source_id:
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET status = 'failed', error_message = $2, updated_at = NOW()
                    WHERE id = $1
                """, source_id, str(e))
            raise

        finally:
            await conn.close()


class DocEmbedProcessor(KBJobProcessor):
    """Processor for DOC_EMBED jobs - generate embeddings for chunks."""

    async def process(self, job: KBJob) -> None:
        """Generate embeddings for document chunks."""
        source_id = UUID(job.source_id) if job.source_id else None
        source_name = job.source_name

        logger.info(f"Processing DOC_EMBED for {source_name}")

        if not source_id:
            raise ValueError("DOC_EMBED job missing source_id")

        if not self.config.embeddings.enabled:
            logger.warning("Embeddings disabled, skipping DOC_EMBED")
            return

        settings = Settings()
        conn = await asyncpg.connect(dsn=settings.database_url)

        try:
            # Get chunks without embeddings
            chunks = await conn.fetch("""
                SELECT dc.id, dc.content
                FROM robomonkey_docs.doc_chunk dc
                LEFT JOIN robomonkey_docs.doc_chunk_embedding dce ON dc.id = dce.chunk_id
                WHERE dc.source_id = $1 AND dce.chunk_id IS NULL
            """, source_id)

            if not chunks:
                logger.info(f"No chunks need embeddings for {source_name}")
                return

            logger.info(f"Generating embeddings for {len(chunks)} chunks")

            # Get embedding function
            from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed
            from yonk_code_robomonkey.embeddings.ollama import ollama_embed

            # Determine provider settings
            provider = self.config.embeddings.provider
            model = self.config.embeddings.model
            batch_size = self.config.embeddings.batch_size

            # Get model-specific max input length
            max_chars = get_model_max_chars(model)
            logger.info(f"Using max input length {max_chars} chars for model {model}")

            if provider == "ollama":
                base_url = self.config.embeddings.ollama.base_url
                api_key = ""
            elif provider == "vllm":
                base_url = self.config.embeddings.vllm.base_url
                api_key = self.config.embeddings.vllm.api_key
            else:  # openai
                base_url = self.config.embeddings.openai.base_url
                api_key = self.config.embeddings.openai.api_key

            # Create embed function closure for mean pooling
            async def embed_batch(texts: list[str]) -> list[list[float]]:
                if provider == "ollama":
                    return await ollama_embed(texts, model, base_url)
                else:
                    return await vllm_embed(texts, model, base_url, api_key)

            # Process in batches
            embedded_count = 0
            long_text_count = 0

            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]

                try:
                    # Separate short and long texts for optimal processing
                    short_chunks = []
                    long_chunks = []
                    for chunk in batch:
                        if len(chunk["content"]) <= max_chars:
                            short_chunks.append(chunk)
                        else:
                            long_chunks.append(chunk)
                            long_text_count += 1

                    # Process short texts in batch (more efficient)
                    if short_chunks:
                        texts = [c["content"] for c in short_chunks]
                        embeddings = await embed_batch(texts)

                        for chunk, embedding in zip(short_chunks, embeddings):
                            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                            await conn.execute("""
                                INSERT INTO robomonkey_docs.doc_chunk_embedding (chunk_id, embedding)
                                VALUES ($1, $2::vector)
                                ON CONFLICT (chunk_id) DO UPDATE SET embedding = $2::vector
                            """, chunk["id"], embedding_str)
                            embedded_count += 1

                    # Process long texts individually with mean pooling
                    for chunk in long_chunks:
                        embedding = await embed_long_text(
                            text=chunk["content"],
                            max_chars=max_chars,
                            embed_func=embed_batch,
                            overlap_chars=min(200, max_chars // 5),
                        )
                        embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                        await conn.execute("""
                            INSERT INTO robomonkey_docs.doc_chunk_embedding (chunk_id, embedding)
                            VALUES ($1, $2::vector)
                            ON CONFLICT (chunk_id) DO UPDATE SET embedding = $2::vector
                        """, chunk["id"], embedding_str)
                        embedded_count += 1

                except Exception as e:
                    logger.error(f"Error generating embeddings for batch: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            if long_text_count > 0:
                logger.info(f"Used mean pooling for {long_text_count} long chunks")

            logger.info(f"Finished generating embeddings for {source_name}")

        finally:
            await conn.close()


class DocFeaturesProcessor(KBJobProcessor):
    """Processor for DOC_FEATURES jobs - extract features from document."""

    async def process(self, job: KBJob) -> None:
        """Extract features from document chunks."""
        source_id = UUID(job.source_id) if job.source_id else None
        source_name = job.source_name

        logger.info(f"Processing DOC_FEATURES for {source_name}")

        if not source_id:
            raise ValueError("DOC_FEATURES job missing source_id")

        settings = Settings()
        conn = await asyncpg.connect(dsn=settings.database_url)

        try:
            # Get chunks for feature extraction
            chunks = await conn.fetch("""
                SELECT id, content, page_number
                FROM robomonkey_docs.doc_chunk
                WHERE source_id = $1
                ORDER BY chunk_index
            """, source_id)

            if not chunks:
                logger.info(f"No chunks found for feature extraction: {source_name}")
                return

            # Convert to dicts
            chunk_dicts = [
                {
                    "id": chunk["id"],
                    "content": chunk["content"],
                    "page_number": chunk["page_number"],
                }
                for chunk in chunks
            ]

            # Extract features
            from yonk_code_robomonkey.knowledge_base.feature_extractor import FeatureExtractor
            extractor = FeatureExtractor()
            features = extractor.extract_features(chunk_dicts)

            logger.info(f"Extracted {len(features)} features from {len(chunks)} chunks")

            # Delete existing features
            await conn.execute("""
                DELETE FROM robomonkey_docs.doc_feature WHERE source_id = $1
            """, source_id)

            # Insert features
            for feature in features:
                chunk_ids = [str(cid) for cid in feature.chunk_ids] if feature.chunk_ids else []

                await conn.execute("""
                    INSERT INTO robomonkey_docs.doc_feature (
                        source_id, name, feature_type, category, description,
                        signature, epas_support, postgres_equivalent, example_usage,
                        chunk_ids, mention_count, first_seen_page, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
                    ON CONFLICT (source_id, name, feature_type) DO UPDATE SET
                        mention_count = EXCLUDED.mention_count,
                        chunk_ids = EXCLUDED.chunk_ids
                """,
                    source_id, feature.name, feature.feature_type, feature.category,
                    feature.description, feature.signature, feature.epas_support,
                    feature.postgres_equivalent, feature.example_usage,
                    chunk_ids, feature.mention_count, feature.first_seen_page, '{}'
                )

            logger.info(f"Stored {len(features)} features for {source_name}")

        finally:
            await conn.close()


class DocSummarizeProcessor(KBJobProcessor):
    """Processor for DOC_SUMMARIZE jobs - generate document summary."""

    async def process(self, job: KBJob) -> None:
        """Generate summary for document."""
        source_id = UUID(job.source_id) if job.source_id else None
        source_name = job.source_name

        logger.info(f"Processing DOC_SUMMARIZE for {source_name}")

        if not source_id:
            raise ValueError("DOC_SUMMARIZE job missing source_id")

        settings = Settings()
        conn = await asyncpg.connect(dsn=settings.database_url)

        try:
            # Get source info
            source = await conn.fetchrow("""
                SELECT name, doc_type, description, total_pages
                FROM robomonkey_docs.doc_source
                WHERE id = $1
            """, source_id)

            if not source:
                raise ValueError(f"Source not found: {source_id}")

            # Get chunks for summarization
            chunks = await conn.fetch("""
                SELECT id, content, page_number
                FROM robomonkey_docs.doc_chunk
                WHERE source_id = $1
                ORDER BY chunk_index
            """, source_id)

            if not chunks:
                logger.info(f"No chunks found for summarization: {source_name}")
                return

            # Convert to dicts
            chunk_dicts = [{"content": chunk["content"]} for chunk in chunks]

            # Get features for summary
            from yonk_code_robomonkey.knowledge_base.feature_extractor import FeatureExtractor
            extractor = FeatureExtractor()
            features = extractor.extract_features([
                {"id": c["id"], "content": c["content"], "page_number": c["page_number"]}
                for c in chunks
            ])

            # Generate summary
            from yonk_code_robomonkey.knowledge_base.summary_generator import generate_simple_summary
            title = source["description"] or source_name
            summary = generate_simple_summary(
                title, source["doc_type"], chunk_dicts, features
            )

            # Delete existing summary
            await conn.execute("""
                DELETE FROM robomonkey_docs.doc_summary WHERE source_id = $1
            """, source_id)

            # Insert summary
            await conn.execute("""
                INSERT INTO robomonkey_docs.doc_summary (
                    source_id, summary, key_topics, target_audience, document_purpose, generated_by
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
                source_id, summary.summary, summary.key_topics,
                summary.target_audience, summary.document_purpose, summary.generated_by
            )

            logger.info(f"Generated summary for {source_name}")

        finally:
            await conn.close()


# Registry of KB processors
KB_PROCESSORS: dict[str, type[KBJobProcessor]] = {
    "DOC_INDEX": DocIndexProcessor,
    "DOC_EMBED": DocEmbedProcessor,
    "DOC_FEATURES": DocFeaturesProcessor,
    "DOC_SUMMARIZE": DocSummarizeProcessor,
}


def get_kb_processor(job_type: str, config: DaemonConfig, pool: asyncpg.Pool) -> KBJobProcessor:
    """Get processor instance for KB job type."""
    processor_class = KB_PROCESSORS.get(job_type)
    if not processor_class:
        raise ValueError(f"Unknown KB job type: {job_type}")

    return processor_class(config, pool)
