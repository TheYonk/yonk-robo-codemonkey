# Java and C Call Graph Extraction Design

Add call graph (CALLS edge) extraction support for Java and C languages.

## Current State

- **Java**: Symbol extraction exists, inheritance/implements exists, but NO CALLS extraction
- **C**: Not supported at all (no language detection, no parsing, no extraction)

## Todo List

- [x] Research current implementation patterns
- [x] Add Java call extraction (`_extract_java_calls`)
- [x] Add C language detection (`.c`, `.h` extensions)
- [x] Add C parser support
- [x] Add C symbol extraction (functions, structs, typedefs)
- [x] Add C edge extraction (includes, calls)
- [x] Test implementations
- [x] Update CLAUDE.md language support table

## Implementation Plan

### 1. Java Call Extraction

Add `_extract_java_calls()` function to `extract_edges.py`:

```python
def _extract_java_calls(source: bytes, root: any) -> Iterator[Edge]:
    """Extract Java method calls (best-effort)."""
    current_method = None

    for node in _traverse_tree(root):
        # Track current method context
        if node.type == "method_declaration":
            name_node = _find_child(node, "identifier")
            if name_node:
                current_method = _get_text(source, name_node)

        # Find method invocations
        if node.type == "method_invocation" and current_method:
            # Get method name being called
            # Handles: foo(), obj.foo(), this.foo()
            ...
```

Tree-sitter Java node types for calls:
- `method_invocation` - method call
- `object_creation_expression` - new ClassName()

### 2. C Language Support

#### a. Language Detection (`language_detect.py`)

```python
Language = Literal["python", "javascript", "typescript", "go", "java", "c", "sql", "unknown"]

EXTENSION_MAP = {
    # C
    ".c": "c",
    ".h": "c",
    ".cc": "c",  # Could also be C++ but we'll treat as C
    ...
}
```

#### b. Parser Support (`parsers.py`)

```python
lang_map = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "go": "go",
    "java": "java",
    "c": "c",
}
```

#### c. Symbol Extraction (`extract_symbols.py`)

C symbols to extract:
- Functions: `function_definition`
- Structs: `struct_specifier`
- Typedefs: `type_definition`
- Enums: `enum_specifier`

```python
def _extract_c_symbols(source: bytes, tree: any, file_path: str) -> Iterator[Symbol]:
    """Extract C symbols: functions, structs, typedefs."""
    root = tree.root_node

    for node in _traverse_tree(root):
        if node.type == "function_definition":
            yield _extract_c_function(source, node)
        elif node.type == "struct_specifier":
            # Only if it has a name
            ...
```

#### d. Edge Extraction (`extract_edges.py`)

C edges to extract:
- IMPORTS: `#include <header.h>` or `#include "header.h"`
- CALLS: function calls

```python
def _extract_c_edges(source: bytes, tree: any, file_path: str) -> Iterator[Edge]:
    """Extract C edges: includes, calls."""
    root = tree.root_node

    yield from _extract_c_includes(source, root)
    yield from _extract_c_calls(source, root)

def _extract_c_includes(source: bytes, root: any) -> Iterator[Edge]:
    """Extract #include directives."""
    for node in _traverse_tree(root):
        if node.type == "preproc_include":
            # Get included file: <stdio.h> or "myheader.h"
            ...

def _extract_c_calls(source: bytes, root: any) -> Iterator[Edge]:
    """Extract C function calls."""
    current_function = None

    for node in _traverse_tree(root):
        if node.type == "function_definition":
            # Get function name from declarator
            ...

        if node.type == "call_expression" and current_function:
            # Get called function name
            ...
```

## Tree-sitter Node Types Reference

### Java
- `method_declaration` - method definition
- `method_invocation` - method call
- `object_creation_expression` - new Foo()
- `identifier` - simple name

### C
- `function_definition` - function def
- `function_declarator` - function name and params
- `call_expression` - function call
- `preproc_include` - #include directive
- `system_lib_string` - <header.h>
- `string_literal` - "header.h"
- `struct_specifier` - struct definition
- `type_definition` - typedef

## Testing

Test files needed:
- `tests/fixtures/java_calls.java` - Java with method calls
- `tests/fixtures/c_calls.c` - C with function calls

## Notes

- C has no built-in OOP, so no inheritance edges
- C++ could be added later (more complex with classes, templates)
- Header files (.h) will be parsed as C

---

## Implementation Details

### Files Modified

1. **`src/yonk_code_robomonkey/indexer/language_detect.py`**
   - Added `"c"` to Language type
   - Added `.c` and `.h` extensions to EXTENSION_MAP

2. **`src/yonk_code_robomonkey/indexer/treesitter/parsers.py`**
   - Added `"c": "c"` to lang_map

3. **`src/yonk_code_robomonkey/indexer/treesitter/extract_symbols.py`**
   - Added `"c": _extract_c_symbols` to extractors
   - Added `_extract_c_symbols()` - extracts functions, structs, typedefs
   - Added `_extract_c_function()` - handles function definitions
   - Added `_extract_c_struct()` - handles named struct specifiers
   - Added `_extract_c_typedef()` - handles typedef declarations

4. **`src/yonk_code_robomonkey/indexer/treesitter/extract_edges.py`**
   - Added `"c": _extract_c_edges` to extractors
   - Added `_extract_java_calls()` - extracts method_invocation and object_creation_expression
   - Added `_extract_c_edges()` - orchestrates C edge extraction
   - Added `_extract_c_includes()` - extracts #include directives (system and local)
   - Added `_extract_c_calls()` - extracts call_expression within functions

### Test Results

**Java:**
```
Symbols found: 3
  class: Calculator
  method: Calculator.add
  method: Calculator.multiply
CALLS edges found: 3
  multiply -> add
  multiply -> Helper (constructor)
  multiply -> helper.compute
```

**C:**
```
Symbols found: 4
  typedef: Point
  struct: Node
  function: add
  function: main
IMPORTS edges found: 2
  -> stdio.h
  -> myheader.h
CALLS edges found: 2
  main -> add
  main -> printf
```

### Notes

- Java call extraction handles both method calls and constructor calls (`new ClassName()`)
- C struct extraction deduplicates to avoid extracting the same struct twice
- C #include extracts both system includes (`<header.h>`) and local includes (`"header.h"`)
- C function extraction handles pointer-returning functions via pointer_declarator
