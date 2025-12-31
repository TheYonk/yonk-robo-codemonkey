"""
Database introspection and analysis module.

Provides tools for extracting Postgres schema, analyzing stored routines,
discovering application database calls, and generating architecture reports.
"""

from codegraph_mcp.db_introspect.schema_extractor import extract_db_schema, DBSchema
from codegraph_mcp.db_introspect.routine_analyzer import analyze_routine, RoutineAnalysis
from codegraph_mcp.db_introspect.app_call_discoverer import discover_db_calls, DBCall
from codegraph_mcp.db_introspect.report_generator import generate_db_architecture_report, DBReportResult

__all__ = [
    "extract_db_schema",
    "DBSchema",
    "analyze_routine",
    "RoutineAnalysis",
    "discover_db_calls",
    "DBCall",
    "generate_db_architecture_report",
    "DBReportResult"
]
