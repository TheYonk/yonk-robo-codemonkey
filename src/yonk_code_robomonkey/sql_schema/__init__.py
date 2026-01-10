"""SQL Schema Intelligence module.

Provides specialized handling for SQL schema files:
- Parse CREATE TABLE, CREATE FUNCTION, CREATE PROCEDURE, CREATE TRIGGER
- Extract structured metadata (columns, constraints, parameters)
- Generate LLM summaries for tables and routines
- Map column usage across the codebase
"""
from __future__ import annotations

from .parser import (
    ParsedColumn,
    ParsedConstraint,
    ParsedIndex,
    ParsedTable,
    ParsedParameter,
    ParsedRoutine,
    parse_sql_file,
    parse_create_table,
    parse_create_routine,
)

from .extractor import (
    extract_and_store_sql_metadata,
    extract_and_store_sql_content,
    extract_schema_metadata_from_repo,
    scan_sql_files,
    reextract_file,
)

from .column_mapper import (
    map_column_usage_for_table,
    map_all_column_usage,
)

from .summarizer import (
    generate_table_summary,
    generate_routine_summary,
    generate_summaries_for_repo,
)

from . import queries

__all__ = [
    # Parser types
    "ParsedColumn",
    "ParsedConstraint",
    "ParsedIndex",
    "ParsedTable",
    "ParsedParameter",
    "ParsedRoutine",
    # Parser functions
    "parse_sql_file",
    "parse_create_table",
    "parse_create_routine",
    # Extractor functions
    "extract_and_store_sql_metadata",
    "extract_and_store_sql_content",
    "extract_schema_metadata_from_repo",
    "scan_sql_files",
    "reextract_file",
    # Column mapper
    "map_column_usage_for_table",
    "map_all_column_usage",
    # Summarizer
    "generate_table_summary",
    "generate_routine_summary",
    "generate_summaries_for_repo",
    # Queries module
    "queries",
]
