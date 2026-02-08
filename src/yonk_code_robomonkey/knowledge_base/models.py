"""
Pydantic models for the Knowledge Base / Document indexing system.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocType(str, Enum):
    """Document types for categorization."""
    EPAS_DOCS = "epas_docs"
    MIGRATION_TOOLKIT = "migration_toolkit"
    MIGRATION_ISSUES = "migration_issues"
    GENERAL = "general"
    ORACLE_DOCS = "oracle_docs"
    POSTGRES_DOCS = "postgres_docs"


class ChunkType(str, Enum):
    """Types of content chunks."""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"


class SourceStatus(str, Enum):
    """Status of document source processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


# ============ Database Models ============

class DocSource(BaseModel):
    """Represents a source document (PDF, markdown, etc.)."""
    id: UUID
    name: str
    file_path: Optional[str] = None
    doc_type: DocType = DocType.GENERAL
    description: Optional[str] = None
    total_pages: Optional[int] = None
    total_chunks: int = 0
    file_size_bytes: Optional[int] = None
    content_hash: Optional[str] = None
    version: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: SourceStatus = SourceStatus.PENDING
    error_message: Optional[str] = None
    indexed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    repo_name: Optional[str] = None  # repo_registry name, None = global doc


class DocChunk(BaseModel):
    """Represents a chunk of document content."""
    id: UUID
    source_id: UUID
    content: str
    content_hash: Optional[str] = None

    # Structure metadata
    section_path: list[str] = Field(default_factory=list)
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    page_number: Optional[int] = None
    chunk_index: int

    # Chunk boundaries
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    char_count: Optional[int] = None
    token_count_approx: Optional[int] = None

    # Content classification
    chunk_type: ChunkType = ChunkType.PARAGRAPH
    language: Optional[str] = None

    # Topics and tags
    topics: list[str] = Field(default_factory=list)
    oracle_constructs: list[str] = Field(default_factory=list)
    epas_features: list[str] = Field(default_factory=list)

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============ API Request/Response Models ============

class DocIndexRequest(BaseModel):
    """Request to index a document or directory."""
    path: str = Field(..., description="File path or directory to index")
    doc_type: DocType = Field(default=DocType.GENERAL, description="Document type for categorization")
    name: Optional[str] = Field(default=None, description="Custom name (defaults to filename)")
    version: Optional[str] = Field(default=None, description="Version string (e.g., '18' for EPAS v18)")
    description: Optional[str] = Field(default=None, description="Description of the document")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    repo: Optional[str] = Field(default=None, description="Associate with repo name. None = global doc.")
    recursive: bool = Field(default=False, description="Process subdirectories recursively")


class DocIndexResult(BaseModel):
    """Result of indexing operation."""
    source_id: UUID
    name: str
    total_chunks: int
    total_pages: Optional[int] = None
    status: SourceStatus
    message: str


class DocReindexRequest(BaseModel):
    """Request to reindex a document."""
    name: str = Field(..., description="Document name to reindex")
    force: bool = Field(default=False, description="Force reindex even if unchanged")


class DocListItem(BaseModel):
    """Document info for listing."""
    id: UUID
    name: str
    doc_type: DocType
    total_chunks: int
    total_pages: Optional[int] = None
    status: SourceStatus
    version: Optional[str] = None
    indexed_at: Optional[datetime] = None
    file_size_bytes: Optional[int] = None
    repo_name: str = "global"


class DocSearchParams(BaseModel):
    """Parameters for document search."""
    query: str = Field(..., description="Search query")
    doc_types: Optional[list[DocType]] = Field(default=None, description="Filter by document types")
    doc_names: Optional[list[str]] = Field(default=None, description="Filter by document names")
    topics: Optional[list[str]] = Field(default=None, description="Filter by topics")
    oracle_constructs: Optional[list[str]] = Field(default=None, description="Filter by Oracle constructs")
    epas_features: Optional[list[str]] = Field(default=None, description="Filter by EPAS features")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    search_mode: str = Field(default="hybrid", description="Search mode: hybrid, semantic, fts")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum relevance score")
    repo_name: Optional[str] = Field(default=None, description="Filter to specific repo name. None = all docs.")
    include_global: bool = Field(default=True, description="Include docs with no repo (global docs) when repo_name is set")


class DocChunkResult(BaseModel):
    """A document chunk search result with relevance score."""
    chunk_id: UUID
    content: str
    source_document: str
    doc_type: DocType
    section_path: list[str]
    heading: Optional[str] = None
    page_number: Optional[int] = None
    chunk_index: int
    topics: list[str] = Field(default_factory=list)
    oracle_constructs: list[str] = Field(default_factory=list)
    epas_features: list[str] = Field(default_factory=list)

    # Scoring
    score: float
    vec_score: Optional[float] = None
    fts_score: Optional[float] = None
    keyword_matches: int = Field(default=0, description="Number of query keywords found in this chunk")

    # For citation
    citation: Optional[str] = None
    repo_name: str = "global"  # repo_registry name, "global" when None


class DocSearchResult(BaseModel):
    """Result of document search."""
    query: str
    total_found: int
    chunks: list[DocChunkResult]
    search_mode: str
    execution_time_ms: Optional[float] = None
    extracted_keywords: list[str] = Field(default_factory=list, description="Keywords extracted from query")


class DocContextParams(BaseModel):
    """Parameters for getting RAG context."""
    query: str = Field(..., description="Query to find relevant context")
    context_type: Optional[str] = Field(default=None, description="Context type: oracle_construct, epas_feature, migration_issue")
    max_tokens: int = Field(default=2000, ge=100, le=10000, description="Maximum tokens in context")
    doc_types: Optional[list[DocType]] = Field(default=None, description="Filter by document types")
    doc_names: Optional[list[str]] = Field(default=None, description="Filter by document names")
    include_citations: bool = Field(default=True, description="Include source citations")


class DocContextResult(BaseModel):
    """Result of context retrieval for RAG."""
    context: str  # Formatted context string ready for LLM
    chunks_used: int
    total_tokens_approx: int
    sources: list[str]  # List of source citations


# ============ Internal Processing Models ============

class ExtractedSection(BaseModel):
    """A section extracted from a document."""
    content: str
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    page_number: Optional[int] = None
    start_char: int
    end_char: int
    chunk_type: ChunkType = ChunkType.PARAGRAPH
    language: Optional[str] = None  # For code blocks
    children: list["ExtractedSection"] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    """A fully extracted document ready for chunking."""
    source_path: str
    title: Optional[str] = None
    total_pages: Optional[int] = None
    sections: list[ExtractedSection]
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============ Ask Docs (RAG Q&A) Models ============

class DocAskRequest(BaseModel):
    """Request for RAG Q&A - ask a question about the documentation."""
    question: str = Field(..., description="Natural language question about the documentation")
    doc_types: Optional[list[str]] = Field(default=None, description="Filter by document types")
    doc_names: Optional[list[str]] = Field(default=None, description="Filter by document names")
    max_context_tokens: int = Field(default=6000, ge=1000, le=12000, description="Maximum tokens for context")


class DocAskSource(BaseModel):
    """A source used in a RAG Q&A answer."""
    index: int = Field(..., description="Citation index [1], [2], etc.")
    document: str = Field(..., description="Source document name")
    section: Optional[str] = Field(default=None, description="Section heading if available")
    page: Optional[int] = Field(default=None, description="Page number if available")
    chunk_id: UUID = Field(..., description="UUID of the chunk")
    relevance_score: float = Field(..., description="Search relevance score")
    preview: str = Field(..., description="First 200 chars of the chunk")


class DocAskResult(BaseModel):
    """Result of RAG Q&A - synthesized answer with citations."""
    question: str = Field(..., description="The original question")
    answer: str = Field(..., description="LLM-generated answer with inline citations [1], [2]")
    confidence: str = Field(..., description="Confidence level: high, medium, low, no_answer")
    sources_summary: str = Field(
        default="",
        description="LLM-generated summary describing what sources were found and their relevance"
    )
    sources: list[DocAskSource] = Field(default_factory=list, description="Sources used in the answer")
    chunks_used: int = Field(..., description="Number of chunks used for context")
    execution_time_ms: float = Field(..., description="Total execution time in milliseconds")
    model_used: str = Field(..., description="LLM model used for generation")


class ChunkingConfig(BaseModel):
    """Configuration for the chunking algorithm.

    IMPORTANT: Chunk sizes should be configured based on your embedding model's
    max input length. Use ChunkingConfig.for_model() to get optimal settings.

    Common model limits:
    - all-MiniLM-L6-v2: ~256 tokens (~1000 chars)
    - all-mpnet-base-v2: ~384 tokens (~1500 chars)
    - text-embedding-3-small: ~8191 tokens (~32000 chars)
    """
    max_chunk_chars: int = Field(default=1500, description="Maximum characters per chunk")
    min_chunk_chars: int = Field(default=100, description="Minimum characters per chunk")
    target_chunk_chars: int = Field(default=1000, description="Target chunk size")
    overlap_chars: int = Field(default=100, description="Overlap between chunks")
    preserve_code_blocks: bool = Field(default=True, description="Keep code blocks intact")
    preserve_tables: bool = Field(default=True, description="Keep tables intact")
    include_heading_in_chunks: bool = Field(default=True, description="Include section heading in each chunk")

    @classmethod
    def for_model(cls, model_name: str) -> "ChunkingConfig":
        """Create chunking config optimized for a specific embedding model.

        Uses the centralized model limits from config_settings.
        """
        # Import here to avoid circular dependency
        from ..config_settings import ChunkConfig as CoreChunkConfig

        core_config = CoreChunkConfig.for_model(model_name)

        return cls(
            max_chunk_chars=core_config.max_chars,
            target_chunk_chars=core_config.target_chars,
            min_chunk_chars=core_config.min_chars,
            overlap_chars=core_config.overlap_chars,
        )
