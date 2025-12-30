"""Tree-sitter parser setup for supported languages.

Uses tree-sitter-languages for pre-built parsers.
"""
from __future__ import annotations
from tree_sitter import Parser
import tree_sitter_languages


# Cached parsers for each language
_PARSERS: dict[str, Parser] = {}


def get_parser(language: str) -> Parser | None:
    """Get or create a tree-sitter parser for the given language.

    Args:
        language: Language identifier (python, javascript, typescript, go, java)

    Returns:
        Parser instance or None if language not supported
    """
    if language in _PARSERS:
        return _PARSERS[language]

    # Map our language names to tree-sitter-languages names
    lang_map = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "go": "go",
        "java": "java",
    }

    ts_lang_name = lang_map.get(language)
    if not ts_lang_name:
        return None

    try:
        # Use get_parser directly from tree-sitter-languages
        parser = tree_sitter_languages.get_parser(ts_lang_name)

        # Cache it
        _PARSERS[language] = parser
        return parser

    except Exception as e:
        # Language not available
        print(f"Warning: Could not load parser for {language}: {e}")
        return None


def parse_file(file_path: str, language: str) -> tuple[bytes, any] | None:
    """Parse a file with tree-sitter.

    Args:
        file_path: Path to file to parse
        language: Language identifier

    Returns:
        Tuple of (source_bytes, tree) or None if parsing failed
    """
    parser = get_parser(language)
    if not parser:
        return None

    try:
        with open(file_path, "rb") as f:
            source = f.read()

        tree = parser.parse(source)
        return (source, tree)

    except Exception:
        return None
