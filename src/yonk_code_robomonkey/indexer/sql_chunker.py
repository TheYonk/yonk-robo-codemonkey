"""Smart SQL file chunker.

Chunks SQL files by statements, with options to skip data-heavy statements.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator
import re


@dataclass
class SQLStatement:
    """Parsed SQL statement."""
    statement_type: str  # CREATE, ALTER, INSERT, COPY, etc.
    content: str
    start_line: int
    end_line: int
    is_data_statement: bool  # True for INSERT, COPY, LOAD


@dataclass
class SQLChunk:
    """SQL chunk for indexing."""
    content: str
    start_line: int
    end_line: int
    statement_types: list[str]  # Types of statements in this chunk
    num_statements: int


def parse_sql_statements(
    sql_content: str,
    skip_data_statements: bool = False
) -> Iterator[SQLStatement]:
    """Parse SQL file into individual statements.

    Args:
        sql_content: SQL file content
        skip_data_statements: If True, skip INSERT, COPY, LOAD statements

    Yields:
        SQLStatement objects
    """
    lines = sql_content.split('\n')

    current_statement = []
    current_start_line = 0
    in_statement = False
    in_dollar_quote = False
    dollar_quote_tag = None

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip empty lines and comments outside statements
        if not in_statement and (not stripped or stripped.startswith('--')):
            continue

        # Check for dollar-quoted strings (PostgreSQL)
        # e.g., $$ or $tag$
        dollar_matches = re.finditer(r'\$(\w*)\$', line)
        for match in dollar_matches:
            tag = match.group(1)
            if not in_dollar_quote:
                in_dollar_quote = True
                dollar_quote_tag = tag
            elif tag == dollar_quote_tag:
                in_dollar_quote = False
                dollar_quote_tag = None

        # Start new statement
        if not in_statement and not stripped.startswith('--'):
            in_statement = True
            current_start_line = line_num
            current_statement = [line]
        else:
            current_statement.append(line)

        # Check for statement end (semicolon not in dollar quote)
        if in_statement and not in_dollar_quote and ';' in line:
            # Statement complete
            statement_content = '\n'.join(current_statement)
            statement_type = _get_statement_type(statement_content)
            is_data = _is_data_statement(statement_type)

            # Skip if requested
            if not (skip_data_statements and is_data):
                yield SQLStatement(
                    statement_type=statement_type,
                    content=statement_content,
                    start_line=current_start_line,
                    end_line=line_num,
                    is_data_statement=is_data
                )

            # Reset for next statement
            current_statement = []
            in_statement = False

    # Handle incomplete statement at end of file
    if current_statement:
        statement_content = '\n'.join(current_statement)
        statement_type = _get_statement_type(statement_content)
        is_data = _is_data_statement(statement_type)

        if not (skip_data_statements and is_data):
            yield SQLStatement(
                statement_type=statement_type,
                content=statement_content,
                start_line=current_start_line,
                end_line=len(lines),
                is_data_statement=is_data
            )


def chunk_sql_statements(
    statements: list[SQLStatement],
    max_chunk_size: int = 5000,  # characters
    max_statements_per_chunk: int = 50
) -> Iterator[SQLChunk]:
    """Group SQL statements into chunks.

    Groups related statements (e.g., CREATE TABLE + indexes) together.

    Args:
        statements: List of parsed statements
        max_chunk_size: Maximum chunk size in characters
        max_statements_per_chunk: Maximum statements per chunk

    Yields:
        SQLChunk objects
    """
    if not statements:
        return

    current_chunk_statements = []
    current_chunk_size = 0

    for stmt in statements:
        stmt_size = len(stmt.content)

        # Start new chunk if:
        # 1. Adding this would exceed max size
        # 2. We've hit max statements per chunk
        # 3. Statement type changes from schema to data or vice versa
        should_start_new = (
            (current_chunk_size + stmt_size > max_chunk_size and current_chunk_statements) or
            (len(current_chunk_statements) >= max_statements_per_chunk) or
            (current_chunk_statements and
             _is_schema_statement(current_chunk_statements[0].statement_type) !=
             _is_schema_statement(stmt.statement_type))
        )

        if should_start_new:
            # Yield current chunk
            yield _create_chunk(current_chunk_statements)
            current_chunk_statements = []
            current_chunk_size = 0

        # Add to current chunk
        current_chunk_statements.append(stmt)
        current_chunk_size += stmt_size

    # Yield final chunk
    if current_chunk_statements:
        yield _create_chunk(current_chunk_statements)


def chunk_sql_file(
    sql_content: str,
    skip_data_statements: bool = False,
    max_chunk_size: int = 5000,
    max_statements_per_chunk: int = 50
) -> Iterator[SQLChunk]:
    """Chunk SQL file for indexing.

    Convenience function that parses and chunks in one step.

    Args:
        sql_content: SQL file content
        skip_data_statements: If True, skip INSERT/COPY/LOAD statements
        max_chunk_size: Maximum chunk size in characters
        max_statements_per_chunk: Maximum statements per chunk

    Yields:
        SQLChunk objects ready for indexing
    """
    statements = list(parse_sql_statements(sql_content, skip_data_statements))
    yield from chunk_sql_statements(statements, max_chunk_size, max_statements_per_chunk)


# Helper functions

def _get_statement_type(statement: str) -> str:
    """Extract statement type from SQL statement.

    Returns: CREATE, ALTER, INSERT, COPY, SELECT, etc.
    """
    # Remove comments and normalize whitespace
    clean = re.sub(r'--.*$', '', statement, flags=re.MULTILINE)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
    clean = ' '.join(clean.split())

    # Extract first keyword
    match = re.match(r'^\s*(\w+)', clean, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return 'UNKNOWN'


def _is_data_statement(statement_type: str) -> bool:
    """Check if statement is a data statement (INSERT, COPY, LOAD)."""
    return statement_type in ('INSERT', 'COPY', 'LOAD', 'UPDATE', 'DELETE')


def _is_schema_statement(statement_type: str) -> bool:
    """Check if statement is a schema definition statement."""
    return statement_type in (
        'CREATE', 'ALTER', 'DROP', 'GRANT', 'REVOKE',
        'COMMENT', 'SET', 'BEGIN', 'COMMIT', 'ROLLBACK'
    )


def _create_chunk(statements: list[SQLStatement]) -> SQLChunk:
    """Create chunk from list of statements."""
    if not statements:
        raise ValueError("Cannot create chunk from empty statement list")

    content = '\n\n'.join(stmt.content for stmt in statements)
    start_line = statements[0].start_line
    end_line = statements[-1].end_line
    statement_types = list(set(stmt.statement_type for stmt in statements))

    return SQLChunk(
        content=content,
        start_line=start_line,
        end_line=end_line,
        statement_types=statement_types,
        num_statements=len(statements)
    )


def get_sql_stats(sql_content: str) -> dict[str, any]:
    """Get statistics about SQL file.

    Useful for deciding whether to skip data statements.

    Returns:
        Dictionary with counts of each statement type
    """
    statements = list(parse_sql_statements(sql_content, skip_data_statements=False))

    stats = {
        'total_statements': len(statements),
        'total_lines': len(sql_content.split('\n')),
        'total_size': len(sql_content),
        'statement_types': {},
        'data_statements': 0,
        'schema_statements': 0,
    }

    for stmt in statements:
        # Count by type
        stats['statement_types'][stmt.statement_type] = \
            stats['statement_types'].get(stmt.statement_type, 0) + 1

        # Count categories
        if stmt.is_data_statement:
            stats['data_statements'] += 1
        elif _is_schema_statement(stmt.statement_type):
            stats['schema_statements'] += 1

    return stats
