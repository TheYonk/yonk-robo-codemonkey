"""
HTML document extractor using BeautifulSoup.

Extracts structured content from HTML files:
- Headings (h1-h6) with hierarchy
- Code blocks (pre, code)
- Lists (ul, ol)
- Tables
- Paragraphs
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ..models import ChunkType, ExtractedDocument, ExtractedSection

logger = logging.getLogger(__name__)


class HTMLExtractor:
    """Extract structured content from HTML files."""

    def extract(self, file_path: str) -> ExtractedDocument:
        """Extract content from an HTML file.

        Args:
            file_path: Path to the HTML file

        Returns:
            ExtractedDocument with sections and metadata
        """
        from bs4 import BeautifulSoup

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(content, "html.parser")

        # Remove script, style, and nav elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        sections = self._parse_html(soup)

        # Extract title
        title = None
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)
        if not title:
            title = path.stem

        return ExtractedDocument(
            source_path=str(path),
            title=title,
            total_pages=None,
            sections=sections,
            metadata={
                "file_size": path.stat().st_size,
                "filename": path.name,
            }
        )

    def _parse_html(self, soup) -> list[ExtractedSection]:
        """Parse HTML soup into sections."""
        sections: list[ExtractedSection] = []

        # Find the main content area
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup

        current_heading: Optional[str] = None
        current_heading_level: int = 0
        current_content: list[str] = []
        char_offset: int = 0

        for element in main.descendants:
            if element.name is None:
                continue

            # Headings
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                # Save current content
                if current_content:
                    content_text = "\n".join(current_content)
                    sections.append(ExtractedSection(
                        content=content_text,
                        heading=current_heading,
                        heading_level=current_heading_level,
                        page_number=None,
                        start_char=char_offset,
                        end_char=char_offset + len(content_text),
                        chunk_type=ChunkType.PARAGRAPH,
                    ))
                    char_offset += len(content_text)
                    current_content = []

                current_heading = element.get_text(strip=True)
                current_heading_level = int(element.name[1])
                continue

            # Code blocks
            if element.name in ["pre", "code"]:
                text = element.get_text()
                if text.strip():
                    # Detect language from class
                    lang = None
                    classes = element.get("class", [])
                    for cls in classes:
                        if cls.startswith("language-"):
                            lang = cls[9:]
                            break
                        elif cls in ["python", "javascript", "sql", "java", "go", "rust"]:
                            lang = cls
                            break

                    sections.append(ExtractedSection(
                        content=text.strip(),
                        heading=current_heading,
                        heading_level=current_heading_level,
                        page_number=None,
                        start_char=char_offset,
                        end_char=char_offset + len(text),
                        chunk_type=ChunkType.CODE_BLOCK,
                        language=lang,
                    ))
                    char_offset += len(text)
                continue

            # Tables
            if element.name == "table":
                table_text = self._extract_table(element)
                if table_text:
                    sections.append(ExtractedSection(
                        content=table_text,
                        heading=current_heading,
                        heading_level=current_heading_level,
                        page_number=None,
                        start_char=char_offset,
                        end_char=char_offset + len(table_text),
                        chunk_type=ChunkType.TABLE,
                    ))
                    char_offset += len(table_text)
                continue

            # Lists
            if element.name in ["ul", "ol"]:
                list_text = self._extract_list(element)
                if list_text:
                    current_content.append(list_text)
                continue

            # Paragraphs and divs with text
            if element.name in ["p", "div"]:
                text = element.get_text(strip=True)
                if text and len(text) > 10:  # Skip very short text
                    current_content.append(text)

        # Don't forget the last section
        if current_content:
            content_text = "\n".join(current_content)
            sections.append(ExtractedSection(
                content=content_text,
                heading=current_heading,
                heading_level=current_heading_level,
                page_number=None,
                start_char=char_offset,
                end_char=char_offset + len(content_text),
                chunk_type=ChunkType.PARAGRAPH,
            ))

        return sections

    def _extract_table(self, table_element) -> str:
        """Extract table content as text."""
        rows = []
        for tr in table_element.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                cells.append(td.get_text(strip=True))
            if cells:
                rows.append(" | ".join(cells))

        return "\n".join(rows)

    def _extract_list(self, list_element) -> str:
        """Extract list content as text."""
        items = []
        for li in list_element.find_all("li", recursive=False):
            text = li.get_text(strip=True)
            if text:
                items.append(f"- {text}")

        return "\n".join(items)
