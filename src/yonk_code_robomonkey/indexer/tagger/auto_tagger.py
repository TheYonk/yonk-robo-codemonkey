"""Auto-tagging system for code entities.

Applies tag rules to files, symbols, and chunks during indexing.
"""
from __future__ import annotations
import re
from pathlib import Path
import asyncpg


class AutoTagger:
    """Applies tags to entities based on tag rules."""

    def __init__(self, conn: asyncpg.Connection, schema_name: str, repo_id: str):
        """Initialize auto-tagger.

        Args:
            conn: Database connection
            schema_name: Repository schema name
            repo_id: Repository UUID
        """
        self.conn = conn
        self.schema_name = schema_name
        self.repo_id = repo_id
        self._rules_cache = None

    async def load_rules(self) -> list[dict]:
        """Load all tag rules from database.

        Returns:
            List of rule dicts with tag_id, match_type, pattern, weight
        """
        if self._rules_cache is not None:
            return self._rules_cache

        rules = await self.conn.fetch(f"""
            SELECT tr.id, tr.tag_id, t.name as tag_name, tr.match_type, tr.pattern, tr.weight
            FROM {self.schema_name}.tag_rule tr
            JOIN {self.schema_name}.tag t ON tr.tag_id = t.id
        """)

        self._rules_cache = [dict(r) for r in rules]
        return self._rules_cache

    async def apply_file_tags(self, file_id: str, file_path: str) -> list[str]:
        """Apply tags to a file based on its path.

        Args:
            file_id: File UUID
            file_path: Relative file path

        Returns:
            List of tag names applied
        """
        rules = await self.load_rules()
        applied_tags = []

        for rule in rules:
            if rule['match_type'] == 'PATH':
                if self._match_path(file_path, rule['pattern']):
                    await self._apply_tag(file_id, 'FILE', rule['tag_id'], rule['weight'])
                    applied_tags.append(rule['tag_name'])

            elif rule['match_type'] == 'REGEX':
                if re.search(rule['pattern'], file_path):
                    await self._apply_tag(file_id, 'FILE', rule['tag_id'], rule['weight'])
                    applied_tags.append(rule['tag_name'])

        return applied_tags

    def _match_path(self, file_path: str, pattern: str) -> bool:
        """Check if file path matches pattern.

        Supports:
        - Exact match: "node_modules"
        - Wildcard: "*/node_modules/*"
        - Contains: "*node_modules*"

        Args:
            file_path: File path to check
            pattern: Pattern to match against

        Returns:
            True if matches
        """
        # Convert glob pattern to regex
        regex_pattern = pattern.replace('**', '.*').replace('*', '[^/]*')
        regex_pattern = f"^{regex_pattern}$"

        return bool(re.match(regex_pattern, file_path))

    async def _apply_tag(self, entity_id: str, entity_type: str, tag_id: str, confidence: float):
        """Apply tag to entity.

        Args:
            entity_id: Entity UUID
            entity_type: 'FILE', 'SYMBOL', or 'CHUNK'
            tag_id: Tag UUID
            confidence: Confidence score (0.0-1.0)
        """
        await self.conn.execute(f"""
            INSERT INTO {self.schema_name}.entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
            VALUES ($1, $2, $3, $4, $5, 'AUTO_RULE')
            ON CONFLICT (repo_id, entity_type, entity_id, tag_id) DO UPDATE
            SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
        """, self.repo_id, entity_type, entity_id, tag_id, confidence)


async def initialize_default_tags(conn: asyncpg.Connection, schema_name: str):
    """Initialize default tag rules for a repository.

    Creates tags and rules for:
    - vendor (node_modules, vendor/, third_party/)
    - generated (dist/, build/, .min.js, etc.)
    - test (test/, __tests__, *.test.*, *.spec.*)

    Args:
        conn: Database connection
        schema_name: Repository schema name
    """
    # Define default tags
    default_tags = [
        {
            'name': 'vendor',
            'description': 'Third-party vendor code (node_modules, vendor/, etc.)',
            'rules': [
                {'match_type': 'PATH', 'pattern': '**/node_modules/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/vendor/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/third_party/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/.venv/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/venv/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/site-packages/**', 'weight': 1.0},
            ]
        },
        {
            'name': 'generated',
            'description': 'Generated/compiled code (dist/, build/, minified files)',
            'rules': [
                {'match_type': 'PATH', 'pattern': '**/dist/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/build/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/*.min.js', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/*.min.css', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/bundle.js', 'weight': 1.0},
            ]
        },
        {
            'name': 'test',
            'description': 'Test files and test utilities',
            'rules': [
                {'match_type': 'PATH', 'pattern': '**/test/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/tests/**', 'weight': 1.0},
                {'match_type': 'PATH', 'pattern': '**/__tests__/**', 'weight': 1.0},
                {'match_type': 'REGEX', 'pattern': r'\.test\.(js|ts|py|go|java)$', 'weight': 1.0},
                {'match_type': 'REGEX', 'pattern': r'\.spec\.(js|ts|py|go|java)$', 'weight': 1.0},
                {'match_type': 'REGEX', 'pattern': r'_test\.(go|rs)$', 'weight': 1.0},
            ]
        },
    ]

    for tag_def in default_tags:
        # Create tag
        tag_id = await conn.fetchval(f"""
            INSERT INTO {schema_name}.tag (name, description)
            VALUES ($1, $2)
            ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description
            RETURNING id
        """, tag_def['name'], tag_def['description'])

        # Create rules
        for rule in tag_def['rules']:
            await conn.execute(f"""
                INSERT INTO {schema_name}.tag_rule (tag_id, match_type, pattern, weight)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, tag_id, rule['match_type'], rule['pattern'], rule['weight'])
