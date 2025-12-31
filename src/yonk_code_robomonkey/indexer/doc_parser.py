"""Document parser for extracting plain text from documentation files.

Supports Markdown, reStructuredText, and AsciiDoc.
"""
from __future__ import annotations
from pathlib import Path
import re


def parse_document(file_path: Path, doc_type: str) -> tuple[str, str]:
    """Parse a documentation file to extract title and content.

    Args:
        file_path: Path to the documentation file
        doc_type: Type of document ('markdown', 'restructuredtext', 'asciidoc')

    Returns:
        Tuple of (title, content) where content is plain text
    """
    content = file_path.read_text(encoding="utf-8", errors="replace")

    if doc_type == "markdown":
        return _parse_markdown(content, file_path.name)
    elif doc_type == "restructuredtext":
        return _parse_rst(content, file_path.name)
    elif doc_type == "asciidoc":
        return _parse_asciidoc(content, file_path.name)
    else:
        # Fallback: use filename as title, content as-is
        return (file_path.stem, content)


def _parse_markdown(content: str, filename: str) -> tuple[str, str]:
    """Parse Markdown to extract title and plain text.

    Args:
        content: Markdown content
        filename: Filename for fallback title

    Returns:
        Tuple of (title, plain_text)
    """
    # Extract title from first H1 or use filename
    title = filename
    lines = content.split("\n")

    for i, line in enumerate(lines):
        # Check for # Header
        if line.startswith("# "):
            title = line[2:].strip()
            break
        # Check for Header with ===== underline
        if i + 1 < len(lines) and lines[i + 1].strip() and all(c == "=" for c in lines[i + 1].strip()):
            title = line.strip()
            break

    # Simple markdown to plain text conversion
    # Remove code blocks
    plain = re.sub(r"```[\s\S]*?```", "", content)
    plain = re.sub(r"`[^`]+`", "", plain)

    # Remove links but keep text
    plain = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", plain)

    # Remove images
    plain = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", "", plain)

    # Remove emphasis markers
    plain = re.sub(r"\*\*([^\*]+)\*\*", r"\1", plain)
    plain = re.sub(r"\*([^\*]+)\*", r"\1", plain)
    plain = re.sub(r"__([^_]+)__", r"\1", plain)
    plain = re.sub(r"_([^_]+)_", r"\1", plain)

    # Remove header markers
    plain = re.sub(r"^#+\s+", "", plain, flags=re.MULTILINE)

    # Clean up extra whitespace
    plain = re.sub(r"\n{3,}", "\n\n", plain)

    return (title, plain.strip())


def _parse_rst(content: str, filename: str) -> tuple[str, str]:
    """Parse reStructuredText to extract title and plain text.

    Args:
        content: RST content
        filename: Filename for fallback title

    Returns:
        Tuple of (title, plain_text)
    """
    # Extract title (first heading)
    title = filename
    lines = content.split("\n")

    for i, line in enumerate(lines):
        # Check for overline/underline style heading
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and all(c == next_line[0] for c in next_line) and next_line[0] in "=-~`:#'\"^_*+<>":
                if line.strip():
                    title = line.strip()
                    break

    # Simple RST to plain text conversion
    # Remove code blocks
    plain = re.sub(r"::\n\n[\s\S]*?(?=\n\S)", "", content)

    # Remove directives
    plain = re.sub(r"\.\. \w+::", "", plain)

    # Remove inline code
    plain = re.sub(r"``[^`]+``", "", plain)

    # Remove links
    plain = re.sub(r"`[^`]+`_", "", plain)

    # Remove emphasis
    plain = re.sub(r"\*\*([^\*]+)\*\*", r"\1", plain)
    plain = re.sub(r"\*([^\*]+)\*", r"\1", plain)

    # Remove section markers
    for marker in "=-~`:#'\"^_*+<>":
        plain = re.sub(f"^{re.escape(marker)}+$", "", plain, flags=re.MULTILINE)

    # Clean up extra whitespace
    plain = re.sub(r"\n{3,}", "\n\n", plain)

    return (title, plain.strip())


def _parse_asciidoc(content: str, filename: str) -> tuple[str, str]:
    """Parse AsciiDoc to extract title and plain text.

    Args:
        content: AsciiDoc content
        filename: Filename for fallback title

    Returns:
        Tuple of (title, plain_text)
    """
    # Extract title (first = heading or document title)
    title = filename
    lines = content.split("\n")

    for line in lines:
        if line.startswith("= "):
            title = line[2:].strip()
            break

    # Simple AsciiDoc to plain text conversion
    # Remove code blocks
    plain = re.sub(r"----\n[\s\S]*?\n----", "", content)

    # Remove inline code
    plain = re.sub(r"`[^`]+`", "", plain)

    # Remove links
    plain = re.sub(r"link:([^\[]+)\[([^\]]+)\]", r"\2", plain)
    plain = re.sub(r"https?://[^\s\[]+\[([^\]]+)\]", r"\1", plain)

    # Remove emphasis
    plain = re.sub(r"\*\*([^\*]+)\*\*", r"\1", plain)
    plain = re.sub(r"\*([^\*]+)\*", r"\1", plain)
    plain = re.sub(r"__([^_]+)__", r"\1", plain)
    plain = re.sub(r"_([^_]+)_", r"\1", plain)

    # Remove header markers
    plain = re.sub(r"^=+\s+", "", plain, flags=re.MULTILINE)

    # Clean up extra whitespace
    plain = re.sub(r"\n{3,}", "\n\n", plain)

    return (title, plain.strip())
