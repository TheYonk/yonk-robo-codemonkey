"""
Plain text document extractor.

Extracts content from plain text files with basic structure detection:
- Paragraph breaks (double newlines)
- Simple heading detection (all caps lines, underlined text)
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ..models import ChunkType, ExtractedDocument, ExtractedSection

logger = logging.getLogger(__name__)


class PlainTextExtractor:
    """Extract structured content from plain text files."""

    def extract(self, file_path: str) -> ExtractedDocument:
        """Extract content from a plain text file.

        Args:
            file_path: Path to the text file

        Returns:
            ExtractedDocument with sections and metadata
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        sections = self._parse_text(content)

        return ExtractedDocument(
            source_path=str(path),
            title=path.stem,
            total_pages=None,
            sections=sections,
            metadata={
                "file_size": path.stat().st_size,
                "filename": path.name,
            }
        )

    def _parse_text(self, content: str) -> list[ExtractedSection]:
        """Parse plain text content into sections."""
        sections: list[ExtractedSection] = []

        # Split by double newlines (paragraph breaks)
        paragraphs = re.split(r"\n\s*\n", content)

        current_heading: Optional[str] = None
        current_heading_level: int = 0
        char_offset: int = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Detect headings
            is_heading, heading_level = self._detect_heading(para)

            if is_heading:
                current_heading = para
                current_heading_level = heading_level
            else:
                sections.append(ExtractedSection(
                    content=para,
                    heading=current_heading,
                    heading_level=current_heading_level,
                    page_number=None,
                    start_char=char_offset,
                    end_char=char_offset + len(para),
                    chunk_type=ChunkType.PARAGRAPH,
                ))

            char_offset += len(para) + 2  # +2 for paragraph break

        return sections

    def _detect_heading(self, text: str) -> tuple[bool, int]:
        """Detect if text is a heading.

        Returns:
            (is_heading, heading_level)
        """
        lines = text.split("\n")

        # Check for underlined headings (like in RST)
        if len(lines) >= 2:
            underline = lines[-1]
            if re.match(r"^[=\-~^\"\'`]+$", underline) and len(underline) >= 3:
                # This is an underlined heading
                if "=" in underline:
                    return True, 1
                elif "-" in underline:
                    return True, 2
                else:
                    return True, 3

        # Check for all-caps lines (potential headings)
        first_line = lines[0].strip()
        if first_line.isupper() and len(first_line) < 100 and len(first_line.split()) <= 10:
            return True, 2

        # Check for numbered sections
        if re.match(r"^\d+\.\s+[A-Z]", first_line):
            return True, 2
        if re.match(r"^\d+\.\d+\s+", first_line):
            return True, 3

        return False, 0
