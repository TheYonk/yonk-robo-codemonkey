"""
Smart document chunker with semantic awareness.

Creates semantically meaningful chunks with:
- Target size of 500-1500 tokens (2000-6000 chars)
- Overlap between chunks (~100 tokens)
- Section hierarchy preservation
- Heading inclusion in each chunk
- Whitespace normalization
"""

import hashlib
import logging
import re
from typing import Optional
from uuid import uuid4


def normalize_whitespace(text: str) -> str:
    """Normalize excessive whitespace in text.

    - Collapses multiple spaces to single space
    - Collapses 3+ newlines to 2 newlines (preserves paragraph breaks)
    - Strips leading/trailing whitespace from lines
    - Removes trailing whitespace from entire text
    """
    if not text:
        return text

    # Replace tabs with spaces
    text = text.replace('\t', ' ')

    # Collapse multiple spaces (but not newlines) to single space
    text = re.sub(r'[^\S\n]+', ' ', text)

    # Strip whitespace from each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Collapse 3+ consecutive newlines to 2 (preserve paragraph breaks)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove leading/trailing whitespace
    text = text.strip()

    return text

from .models import (
    ChunkingConfig,
    ChunkType,
    DocChunk,
    ExtractedDocument,
    ExtractedSection,
)

logger = logging.getLogger(__name__)

# Oracle constructs to detect and tag
ORACLE_CONSTRUCTS = {
    "rownum": ["rownum", "pagination", "oracle-specific"],
    "connect by": ["hierarchical-query", "connect-by", "oracle-specific"],
    "start with": ["hierarchical-query", "connect-by", "oracle-specific"],
    "decode": ["decode", "case-expression", "oracle-specific"],
    "nvl": ["null-handling", "nvl", "oracle-specific"],
    "nvl2": ["null-handling", "nvl2", "oracle-specific"],
    "sysdate": ["datetime", "sysdate", "oracle-specific"],
    "dual": ["dual", "oracle-specific"],
    "dbms_output": ["dbms_output", "package", "oracle-specific"],
    "dbms_lob": ["dbms_lob", "package", "lob", "oracle-specific"],
    "dbms_sql": ["dbms_sql", "package", "dynamic-sql", "oracle-specific"],
    "dbms_utility": ["dbms_utility", "package", "oracle-specific"],
    "dbms_scheduler": ["dbms_scheduler", "package", "scheduling", "oracle-specific"],
    "dbms_job": ["dbms_job", "package", "scheduling", "oracle-specific"],
    "utl_file": ["utl_file", "package", "file-io", "oracle-specific"],
    "utl_http": ["utl_http", "package", "http", "oracle-specific"],
    "xmltype": ["xmltype", "xml", "datatype", "oracle-specific"],
    "varchar2": ["varchar2", "datatype", "oracle-specific"],
    "number(": ["number", "datatype", "oracle-specific"],
    "pls_integer": ["pls_integer", "datatype", "plsql", "oracle-specific"],
    "ref cursor": ["ref-cursor", "cursor", "plsql", "oracle-specific"],
    "bulk collect": ["bulk-collect", "plsql", "oracle-specific"],
    "forall": ["forall", "plsql", "bulk-operations", "oracle-specific"],
    "autonomous_transaction": ["autonomous-transaction", "plsql", "oracle-specific"],
    "pragma": ["pragma", "plsql", "oracle-specific"],
    "all_": ["data-dictionary", "oracle-specific"],
    "dba_": ["data-dictionary", "oracle-specific"],
    "user_": ["data-dictionary", "oracle-specific"],
    "v$": ["dynamic-view", "oracle-specific"],
}

# EPAS features to detect and tag
EPAS_FEATURES = {
    "dblink_ora": ["dblink_ora", "dblink", "epas-specific"],
    "edb*plus": ["edbplus", "sqlplus", "epas-specific"],
    "edbplus": ["edbplus", "sqlplus", "epas-specific"],
    "spl": ["spl", "plsql", "epas-specific"],
    "oracle compatibility": ["oracle-compatibility", "epas-specific"],
    "edb_redwood": ["redwood", "oracle-compatibility", "epas-specific"],
    "edb_stmt_level_tx": ["statement-level-tx", "epas-specific"],
    "edb_data_redaction": ["data-redaction", "security", "epas-specific"],
}


class DocumentChunker:
    """Chunks documents into semantically meaningful pieces."""

    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()

    def chunk_document(
        self,
        document: ExtractedDocument,
        source_id: str,
    ) -> list[DocChunk]:
        """Chunk an extracted document into DocChunk objects.

        Args:
            document: The extracted document to chunk
            source_id: UUID of the doc_source record

        Returns:
            List of DocChunk objects ready for database insertion
        """
        chunks: list[DocChunk] = []
        chunk_index = 0

        # Build section hierarchy for breadcrumbs
        section_stack: list[tuple[int, str]] = []  # (level, heading)

        for section in document.sections:
            # Update section stack for breadcrumb
            if section.heading:
                level = section.heading_level or 1
                # Pop sections at same or lower level
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, section.heading))

            # Build section path from stack
            section_path = [h for _, h in section_stack]

            # Chunk the section content
            section_chunks = self._chunk_section(
                section=section,
                section_path=section_path,
                source_id=source_id,
                start_chunk_index=chunk_index,
            )

            chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        logger.info(f"Created {len(chunks)} chunks from document: {document.source_path}")
        return chunks

    def _chunk_section(
        self,
        section: ExtractedSection,
        section_path: list[str],
        source_id: str,
        start_chunk_index: int,
    ) -> list[DocChunk]:
        """Chunk a single section, handling overlap and size constraints."""
        chunks: list[DocChunk] = []
        content = section.content.strip()

        if not content:
            return chunks

        # For code blocks and tables, try to keep them intact
        if section.chunk_type in [ChunkType.CODE_BLOCK, ChunkType.TABLE]:
            if len(content) <= self.config.max_chunk_chars:
                # Keep intact
                chunks.append(self._create_chunk(
                    content=content,
                    section=section,
                    section_path=section_path,
                    source_id=source_id,
                    chunk_index=start_chunk_index,
                ))
                return chunks

        # Split content into smaller chunks
        text_chunks = self._split_text(content)

        for i, text in enumerate(text_chunks):
            # Include heading in chunk if configured
            if self.config.include_heading_in_chunks and section.heading and i == 0:
                text = f"## {section.heading}\n\n{text}"

            chunks.append(self._create_chunk(
                content=text,
                section=section,
                section_path=section_path,
                source_id=source_id,
                chunk_index=start_chunk_index + i,
            ))

        return chunks

    def _split_text(self, text: str) -> list[str]:
        """Split text into chunks with overlap.

        Uses a hierarchical splitting strategy:
        1. Try to split on paragraph boundaries
        2. Fall back to sentence boundaries
        3. Fall back to word boundaries
        """
        target = self.config.target_chunk_chars
        max_size = self.config.max_chunk_chars
        min_size = self.config.min_chunk_chars
        overlap = self.config.overlap_chars

        if len(text) <= max_size:
            return [text]

        chunks = []
        current_pos = 0

        while current_pos < len(text):
            # Determine end position for this chunk
            end_pos = min(current_pos + target, len(text))

            if end_pos < len(text):
                # Try to find a good break point
                chunk_text = text[current_pos:current_pos + max_size]

                # Try paragraph break first
                para_break = self._find_break_point(chunk_text, target, "\n\n")
                if para_break > min_size:
                    end_pos = current_pos + para_break
                else:
                    # Try sentence break
                    sent_break = self._find_break_point(chunk_text, target, ". ")
                    if sent_break > min_size:
                        end_pos = current_pos + sent_break + 1  # Include the period
                    else:
                        # Try newline break
                        line_break = self._find_break_point(chunk_text, target, "\n")
                        if line_break > min_size:
                            end_pos = current_pos + line_break

            chunk = text[current_pos:end_pos].strip()
            if chunk:
                chunks.append(chunk)

            # Move position with overlap
            if end_pos >= len(text):
                break

            # Advance position, avoiding going backwards
            new_pos = end_pos - overlap
            if new_pos <= current_pos:
                current_pos = end_pos
            else:
                current_pos = new_pos

        return chunks

    def _find_break_point(self, text: str, target: int, delimiter: str) -> int:
        """Find the best break point near the target position."""
        # Look for delimiter within a window around target
        window_start = max(0, target - 500)
        window_end = min(len(text), target + 500)

        # Search backwards from target first
        search_text = text[window_start:target]
        last_delim = search_text.rfind(delimiter)
        if last_delim >= 0:
            return window_start + last_delim + len(delimiter)

        # Search forward from target
        search_text = text[target:window_end]
        first_delim = search_text.find(delimiter)
        if first_delim >= 0:
            return target + first_delim + len(delimiter)

        return target

    def _create_chunk(
        self,
        content: str,
        section: ExtractedSection,
        section_path: list[str],
        source_id: str,
        chunk_index: int,
    ) -> DocChunk:
        """Create a DocChunk with all metadata."""
        # Normalize whitespace in content
        content = normalize_whitespace(content)

        # Calculate content hash (after normalization)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Approximate token count (rough estimate: 1 token ≈ 4 chars)
        token_count_approx = len(content) // 4

        # Extract topics and tags
        topics = self._extract_topics(content, section_path)
        oracle_constructs = self._detect_oracle_constructs(content)
        epas_features = self._detect_epas_features(content)

        return DocChunk(
            id=uuid4(),
            source_id=source_id,
            content=content,
            content_hash=content_hash,
            section_path=section_path,
            heading=section.heading,
            heading_level=section.heading_level,
            page_number=section.page_number,
            chunk_index=chunk_index,
            start_char=section.start_char,
            end_char=section.end_char,
            char_count=len(content),
            token_count_approx=token_count_approx,
            chunk_type=section.chunk_type,
            language=section.language,
            topics=topics,
            oracle_constructs=oracle_constructs,
            epas_features=epas_features,
            metadata={},
        )

    def _extract_topics(self, content: str, section_path: list[str]) -> list[str]:
        """Extract topics/keywords from content."""
        topics = set()

        # Add section path as topics
        for heading in section_path:
            # Clean and add as topic
            clean = re.sub(r"[^\w\s]", "", heading.lower())
            words = clean.split()
            if len(words) <= 4:  # Only short headings as topics
                topics.add(clean)

        # Extract SQL keywords
        sql_keywords = ["select", "insert", "update", "delete", "create", "alter",
                        "drop", "index", "table", "view", "function", "procedure",
                        "trigger", "sequence", "constraint", "foreign key", "primary key"]
        content_lower = content.lower()
        for kw in sql_keywords:
            if kw in content_lower:
                topics.add(kw)

        return list(topics)[:20]  # Limit to 20 topics

    def _detect_oracle_constructs(self, content: str) -> list[str]:
        """Detect Oracle-specific constructs in content."""
        found_tags = set()
        content_lower = content.lower()

        for construct, tags in ORACLE_CONSTRUCTS.items():
            if construct in content_lower:
                found_tags.update(tags)

        return list(found_tags)

    def _detect_epas_features(self, content: str) -> list[str]:
        """Detect EPAS-specific features in content."""
        found_tags = set()
        content_lower = content.lower()

        for feature, tags in EPAS_FEATURES.items():
            if feature in content_lower:
                found_tags.update(tags)

        return list(found_tags)


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Uses tiktoken if available, otherwise falls back to character-based estimate.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Fallback: roughly 4 characters per token
        return len(text) // 4
