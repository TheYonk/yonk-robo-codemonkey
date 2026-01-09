"""Extract code references from documentation.

Parses markdown, reStructuredText, and AsciiDoc documents to find
references to code elements (functions, classes, files, imports).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class CodeReference:
    """A code reference extracted from documentation."""
    text: str                          # The raw reference text
    ref_type: str                      # 'symbol', 'file', 'import', 'module', 'code_block'
    line_number: int | None = None     # Line in document
    context: str = ""                  # Surrounding text for disambiguation
    confidence: float = 1.0            # Extraction confidence (0-1.0)
    expected_kind: str | None = None   # 'function', 'class', 'method', 'variable', etc.


# Code file extensions to recognize
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.rs', '.rb',
    '.cpp', '.c', '.h', '.hpp', '.cs', '.php', '.swift', '.kt', '.scala',
    '.yaml', '.yml', '.json', '.toml', '.sql', '.sh', '.bash'
}

# Patterns for extracting code references
MARKDOWN_PATTERNS = {
    # Inline code: `function_name()` or `ClassName`
    'inline_code': re.compile(r'`([^`\n]+)`'),

    # Fenced code blocks: ```python ... ```
    'code_block': re.compile(r'```(\w*)\n([\s\S]*?)```'),

    # Links to files: [text](file.py) or [text](path/to/file.py)
    'link_file': re.compile(r'\[([^\]]*)\]\(([^)]+\.(?:py|js|ts|tsx|jsx|go|java|rs|rb|cpp|c|h|yaml|yml|json|sql))\)'),

    # File paths in text: src/api/routes.py, ./config.yaml
    'file_path': re.compile(r'(?:^|[\s\(\[\{])([a-zA-Z0-9_./\-]+\.(?:py|js|ts|tsx|jsx|go|java|rs|rb|cpp|c|h|hpp|yaml|yml|json|toml|sql|sh))(?:[\s\)\]\}:,]|$)', re.MULTILINE),
}

RST_PATTERNS = {
    # Inline code: ``function_name()``
    'inline_code': re.compile(r'``([^`]+)``'),

    # Python role references: :py:func:`function_name`
    'py_role': re.compile(r':py:(?:func|class|meth|attr|mod|data|const|obj|exc)`([^`]+)`'),

    # Generic role references: :ref:`label`
    'role_ref': re.compile(r':(?:ref|doc|mod|func|class|meth)`([^`]+)`'),
}

ASCIIDOC_PATTERNS = {
    # Inline code: `function_name()`
    'inline_code': re.compile(r'`([^`]+)`'),

    # Source blocks: [source,python]\n----\n...\n----
    'code_block': re.compile(r'\[source,(\w+)\]\n----\n([\s\S]*?)\n----'),
}

# Patterns for identifying code constructs within inline code
CODE_CONSTRUCT_PATTERNS = {
    # Function calls: function_name() or module.function()
    'function_call': re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*\('),

    # Class names (PascalCase)
    'class_name': re.compile(r'^([A-Z][a-zA-Z0-9_]*)$'),

    # Method calls: obj.method() or Class.method()
    'method_call': re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\s*\('),

    # Module paths: module.submodule or package.module
    'module_path': re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)$'),

    # Simple identifiers: variable_name or CONSTANT_NAME
    'identifier': re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)$'),

    # Import statements: from x import y or import x
    'import_stmt': re.compile(r'^(?:from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+)?import\s+([a-zA-Z_][a-zA-Z0-9_.,\s]*)'),

    # Decorator: @decorator_name
    'decorator': re.compile(r'^@([a-zA-Z_][a-zA-Z0-9_.]*)'),
}


def extract_references(
    content: str,
    doc_type: str = "markdown",
    max_references: int = 100
) -> list[CodeReference]:
    """Extract code references from document content.

    Args:
        content: Document content
        doc_type: Document type ('markdown', 'rst', 'asciidoc')
        max_references: Maximum number of references to extract

    Returns:
        List of CodeReference objects
    """
    references: list[CodeReference] = []
    seen_refs: set[str] = set()

    # Select patterns based on document type
    if doc_type in ('rst', 'restructuredtext'):
        patterns = RST_PATTERNS
    elif doc_type == 'asciidoc':
        patterns = ASCIIDOC_PATTERNS
    else:
        patterns = MARKDOWN_PATTERNS

    lines = content.split('\n')

    # Extract inline code references
    if 'inline_code' in patterns:
        for ref in _extract_inline_code(content, lines, patterns['inline_code'], seen_refs):
            references.append(ref)
            if len(references) >= max_references:
                return references

    # Extract file path references
    if 'file_path' in patterns:
        for ref in _extract_file_paths(content, lines, patterns['file_path'], seen_refs):
            references.append(ref)
            if len(references) >= max_references:
                return references

    # Extract link file references
    if 'link_file' in patterns:
        for ref in _extract_link_files(content, lines, patterns['link_file'], seen_refs):
            references.append(ref)
            if len(references) >= max_references:
                return references

    # Extract code block references
    if 'code_block' in patterns:
        for ref in _extract_code_blocks(content, patterns['code_block'], seen_refs):
            references.append(ref)
            if len(references) >= max_references:
                return references

    # Extract RST role references
    if 'py_role' in patterns:
        for ref in _extract_rst_roles(content, lines, patterns['py_role'], seen_refs):
            references.append(ref)
            if len(references) >= max_references:
                return references

    return references


def _extract_inline_code(
    content: str,
    lines: list[str],
    pattern: re.Pattern,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract references from inline code spans."""
    for match in pattern.finditer(content):
        code_text = match.group(1).strip()

        # Skip if already seen or too short/long
        if code_text in seen or len(code_text) < 2 or len(code_text) > 200:
            continue

        # Skip common non-code patterns
        if _is_likely_prose(code_text):
            continue

        seen.add(code_text)

        # Find line number
        line_num = _find_line_number(content, match.start(), lines)

        # Determine reference type and expected kind
        ref_type, expected_kind, confidence = _classify_code_reference(code_text)

        if ref_type:
            yield CodeReference(
                text=code_text,
                ref_type=ref_type,
                line_number=line_num,
                context=_get_context(content, match.start(), match.end()),
                confidence=confidence,
                expected_kind=expected_kind
            )


def _extract_file_paths(
    content: str,
    lines: list[str],
    pattern: re.Pattern,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract file path references."""
    for match in pattern.finditer(content):
        file_path = match.group(1).strip()

        if file_path in seen:
            continue

        # Validate it looks like a real file path
        if not _is_valid_file_path(file_path):
            continue

        seen.add(file_path)
        line_num = _find_line_number(content, match.start(), lines)

        yield CodeReference(
            text=file_path,
            ref_type='file',
            line_number=line_num,
            context=_get_context(content, match.start(), match.end()),
            confidence=0.9,
            expected_kind='file'
        )


def _extract_link_files(
    content: str,
    lines: list[str],
    pattern: re.Pattern,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract file paths from markdown links."""
    for match in pattern.finditer(content):
        file_path = match.group(2).strip()

        if file_path in seen:
            continue

        seen.add(file_path)
        line_num = _find_line_number(content, match.start(), lines)

        yield CodeReference(
            text=file_path,
            ref_type='file',
            line_number=line_num,
            context=match.group(1),  # Use link text as context
            confidence=0.95,
            expected_kind='file'
        )


def _extract_code_blocks(
    content: str,
    pattern: re.Pattern,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract references from code blocks."""
    for match in pattern.finditer(content):
        language = match.group(1).lower() if match.group(1) else ""
        code_content = match.group(2)

        # Extract imports from code blocks
        for ref in _extract_imports_from_code(code_content, language, seen):
            yield ref

        # Extract function/class definitions from code blocks
        for ref in _extract_definitions_from_code(code_content, language, seen):
            yield ref


def _extract_imports_from_code(
    code: str,
    language: str,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract import statements from code blocks."""
    if language not in ('python', 'py', 'javascript', 'js', 'typescript', 'ts', ''):
        return

    # Python imports
    python_import = re.compile(r'^(?:from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+)?import\s+([a-zA-Z_][a-zA-Z0-9_.,\s]*)', re.MULTILINE)

    for match in python_import.finditer(code):
        from_module = match.group(1)
        imports = match.group(2)

        if from_module and from_module not in seen:
            seen.add(from_module)
            yield CodeReference(
                text=from_module,
                ref_type='import',
                confidence=0.95,
                expected_kind='module'
            )

        # Parse individual imports
        for imp in imports.split(','):
            imp = imp.strip().split(' as ')[0].strip()
            if imp and imp not in seen:
                seen.add(imp)
                yield CodeReference(
                    text=imp,
                    ref_type='import',
                    confidence=0.9,
                    expected_kind='module' if '.' in imp else 'symbol'
                )


def _extract_definitions_from_code(
    code: str,
    language: str,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract function/class definitions from code blocks."""
    # Python definitions
    if language in ('python', 'py', ''):
        # Functions: def function_name(
        func_pattern = re.compile(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.MULTILINE)
        for match in func_pattern.finditer(code):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                yield CodeReference(
                    text=name,
                    ref_type='symbol',
                    confidence=0.85,
                    expected_kind='function'
                )

        # Classes: class ClassName
        class_pattern = re.compile(r'^class\s+([A-Z][a-zA-Z0-9_]*)', re.MULTILINE)
        for match in class_pattern.finditer(code):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                yield CodeReference(
                    text=name,
                    ref_type='symbol',
                    confidence=0.85,
                    expected_kind='class'
                )

    # JavaScript/TypeScript definitions
    if language in ('javascript', 'js', 'typescript', 'ts', ''):
        # Functions: function name( or const name = (
        func_pattern = re.compile(r'(?:function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s*)?\()', re.MULTILINE)
        for match in func_pattern.finditer(code):
            name = match.group(1) or match.group(2)
            if name and name not in seen:
                seen.add(name)
                yield CodeReference(
                    text=name,
                    ref_type='symbol',
                    confidence=0.8,
                    expected_kind='function'
                )


def _extract_rst_roles(
    content: str,
    lines: list[str],
    pattern: re.Pattern,
    seen: set[str]
) -> Iterator[CodeReference]:
    """Extract references from RST role syntax."""
    for match in pattern.finditer(content):
        ref_text = match.group(1).strip()

        if ref_text in seen:
            continue

        seen.add(ref_text)
        line_num = _find_line_number(content, match.start(), lines)

        # Determine expected kind from role type
        role_match = re.search(r':py:(\w+):', match.group(0))
        expected_kind = None
        if role_match:
            role_type = role_match.group(1)
            kind_map = {
                'func': 'function',
                'class': 'class',
                'meth': 'method',
                'attr': 'attribute',
                'mod': 'module',
                'data': 'variable',
                'const': 'constant',
            }
            expected_kind = kind_map.get(role_type)

        yield CodeReference(
            text=ref_text,
            ref_type='symbol' if expected_kind != 'module' else 'module',
            line_number=line_num,
            context=_get_context(content, match.start(), match.end()),
            confidence=0.95,
            expected_kind=expected_kind
        )


def _classify_code_reference(code_text: str) -> tuple[str | None, str | None, float]:
    """Classify a code reference into type and expected kind.

    Returns:
        (ref_type, expected_kind, confidence)
    """
    # Check for file path
    if '/' in code_text or '\\' in code_text:
        ext = code_text.split('.')[-1] if '.' in code_text else ''
        if f'.{ext}' in CODE_EXTENSIONS:
            return ('file', 'file', 0.9)

    # Check for import statement
    if code_text.startswith('from ') or code_text.startswith('import '):
        return ('import', 'module', 0.9)

    # Check for decorator
    if code_text.startswith('@'):
        return ('symbol', 'decorator', 0.85)

    # Check for function call: name() or module.name()
    if CODE_CONSTRUCT_PATTERNS['function_call'].match(code_text):
        # Extract function name
        func_match = CODE_CONSTRUCT_PATTERNS['function_call'].match(code_text)
        if func_match:
            func_name = func_match.group(1)
            if '.' in func_name:
                return ('symbol', 'method', 0.85)
            return ('symbol', 'function', 0.85)

    # Check for class name (PascalCase)
    if CODE_CONSTRUCT_PATTERNS['class_name'].match(code_text):
        return ('symbol', 'class', 0.8)

    # Check for module path: module.submodule
    if CODE_CONSTRUCT_PATTERNS['module_path'].match(code_text):
        return ('module', 'module', 0.7)

    # Check for simple identifier
    if CODE_CONSTRUCT_PATTERNS['identifier'].match(code_text):
        # Could be function, class, variable, etc.
        if code_text.isupper():
            return ('symbol', 'constant', 0.7)
        elif code_text[0].isupper():
            return ('symbol', 'class', 0.75)
        else:
            return ('symbol', None, 0.6)  # Unknown kind

    return (None, None, 0.0)


def _is_likely_prose(text: str) -> bool:
    """Check if text is likely prose rather than code."""
    # Skip if contains spaces (likely prose or command)
    if ' ' in text and not text.startswith('from ') and not text.startswith('import '):
        # Allow module paths with spaces around operators
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', text.replace(' ', '')):
            return True

    # Skip common prose patterns
    prose_patterns = [
        r'^[a-z]+$',  # Single lowercase word (likely prose)
        r'^\d+$',     # Just numbers
        r'^[A-Z][a-z]+ [a-z]+',  # "Title case words"
    ]

    for pattern in prose_patterns:
        if re.match(pattern, text) and len(text) < 20:
            # Exception for common code terms
            code_terms = {'true', 'false', 'null', 'none', 'self', 'this', 'return', 'async', 'await'}
            if text.lower() not in code_terms:
                return True

    return False


def _is_valid_file_path(path: str) -> bool:
    """Check if a string looks like a valid file path."""
    # Must have a valid extension
    parts = path.split('.')
    if len(parts) < 2:
        return False

    ext = '.' + parts[-1]
    if ext not in CODE_EXTENSIONS:
        return False

    # Should not be too short or contain weird chars
    if len(path) < 3:
        return False

    # Should not start with certain patterns
    if path.startswith('http://') or path.startswith('https://'):
        return False

    return True


def _find_line_number(content: str, position: int, lines: list[str]) -> int:
    """Find the line number for a position in content."""
    newlines = content[:position].count('\n')
    return newlines + 1


def _get_context(content: str, start: int, end: int, context_chars: int = 50) -> str:
    """Get surrounding context for a match."""
    ctx_start = max(0, start - context_chars)
    ctx_end = min(len(content), end + context_chars)

    context = content[ctx_start:ctx_end].strip()
    # Clean up newlines
    context = ' '.join(context.split())

    return context
