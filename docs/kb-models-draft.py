"""
Knowledge Base Models Draft
===========================
This file contains the planned Pydantic models for the knowledge base feature.
To be placed in src/yonk_code_robomonkey/knowledge_base/models.py when implementing.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# ENUMS
# ============================================================================

class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"
    CRAWL = "crawl"


class SourceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChunkType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"


class MimeType(str, Enum):
    PDF = "application/pdf"
    MARKDOWN = "text/markdown"
    HTML = "text/html"
    PLAIN = "text/plain"


# ============================================================================
# SOURCE MODELS
# ============================================================================

class KBSourceCreate(BaseModel):
    """Request model for creating a KB source."""
    source_type: SourceType
    source_url: Optional[str] = None
    original_filename: Optional[str] = None
    title: Optional[str] = None
    refresh_interval_hours: Optional[int] = None


class KBSource(BaseModel):
    """Database model for kb_source table."""
    id: UUID
    repo_id: UUID
    source_type: SourceType
    source_url: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    content_hash: Optional[str] = None
    title: Optional[str] = None
    status: SourceStatus = SourceStatus.PENDING
    error_message: Optional[str] = None
    chunks_count: int = 0
    file_size_bytes: Optional[int] = None
    last_fetched_at: Optional[datetime] = None
    refresh_interval_hours: Optional[int] = None
    etag: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KBSourceSummary(BaseModel):
    """Lightweight source info for listings."""
    id: UUID
    source_type: SourceType
    title: Optional[str]
    original_filename: Optional[str]
    status: SourceStatus
    chunks_count: int
    created_at: datetime


# ============================================================================
# CHUNK MODELS
# ============================================================================

class KBChunk(BaseModel):
    """Database model for kb_chunk table."""
    id: UUID
    repo_id: UUID
    source_id: UUID
    chunk_index: int
    start_char: int
    end_char: int
    content: str
    content_hash: str
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    parent_chunk_id: Optional[UUID] = None
    breadcrumb: list[str] = Field(default_factory=list)
    chunk_type: ChunkType
    language: Optional[str] = None
    extracted_topics: list[str] = Field(default_factory=list)
    extracted_entities: list[dict] = Field(default_factory=list)
    token_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KBChunkWithContext(BaseModel):
    """Chunk with additional context for display."""
    chunk: KBChunk
    source_title: Optional[str]
    source_url: Optional[str]
    parent_heading: Optional[str]
    sibling_headings: list[str] = Field(default_factory=list)


# ============================================================================
# SEARCH MODELS
# ============================================================================

class KBSearchRequest(BaseModel):
    """Request model for KB search."""
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    fts_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    chunk_types: Optional[list[ChunkType]] = None
    source_ids: Optional[list[UUID]] = None
    require_text_match: bool = False


class KBSearchResult(BaseModel):
    """Single search result with scoring."""
    chunk_id: UUID
    content: str
    heading: Optional[str]
    breadcrumb: list[str]
    source_title: Optional[str]
    source_url: Optional[str]
    chunk_type: ChunkType
    vec_score: float
    fts_score: float
    combined_score: float
    # Explainability
    matched_terms: list[str] = Field(default_factory=list)


class KBSearchResponse(BaseModel):
    """Response model for KB search."""
    query: str
    results: list[KBSearchResult]
    total_chunks_searched: int
    search_time_ms: float


# ============================================================================
# CROSS-REFERENCE MODELS
# ============================================================================

class ReferenceType(str, Enum):
    INTERNAL_LINK = "internal_link"
    EXTERNAL_LINK = "external_link"
    SEE_ALSO = "see_also"
    CITATION = "citation"


class KBCrossReference(BaseModel):
    """Database model for kb_cross_reference table."""
    id: UUID
    source_chunk_id: UUID
    target_chunk_id: Optional[UUID] = None
    target_url: Optional[str] = None
    reference_text: Optional[str] = None
    reference_type: ReferenceType
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# KNOWLEDGE BASE MODELS
# ============================================================================

class KnowledgeBaseCreate(BaseModel):
    """Request model for creating a knowledge base."""
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: Optional[str] = None


class KnowledgeBase(BaseModel):
    """Knowledge base info (from repo_registry with repo_type='knowledge_base')."""
    id: UUID
    name: str
    description: Optional[str]
    sources_count: int = 0
    chunks_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseStats(BaseModel):
    """Statistics for a knowledge base."""
    id: UUID
    name: str
    sources_count: int
    sources_by_status: dict[str, int]
    sources_by_type: dict[str, int]
    chunks_count: int
    chunks_by_type: dict[str, int]
    embeddings_count: int
    total_tokens: int
    storage_bytes: int


# ============================================================================
# CHUNKING CONFIG
# ============================================================================

class ChunkingConfig(BaseModel):
    """Configuration for the chunking algorithm."""
    max_chunk_chars: int = Field(default=2000, ge=100, le=10000)
    min_chunk_chars: int = Field(default=100, ge=10, le=1000)
    overlap_chars: int = Field(default=100, ge=0, le=500)
    preserve_code_blocks: bool = True
    split_on_sentences: bool = True
    include_heading_in_chunks: bool = True


# ============================================================================
# EXTRACTION RESULTS
# ============================================================================

class ExtractedSection(BaseModel):
    """Result from document extraction."""
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    content: str
    chunk_type: ChunkType
    start_char: int
    end_char: int
    language: Optional[str] = None  # For code blocks
    children: list["ExtractedSection"] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Full extraction result from a document."""
    title: Optional[str] = None
    mime_type: MimeType
    sections: list[ExtractedSection]
    links: list[dict] = Field(default_factory=list)  # {"text": str, "url": str}
    metadata: dict = Field(default_factory=dict)


# ============================================================================
# WEB SCRAPING
# ============================================================================

class ScrapeRequest(BaseModel):
    """Request model for web scraping."""
    urls: list[str]
    depth: int = Field(default=0, ge=0, le=3)
    follow_patterns: list[str] = Field(default_factory=list)  # Regex patterns for links to follow
    exclude_patterns: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=100, ge=1, le=1000)


class ScrapeResult(BaseModel):
    """Result from scraping a single URL."""
    url: str
    status: str  # 'success', 'failed', 'skipped'
    source_id: Optional[UUID] = None
    error_message: Optional[str] = None
    redirected_to: Optional[str] = None


# ============================================================================
# API RESPONSES
# ============================================================================

class KBCreateResponse(BaseModel):
    """Response when creating a knowledge base."""
    id: UUID
    name: str
    message: str = "Knowledge base created successfully"


class UploadResponse(BaseModel):
    """Response when uploading files."""
    sources: list[KBSourceSummary]
    message: str


class ScrapeResponse(BaseModel):
    """Response when scraping URLs."""
    results: list[ScrapeResult]
    queued_count: int
    failed_count: int
    message: str
