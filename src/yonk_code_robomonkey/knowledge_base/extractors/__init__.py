"""
Document extractors for different file formats.

Each extractor converts a document into a structured ExtractedDocument
that can then be chunked and indexed.
"""

from .pdf import PDFExtractor
from .markdown import MarkdownExtractor
from .html import HTMLExtractor
from .plain import PlainTextExtractor

# Map file extensions to extractors
EXTRACTOR_MAP = {
    ".pdf": PDFExtractor,
    ".md": MarkdownExtractor,
    ".markdown": MarkdownExtractor,
    ".html": HTMLExtractor,
    ".htm": HTMLExtractor,
    ".txt": PlainTextExtractor,
    ".text": PlainTextExtractor,
    ".rst": PlainTextExtractor,  # TODO: Add dedicated RST extractor
    ".adoc": PlainTextExtractor,  # TODO: Add dedicated AsciiDoc extractor
}


def get_extractor(file_path: str):
    """Get the appropriate extractor for a file based on extension."""
    import os
    _, ext = os.path.splitext(file_path.lower())

    extractor_class = EXTRACTOR_MAP.get(ext)
    if extractor_class is None:
        raise ValueError(f"No extractor available for file type: {ext}")

    return extractor_class()


__all__ = [
    "PDFExtractor",
    "MarkdownExtractor",
    "HTMLExtractor",
    "PlainTextExtractor",
    "get_extractor",
    "EXTRACTOR_MAP",
]
