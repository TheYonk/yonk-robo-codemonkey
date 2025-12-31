"""Ruleset loader for migration assessment."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
import hashlib


@dataclass
class MigrationRule:
    """A single migration rule."""
    id: str
    category: str
    severity: str
    title: str
    pattern: str
    description: str
    mapping: dict[str, Any]
    source_db: str | None = None


@dataclass
class MigrationRuleset:
    """Complete migration ruleset."""
    version: str
    severity_weights: dict[str, int]
    category_multipliers: dict[str, float]
    tiers: dict[str, list[int]]
    detection: dict[str, Any]
    common_rules: list[MigrationRule]
    oracle_rules: list[MigrationRule]
    sqlserver_rules: list[MigrationRule]
    mongodb_rules: list[MigrationRule]
    mysql_rules: list[MigrationRule]
    content_hash: str

    def get_rules_for_db(self, source_db: str) -> list[MigrationRule]:
        """Get all applicable rules for a source database."""
        rules = list(self.common_rules)

        if source_db == "oracle":
            rules.extend(self.oracle_rules)
        elif source_db == "sqlserver":
            rules.extend(self.sqlserver_rules)
        elif source_db == "mongodb":
            rules.extend(self.mongodb_rules)
        elif source_db == "mysql":
            rules.extend(self.mysql_rules)

        return rules

    def get_tier(self, score: int) -> str:
        """Get migration tier based on score."""
        for tier, (min_score, max_score) in self.tiers.items():
            if min_score <= score <= max_score:
                return tier
        return "extreme"  # Default to extreme if out of range


def load_migration_rules(ruleset_path: str | None = None) -> MigrationRuleset:
    """Load migration rules from YAML file.

    Args:
        ruleset_path: Path to YAML ruleset file, or None to use default

    Returns:
        Parsed MigrationRuleset
    """
    if ruleset_path is None:
        # Default to rules/migration_rules.yaml relative to project root
        ruleset_path = str(Path(__file__).parents[3] / "rules" / "migration_rules.yaml")

    with open(ruleset_path, 'r') as f:
        raw_data = f.read()
        data = yaml.safe_load(raw_data)

    # Calculate content hash for caching
    content_hash = hashlib.sha256(raw_data.encode()).hexdigest()[:16]

    # Parse rules
    common_rules = _parse_rules(data.get("common_rules", []), None)
    oracle_rules = _parse_rules(data.get("oracle_rules", []), "oracle")
    sqlserver_rules = _parse_rules(data.get("sqlserver_rules", []), "sqlserver")
    mongodb_rules = _parse_rules(data.get("mongodb_rules", []), "mongodb")
    mysql_rules = _parse_rules(data.get("mysql_rules", []), "mysql")

    return MigrationRuleset(
        version=data.get("version", "1.0"),
        severity_weights=data.get("severity_weights", {}),
        category_multipliers=data.get("category_multipliers", {}),
        tiers=data.get("tiers", {}),
        detection=data.get("detection", {}),
        common_rules=common_rules,
        oracle_rules=oracle_rules,
        sqlserver_rules=sqlserver_rules,
        mongodb_rules=mongodb_rules,
        mysql_rules=mysql_rules,
        content_hash=content_hash
    )


def _parse_rules(rules_data: list[dict], source_db: str | None) -> list[MigrationRule]:
    """Parse rule dictionaries into MigrationRule objects."""
    rules = []

    for rule_data in rules_data:
        rules.append(MigrationRule(
            id=rule_data["id"],
            category=rule_data["category"],
            severity=rule_data["severity"],
            title=rule_data["title"],
            pattern=rule_data["pattern"],
            description=rule_data["description"],
            mapping=rule_data.get("mapping", {}),
            source_db=source_db
        ))

    return rules
