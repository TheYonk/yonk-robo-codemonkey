"""
PDF document extractor using pdfplumber.

Extracts text from PDFs while preserving structure:
- Page numbers
- Headings (detected by font size/style)
- Code blocks (detected by monospace fonts)
- Tables
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ..models import ChunkType, ExtractedDocument, ExtractedSection

logger = logging.getLogger(__name__)


def _sanitize_text(text: str) -> str:
    """Remove null bytes and other problematic characters for PostgreSQL."""
    if not text:
        return text
    # Remove null bytes which cause "invalid byte sequence for encoding UTF8: 0x00"
    return text.replace('\x00', '').replace('\x00', '')


class PDFExtractor:
    """Extract structured content from PDF files."""

    def __init__(self):
        self.heading_font_size_threshold = 12  # Fonts larger than this may be headings
        self.code_font_names = ["courier", "mono", "consolas", "menlo", "source code"]

    def extract(self, file_path: str) -> ExtractedDocument:
        """Extract content from a PDF file.

        Args:
            file_path: Path to the PDF file

        Returns:
            ExtractedDocument with sections and metadata
        """
        import pdfplumber

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        sections: list[ExtractedSection] = []
        current_heading: Optional[str] = None
        current_heading_level: int = 1
        current_content: list[str] = []
        current_start_char: int = 0
        total_chars: int = 0

        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"Processing PDF with {total_pages} pages: {path.name}")

            for page_num, page in enumerate(pdf.pages, start=1):
                # Extract text from page and sanitize (remove null bytes)
                try:
                    page_text = page.extract_text() or ""
                    page_text = _sanitize_text(page_text)
                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num}: {e}")
                    continue

                if not page_text.strip():
                    continue

                # Process the page text
                lines = page_text.split("\n")

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Detect if line is a heading (heuristics)
                    is_heading, heading_level = self._detect_heading(line, page)

                    if is_heading:
                        # Save previous section if exists
                        if current_content:
                            content_text = "\n".join(current_content)
                            sections.append(ExtractedSection(
                                content=content_text,
                                heading=current_heading,
                                heading_level=current_heading_level,
                                page_number=page_num,
                                start_char=current_start_char,
                                end_char=total_chars,
                                chunk_type=ChunkType.PARAGRAPH,
                            ))
                            current_content = []

                        current_heading = line
                        current_heading_level = heading_level
                        current_start_char = total_chars
                    else:
                        current_content.append(line)

                    total_chars += len(line) + 1  # +1 for newline

                # Also extract tables from page
                try:
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            table_text = _sanitize_text(self._format_table(table))
                            if table_text:
                                sections.append(ExtractedSection(
                                    content=table_text,
                                    heading=current_heading,
                                    heading_level=current_heading_level,
                                    page_number=page_num,
                                    start_char=total_chars,
                                    end_char=total_chars + len(table_text),
                                    chunk_type=ChunkType.TABLE,
                                ))
                                total_chars += len(table_text)
                except Exception as e:
                    logger.warning(f"Error extracting tables from page {page_num}: {e}")

            # Don't forget the last section
            if current_content:
                content_text = "\n".join(current_content)
                sections.append(ExtractedSection(
                    content=content_text,
                    heading=current_heading,
                    heading_level=current_heading_level,
                    page_number=total_pages,
                    start_char=current_start_char,
                    end_char=total_chars,
                    chunk_type=ChunkType.PARAGRAPH,
                ))

        # Post-process: detect code blocks within sections
        sections = self._detect_code_blocks(sections)

        # Extract title from first heading or filename
        title = None
        for section in sections:
            if section.heading:
                title = section.heading
                break
        if not title:
            title = path.stem

        return ExtractedDocument(
            source_path=str(path),
            title=title,
            total_pages=total_pages,
            sections=sections,
            metadata={
                "file_size": path.stat().st_size,
                "filename": path.name,
            }
        )

    def _detect_heading(self, line: str, page) -> tuple[bool, int]:
        """Detect if a line is a heading and determine its level.

        Returns:
            (is_heading, heading_level)
        """
        # Common heading patterns
        heading_patterns = [
            # Chapter/Section patterns
            (r"^Chapter\s+\d+", 1),
            (r"^CHAPTER\s+\d+", 1),
            (r"^Part\s+[IVXLCDM\d]+", 1),
            (r"^PART\s+[IVXLCDM\d]+", 1),
            (r"^\d+\.\s+[A-Z]", 2),  # "1. Introduction"
            (r"^\d+\.\d+\s+", 3),  # "1.1 Subsection"
            (r"^\d+\.\d+\.\d+\s+", 4),  # "1.1.1 Sub-subsection"
            (r"^[A-Z][A-Z\s]{5,}$", 2),  # ALL CAPS HEADING
            (r"^Appendix\s+[A-Z]", 1),
            (r"^APPENDIX\s+[A-Z]", 1),
        ]

        for pattern, level in heading_patterns:
            if re.match(pattern, line):
                return True, level

        # Length-based heuristic: very short lines that look like titles
        if len(line) < 80 and line[0].isupper() and not line.endswith("."):
            # Check if it's not a regular sentence
            words = line.split()
            if len(words) <= 8:
                # Could be a heading
                return True, 2

        return False, 0

    def _format_table(self, table: list[list]) -> str:
        """Format a table as text."""
        if not table:
            return ""

        lines = []
        for row in table:
            # Clean up cells
            cells = [str(cell).strip() if cell else "" for cell in row]
            lines.append(" | ".join(cells))

        return "\n".join(lines)

    def _detect_code_blocks(self, sections: list[ExtractedSection]) -> list[ExtractedSection]:
        """Post-process sections to detect code blocks within content."""
        result = []

        for section in sections:
            # Look for code-like patterns
            content = section.content

            # Patterns that indicate code
            code_patterns = [
                r"^\s{4,}",  # Indented lines
                r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s",  # SQL
                r"^(BEGIN|END|DECLARE|EXCEPTION)\s*;?\s*$",  # PL/SQL
                r"^(def |class |import |from |if |for |while )",  # Python
                r"^(function |const |let |var |import |export )",  # JavaScript
                r"^(CREATE OR REPLACE|GRANT|REVOKE)\s",  # SQL DDL
            ]

            # Check if the entire section looks like code
            lines = content.split("\n")
            code_line_count = 0
            for line in lines:
                for pattern in code_patterns:
                    if re.match(pattern, line, re.IGNORECASE):
                        code_line_count += 1
                        break

            # If more than 50% of lines look like code, mark as code block
            if len(lines) > 0 and code_line_count / len(lines) > 0.5:
                section.chunk_type = ChunkType.CODE_BLOCK
                # Try to detect language
                section.language = self._detect_language(content)

            result.append(section)

        return result

    def _detect_language(self, content: str) -> Optional[str]:
        """Detect the programming language of a code block."""
        content_lower = content.lower()

        # SQL patterns
        sql_keywords = ["select", "insert", "update", "delete", "create table",
                        "alter table", "drop table", "begin", "end;", "declare"]
        if any(kw in content_lower for kw in sql_keywords):
            # Check for PL/SQL specific
            plsql_keywords = ["dbms_", "utl_", "pragma", "exception", "cursor",
                              "bulk collect", "forall", "ref cursor"]
            if any(kw in content_lower for kw in plsql_keywords):
                return "plsql"
            return "sql"

        # Python patterns
        if "def " in content or "import " in content or "class " in content:
            return "python"

        # JavaScript patterns
        if "function " in content or "const " in content or "=>" in content:
            return "javascript"

        return None
