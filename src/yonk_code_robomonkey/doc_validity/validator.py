"""Document validation logic.

Validates documentation against the codebase to detect stale references.
"""
from __future__ import annotations
import asyncpg
import hashlib
from dataclasses import dataclass, field
from typing import Any

from .reference_extractor import CodeReference, extract_references
from . import queries


@dataclass
class ValidationIssue:
    """An issue found during validation."""
    issue_type: str       # MISSING_SYMBOL, MISSING_FILE, INVALID_IMPORT, STALE_API, SEMANTIC_DRIFT
    severity: str         # error, warning, info
    reference_text: str   # The problematic reference
    reference_line: int | None = None
    expected_type: str | None = None
    found_match: str | None = None
    found_similarity: float | None = None
    suggestion: str | None = None


@dataclass
class ReferenceValidationResult:
    """Result of validating a single reference."""
    reference: CodeReference
    is_valid: bool
    issue: ValidationIssue | None = None
    matched_entity: dict[str, Any] | None = None


@dataclass
class ValidationResult:
    """Result of validating a document."""
    document_id: str
    references_checked: int
    references_valid: int
    issues: list[ValidationIssue] = field(default_factory=list)
    related_code_files: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str = ""


async def validate_reference(
    ref: CodeReference,
    repo_id: str,
    conn: asyncpg.Connection
) -> ReferenceValidationResult:
    """Validate a single code reference against the codebase.

    Args:
        ref: The code reference to validate
        repo_id: Repository UUID
        conn: Database connection

    Returns:
        ReferenceValidationResult with validation outcome
    """
    if ref.ref_type == 'file':
        return await _validate_file_reference(ref, repo_id, conn)
    elif ref.ref_type == 'symbol':
        return await _validate_symbol_reference(ref, repo_id, conn)
    elif ref.ref_type == 'import':
        return await _validate_import_reference(ref, repo_id, conn)
    elif ref.ref_type == 'module':
        return await _validate_module_reference(ref, repo_id, conn)
    else:
        # Unknown reference type - consider valid with low confidence
        return ReferenceValidationResult(
            reference=ref,
            is_valid=True,
            issue=None
        )


async def _validate_file_reference(
    ref: CodeReference,
    repo_id: str,
    conn: asyncpg.Connection
) -> ReferenceValidationResult:
    """Validate a file path reference."""
    file_record = await queries.find_file_by_path(conn, repo_id, ref.text)

    if file_record:
        return ReferenceValidationResult(
            reference=ref,
            is_valid=True,
            matched_entity=file_record
        )

    # Try to find similar files for suggestion
    suggestion = None
    closest_match = None
    similarity = 0.0

    # Extract filename from path
    filename = ref.text.split('/')[-1].split('\\')[-1]

    # Search for files with similar names
    similar_files = await conn.fetch(
        """
        SELECT path, similarity(path, $2) as sim
        FROM file
        WHERE repo_id = $1
          AND (path ILIKE '%' || $3 || '%' OR path ILIKE '%' || $2 || '%')
        ORDER BY similarity(path, $2) DESC
        LIMIT 3
        """,
        repo_id, ref.text, filename
    )

    if similar_files:
        closest_match = similar_files[0]['path']
        similarity = float(similar_files[0]['sim']) if similar_files[0]['sim'] else 0.0
        suggestion = f"File not found. Did you mean '{closest_match}'?"

    return ReferenceValidationResult(
        reference=ref,
        is_valid=False,
        issue=ValidationIssue(
            issue_type='MISSING_FILE',
            severity='warning',
            reference_text=ref.text,
            reference_line=ref.line_number,
            expected_type='file',
            found_match=closest_match,
            found_similarity=similarity,
            suggestion=suggestion or "File not found in codebase. Was it renamed or deleted?"
        )
    )


async def _validate_symbol_reference(
    ref: CodeReference,
    repo_id: str,
    conn: asyncpg.Connection
) -> ReferenceValidationResult:
    """Validate a symbol reference (function, class, method, etc.)."""
    # Extract the symbol name (remove parentheses, dots for method calls)
    symbol_name = ref.text
    if '(' in symbol_name:
        symbol_name = symbol_name.split('(')[0]
    if '.' in symbol_name:
        # For method calls like obj.method(), check for the method name
        parts = symbol_name.split('.')
        symbol_name = parts[-1]  # Use last part as primary search

    # Search for matching symbols
    matching_symbols = await queries.find_symbol_by_name(
        conn, repo_id, symbol_name, ref.expected_kind
    )

    if matching_symbols:
        # Check if we have an exact match
        for sym in matching_symbols:
            if sym['name'] == symbol_name:
                return ReferenceValidationResult(
                    reference=ref,
                    is_valid=True,
                    matched_entity=dict(sym)
                )

        # Close match found
        best_match = matching_symbols[0]
        similarity = float(best_match['sim']) if best_match.get('sim') else 0.8

        if similarity > 0.7:
            # Close enough to be considered valid with a suggestion
            return ReferenceValidationResult(
                reference=ref,
                is_valid=True,
                matched_entity=dict(best_match),
                issue=ValidationIssue(
                    issue_type='STALE_API',
                    severity='info',
                    reference_text=ref.text,
                    reference_line=ref.line_number,
                    expected_type=ref.expected_kind,
                    found_match=best_match['name'],
                    found_similarity=similarity,
                    suggestion=f"Found similar symbol '{best_match['name']}' ({best_match['kind']}). Consider updating reference."
                )
            )

    # No match found - search for any symbol containing the name
    fuzzy_matches = await conn.fetch(
        """
        SELECT name, kind, fqn, similarity(name, $2) as sim
        FROM symbol
        WHERE repo_id = $1
          AND (name ILIKE '%' || $2 || '%' OR fqn ILIKE '%' || $2 || '%')
        ORDER BY similarity(name, $2) DESC
        LIMIT 3
        """,
        repo_id, symbol_name
    )

    closest_match = None
    similarity = 0.0
    suggestion = None

    if fuzzy_matches:
        closest_match = fuzzy_matches[0]['name']
        similarity = float(fuzzy_matches[0]['sim']) if fuzzy_matches[0]['sim'] else 0.0
        suggestion = f"Symbol not found. Did you mean '{closest_match}' ({fuzzy_matches[0]['kind']})?"

    return ReferenceValidationResult(
        reference=ref,
        is_valid=False,
        issue=ValidationIssue(
            issue_type='MISSING_SYMBOL',
            severity='error' if ref.confidence > 0.8 else 'warning',
            reference_text=ref.text,
            reference_line=ref.line_number,
            expected_type=ref.expected_kind,
            found_match=closest_match,
            found_similarity=similarity,
            suggestion=suggestion or f"Symbol '{symbol_name}' not found in codebase."
        )
    )


async def _validate_import_reference(
    ref: CodeReference,
    repo_id: str,
    conn: asyncpg.Connection
) -> ReferenceValidationResult:
    """Validate an import reference (module/package)."""
    import_name = ref.text

    # Check if it's an internal module (file exists)
    # Convert module path to file path: foo.bar -> foo/bar.py
    possible_paths = [
        import_name.replace('.', '/') + '.py',
        import_name.replace('.', '/') + '/__init__.py',
        import_name.replace('.', '/'),
    ]

    for path in possible_paths:
        file_record = await queries.find_file_by_path(conn, repo_id, path)
        if file_record:
            return ReferenceValidationResult(
                reference=ref,
                is_valid=True,
                matched_entity=file_record
            )

    # Check if it matches any symbol (could be importing a function/class)
    matching_symbols = await queries.find_symbol_by_name(conn, repo_id, import_name)
    if matching_symbols:
        return ReferenceValidationResult(
            reference=ref,
            is_valid=True,
            matched_entity=dict(matching_symbols[0])
        )

    # Could be an external package - check if any file imports it
    import_check = await conn.fetchrow(
        """
        SELECT COUNT(*) as cnt FROM chunk
        WHERE repo_id = $1
          AND content ILIKE '%import%' || $2 || '%'
        LIMIT 1
        """,
        repo_id, import_name.split('.')[0]
    )

    if import_check and import_check['cnt'] > 0:
        # Found in imports, likely an external package
        return ReferenceValidationResult(
            reference=ref,
            is_valid=True,
            issue=ValidationIssue(
                issue_type='STALE_API',
                severity='info',
                reference_text=ref.text,
                reference_line=ref.line_number,
                expected_type='module',
                suggestion=f"'{import_name}' appears to be an external package. Verify it's still used."
            )
        )

    # Not found anywhere
    return ReferenceValidationResult(
        reference=ref,
        is_valid=False,
        issue=ValidationIssue(
            issue_type='INVALID_IMPORT',
            severity='warning',
            reference_text=ref.text,
            reference_line=ref.line_number,
            expected_type='module',
            suggestion=f"Module/package '{import_name}' not found. Was it removed or renamed?"
        )
    )


async def _validate_module_reference(
    ref: CodeReference,
    repo_id: str,
    conn: asyncpg.Connection
) -> ReferenceValidationResult:
    """Validate a module path reference."""
    module_path = ref.text

    # Convert module.submodule to directory path
    dir_path = module_path.replace('.', '/')

    # Check if directory exists (has files)
    files_in_module = await conn.fetch(
        """
        SELECT path FROM file
        WHERE repo_id = $1
          AND (path LIKE $2 || '/%' OR path LIKE $2 || '.%')
        LIMIT 1
        """,
        repo_id, dir_path
    )

    if files_in_module:
        return ReferenceValidationResult(
            reference=ref,
            is_valid=True,
            matched_entity={'path': dir_path, 'type': 'module'}
        )

    # Search for similar paths
    similar_modules = await conn.fetch(
        """
        SELECT DISTINCT
            SUBSTRING(path FROM 1 FOR POSITION('/' IN path || '/') - 1) as module_root
        FROM file
        WHERE repo_id = $1
          AND path ILIKE '%' || $2 || '%'
        LIMIT 3
        """,
        repo_id, module_path.split('.')[0]
    )

    suggestion = None
    if similar_modules:
        suggestion = f"Module not found. Similar: {', '.join(r['module_root'] for r in similar_modules if r['module_root'])}"

    return ReferenceValidationResult(
        reference=ref,
        is_valid=False,
        issue=ValidationIssue(
            issue_type='MISSING_FILE',
            severity='warning',
            reference_text=ref.text,
            reference_line=ref.line_number,
            expected_type='module',
            suggestion=suggestion or f"Module '{module_path}' not found in codebase."
        )
    )


async def validate_document(
    document_id: str,
    repo_id: str,
    conn: asyncpg.Connection,
    doc_type: str = "markdown",
    content: str | None = None,
    max_references: int = 100
) -> ValidationResult:
    """Validate all code references in a document.

    Args:
        document_id: Document UUID
        repo_id: Repository UUID
        conn: Database connection
        doc_type: Document type (markdown, rst, asciidoc)
        content: Document content (if None, will be fetched from DB)
        max_references: Maximum references to check

    Returns:
        ValidationResult with all issues found
    """
    # Get document content if not provided
    if content is None:
        doc = await queries.get_document_by_id(conn, document_id)
        if not doc:
            return ValidationResult(
                document_id=document_id,
                references_checked=0,
                references_valid=0,
                issues=[ValidationIssue(
                    issue_type='MISSING_FILE',
                    severity='error',
                    reference_text=document_id,
                    suggestion="Document not found in database"
                )],
                content_hash=""
            )
        content = doc['content']

    # Extract code references
    references = extract_references(content, doc_type, max_references)

    # Validate each reference
    issues: list[ValidationIssue] = []
    valid_count = 0

    for ref in references:
        result = await validate_reference(ref, repo_id, conn)
        if result.is_valid:
            valid_count += 1
        if result.issue:
            issues.append(result.issue)

    # Get related code files for freshness calculation
    doc_record = await queries.get_document_by_id(conn, document_id)
    related_files = []
    if doc_record and doc_record.get('path'):
        related_files = await queries.get_related_code_files(
            conn, repo_id, doc_record['path']
        )

    # Calculate content hash for caching
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    return ValidationResult(
        document_id=document_id,
        references_checked=len(references),
        references_valid=valid_count,
        issues=issues,
        related_code_files=related_files,
        content_hash=content_hash
    )
