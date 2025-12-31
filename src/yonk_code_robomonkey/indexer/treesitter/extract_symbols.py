"""Extract symbol definitions from parsed trees.

Extracts functions, classes, methods, interfaces from Python, JS/TS, Go, Java.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator
import hashlib


@dataclass
class Symbol:
    """Extracted symbol information."""
    fqn: str  # Fully qualified name
    name: str  # Simple name
    kind: str  # function, class, method, interface, etc.
    signature: str  # Best-effort signature
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    docstring: str | None
    hash: str  # Hash of symbol content


def extract_symbols(
    source: bytes,
    tree: any,
    language: str,
    file_path: str = ""
) -> list[Symbol]:
    """Extract all symbols from a parsed tree.

    Args:
        source: Source code bytes
        tree: Tree-sitter parse tree
        language: Language identifier
        file_path: File path for FQN generation

    Returns:
        List of extracted symbols
    """
    extractors = {
        "python": _extract_python_symbols,
        "javascript": _extract_javascript_symbols,
        "typescript": _extract_typescript_symbols,
        "go": _extract_go_symbols,
        "java": _extract_java_symbols,
    }

    extractor = extractors.get(language)
    if not extractor:
        return []

    return list(extractor(source, tree, file_path))


def _extract_python_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract Python functions and classes."""
    root = tree.root_node

    # Keep track of nodes we've already processed (to avoid duplicates)
    processed = set()

    # Find all function and class definitions at module level
    for node in root.children:
        if node.type == "function_definition" and node.id not in processed:
            processed.add(node.id)
            yield _extract_python_function(source, node, [])

        elif node.type == "class_definition" and node.id not in processed:
            processed.add(node.id)
            # Extract class
            class_symbol = _extract_python_class(source, node)
            yield class_symbol

            # Extract methods
            class_name = class_symbol.name
            body = _find_child(node, "block")
            if body:
                for child in body.children:
                    if child.type == "function_definition" and child.id not in processed:
                        processed.add(child.id)
                        yield _extract_python_function(source, child, [class_name])


def _extract_python_function(source: bytes, node: any, parents: list[str]) -> Symbol:
    """Extract a Python function or method."""
    # Get function name
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "unknown"

    # Build FQN
    fqn = ".".join(parents + [name]) if parents else name

    # Get parameters for signature
    params_node = _find_child(node, "parameters")
    params = _get_text(source, params_node) if params_node else "()"

    # Determine kind
    kind = "method" if parents else "function"

    # Extract docstring
    docstring = _extract_python_docstring(source, node)

    # Get positions
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    start_byte = node.start_byte
    end_byte = node.end_byte

    # Calculate hash
    content = source[start_byte:end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=fqn,
        name=name,
        kind=kind,
        signature=f"{name}{params}",
        start_line=start_line,
        end_line=end_line,
        start_byte=start_byte,
        end_byte=end_byte,
        docstring=docstring,
        hash=content_hash
    )


def _extract_python_class(source: bytes, node: any) -> Symbol:
    """Extract a Python class."""
    # Get class name
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "unknown"

    # Get base classes if any
    bases_node = _find_child(node, "argument_list")
    bases = _get_text(source, bases_node) if bases_node else ""

    # Extract docstring
    docstring = _extract_python_docstring(source, node)

    # Get positions
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    start_byte = node.start_byte
    end_byte = node.end_byte

    # Calculate hash
    content = source[start_byte:end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=name,
        name=name,
        kind="class",
        signature=f"class {name}{bases}",
        start_line=start_line,
        end_line=end_line,
        start_byte=start_byte,
        end_byte=end_byte,
        docstring=docstring,
        hash=content_hash
    )


def _extract_python_docstring(source: bytes, node: any) -> str | None:
    """Extract docstring from Python function or class."""
    body = _find_child(node, "block")
    if not body or not body.children:
        return None

    # Check first statement in body
    first_stmt = body.children[0]
    if first_stmt.type == "expression_statement":
        expr = first_stmt.children[0] if first_stmt.children else None
        if expr and expr.type == "string":
            text = _get_text(source, expr)
            # Remove quotes
            return text.strip('"""').strip("'''").strip('"').strip("'").strip()

    return None


def _extract_javascript_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract JavaScript functions and classes."""
    root = tree.root_node

    for node in _traverse_tree(root):
        if node.type == "function_declaration":
            yield _extract_js_function(source, node, [])

        elif node.type == "class_declaration":
            class_symbol = _extract_js_class(source, node)
            yield class_symbol

            # Extract methods
            class_name = class_symbol.name
            body = _find_child(node, "class_body")
            if body:
                for child in body.children:
                    if child.type == "method_definition":
                        yield _extract_js_method(source, child, [class_name])


def _extract_js_function(source: bytes, node: any, parents: list[str]) -> Symbol:
    """Extract JavaScript function."""
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "anonymous"

    fqn = ".".join(parents + [name]) if parents else name

    params_node = _find_child(node, "formal_parameters")
    params = _get_text(source, params_node) if params_node else "()"

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = source[node.start_byte:node.end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=fqn,
        name=name,
        kind="function",
        signature=f"function {name}{params}",
        start_line=start_line,
        end_line=end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        docstring=None,
        hash=content_hash
    )


def _extract_js_class(source: bytes, node: any) -> Symbol:
    """Extract JavaScript class."""
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "anonymous"

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = source[node.start_byte:node.end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=name,
        name=name,
        kind="class",
        signature=f"class {name}",
        start_line=start_line,
        end_line=end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        docstring=None,
        hash=content_hash
    )


def _extract_js_method(source: bytes, node: any, parents: list[str]) -> Symbol:
    """Extract JavaScript method."""
    # Get method name
    name_node = _find_child(node, "property_identifier")
    name = _get_text(source, name_node) if name_node else "unknown"

    fqn = ".".join(parents + [name])

    params_node = _find_child(node, "formal_parameters")
    params = _get_text(source, params_node) if params_node else "()"

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = source[node.start_byte:node.end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=fqn,
        name=name,
        kind="method",
        signature=f"{name}{params}",
        start_line=start_line,
        end_line=end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        docstring=None,
        hash=content_hash
    )


def _extract_typescript_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract TypeScript symbols (similar to JavaScript with interfaces)."""
    # Start with JavaScript extraction
    yield from _extract_javascript_symbols(source, tree, file_path)

    # Add TypeScript-specific: interfaces
    root = tree.root_node
    for node in _traverse_tree(root):
        if node.type == "interface_declaration":
            name_node = _find_child(node, "type_identifier")
            name = _get_text(source, name_node) if name_node else "unknown"

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte]
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            yield Symbol(
                fqn=name,
                name=name,
                kind="interface",
                signature=f"interface {name}",
                start_line=start_line,
                end_line=end_line,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                docstring=None,
                hash=content_hash
            )


def _extract_go_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract Go functions and types."""
    root = tree.root_node

    for node in _traverse_tree(root):
        if node.type == "function_declaration":
            name_node = _find_child(node, "identifier")
            name = _get_text(source, name_node) if name_node else "unknown"

            params_node = _find_child(node, "parameter_list")
            params = _get_text(source, params_node) if params_node else "()"

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte]
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            yield Symbol(
                fqn=name,
                name=name,
                kind="function",
                signature=f"func {name}{params}",
                start_line=start_line,
                end_line=end_line,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                docstring=None,
                hash=content_hash
            )

        elif node.type == "method_declaration":
            name_node = _find_child(node, "field_identifier")
            name = _get_text(source, name_node) if name_node else "unknown"

            receiver = _find_child(node, "parameter_list")
            receiver_text = _get_text(source, receiver) if receiver else ""

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte]
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            yield Symbol(
                fqn=name,
                name=name,
                kind="method",
                signature=f"func {receiver_text} {name}",
                start_line=start_line,
                end_line=end_line,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                docstring=None,
                hash=content_hash
            )


def _extract_java_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract Java classes and methods."""
    root = tree.root_node

    for node in _traverse_tree(root):
        if node.type == "class_declaration":
            class_symbol = _extract_java_class(source, node)
            yield class_symbol

            # Extract methods
            class_name = class_symbol.name
            body = _find_child(node, "class_body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        yield _extract_java_method(source, child, [class_name])

        elif node.type == "interface_declaration":
            name_node = _find_child(node, "identifier")
            name = _get_text(source, name_node) if name_node else "unknown"

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte]
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            yield Symbol(
                fqn=name,
                name=name,
                kind="interface",
                signature=f"interface {name}",
                start_line=start_line,
                end_line=end_line,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                docstring=None,
                hash=content_hash
            )


def _extract_java_class(source: bytes, node: any) -> Symbol:
    """Extract Java class."""
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "unknown"

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = source[node.start_byte:node.end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=name,
        name=name,
        kind="class",
        signature=f"class {name}",
        start_line=start_line,
        end_line=end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        docstring=None,
        hash=content_hash
    )


def _extract_java_method(source: bytes, node: any, parents: list[str]) -> Symbol:
    """Extract Java method."""
    name_node = _find_child(node, "identifier")
    name = _get_text(source, name_node) if name_node else "unknown"

    fqn = ".".join(parents + [name])

    params_node = _find_child(node, "formal_parameters")
    params = _get_text(source, params_node) if params_node else "()"

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = source[node.start_byte:node.end_byte]
    content_hash = hashlib.sha256(content).hexdigest()[:16]

    return Symbol(
        fqn=fqn,
        name=name,
        kind="method",
        signature=f"{name}{params}",
        start_line=start_line,
        end_line=end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        docstring=None,
        hash=content_hash
    )


# Helper functions

def _traverse_tree(node: any) -> Iterator[any]:
    """Traverse tree depth-first."""
    yield node
    for child in node.children:
        yield from _traverse_tree(child)


def _find_child(node: any, child_type: str) -> any | None:
    """Find first child of given type."""
    for child in node.children:
        if child.type == child_type:
            return child
    return None


def _get_text(source: bytes, node: any) -> str:
    """Get text for a node."""
    if not node:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
