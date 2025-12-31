"""
Migration Assessment Module

Provides database migration assessment capabilities including:
- Auto-detection of source databases
- Code-side database usage scanning
- Stored procedure analysis
- SQL dialect feature detection
- Scoring and risk assessment
- Report generation
"""

from codegraph_mcp.migration.ruleset import load_migration_rules, MigrationRuleset
from codegraph_mcp.migration.detector import detect_source_databases
from codegraph_mcp.migration.assessor import assess_migration, MigrationAssessmentResult

__all__ = [
    "load_migration_rules",
    "MigrationRuleset",
    "detect_source_databases",
    "assess_migration",
    "MigrationAssessmentResult"
]
