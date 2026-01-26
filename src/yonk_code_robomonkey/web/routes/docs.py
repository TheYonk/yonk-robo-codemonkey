"""
API routes for document indexing and search.

Provides REST endpoints for:
- Indexing PDFs and other documents
- Searching documentation
- Retrieving context for RAG
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from yonk_code_robomonkey.config import Settings
from yonk_code_robomonkey.daemon.kb_queue import KBJobQueue
from ...knowledge_base.chunker import DocumentChunker
from ...knowledge_base.extractors import get_extractor
from ...knowledge_base.models import (
    ChunkingConfig,
    DocAskRequest,
    DocContextParams,
    DocIndexRequest,
    DocIndexResult,
    DocListItem,
    DocSearchParams,
    DocType,
    SourceStatus,
)
from ...knowledge_base.search import doc_get_context, doc_search
from ...knowledge_base.ask_docs import ask_docs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


# ============ Pydantic Models for API ============

class DocSearchRequest(BaseModel):
    """Search request body.

    Supports hybrid search (vector + FTS) with optional context expansion
    and LLM-powered summarization.
    """
    query: str = Field(..., description="Search query")
    doc_types: Optional[list[str]] = Field(default=None, description="Filter by doc types (e.g., ['epas_docs', 'migration_toolkit'])")
    doc_names: Optional[list[str]] = Field(default=None, description="Filter by specific document names")
    topics: Optional[list[str]] = Field(default=None, description="Filter by topics")
    oracle_constructs: Optional[list[str]] = Field(default=None, description="Filter by Oracle constructs (e.g., ['ROWNUM', 'CONNECT BY'])")
    epas_features: Optional[list[str]] = Field(default=None, description="Filter by EPAS features (e.g., ['dblink_ora', 'SPL'])")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    search_mode: str = Field(default="hybrid", description="Search mode: 'hybrid' (vector+FTS), 'semantic' (vector only), or 'fts' (text only)")
    context_chunks: int = Field(default=0, ge=0, le=3, description="Number of chunks before/after each result to include (0-3). 0 returns just the matched chunk.")
    summarize: bool = Field(default=False, description="If true, use LLM to summarize each result with context to answer the query")
    use_llm_keywords: bool = Field(default=False, description="If true, use LLM to extract better search keywords (improves FTS accuracy for complex questions)")


class DocContextRequest(BaseModel):
    """Context retrieval request."""
    query: str = Field(..., description="Query to find relevant context")
    context_type: Optional[str] = Field(default=None, description="oracle_construct, epas_feature, migration_issue")
    max_tokens: int = Field(default=2000, ge=100, le=10000)
    doc_types: Optional[list[str]] = Field(default=None)
    doc_names: Optional[list[str]] = Field(default=None)
    include_citations: bool = Field(default=True)


class DocUploadRequest(BaseModel):
    """Document upload metadata."""
    doc_type: str = Field(default="general")
    version: Optional[str] = None
    description: Optional[str] = None


# ============ Helper Functions ============


async def get_embedding_func():
    """Get the embedding function for vector search."""
    settings = Settings()

    # Check if embeddings are configured
    if not settings.embeddings_provider:
        return None

    async def embed(text: str) -> list[float]:
        from ...embeddings.ollama import ollama_embed
        from ...embeddings.vllm_openai import vllm_embed

        if settings.embeddings_provider == "ollama":
            embeddings = await ollama_embed(
                texts=[text],
                model=settings.embeddings_model,
                base_url=settings.embeddings_base_url,
            )
        else:  # vllm or openai
            embeddings = await vllm_embed(
                texts=[text],
                model=settings.embeddings_model,
                base_url=settings.embeddings_base_url,
                api_key=getattr(settings, 'vllm_api_key', None) or '',
            )
        return embeddings[0] if embeddings else []

    return embed


async def get_kb_queue() -> KBJobQueue:
    """Get a KB job queue instance for queuing document processing jobs."""
    settings = Settings()
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=2,
        command_timeout=30.0,
    )
    return KBJobQueue(pool=pool, worker_id="web-api")


# ============ API Endpoints ============

@router.get("/")
async def list_documents() -> dict[str, Any]:
    """List all indexed documents with stats."""
    import time
    start_time = time.time()
    settings = Settings()

    try:
        conn = await asyncpg.connect(dsn=settings.database_url, timeout=5)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return {"documents": [], "total": 0, "error": f"Database connection failed: {str(e)}"}

    logger.debug(f"DB connect took {time.time() - start_time:.2f}s")

    try:
        # Check if schema exists
        schema_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'robomonkey_docs'
            )
        """)

        if not schema_exists:
            return {
                "documents": [],
                "total": 0,
                "message": "Document schema not initialized. Run 'robomonkey db init-docs' first."
            }

        # Simple query first - get basic columns that should always exist
        rows = await conn.fetch("""
            SELECT
                id, name, doc_type, total_chunks, total_pages,
                status, version, indexed_at, file_size_bytes,
                description, file_path, error_message
            FROM robomonkey_docs.doc_source
            ORDER BY indexed_at DESC NULLS LAST
        """)

        # Check if new columns exist
        has_new_cols = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'robomonkey_docs'
                AND table_name = 'doc_source'
                AND column_name = 'chunks_expected'
            )
        """)

        # If new columns exist, get those values separately
        new_col_data = {}
        if has_new_cols:
            extra_rows = await conn.fetch("""
                SELECT id, chunks_expected, stop_requested
                FROM robomonkey_docs.doc_source
            """)
            for r in extra_rows:
                new_col_data[str(r["id"])] = {
                    "chunks_expected": r["chunks_expected"],
                    "stop_requested": r["stop_requested"] or False,
                }

        documents = []
        for row in rows:
            doc_id = str(row["id"])
            doc = {
                "id": doc_id,
                "name": row["name"],
                "doc_type": row["doc_type"],
                "title": row["description"],
                "chunks_count": row["total_chunks"] or 0,
                "total_pages": row["total_pages"],
                "status": row["status"],
                "version": row["version"],
                "indexed_at": row["indexed_at"].isoformat() if row["indexed_at"] else None,
                "source_path": row["file_path"],
                "error_message": row["error_message"],
                "chunks_expected": new_col_data.get(doc_id, {}).get("chunks_expected"),
                "stop_requested": new_col_data.get(doc_id, {}).get("stop_requested", False),
            }
            documents.append(doc)

        elapsed = time.time() - start_time
        logger.info(f"list_documents completed in {elapsed:.2f}s, {len(documents)} docs")

        return {
            "documents": documents,
            "total": len(documents),
        }

    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        import traceback
        traceback.print_exc()
        return {"documents": [], "total": 0, "error": str(e)}

    finally:
        await conn.close()


@router.get("/{doc_name}")
async def get_document(doc_name: str) -> dict[str, Any]:
    """Get details of a specific document including its chunks."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        row = await conn.fetchrow("""
            SELECT
                id, name, file_path, doc_type, description,
                total_pages, total_chunks, file_size_bytes,
                content_hash, version, metadata, status,
                error_message, indexed_at, created_at, updated_at
            FROM robomonkey_docs.doc_source
            WHERE name = $1
        """, doc_name)

        if not row:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        # Get all chunks for this document
        chunks = await conn.fetch("""
            SELECT
                id, content, section_path, heading, heading_level,
                page_number, chunk_index, char_count, token_count_approx,
                topics, oracle_constructs, epas_features
            FROM robomonkey_docs.doc_chunk
            WHERE source_id = $1
            ORDER BY chunk_index
        """, row["id"])

        return {
            "document": {
                "id": str(row["id"]),
                "name": row["name"],
                "file_path": row["file_path"],
                "doc_type": row["doc_type"],
                "title": row["description"],
                "total_pages": row["total_pages"],
                "chunks_count": row["total_chunks"] or 0,
                "status": row["status"],
            },
            "chunks": [
                {
                    "id": str(chunk["id"]),
                    "content": chunk["content"],
                    "section_path": chunk["section_path"] or [],
                    "heading": chunk["heading"],
                    "heading_level": chunk["heading_level"],
                    "page_number": chunk["page_number"],
                    "chunk_index": chunk["chunk_index"],
                    "char_count": chunk["char_count"],
                    "token_count_approx": chunk["token_count_approx"],
                    "topics": chunk["topics"] or [],
                    "oracle_constructs": chunk["oracle_constructs"] or [],
                    "epas_features": chunk["epas_features"] or [],
                }
                for chunk in chunks
            ],
        }

    finally:
        await conn.close()


@router.delete("/{doc_name}")
async def delete_document(doc_name: str) -> dict[str, str]:
    """Delete a document and its chunks."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get source ID
        source_id = await conn.fetchval("""
            SELECT id FROM robomonkey_docs.doc_source WHERE name = $1
        """, doc_name)

        if not source_id:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        # Delete (cascades to chunks and embeddings)
        await conn.execute("""
            DELETE FROM robomonkey_docs.doc_source WHERE id = $1
        """, source_id)

        return {"status": "deleted", "document": doc_name}

    finally:
        await conn.close()


@router.post("/index")
async def index_document(
    request: DocIndexRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Index a document or directory of documents.

    Creates source records immediately and queues processing via the daemon job queue.
    Poll /api/docs/{name} to check processing status.
    """
    settings = Settings()

    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {request.path}")

    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Ensure schema exists
        await _ensure_docs_schema(conn)

        # Collect files to process
        files_to_index = []
        if path.is_dir():
            if request.recursive:
                # Recursive directory traversal
                for file_path in path.rglob("*"):
                    if file_path.is_file() and file_path.suffix.lower() in [".pdf", ".md", ".html", ".txt", ".markdown"]:
                        files_to_index.append(file_path)
            else:
                # Single level
                for file_path in path.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in [".pdf", ".md", ".html", ".txt", ".markdown"]:
                        files_to_index.append(file_path)
        else:
            files_to_index.append(path)

        if not files_to_index:
            raise HTTPException(status_code=400, detail="No indexable files found (.pdf, .md, .html, .txt)")

        # Create source records for all files (status='pending')
        queued_sources = []
        jobs_queued = 0

        for file_path in files_to_index:
            source_id = uuid4()
            file_name = f"{request.name}_{file_path.stem}" if request.name else file_path.stem

            # Check for existing
            existing = await conn.fetchrow("""
                SELECT id, content_hash FROM robomonkey_docs.doc_source WHERE name = $1
            """, file_name)

            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

            if existing:
                if existing["content_hash"] == content_hash:
                    queued_sources.append({
                        "source_id": str(existing["id"]),
                        "name": file_name,
                        "file": str(file_path),
                        "status": "unchanged",
                    })
                    continue
                else:
                    # Will reindex - delete old chunks
                    await conn.execute("""
                        DELETE FROM robomonkey_docs.doc_chunk WHERE source_id = $1
                    """, existing["id"])
                    source_id = existing["id"]
                    # Update existing record to pending
                    await conn.execute("""
                        UPDATE robomonkey_docs.doc_source SET
                            status = 'pending',
                            file_path = $2,
                            content_hash = $3,
                            error_message = NULL,
                            updated_at = NOW()
                        WHERE id = $1
                    """, source_id, str(file_path), content_hash)
            else:
                # Create new source record as pending
                await conn.execute("""
                    INSERT INTO robomonkey_docs.doc_source (
                        id, name, file_path, doc_type, description,
                        content_hash, version, metadata, status
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, 'pending')
                """,
                    source_id, file_name, str(file_path), request.doc_type.value if request.doc_type else 'general',
                    request.description, content_hash, request.version,
                    json.dumps(request.metadata) if request.metadata else '{}',
                )

            queued_sources.append({
                "source_id": str(source_id),
                "name": file_name,
                "file": str(file_path),
                "status": "pending",
            })

            # Queue job via daemon job queue
            job_id = await conn.fetchval("""
                SELECT robomonkey_docs.enqueue_kb_job(
                    $1, $2, $3, 'DOC_INDEX', $4::jsonb, 7, $5
                )
            """,
                source_id, file_name, str(file_path),
                json.dumps({
                    "doc_type": request.doc_type.value if request.doc_type else 'general',
                    "description": request.description,
                    "version": request.version,
                    "metadata": request.metadata or {},
                }),
                f"{file_name}:index"
            )

            if job_id:
                jobs_queued += 1
                logger.info(f"Queued DOC_INDEX job {job_id} for {file_name}")

        return {
            "message": f"Queued {jobs_queued} files for processing via daemon",
            "total_files": len(files_to_index),
            "sources": queued_sources,
        }

    finally:
        await conn.close()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = "general",
    version: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Upload and index a document file."""
    settings = Settings()

    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".md", ".html", ".txt", ".markdown"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .pdf, .md, .html, .txt"
        )

    # Save to temp location
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await _index_single_file(
            file_path=tmp_path,
            doc_type=DocType(doc_type),
            name=Path(file.filename).stem,
            version=version,
            description=description,
            metadata={"original_filename": file.filename},
            settings=settings,
        )
        return result
    finally:
        # Cleanup temp file
        os.unlink(tmp_path)


@router.post("/reindex/{doc_name}")
async def reindex_document(
    doc_name: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
) -> dict[str, Any]:
    """Reindex an existing document (queues via daemon job queue)."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get existing source
        source = await conn.fetchrow("""
            SELECT id, file_path, doc_type, version, description, content_hash
            FROM robomonkey_docs.doc_source
            WHERE name = $1
        """, doc_name)

        if not source:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        if not source["file_path"]:
            raise HTTPException(status_code=400, detail="Document has no file path (was uploaded)")

        # Check if file exists
        file_path = Path(source["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=400, detail=f"Original file no longer exists: {source['file_path']}")

        current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if current_hash == source["content_hash"] and not force:
            return {
                "status": "unchanged",
                "message": "Document has not changed. Use force=true to reindex anyway."
            }

        # Delete existing chunks, features, summary
        await conn.execute("DELETE FROM robomonkey_docs.doc_chunk WHERE source_id = $1", source["id"])
        try:
            await conn.execute("DELETE FROM robomonkey_docs.doc_feature WHERE source_id = $1", source["id"])
            await conn.execute("DELETE FROM robomonkey_docs.doc_summary WHERE source_id = $1", source["id"])
        except Exception:
            pass  # Tables may not exist yet

        # Update status to pending and reset counts
        await conn.execute("""
            UPDATE robomonkey_docs.doc_source
            SET status = 'pending', error_message = NULL, content_hash = $2,
                total_chunks = 0, total_pages = NULL, updated_at = NOW()
            WHERE id = $1
        """, source["id"], current_hash)

        # Queue job via daemon job queue
        job_id = await conn.fetchval("""
            SELECT robomonkey_docs.enqueue_kb_job(
                $1, $2, $3, 'DOC_INDEX', $4::jsonb, 7, $5
            )
        """,
            source["id"], doc_name, str(file_path),
            json.dumps({
                "doc_type": source["doc_type"],
                "force": force,
            }),
            f"{doc_name}:reindex"
        )

        logger.info(f"Queued DOC_INDEX job {job_id} for reindexing {doc_name}")

        return {
            "status": "pending",
            "message": f"Queued {doc_name} for reprocessing via daemon",
            "source_id": str(source["id"]),
            "job_id": str(job_id) if job_id else None,
        }

    finally:
        await conn.close()


@router.post("/reindex-all")
async def reindex_all_documents(
    force: bool = True,
) -> dict[str, Any]:
    """Reindex ALL documents - re-chunk with whitespace normalization and re-embed.

    This will:
    1. Delete all existing chunks for each document
    2. Re-process documents with current chunking code (includes whitespace normalization)
    3. Queue embedding jobs for all new chunks
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all documents with file paths
        sources = await conn.fetch("""
            SELECT id, name, file_path, doc_type, version, description
            FROM robomonkey_docs.doc_source
            WHERE file_path IS NOT NULL
            ORDER BY name
        """)

        if not sources:
            return {
                "status": "no_documents",
                "message": "No documents with file paths found to reindex"
            }

        queued = []
        skipped = []
        errors = []

        for source in sources:
            try:
                file_path = Path(source["file_path"])
                if not file_path.exists():
                    skipped.append({"name": source["name"], "reason": "file not found"})
                    continue

                current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

                # Delete existing chunks
                await conn.execute("DELETE FROM robomonkey_docs.doc_chunk WHERE source_id = $1", source["id"])
                try:
                    await conn.execute("DELETE FROM robomonkey_docs.doc_feature WHERE source_id = $1", source["id"])
                    await conn.execute("DELETE FROM robomonkey_docs.doc_summary WHERE source_id = $1", source["id"])
                except Exception:
                    pass

                # Update status to pending
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET status = 'pending', error_message = NULL, content_hash = $2,
                        total_chunks = 0, total_pages = NULL, updated_at = NOW()
                    WHERE id = $1
                """, source["id"], current_hash)

                # Queue job
                job_id = await conn.fetchval("""
                    SELECT robomonkey_docs.enqueue_kb_job(
                        $1, $2, $3, 'DOC_INDEX', $4::jsonb, 5, $5
                    )
                """,
                    source["id"], source["name"], str(file_path),
                    json.dumps({
                        "doc_type": source["doc_type"],
                        "force": True,
                    }),
                    f"{source['name']}:reindex-all"
                )

                queued.append({"name": source["name"], "job_id": str(job_id) if job_id else None})

            except Exception as e:
                errors.append({"name": source["name"], "error": str(e)})

        return {
            "status": "queued",
            "message": f"Queued {len(queued)} documents for reprocessing",
            "queued": queued,
            "skipped": skipped,
            "errors": errors,
        }

    finally:
        await conn.close()


@router.post("/search")
async def search_documents(request: DocSearchRequest) -> dict[str, Any]:
    """Search document chunks with optional context expansion and summarization.

    Performs hybrid search combining vector similarity (60%) and full-text search (40%).

    **Search Modes:**
    - `hybrid` (default): Combines semantic and text search for best results
    - `semantic`: Vector similarity only (requires embeddings configured)
    - `fts`: Full-text search only (keyword matching)

    **Context Expansion:**
    Set `context_chunks` (1-3) to include surrounding chunks with each result.
    This provides more context around the matched text.

    **Summarization:**
    Set `summarize=true` to get LLM-generated summaries for each result that
    directly answer your query. Automatically includes +-1 chunk for context.
    Requires LLM configured in daemon.
    """
    settings = Settings()

    try:
        # Convert doc_types strings to enum
        doc_types = None
        if request.doc_types:
            doc_types = [DocType(dt) for dt in request.doc_types]

        params = DocSearchParams(
            query=request.query,
            doc_types=doc_types,
            doc_names=request.doc_names,
            topics=request.topics,
            oracle_constructs=request.oracle_constructs,
            epas_features=request.epas_features,
            top_k=request.top_k,
            search_mode=request.search_mode,
        )

        embedding_func = await get_embedding_func()

        # Check if semantic search requested but no embedding function
        if request.search_mode == "semantic" and embedding_func is None:
            raise HTTPException(
                status_code=400,
                detail="Semantic search requires embeddings to be configured. Check EMBEDDINGS_PROVIDER in .env"
            )

        result = await doc_search(
            params, settings.database_url, embedding_func,
            use_llm_keywords=request.use_llm_keywords
        )

        # Build response chunks with optional context expansion
        chunks_response = []

        if request.context_chunks > 0 or request.summarize:
            # Need to fetch context for each chunk
            conn = await asyncpg.connect(dsn=settings.database_url)
            try:
                for chunk in result.chunks:
                    # Use at least 1 context chunk for summarization
                    ctx_count = max(request.context_chunks, 1 if request.summarize else 0)

                    # Get chunk's source_id and chunk_index
                    chunk_info = await conn.fetchrow("""
                        SELECT source_id, chunk_index
                        FROM robomonkey_docs.doc_chunk
                        WHERE id = $1
                    """, chunk.chunk_id)

                    if not chunk_info:
                        chunks_response.append(chunk.model_dump())
                        continue

                    # Get surrounding chunks
                    context_rows = await conn.fetch("""
                        SELECT id, content, chunk_index, heading, page_number
                        FROM robomonkey_docs.doc_chunk
                        WHERE source_id = $1
                        AND chunk_index BETWEEN $2 AND $3
                        ORDER BY chunk_index
                    """, chunk_info["source_id"],
                        chunk_info["chunk_index"] - ctx_count,
                        chunk_info["chunk_index"] + ctx_count)

                    # Build context chunks list
                    context_list = []
                    full_context_text = []
                    for row in context_rows:
                        is_target = str(row["id"]) == str(chunk.chunk_id)
                        context_list.append({
                            "chunk_id": str(row["id"]),
                            "content": row["content"],
                            "chunk_index": row["chunk_index"],
                            "heading": row["heading"],
                            "page_number": row["page_number"],
                            "is_target": is_target,
                        })
                        full_context_text.append(row["content"])

                    chunk_data = chunk.model_dump()
                    chunk_data["context_chunks"] = context_list
                    chunk_data["context_text"] = "\n\n---\n\n".join(full_context_text)

                    # Summarize if requested
                    if request.summarize:
                        summary = await _summarize_for_query(
                            request.query,
                            chunk_data["context_text"],
                            chunk.source_document,
                            settings
                        )
                        chunk_data["summary"] = summary

                    chunks_response.append(chunk_data)
            finally:
                await conn.close()
        else:
            chunks_response = [chunk.model_dump() for chunk in result.chunks]

        return {
            "query": result.query,
            "total_found": result.total_found,
            "search_mode": result.search_mode,
            "execution_time_ms": result.execution_time_ms,
            "context_chunks_requested": request.context_chunks,
            "summarize_requested": request.summarize,
            "chunks": chunks_response,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/ask")
async def ask_documents(request: DocAskRequest) -> dict[str, Any]:
    """Ask a question and get an LLM-generated answer from documentation.

    This is a RAG Q&A feature that:
    1. Searches for relevant documentation chunks
    2. Uses an LLM to synthesize a cohesive answer with inline citations
    3. Returns the answer along with source information

    Unlike search (which returns ranked chunks) or search+summarize (which
    summarizes each chunk individually), this produces ONE cohesive answer
    synthesized across multiple relevant chunks.

    **Example Questions:**
    - "How does EPAS handle Oracle's XMLParse function?"
    - "What is the syntax for CONNECT BY in EPAS?"
    - "How do I migrate Oracle packages to PostgreSQL?"

    **Response includes:**
    - `answer`: The synthesized answer with inline citations [1], [2]
    - `confidence`: "high", "medium", "low", or "no_answer"
    - `sources`: List of sources used with document, section, page info
    """
    settings = Settings()

    try:
        embedding_func = await get_embedding_func()

        result = await ask_docs(request, settings.database_url, embedding_func)

        return {
            "question": result.question,
            "answer": result.answer,
            "confidence": result.confidence,
            "sources": [
                {
                    "index": s.index,
                    "document": s.document,
                    "section": s.section,
                    "page": s.page,
                    "chunk_id": str(s.chunk_id),
                    "relevance_score": s.relevance_score,
                    "preview": s.preview,
                }
                for s in result.sources
            ],
            "chunks_used": result.chunks_used,
            "execution_time_ms": result.execution_time_ms,
            "model_used": result.model_used,
        }

    except Exception as e:
        logger.error(f"Ask docs error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Ask failed: {str(e)}")


async def _summarize_for_query(query: str, context: str, source: str, settings) -> str:
    """Use LLM to summarize context in response to query."""
    try:
        # Try to use daemon's LLM config
        import yaml
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "robomonkey-daemon.yaml"
        if not config_path.exists():
            return "(Summarization unavailable - daemon config not found)"

        with open(config_path) as f:
            config = yaml.safe_load(f)

        llm_config = config.get("llm", {}).get("small", {})
        if not llm_config:
            return "(Summarization unavailable - LLM not configured)"

        provider = llm_config.get("provider", "ollama")
        model = llm_config.get("model", "llama3.2")
        base_url = llm_config.get("base_url", "http://localhost:11434")

        prompt = f"""Based on the following documentation excerpt from "{source}", answer this question concisely:

Question: {query}

Documentation:
{context[:4000]}

Provide a brief, direct answer (2-3 sentences) based only on the documentation above. If the documentation doesn't answer the question, say so."""

        if provider == "ollama":
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False}
                )
                if resp.status_code == 200:
                    return resp.json().get("response", "(No response)")
                return f"(LLM error: {resp.status_code})"
        else:  # openai-compatible
            import httpx
            api_key = llm_config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                return f"(LLM error: {resp.status_code})"

    except Exception as e:
        logger.warning(f"Summarization failed: {e}")
        return f"(Summarization error: {str(e)})"


@router.get("/chunk/{chunk_id}/context")
async def get_chunk_context(chunk_id: str, context_chunks: int = 2) -> dict[str, Any]:
    """Get a chunk with surrounding context chunks.

    Args:
        chunk_id: UUID of the chunk
        context_chunks: Number of chunks before and after to include (default 2)
    """
    settings = Settings()

    try:
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            # Get the target chunk and its position
            target = await conn.fetchrow("""
                SELECT
                    dc.id, dc.content, dc.source_id, dc.chunk_index,
                    dc.heading, dc.section_path, dc.page_number,
                    ds.name as source_name, ds.doc_type
                FROM robomonkey_docs.doc_chunk dc
                JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
                WHERE dc.id = $1
            """, chunk_id)

            if not target:
                raise HTTPException(status_code=404, detail="Chunk not found")

            # Get surrounding chunks from the same document
            context = await conn.fetch("""
                SELECT
                    dc.id, dc.content, dc.chunk_index,
                    dc.heading, dc.section_path, dc.page_number
                FROM robomonkey_docs.doc_chunk dc
                WHERE dc.source_id = $1
                AND dc.chunk_index BETWEEN $2 AND $3
                ORDER BY dc.chunk_index
            """, target["source_id"],
                target["chunk_index"] - context_chunks,
                target["chunk_index"] + context_chunks)

            chunks = []
            for row in context:
                chunks.append({
                    "id": str(row["id"]),
                    "content": row["content"],
                    "chunk_index": row["chunk_index"],
                    "heading": row["heading"],
                    "section_path": row["section_path"] or [],
                    "page_number": row["page_number"],
                    "is_target": str(row["id"]) == chunk_id,
                })

            return {
                "target_chunk_id": chunk_id,
                "source_document": target["source_name"],
                "doc_type": target["doc_type"],
                "chunks": chunks,
                "total_context_chunks": len(chunks),
            }

        finally:
            await conn.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chunk context: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get context: {str(e)}")


@router.get("/{doc_name}/features")
async def get_document_features(doc_name: str) -> dict[str, Any]:
    """Get extracted features for a document."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get source ID
        source = await conn.fetchrow("""
            SELECT id, name FROM robomonkey_docs.doc_source WHERE name = $1
        """, doc_name)

        if not source:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        # Get features
        features = await conn.fetch("""
            SELECT name, feature_type, category, description, signature,
                   epas_support, postgres_equivalent, mention_count, first_seen_page
            FROM robomonkey_docs.doc_feature
            WHERE source_id = $1
            ORDER BY mention_count DESC, name
        """, source["id"])

        # Get descriptions from feature definitions if not in DB
        from ...knowledge_base.feature_extractor import (
            ORACLE_PACKAGES, ORACLE_SYNTAX, ORACLE_PLSQL,
            ORACLE_DATATYPES, EPAS_FEATURES
        )

        def get_feature_description(name: str, feature_type: str, db_desc: str) -> str:
            """Get description from definitions or DB."""
            if db_desc:
                return db_desc
            # Look up in definitions
            name_upper = name.upper()
            if feature_type == "package" and name_upper in ORACLE_PACKAGES:
                return ORACLE_PACKAGES[name_upper].get("description", "")
            if name_upper in ORACLE_SYNTAX:
                return ORACLE_SYNTAX[name_upper].get("description", "")
            if name_upper in ORACLE_PLSQL:
                return ORACLE_PLSQL[name_upper].get("description", "")
            if name_upper in ORACLE_DATATYPES:
                return ORACLE_DATATYPES[name_upper].get("description", "")
            if name in EPAS_FEATURES:
                return EPAS_FEATURES[name].get("description", "")
            return ""

        return {
            "document": doc_name,
            "total_features": len(features),
            "features": [
                {
                    "name": f["name"],
                    "type": f["feature_type"],
                    "category": f["category"],
                    "description": get_feature_description(f["name"], f["feature_type"], f["description"]),
                    "signature": f["signature"],
                    "epas_support": f["epas_support"],
                    "postgres_equivalent": f["postgres_equivalent"],
                    "mentions": f["mention_count"],
                    "first_page": f["first_seen_page"],
                }
                for f in features
            ],
        }

    finally:
        await conn.close()


@router.get("/{doc_name}/summary")
async def get_document_summary(doc_name: str) -> dict[str, Any]:
    """Get summary for a document."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get source ID
        source = await conn.fetchrow("""
            SELECT id, name FROM robomonkey_docs.doc_source WHERE name = $1
        """, doc_name)

        if not source:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        # Get summary
        summary = await conn.fetchrow("""
            SELECT summary, key_topics, target_audience, document_purpose, generated_by, generated_at
            FROM robomonkey_docs.doc_summary
            WHERE source_id = $1
        """, source["id"])

        if not summary:
            return {"document": doc_name, "summary": None}

        return {
            "document": doc_name,
            "summary": summary["summary"],
            "key_topics": summary["key_topics"] or [],
            "target_audience": summary["target_audience"],
            "document_purpose": summary["document_purpose"],
            "generated_by": summary["generated_by"],
            "generated_at": summary["generated_at"].isoformat() if summary["generated_at"] else None,
        }

    finally:
        await conn.close()


@router.get("/stats/embeddings")
async def get_embedding_stats() -> dict[str, Any]:
    """Get embedding statistics for knowledge base documents."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if schema exists
        schema_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'robomonkey_docs'
            )
        """)

        if not schema_exists:
            return {
                "total_chunks": 0,
                "embedded_chunks": 0,
                "pending_chunks": 0,
                "embed_percent": 0,
                "index_status": "no_schema",
                "rebuild_recommended": False,
            }

        # Get chunk counts
        stats = await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM robomonkey_docs.doc_chunk) as total_chunks,
                (SELECT COUNT(*) FROM robomonkey_docs.doc_chunk_embedding) as embedded_chunks
        """)

        total_chunks = stats["total_chunks"] or 0
        embedded_chunks = stats["embedded_chunks"] or 0
        pending_chunks = total_chunks - embedded_chunks
        embed_percent = round((embedded_chunks / total_chunks * 100) if total_chunks > 0 else 0, 1)

        # Get index info - look for any non-primary key index on the embedding table
        # First, get all indexes on the table for debugging
        all_indexes = await conn.fetch("""
            SELECT schemaname, indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'doc_chunk_embedding'
        """)

        logger.info(f"Found {len(all_indexes)} indexes on doc_chunk_embedding: {[(r['schemaname'], r['indexname']) for r in all_indexes]}")

        # Look for vector indexes (by indexdef content, not name)
        index_info = None
        for idx in all_indexes:
            indexdef_lower = idx["indexdef"].lower()
            if any(op in indexdef_lower for op in ['vector_cosine_ops', 'vector_l2_ops', 'vector_ip_ops', 'hnsw', 'ivfflat']):
                # Get size for this index
                try:
                    size = await conn.fetchval("""
                        SELECT pg_size_pretty(pg_relation_size($1::regclass))
                    """, f"{idx['schemaname']}.{idx['indexname']}")
                    index_info = {
                        "indexname": idx["indexname"],
                        "indexdef": idx["indexdef"],
                        "size": size or "unknown",
                        "schemaname": idx["schemaname"],
                    }
                    logger.info(f"Found vector index: {index_info}")
                    break
                except Exception as e:
                    logger.warning(f"Could not get size for index {idx['indexname']}: {e}")
                    index_info = {
                        "indexname": idx["indexname"],
                        "indexdef": idx["indexdef"],
                        "size": "unknown",
                        "schemaname": idx["schemaname"],
                    }
                    break

        index_type = "none"
        index_size = "0 bytes"
        if index_info:
            index_size = index_info["size"]
            if "hnsw" in index_info["indexdef"].lower():
                index_type = "hnsw"
            elif "ivfflat" in index_info["indexdef"].lower():
                index_type = "ivfflat"
            else:
                index_type = "btree"  # Fallback for other index types

        # Check for last rebuild time (using index creation as proxy)
        last_rebuild = await conn.fetchval("""
            SELECT pg_stat_user_indexes.last_idx_scan
            FROM pg_stat_user_indexes
            JOIN pg_indexes ON pg_indexes.indexname = pg_stat_user_indexes.indexrelname
            WHERE pg_indexes.schemaname = 'robomonkey_docs'
            AND pg_indexes.indexname LIKE '%embedding%'
            LIMIT 1
        """)

        # Get recently added embeddings count (since last potential rebuild)
        # We'll use a heuristic: if >20% of embeddings are "new" (no index usage), recommend rebuild
        rebuild_recommended = False
        rebuild_reason = None

        if embedded_chunks > 100:
            # For IVFFlat, recommend rebuild if data grew significantly
            # Heuristic: if pending > 20% of embedded, suggest rebuild
            if pending_chunks > 0 and (pending_chunks / max(embedded_chunks, 1)) > 0.2:
                rebuild_recommended = True
                rebuild_reason = f"{pending_chunks} chunks pending embedding ({round(pending_chunks/total_chunks*100)}% of total)"
            elif index_type == "none" and embedded_chunks > 50:
                rebuild_recommended = True
                rebuild_reason = "No vector index found"

        return {
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "pending_chunks": pending_chunks,
            "embed_percent": embed_percent,
            "index_type": index_type,
            "index_size": index_size,
            "rebuild_recommended": rebuild_recommended,
            "rebuild_reason": rebuild_reason,
        }

    except Exception as e:
        logger.error(f"Error getting embedding stats: {e}")
        return {
            "total_chunks": 0,
            "embedded_chunks": 0,
            "pending_chunks": 0,
            "embed_percent": 0,
            "index_status": "error",
            "error": str(e),
            "rebuild_recommended": False,
        }

    finally:
        await conn.close()


@router.post("/rebuild-indexes")
async def rebuild_indexes() -> dict[str, Any]:
    """Rebuild vector indexes for document embeddings."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        result = await rebuild_doc_vector_indexes(conn)
        return result
    finally:
        await conn.close()


@router.get("/stats/jobs")
async def get_job_stats() -> dict[str, Any]:
    """Get KB job queue statistics."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if KB job queue table exists
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_docs'
                AND table_name = 'kb_job_queue'
            )
        """)

        if not table_exists:
            return {
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "by_type": {},
                "recent_jobs": [],
                "message": "KB job queue not initialized. Start the daemon to initialize."
            }

        # Get overall counts
        counts = await conn.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                COUNT(*) FILTER (WHERE status = 'DONE') as done,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed
            FROM robomonkey_docs.kb_job_queue
        """)

        # Get counts by job type
        by_type = await conn.fetch("""
            SELECT job_type, status, COUNT(*) as count
            FROM robomonkey_docs.kb_job_queue
            GROUP BY job_type, status
            ORDER BY job_type, status
        """)

        type_stats = {}
        for row in by_type:
            job_type = row["job_type"]
            if job_type not in type_stats:
                type_stats[job_type] = {}
            type_stats[job_type][row["status"].lower()] = row["count"]

        # Get recent jobs
        recent = await conn.fetch("""
            SELECT id, source_name, job_type, status, attempts, created_at, completed_at, error
            FROM robomonkey_docs.kb_job_queue
            ORDER BY created_at DESC
            LIMIT 20
        """)

        recent_jobs = [
            {
                "id": str(row["id"]),
                "source_name": row["source_name"],
                "job_type": row["job_type"],
                "status": row["status"],
                "attempts": row["attempts"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "error": row["error"],
            }
            for row in recent
        ]

        return {
            "total": counts["total"],
            "pending": counts["pending"],
            "claimed": counts["claimed"],
            "done": counts["done"],
            "failed": counts["failed"],
            "by_type": type_stats,
            "recent_jobs": recent_jobs,
        }

    except Exception as e:
        logger.error(f"Error getting job stats: {e}")
        return {
            "total": 0,
            "pending": 0,
            "claimed": 0,
            "done": 0,
            "failed": 0,
            "by_type": {},
            "recent_jobs": [],
            "error": str(e),
        }

    finally:
        await conn.close()


@router.post("/{doc_name}/stop")
async def stop_processing(doc_name: str) -> dict[str, Any]:
    """Stop processing a document. Processing will pause at the next chunk batch."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if stop_requested column exists
        has_stop_col = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'robomonkey_docs'
                AND table_name = 'doc_source'
                AND column_name = 'stop_requested'
            )
        """)

        # Get source
        source = await conn.fetchrow("""
            SELECT id, status FROM robomonkey_docs.doc_source WHERE name = $1
        """, doc_name)

        if not source:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        if source["status"] not in ("processing", "pending"):
            return {
                "status": "not_processing",
                "message": f"Document is not currently processing (status: {source['status']})"
            }

        # Set stop flag (or just update status if column doesn't exist)
        if has_stop_col:
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET stop_requested = TRUE, updated_at = NOW()
                WHERE id = $1
            """, source["id"])
        else:
            # Fallback: directly set to stopped if we can't use the flag
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'stopped', updated_at = NOW()
                WHERE id = $1
            """, source["id"])

        return {
            "status": "stop_requested",
            "message": "Stop signal sent. Processing will pause at the next batch.",
            "document": doc_name,
        }

    finally:
        await conn.close()


@router.post("/{doc_name}/resume")
async def resume_processing(
    doc_name: str,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Resume processing a stopped document from where it left off (via daemon job queue)."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if new columns exist
        has_new_cols = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'robomonkey_docs'
                AND table_name = 'doc_source'
                AND column_name = 'chunks_expected'
            )
        """)

        # Get source with appropriate columns
        if has_new_cols:
            source = await conn.fetchrow("""
                SELECT id, file_path, doc_type, status, total_chunks, chunks_expected
                FROM robomonkey_docs.doc_source WHERE name = $1
            """, doc_name)
        else:
            source = await conn.fetchrow("""
                SELECT id, file_path, doc_type, status, total_chunks
                FROM robomonkey_docs.doc_source WHERE name = $1
            """, doc_name)

        if not source:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        if source["status"] not in ("stopped", "failed"):
            return {
                "status": "cannot_resume",
                "message": f"Document cannot be resumed (status: {source['status']}). Only stopped or failed documents can be resumed."
            }

        if not source["file_path"]:
            raise HTTPException(status_code=400, detail="Document has no file path (was uploaded)")

        # Check if file exists
        file_path = Path(source["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=400, detail=f"Original file no longer exists: {source['file_path']}")

        # Get the resume point (last chunk index)
        last_chunk = await conn.fetchval("""
            SELECT MAX(chunk_index) FROM robomonkey_docs.doc_chunk WHERE source_id = $1
        """, source["id"])
        resume_from = (last_chunk or -1) + 1

        # Update status to pending (daemon will set to processing when claimed)
        if has_new_cols:
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'pending', stop_requested = FALSE, error_message = NULL, updated_at = NOW()
                WHERE id = $1
            """, source["id"])
        else:
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'pending', error_message = NULL, updated_at = NOW()
                WHERE id = $1
            """, source["id"])

        # Queue job via daemon job queue with resume point
        job_id = await conn.fetchval("""
            SELECT robomonkey_docs.enqueue_kb_job(
                $1, $2, $3, 'DOC_INDEX', $4::jsonb, 8, $5
            )
        """,
            source["id"], doc_name, str(file_path),
            json.dumps({
                "doc_type": source["doc_type"],
                "resume_from_chunk": resume_from,
            }),
            f"{doc_name}:resume"
        )

        logger.info(f"Queued DOC_INDEX job {job_id} for resuming {doc_name} from chunk {resume_from}")

        return {
            "status": "resuming",
            "message": f"Queued resume from chunk {resume_from} via daemon",
            "document": doc_name,
            "chunks_processed": source["total_chunks"] or 0,
            "chunks_expected": source.get("chunks_expected") if has_new_cols else None,
            "resume_from_chunk": resume_from,
            "job_id": str(job_id) if job_id else None,
        }

    finally:
        await conn.close()


@router.post("/context")
async def get_context(request: DocContextRequest) -> dict[str, Any]:
    """Get formatted context for RAG.

    Returns a formatted string ready to inject into LLM prompts,
    with optional citations.
    """
    settings = Settings()

    doc_types = None
    if request.doc_types:
        doc_types = [DocType(dt) for dt in request.doc_types]

    params = DocContextParams(
        query=request.query,
        context_type=request.context_type,
        max_tokens=request.max_tokens,
        doc_types=doc_types,
        doc_names=request.doc_names,
        include_citations=request.include_citations,
    )

    embedding_func = await get_embedding_func()
    result = await doc_get_context(params, settings.database_url, embedding_func)

    return {
        "context": result.context,
        "chunks_used": result.chunks_used,
        "total_tokens_approx": result.total_tokens_approx,
        "sources": result.sources,
    }


# ============ Internal Functions ============

def _sanitize_text(text: str) -> str:
    """Remove null bytes and other problematic characters for PostgreSQL."""
    if not text:
        return text
    # Remove null bytes which cause "invalid byte sequence for encoding UTF8: 0x00"
    result = text.replace('\x00', '')
    # Also remove other problematic control characters (except newline, tab, carriage return)
    # Keep: printable chars (ord >= 32), tab (9), newline (10), carriage return (13)
    result = ''.join(c for c in result if ord(c) >= 32 or ord(c) in (9, 10, 13))
    # Ensure valid UTF-8 by encoding and decoding
    try:
        result = result.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    except Exception:
        pass  # If this fails, return what we have
    return result


async def _ensure_docs_schema(conn: asyncpg.Connection) -> None:
    """Ensure the docs schema and tables exist."""
    await conn.execute("CREATE SCHEMA IF NOT EXISTS robomonkey_docs")

    table_exists = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'robomonkey_docs' AND table_name = 'doc_source'
        )
    """)

    if not table_exists:
        init_script = Path(__file__).resolve().parents[4] / "scripts" / "init_docs_schema.sql"
        if init_script.exists():
            await conn.execute(init_script.read_text())


async def _process_file_background(
    source_id: UUID,
    file_path: str,
    doc_type: DocType,
    settings,
    resume_from_chunk: int = 0,
) -> None:
    """Process a single file in the background.

    Args:
        source_id: The UUID of the doc_source record
        file_path: Path to the file to process
        doc_type: Document type
        settings: Application settings
        resume_from_chunk: Chunk index to resume from (0 = start fresh)
    """
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        path = Path(file_path)
        if not path.exists():
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'failed', error_message = $2, updated_at = NOW()
                WHERE id = $1
            """, source_id, f"File not found: {file_path}")
            return

        # Update status to processing and clear stop flag
        await conn.execute("""
            UPDATE robomonkey_docs.doc_source
            SET status = 'processing', stop_requested = FALSE, updated_at = NOW()
            WHERE id = $1
        """, source_id)

        # Get extractor
        try:
            extractor = get_extractor(file_path)
        except ValueError as e:
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET status = 'failed', error_message = $2, updated_at = NOW()
                WHERE id = $1
            """, source_id, str(e))
            return

        # Extract content - run in thread pool to avoid blocking event loop
        logger.info(f"Extracting content from: {file_path}")
        import asyncio
        extracted = await asyncio.to_thread(extractor.extract, file_path)

        # Chunk the document - also run in thread pool (can be CPU intensive)
        chunker = DocumentChunker(ChunkingConfig())
        chunks = await asyncio.to_thread(chunker.chunk_document, extracted, str(source_id))
        total_chunks = len(chunks)

        # Update source with stats including expected chunks
        if resume_from_chunk == 0:
            # Fresh start - reset everything
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source SET
                    total_pages = $2,
                    total_chunks = 0,
                    chunks_expected = $3,
                    file_size_bytes = $4,
                    indexed_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
            """,
                source_id, extracted.total_pages, total_chunks, path.stat().st_size,
            )
        else:
            # Resuming - just update expected if not set
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source SET
                    chunks_expected = COALESCE(chunks_expected, $2),
                    updated_at = NOW()
                WHERE id = $1
            """, source_id, total_chunks)

        # Insert chunks in batches with progress updates
        batch_size = 100
        chunks_inserted = resume_from_chunk  # Start count from resume point

        # Skip already processed chunks if resuming
        chunks_to_process = chunks[resume_from_chunk:] if resume_from_chunk > 0 else chunks

        if resume_from_chunk > 0:
            logger.info(f"Resuming from chunk {resume_from_chunk}, {len(chunks_to_process)} chunks remaining")

        for i in range(0, len(chunks_to_process), batch_size):
            # Check for stop signal at the start of each batch
            stop_requested = await conn.fetchval("""
                SELECT stop_requested FROM robomonkey_docs.doc_source WHERE id = $1
            """, source_id)

            if stop_requested:
                logger.info(f"Stop requested for {file_path} at chunk {chunks_inserted}/{total_chunks}")
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET status = 'stopped', stop_requested = FALSE, updated_at = NOW()
                    WHERE id = $1
                """, source_id)
                return  # Exit without error

            batch = chunks_to_process[i:i + batch_size]
            batch_success = 0
            batch_errors = []

            for chunk in batch:
                try:
                    # Sanitize content to remove null bytes
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
                        json.dumps(chunk.metadata) if chunk.metadata else '{}',
                    )
                    batch_success += 1
                except Exception as chunk_err:
                    # Log and skip problematic chunks
                    batch_errors.append(f"chunk {chunk.chunk_index}: {str(chunk_err)[:100]}")
                    logger.warning(f"Skipping chunk {chunk.chunk_index} due to error: {chunk_err}")

            if batch_errors:
                logger.warning(f"Batch had {len(batch_errors)} errors: {batch_errors[:3]}")  # Log first 3

            chunks_inserted += batch_success

            # Update progress every batch
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source
                SET total_chunks = $2, updated_at = NOW()
                WHERE id = $1
            """, source_id, chunks_inserted)

            if chunks_inserted % 500 == 0 or chunks_inserted == total_chunks:
                logger.info(f"Progress: {chunks_inserted}/{total_chunks} chunks inserted for {file_path}")

        logger.info(f"Successfully indexed {total_chunks} chunks from {file_path}")

        # Extract features from chunks (non-fatal if fails)
        try:
            await _extract_and_store_features(conn, source_id, chunks)
        except Exception as e:
            logger.warning(f"Feature extraction failed (non-fatal): {e}")

        # Generate document summary (non-fatal if fails)
        try:
            await _generate_and_store_summary(
                conn, source_id, extracted.title or path.stem,
                doc_type.value if doc_type else "general",
                extracted.total_pages, chunks, settings
            )
        except Exception as e:
            logger.warning(f"Summary generation failed (non-fatal): {e}")

        # Update status to ready
        await conn.execute("""
            UPDATE robomonkey_docs.doc_source
            SET status = 'ready', updated_at = NOW()
            WHERE id = $1
        """, source_id)

        # Generate embeddings if configured
        if settings.embeddings_provider:
            await _generate_chunk_embeddings(conn, source_id, settings)

    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        await conn.execute("""
            UPDATE robomonkey_docs.doc_source
            SET status = 'failed', error_message = $2, updated_at = NOW()
            WHERE id = $1
        """, source_id, str(e))

    finally:
        await conn.close()


async def _index_single_file(
    file_path: str,
    doc_type: DocType,
    name: Optional[str],
    version: Optional[str],
    description: Optional[str],
    metadata: dict[str, Any],
    settings,
    existing_source_id: Optional[UUID] = None,
) -> dict[str, Any]:
    """Index a single document file."""

    path = Path(file_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {file_path}")

    # Use filename as name if not provided
    doc_name = name or path.stem

    # Get extractor
    try:
        extractor = get_extractor(file_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Ensure schema exists
        await conn.execute("""
            CREATE SCHEMA IF NOT EXISTS robomonkey_docs
        """)

        # Check if tables exist, if not run init script
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_docs' AND table_name = 'doc_source'
            )
        """)

        if not table_exists:
            # Run init script
            init_script = Path(__file__).resolve().parents[4] / "scripts" / "init_docs_schema.sql"
            if init_script.exists():
                await conn.execute(init_script.read_text())

        # Calculate content hash
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        # Check for existing document with same name
        if not existing_source_id:
            existing = await conn.fetchrow("""
                SELECT id, content_hash FROM robomonkey_docs.doc_source WHERE name = $1
            """, doc_name)

            if existing:
                if existing["content_hash"] == content_hash:
                    return {
                        "source_id": str(existing["id"]),
                        "name": doc_name,
                        "status": "unchanged",
                        "message": "Document already indexed and unchanged",
                    }
                else:
                    # Delete old chunks
                    await conn.execute("""
                        DELETE FROM robomonkey_docs.doc_chunk WHERE source_id = $1
                    """, existing["id"])
                    existing_source_id = existing["id"]

        # Extract content
        logger.info(f"Extracting content from: {file_path}")
        extracted = extractor.extract(file_path)

        # Chunk the document
        chunker = DocumentChunker(ChunkingConfig())
        source_id = existing_source_id or uuid4()
        chunks = chunker.chunk_document(extracted, str(source_id))

        # Start transaction
        async with conn.transaction():
            # Insert or update source
            if existing_source_id:
                await conn.execute("""
                    UPDATE robomonkey_docs.doc_source SET
                        file_path = $2,
                        doc_type = $3,
                        description = $4,
                        total_pages = $5,
                        total_chunks = $6,
                        file_size_bytes = $7,
                        content_hash = $8,
                        version = $9,
                        metadata = $10::jsonb,
                        status = 'processing',
                        indexed_at = NOW()
                    WHERE id = $1
                """,
                    source_id, str(path), doc_type.value, description,
                    extracted.total_pages, len(chunks), path.stat().st_size,
                    content_hash, version, json.dumps(metadata) if metadata else '{}',
                )
            else:
                await conn.execute("""
                    INSERT INTO robomonkey_docs.doc_source (
                        id, name, file_path, doc_type, description,
                        total_pages, total_chunks, file_size_bytes,
                        content_hash, version, metadata, status, indexed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, 'processing', NOW())
                """,
                    source_id, doc_name, str(path), doc_type.value, description,
                    extracted.total_pages, len(chunks), path.stat().st_size,
                    content_hash, version, json.dumps(metadata) if metadata else '{}',
                )

            # Insert chunks
            for chunk in chunks:
                # Sanitize content to remove null bytes
                safe_content = _sanitize_text(chunk.content)
                safe_heading = _sanitize_text(chunk.heading) if chunk.heading else None

                await conn.execute("""
                    INSERT INTO robomonkey_docs.doc_chunk (
                        id, source_id, content, content_hash,
                        section_path, heading, heading_level, page_number, chunk_index,
                        start_char, end_char, char_count, token_count_approx,
                        chunk_type, language, topics, oracle_constructs, epas_features, metadata
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19::jsonb
                    )
                """,
                    chunk.id, source_id, safe_content, chunk.content_hash,
                    chunk.section_path, safe_heading, chunk.heading_level,
                    chunk.page_number, chunk.chunk_index,
                    chunk.start_char, chunk.end_char, chunk.char_count, chunk.token_count_approx,
                    chunk.chunk_type.value, chunk.language,
                    chunk.topics, chunk.oracle_constructs, chunk.epas_features,
                    json.dumps(chunk.metadata) if chunk.metadata else '{}',
                )

            # Update source status
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source SET status = 'ready' WHERE id = $1
            """, source_id)

        # Generate embeddings if configured
        if settings.embeddings_provider:
            await _generate_chunk_embeddings(conn, source_id, settings)

        return {
            "source_id": str(source_id),
            "name": doc_name,
            "chunks_created": len(chunks),
            "total_pages": extracted.total_pages,
            "status": "ready",
            "message": f"Successfully indexed {len(chunks)} chunks",
        }

    except Exception as e:
        logger.error(f"Error indexing document: {e}")
        # Update source with error
        if existing_source_id or 'source_id' in locals():
            sid = existing_source_id or source_id
            await conn.execute("""
                UPDATE robomonkey_docs.doc_source SET status = 'failed', error_message = $2 WHERE id = $1
            """, sid, str(e))
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        await conn.close()


async def _generate_chunk_embeddings(
    conn: asyncpg.Connection,
    source_id: UUID,
    settings,
) -> None:
    """Generate embeddings for all chunks of a document."""
    from ...embeddings.vllm_openai import vllm_embed
    from ...embeddings.ollama import ollama_embed

    # Check if embeddings are configured
    if not settings.embeddings_provider:
        logger.info("Embeddings provider not configured, skipping embedding generation")
        return

    # Get chunks without embeddings
    chunks = await conn.fetch("""
        SELECT dc.id, dc.content
        FROM robomonkey_docs.doc_chunk dc
        LEFT JOIN robomonkey_docs.doc_chunk_embedding dce ON dc.id = dce.chunk_id
        WHERE dc.source_id = $1 AND dce.chunk_id IS NULL
    """, source_id)

    if not chunks:
        return

    logger.info(f"Generating embeddings for {len(chunks)} chunks")

    # Process in batches
    batch_size = getattr(settings, 'embedding_batch_size', 10) or 10
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c["content"][:8000] for c in batch]  # Truncate to max length

        try:
            # Call appropriate embedding function based on provider
            if settings.embeddings_provider == "ollama":
                embeddings = await ollama_embed(
                    texts=texts,
                    model=settings.embeddings_model,
                    base_url=settings.embeddings_base_url,
                )
            else:  # vllm or openai
                embeddings = await vllm_embed(
                    texts=texts,
                    model=settings.embeddings_model,
                    base_url=settings.embeddings_base_url,
                    api_key=getattr(settings, 'vllm_api_key', '') or '',
                )

            # Insert embeddings (convert list to string format for pgvector)
            for chunk, embedding in zip(batch, embeddings):
                embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                await conn.execute("""
                    INSERT INTO robomonkey_docs.doc_chunk_embedding (chunk_id, embedding)
                    VALUES ($1, $2::vector)
                    ON CONFLICT (chunk_id) DO UPDATE SET embedding = $2::vector
                """, chunk["id"], embedding_str)

        except Exception as e:
            logger.error(f"Error generating embeddings for batch: {e}")
            continue

    logger.info(f"Finished generating embeddings for source {source_id}")


async def _extract_and_store_features(
    conn: asyncpg.Connection,
    source_id: UUID,
    chunks: list,  # List of DocChunk objects
) -> None:
    """Extract features from chunks and store in database."""
    from ...knowledge_base.feature_extractor import FeatureExtractor

    # Convert DocChunk objects to dicts for the extractor
    chunk_dicts = [
        {
            "id": chunk.id,
            "content": chunk.content,
            "page_number": chunk.page_number,
        }
        for chunk in chunks
    ]

    extractor = FeatureExtractor()
    features = extractor.extract_features(chunk_dicts)

    logger.info(f"Extracted {len(features)} features from {len(chunks)} chunks")

    # Delete existing features for this source
    await conn.execute("""
        DELETE FROM robomonkey_docs.doc_feature WHERE source_id = $1
    """, source_id)

    # Insert features
    for feature in features:
        # Convert chunk_ids to list of strings for database
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
            chunk_ids, feature.mention_count, feature.first_seen_page, '{}',
        )

    logger.info(f"Stored {len(features)} features for source {source_id}")


async def _generate_and_store_summary(
    conn: asyncpg.Connection,
    source_id: UUID,
    title: str,
    doc_type: str,
    total_pages: int,
    chunks: list,
    settings,
) -> None:
    """Generate and store document summary."""
    from ...knowledge_base.feature_extractor import FeatureExtractor
    from ...knowledge_base.summary_generator import generate_simple_summary

    # Convert chunks to dicts
    chunk_dicts = [{"content": chunk.content} for chunk in chunks]

    # Get features for keyword-based summary
    extractor = FeatureExtractor()
    features = extractor.extract_features([
        {"id": chunk.id, "content": chunk.content, "page_number": chunk.page_number}
        for chunk in chunks
    ])

    # Generate simple summary (keyword-based, no LLM required)
    summary = generate_simple_summary(title, doc_type, chunk_dicts, features)

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
        summary.target_audience, summary.document_purpose, summary.generated_by,
    )

    logger.info(f"Generated summary for source {source_id}")


async def rebuild_doc_vector_indexes(conn: asyncpg.Connection) -> dict:
    """Rebuild vector indexes for document chunk embeddings."""
    results = {}

    try:
        # Get count of embeddings
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM robomonkey_docs.doc_chunk_embedding
        """)

        if count == 0:
            return {"status": "skipped", "message": "No embeddings to index"}

        # Clean up any legacy index in public schema (from previous bug)
        logger.info("Cleaning up any legacy index in public schema...")
        await conn.execute("DROP INDEX IF EXISTS public.idx_doc_chunk_embedding_vec")

        # Set search_path to ensure index is created in correct schema
        logger.info("Setting search_path to robomonkey_docs...")
        await conn.execute("SET search_path TO robomonkey_docs, public")

        # Drop existing index first
        logger.info("Dropping existing index if any...")
        await conn.execute("DROP INDEX IF EXISTS idx_doc_chunk_embedding_vec")

        # Determine optimal index type based on count
        if count < 10000:
            # IVFFlat for smaller datasets
            lists = max(10, count // 100)
            logger.info(f"Creating IVFFlat index with {lists} lists for {count} embeddings...")
            await conn.execute(f"""
                CREATE INDEX idx_doc_chunk_embedding_vec ON doc_chunk_embedding
                USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})
            """)
            results["index_type"] = "ivfflat"
            results["lists"] = lists
        else:
            # HNSW for larger datasets
            logger.info(f"Creating HNSW index for {count} embeddings...")
            await conn.execute("""
                CREATE INDEX idx_doc_chunk_embedding_vec ON doc_chunk_embedding
                USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
            """)
            results["index_type"] = "hnsw"

        # Verify the index was created
        verify = await conn.fetchrow("""
            SELECT schemaname, indexname, indexdef
            FROM pg_indexes
            WHERE indexname = 'idx_doc_chunk_embedding_vec'
        """)
        if verify:
            logger.info(f"Index created successfully in schema: {verify['schemaname']}")
            results["schema"] = verify["schemaname"]
        else:
            logger.warning("Index creation completed but index not found in pg_indexes!")

        results["status"] = "success"
        results["embeddings_indexed"] = count
        logger.info(f"Rebuilt doc vector index: {results}")

    except Exception as e:
        logger.error(f"Error rebuilding vector index: {e}")
        results["status"] = "error"
        results["error"] = str(e)

    return results
