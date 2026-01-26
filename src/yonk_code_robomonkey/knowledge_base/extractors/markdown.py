"""
Markdown document extractor using markdown-it-py.

Extracts structured content from Markdown files:
- Headings with hierarchy
- Code blocks with language
- Lists
- Tables
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ..models import ChunkType, ExtractedDocument, ExtractedSection

logger = logging.getLogger(__name__)


class MarkdownExtractor:
    """Extract structured content from Markdown files."""

    def extract(self, file_path: str) -> ExtractedDocument:
        """Extract content from a Markdown file.

        Args:
            file_path: Path to the Markdown file

        Returns:
            ExtractedDocument with sections and metadata
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        sections = self._parse_markdown(content)

        # Extract title from first H1 or filename
        title = None
        for section in sections:
            if section.heading and section.heading_level == 1:
                title = section.heading
                break
        if not title:
            title = path.stem

        return ExtractedDocument(
            source_path=str(path),
            title=title,
            total_pages=None,  # Markdown doesn't have pages
            sections=sections,
            metadata={
                "file_size": path.stat().st_size,
                "filename": path.name,
            }
        )

    def _parse_markdown(self, content: str) -> list[ExtractedSection]:
        """Parse Markdown content into sections."""
        sections: list[ExtractedSection] = []
        lines = content.split("\n")

        current_heading: Optional[str] = None
        current_heading_level: int = 0
        current_content: list[str] = []
        current_start_char: int = 0
        char_offset: int = 0

        in_code_block = False
        code_block_lang: Optional[str] = None
        code_block_content: list[str] = []
        code_block_start: int = 0

        for line in lines:
            line_len = len(line) + 1  # +1 for newline

            # Check for code block boundaries
            if line.startswith("```"):
                if not in_code_block:
                    # Start of code block
                    in_code_block = True
                    code_block_lang = line[3:].strip() or None
                    code_block_content = []
                    code_block_start = char_offset

                    # Save current content as section
                    if current_content:
                        content_text = "\n".join(current_content)
                        sections.append(ExtractedSection(
                            content=content_text,
                            heading=current_heading,
                            heading_level=current_heading_level,
                            page_number=None,
                            start_char=current_start_char,
                            end_char=char_offset,
                            chunk_type=ChunkType.PARAGRAPH,
                        ))
                        current_content = []
                        current_start_char = char_offset
                else:
                    # End of code block
                    in_code_block = False
                    code_content = "\n".join(code_block_content)
                    sections.append(ExtractedSection(
                        content=code_content,
                        heading=current_heading,
                        heading_level=current_heading_level,
                        page_number=None,
                        start_char=code_block_start,
                        end_char=char_offset + line_len,
                        chunk_type=ChunkType.CODE_BLOCK,
                        language=code_block_lang,
                    ))
                    current_start_char = char_offset + line_len

                char_offset += line_len
                continue

            if in_code_block:
                code_block_content.append(line)
                char_offset += line_len
                continue

            # Check for headings
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                # Save current content as section
                if current_content:
                    content_text = "\n".join(current_content)
                    sections.append(ExtractedSection(
                        content=content_text,
                        heading=current_heading,
                        heading_level=current_heading_level,
                        page_number=None,
                        start_char=current_start_char,
                        end_char=char_offset,
                        chunk_type=ChunkType.PARAGRAPH,
                    ))
                    current_content = []

                # Start new section with heading
                current_heading = heading_match.group(2).strip()
                current_heading_level = len(heading_match.group(1))
                current_start_char = char_offset
                char_offset += line_len
                continue

            # Check for tables
            if "|" in line and line.strip().startswith("|"):
                # Could be a table row
                current_content.append(line)
                char_offset += line_len
                continue

            # Regular content
            if line.strip():
                current_content.append(line)
            elif current_content:
                # Empty line - could be paragraph break
                current_content.append("")

            char_offset += line_len

        # Don't forget the last section
        if current_content:
            content_text = "\n".join(current_content)
            sections.append(ExtractedSection(
                content=content_text,
                heading=current_heading,
                heading_level=current_heading_level,
                page_number=None,
                start_char=current_start_char,
                end_char=char_offset,
                chunk_type=ChunkType.PARAGRAPH,
            ))

        return sections
