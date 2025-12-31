"""
Database introspection and analysis module.

Provides tools for extracting Postgres schema, analyzing stored routines,
discovering application database calls, and generating architecture reports.
"""

from yonk_code_robomonkey.db_introspect.schema_extractor import extract_db_schema, DBSchema
from yonk_code_robomonkey.db_introspect.routine_analyzer import analyze_routine, RoutineAnalysis
from yonk_code_robomonkey.db_introspect.app_call_discoverer import discover_db_calls, DBCall
from yonk_code_robomonkey.db_introspect.report_generator import generate_db_architecture_report, DBReportResult

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
