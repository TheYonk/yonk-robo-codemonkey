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

    # For citation
    citation: Optional[str] = None


class DocSearchResult(BaseModel):
    """Result of document search."""
    query: str
    total_found: int
    chunks: list[DocChunkResult]
    search_mode: str
    execution_time_ms: Optional[float] = None


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


class ChunkingConfig(BaseModel):
    """Configuration for the chunking algorithm.

    IMPORTANT: Chunk sizes should be configured based on your embedding model's
    max input length. Common limits:
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
        """Create chunking config optimized for a specific embedding model."""
        # Model-specific max input lengths (conservative estimates in chars)
        model_limits = {
            # Sentence-transformers models
            "all-MiniLM-L6-v2": 1000,
            "all-mpnet-base-v2": 1500,
            "all-MiniLM-L12-v2": 1000,
            "paraphrase-MiniLM-L6-v2": 500,
            "multi-qa-MiniLM-L6-cos-v1": 2000,
            "all-distilroberta-v1": 2000,
            # OpenAI models
            "text-embedding-3-small": 30000,
            "text-embedding-3-large": 30000,
            "text-embedding-ada-002": 30000,
            # Ollama/local models
            "nomic-embed-text": 30000,
            "snowflake-arctic-embed2": 2000,
            "mxbai-embed-large": 2000,
        }

        # Find matching limit
        max_chars = 2000  # Default
        model_lower = model_name.lower()
        base_name = model_name.split(":")[0].lower()

        for key, limit in model_limits.items():
            if key.lower() == base_name or key.lower() in model_lower:
                max_chars = limit
                break

        # Calculate optimal chunk sizes
        # Target is 70% of max to leave room for variation
        target_chars = int(max_chars * 0.7)
        # Min is 10% of max
        min_chars = max(100, int(max_chars * 0.1))
        # Overlap is 10% of target
        overlap_chars = int(target_chars * 0.1)

        return cls(
            max_chunk_chars=max_chars,
            target_chunk_chars=target_chars,
            min_chunk_chars=min_chars,
            overlap_chars=overlap_chars,
        )
