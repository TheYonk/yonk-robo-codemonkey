"""Extract edges (imports, calls, inheritance) from parsed trees.

Best-effort extraction for:
- IMPORTS: Module/package imports
- CALLS: Function/method calls (intra-repo)
- INHERITS: Class inheritance
- IMPLEMENTS: Interface implementations (Java/TypeScript)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator


@dataclass
class Edge:
    """Extracted edge information.

    Note: from_symbol_fqn and to_symbol_fqn are string names that will be
    resolved to symbol IDs by the indexer when storing in the database.
    """
    edge_type: str  # IMPORTS, CALLS, INHERITS, IMPLEMENTS
    from_symbol_fqn: str | None  # Source symbol FQN, None for file-level imports
    to_symbol_fqn: str  # Target symbol FQN or import path
    confidence: float  # 0.0-1.0, best-effort matching
    evidence_start_line: int
    evidence_end_line: int


def extract_edges(
    source: bytes,
    tree: any,
    language: str,
    file_path: str = ""
) -> list[Edge]:
    """Extract all edges from a parsed tree.

    Args:
        source: Source code bytes
        tree: Tree-sitter parse tree
        language: Language identifier
        file_path: File path for context

    Returns:
        List of extracted edges
    """
    extractors = {
        "python": _extract_python_edges,
        "javascript": _extract_javascript_edges,
        "typescript": _extract_typescript_edges,
        "go": _extract_go_edges,
        "java": _extract_java_edges,
    }

    extractor = extractors.get(language)
    if not extractor:
        return []

    return list(extractor(source, tree, file_path))


# Python edge extraction

def _extract_python_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract Python edges: imports, calls, inheritance."""
    root = tree.root_node

    # Extract imports (file-level)
    yield from _extract_python_imports(source, root)

    # Extract inheritance
    yield from _extract_python_inheritance(source, root)

    # Extract calls (best-effort)
    yield from _extract_python_calls(source, root)


def _extract_python_imports(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Python import statements."""
    for node in _traverse_tree(root):
        if node.type == "import_statement":
            # import foo, bar
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            for child in node.children:
                if child.type == "dotted_name":
                    module_name = _get_text(source, child)
                    yield Edge(
                        edge_type="IMPORTS",
                        from_symbol_fqn=None,  # File-level import
                        to_symbol_fqn=module_name,
                        confidence=1.0,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )

        elif node.type == "import_from_statement":
            # from foo import bar
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Get module name
            module_name = ""
            for child in node.children:
                if child.type == "dotted_name":
                    module_name = _get_text(source, child)
                    break

            # Get imported names
            for child in node.children:
                if child.type == "dotted_name" and _get_text(source, child) != module_name:
                    imported_name = _get_text(source, child)
                    full_name = f"{module_name}.{imported_name}" if module_name else imported_name
                    yield Edge(
                        edge_type="IMPORTS",
                        from_symbol_fqn=None,
                        to_symbol_fqn=full_name,
                        confidence=1.0,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )


def _extract_python_inheritance(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Python class inheritance."""
    for node in _traverse_tree(root):
        if node.type == "class_definition":
            # Get class name
            class_name_node = _find_child(node, "identifier")
            if not class_name_node:
                continue
            class_name = _get_text(source, class_name_node)

            # Get base classes
            arg_list = _find_child(node, "argument_list")
            if not arg_list:
                continue

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            for child in arg_list.children:
                if child.type == "identifier":
                    base_class = _get_text(source, child)
                    yield Edge(
                        edge_type="INHERITS",
                        from_symbol_fqn=class_name,
                        to_symbol_fqn=base_class,
                        confidence=0.8,  # Best-effort, may not resolve
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )
                elif child.type == "attribute":
                    # Handles module.ClassName
                    base_class = _get_text(source, child)
                    yield Edge(
                        edge_type="INHERITS",
                        from_symbol_fqn=class_name,
                        to_symbol_fqn=base_class,
                        confidence=0.7,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )


def _extract_python_calls(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Python function calls (best-effort, simple names only)."""
    # Track function/method definitions to get caller context
    current_function = None

    for node in _traverse_tree(root):
        # Track current function context
        if node.type == "function_definition":
            name_node = _find_child(node, "identifier")
            if name_node:
                current_function = _get_text(source, name_node)

        # Find call expressions
        if node.type == "call" and current_function:
            # Get function being called
            func_node = node.children[0] if node.children else None
            if not func_node:
                continue

            # Only handle simple identifier calls (not method calls)
            if func_node.type == "identifier":
                called_name = _get_text(source, func_node)
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                yield Edge(
                    edge_type="CALLS",
                    from_symbol_fqn=current_function,
                    to_symbol_fqn=called_name,
                    confidence=0.5,  # Very best-effort
                    evidence_start_line=start_line,
                    evidence_end_line=end_line
                )


# JavaScript/TypeScript edge extraction

def _extract_javascript_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract JavaScript edges: imports, calls, inheritance."""
    root = tree.root_node

    yield from _extract_javascript_imports(source, root)
    yield from _extract_javascript_inheritance(source, root)


def _extract_javascript_imports(source: bytes, root: any) -> Iterator[Edge]:
    """Extract JavaScript/ES6 import statements."""
    for node in _traverse_tree(root):
        if node.type == "import_statement":
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Get source module
            source_node = _find_child(node, "string")
            if source_node:
                module_path = _get_text(source, source_node).strip('"').strip("'")
                yield Edge(
                    edge_type="IMPORTS",
                    from_symbol_fqn=None,
                    to_symbol_fqn=module_path,
                    confidence=1.0,
                    evidence_start_line=start_line,
                    evidence_end_line=end_line
                )


def _extract_javascript_inheritance(source: bytes, root: any) -> Iterator[Edge]:
    """Extract JavaScript class inheritance."""
    for node in _traverse_tree(root):
        if node.type == "class_declaration":
            # Get class name
            class_name_node = _find_child(node, "identifier")
            if not class_name_node:
                continue
            class_name = _get_text(source, class_name_node)

            # Get extends clause
            heritage = _find_child(node, "class_heritage")
            if not heritage:
                continue

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            for child in heritage.children:
                if child.type == "identifier":
                    base_class = _get_text(source, child)
                    yield Edge(
                        edge_type="INHERITS",
                        from_symbol_fqn=class_name,
                        to_symbol_fqn=base_class,
                        confidence=0.8,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )


def _extract_typescript_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract TypeScript edges: imports, inheritance, implements."""
    # Start with JavaScript edges
    yield from _extract_javascript_edges(source, tree, file_path)

    # Add TypeScript-specific: implements
    root = tree.root_node
    for node in _traverse_tree(root):
        if node.type == "class_declaration":
            class_name_node = _find_child(node, "identifier")
            if not class_name_node:
                continue
            class_name = _get_text(source, class_name_node)

            # Look for implements clause
            for child in node.children:
                if child.type == "class_heritage":
                    # Check if this is implements (not extends)
                    for heritage_child in child.children:
                        if heritage_child.type == "implements_clause":
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1

                            for impl_child in heritage_child.children:
                                if impl_child.type == "type_identifier":
                                    interface_name = _get_text(source, impl_child)
                                    yield Edge(
                                        edge_type="IMPLEMENTS",
                                        from_symbol_fqn=class_name,
                                        to_symbol_fqn=interface_name,
                                        confidence=0.9,
                                        evidence_start_line=start_line,
                                        evidence_end_line=end_line
                                    )


# Go edge extraction

def _extract_go_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract Go edges: imports."""
    root = tree.root_node

    yield from _extract_go_imports(source, root)


def _extract_go_imports(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Go import declarations."""
    for node in _traverse_tree(root):
        if node.type == "import_declaration":
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Single import: import "fmt"
            import_spec = _find_child(node, "import_spec")
            if import_spec:
                path_node = _find_child(import_spec, "interpreted_string_literal")
                if path_node:
                    import_path = _get_text(source, path_node).strip('"')
                    yield Edge(
                        edge_type="IMPORTS",
                        from_symbol_fqn=None,
                        to_symbol_fqn=import_path,
                        confidence=1.0,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )

            # Import list: import ( "fmt"; "io" )
            import_spec_list = _find_child(node, "import_spec_list")
            if import_spec_list:
                for child in import_spec_list.children:
                    if child.type == "import_spec":
                        path_node = _find_child(child, "interpreted_string_literal")
                        if path_node:
                            import_path = _get_text(source, path_node).strip('"')
                            yield Edge(
                                edge_type="IMPORTS",
                                from_symbol_fqn=None,
                                to_symbol_fqn=import_path,
                                confidence=1.0,
                                evidence_start_line=start_line,
                                evidence_end_line=end_line
                            )


# Java edge extraction

def _extract_java_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract Java edges: imports, inheritance, implements."""
    root = tree.root_node

    yield from _extract_java_imports(source, root)
    yield from _extract_java_inheritance(source, root)


def _extract_java_imports(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Java import statements."""
    for node in _traverse_tree(root):
        if node.type == "import_declaration":
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Get scoped identifier (package.Class)
            for child in node.children:
                if child.type == "scoped_identifier":
                    import_name = _get_text(source, child)
                    yield Edge(
                        edge_type="IMPORTS",
                        from_symbol_fqn=None,
                        to_symbol_fqn=import_name,
                        confidence=1.0,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )


def _extract_java_inheritance(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Java class inheritance and interface implementation."""
    for node in _traverse_tree(root):
        if node.type == "class_declaration":
            # Get class name
            class_name_node = _find_child(node, "identifier")
            if not class_name_node:
                continue
            class_name = _get_text(source, class_name_node)

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Check for extends
            superclass = _find_child(node, "superclass")
            if superclass:
                type_node = _find_child(superclass, "type_identifier")
                if type_node:
                    base_class = _get_text(source, type_node)
                    yield Edge(
                        edge_type="INHERITS",
                        from_symbol_fqn=class_name,
                        to_symbol_fqn=base_class,
                        confidence=0.9,
                        evidence_start_line=start_line,
                        evidence_end_line=end_line
                    )

            # Check for implements
            interfaces = _find_child(node, "super_interfaces")
            if interfaces:
                interface_list = _find_child(interfaces, "type_list")
                if interface_list:
                    for child in interface_list.children:
                        if child.type == "type_identifier":
                            interface_name = _get_text(source, child)
                            yield Edge(
                                edge_type="IMPLEMENTS",
                                from_symbol_fqn=class_name,
                                to_symbol_fqn=interface_name,
                                confidence=0.9,
                                evidence_start_line=start_line,
                                evidence_end_line=end_line
                            )


# Helper functions (same as extract_symbols.py)

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
