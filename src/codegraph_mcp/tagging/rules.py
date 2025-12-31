"""Tagging rules engine.

Supports PATH, IMPORT, REGEX, and SYMBOL matchers for automatic tagging.
"""
from __future__ import annotations
import asyncpg
import re
from dataclasses import dataclass
from typing import Literal


MatcherType = Literal["PATH", "IMPORT", "REGEX", "SYMBOL"]


@dataclass
class TagRule:
    """A tagging rule definition."""
    tag_name: str
    matcher_type: MatcherType
    pattern: str
    confidence: float = 1.0


# Starter tag rules
STARTER_TAG_RULES = [
    # Database tags
    TagRule("database", "IMPORT", "psycopg", 0.9),
    TagRule("database", "IMPORT", "asyncpg", 0.9),
    TagRule("database", "IMPORT", "sqlalchemy", 0.9),
    TagRule("database", "IMPORT", "django.db", 0.9),
    TagRule("database", "PATH", "/db/", 0.7),
    TagRule("database", "PATH", "/database/", 0.7),
    TagRule("database", "PATH", "/models/", 0.6),
    TagRule("database", "SYMBOL", ".*[Mm]odel$", 0.5),
    TagRule("database", "REGEX", r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)\b", 0.8),

    # Auth tags
    TagRule("auth", "IMPORT", "jwt", 0.9),
    TagRule("auth", "IMPORT", "passport", 0.9),
    TagRule("auth", "IMPORT", "auth", 0.8),
    TagRule("auth", "IMPORT", "oauth", 0.9),
    TagRule("auth", "PATH", "/auth/", 0.8),
    TagRule("auth", "PATH", "/authentication/", 0.8),
    TagRule("auth", "SYMBOL", ".*[Aa]uth.*", 0.6),
    TagRule("auth", "REGEX", r"\b(login|logout|authenticate|authorize|token|session)\b", 0.7),

    # API/HTTP tags
    TagRule("api/http", "IMPORT", "fastapi", 0.9),
    TagRule("api/http", "IMPORT", "flask", 0.9),
    TagRule("api/http", "IMPORT", "django", 0.8),
    TagRule("api/http", "IMPORT", "express", 0.9),
    TagRule("api/http", "IMPORT", "axios", 0.8),
    TagRule("api/http", "IMPORT", "requests", 0.8),
    TagRule("api/http", "IMPORT", "httpx", 0.8),
    TagRule("api/http", "PATH", "/api/", 0.8),
    TagRule("api/http", "PATH", "/routes/", 0.7),
    TagRule("api/http", "PATH", "/endpoints/", 0.8),
    TagRule("api/http", "SYMBOL", ".*[Aa]pi.*", 0.6),
    TagRule("api/http", "REGEX", r"\b(GET|POST|PUT|DELETE|PATCH|router|endpoint)\b", 0.7),

    # Logging tags
    TagRule("logging", "IMPORT", "logging", 0.9),
    TagRule("logging", "IMPORT", "log4j", 0.9),
    TagRule("logging", "IMPORT", "winston", 0.9),
    TagRule("logging", "IMPORT", "pino", 0.9),
    TagRule("logging", "PATH", "/logging/", 0.8),
    TagRule("logging", "SYMBOL", ".*[Ll]ogger.*", 0.7),
    TagRule("logging", "REGEX", r"\b(logger|log\.info|log\.error|log\.debug|console\.log)\b", 0.8),

    # Caching tags
    TagRule("caching", "IMPORT", "redis", 0.9),
    TagRule("caching", "IMPORT", "memcached", 0.9),
    TagRule("caching", "IMPORT", "cache", 0.8),
    TagRule("caching", "PATH", "/cache/", 0.8),
    TagRule("caching", "SYMBOL", ".*[Cc]ache.*", 0.7),
    TagRule("caching", "REGEX", r"\b(cache|cached|caching|memoize)\b", 0.8),

    # Metrics tags
    TagRule("metrics", "IMPORT", "prometheus", 0.9),
    TagRule("metrics", "IMPORT", "statsd", 0.9),
    TagRule("metrics", "IMPORT", "datadog", 0.9),
    TagRule("metrics", "PATH", "/metrics/", 0.8),
    TagRule("metrics", "SYMBOL", ".*[Mm]etric.*", 0.7),
    TagRule("metrics", "REGEX", r"\b(metric|counter|gauge|histogram|timer)\b", 0.8),

    # Payments tags
    TagRule("payments", "IMPORT", "stripe", 0.9),
    TagRule("payments", "IMPORT", "paypal", 0.9),
    TagRule("payments", "IMPORT", "braintree", 0.9),
    TagRule("payments", "PATH", "/payment/", 0.8),
    TagRule("payments", "PATH", "/checkout/", 0.7),
    TagRule("payments", "SYMBOL", ".*[Pp]ayment.*", 0.7),
    TagRule("payments", "REGEX", r"\b(payment|charge|invoice|subscription|billing)\b", 0.7),
]


async def seed_starter_tags(
    database_url: str | None = None,
    conn: asyncpg.Connection | None = None,
    schema_name: str | None = None
) -> None:
    """Seed database with starter tags and rules.

    Args:
        database_url: Database connection string (if conn not provided)
        conn: Existing connection (if database_url not provided)
        schema_name: Optional schema name for schema isolation
    """
    own_conn = False
    if not conn:
        if not database_url:
            raise ValueError("Either database_url or conn must be provided")
        conn = await asyncpg.connect(dsn=database_url)
        own_conn = True

    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        # Extract unique tag names
        tag_names = set(rule.tag_name for rule in STARTER_TAG_RULES)

        # Insert tags (ignore duplicates)
        for tag_name in tag_names:
            await conn.execute(
                """
                INSERT INTO tag (name, description)
                VALUES ($1, $2)
                ON CONFLICT (name) DO NOTHING
                """,
                tag_name,
                f"Auto-generated tag for {tag_name}"
            )

        # Get tag IDs
        tag_rows = await conn.fetch("SELECT id, name FROM tag WHERE name = ANY($1)", list(tag_names))
        tag_id_map = {row["name"]: row["id"] for row in tag_rows}

        # Insert rules (check for existence to avoid duplicates)
        for rule in STARTER_TAG_RULES:
            tag_id = tag_id_map[rule.tag_name]
            # Check if rule already exists
            existing = await conn.fetchrow(
                """
                SELECT id FROM tag_rule
                WHERE tag_id = $1 AND match_type = $2 AND pattern = $3
                """,
                tag_id,
                rule.matcher_type,
                rule.pattern
            )
            if not existing:
                await conn.execute(
                    """
                    INSERT INTO tag_rule (tag_id, match_type, pattern, weight)
                    VALUES ($1, $2, $3, $4)
                    """,
                    tag_id,
                    rule.matcher_type,
                    rule.pattern,
                    rule.confidence
                )

        print(f"Seeded {len(tag_names)} tags and {len(STARTER_TAG_RULES)} rules")

    finally:
        if own_conn:
            await conn.close()


async def apply_tag_rules(
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None
) -> int:
    """Apply tag rules to chunks and documents.

    Args:
        database_url: Database connection string
        repo_id: Optional repository UUID to limit tagging to
        schema_name: Optional schema name for schema isolation

    Returns:
        Number of entity_tag rows created
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        # Fetch all tag rules
        rule_rows = await conn.fetch(
            """
            SELECT tr.id, tr.tag_id, t.name as tag_name, tr.match_type, tr.pattern, tr.weight
            FROM tag_rule tr
            JOIN tag t ON tr.tag_id = t.id
            """
        )

        tags_created = 0

        for rule_row in rule_rows:
            tag_id = rule_row["tag_id"]
            matcher_type = rule_row["match_type"]
            pattern = rule_row["pattern"]
            confidence = rule_row["weight"]

            # Apply rule based on matcher type
            if matcher_type == "PATH":
                # Match against file paths
                if repo_id:
                    chunk_ids = await conn.fetch(
                        """
                        SELECT DISTINCT c.id
                        FROM chunk c
                        JOIN file f ON c.file_id = f.id
                        WHERE c.repo_id = $1 AND f.path LIKE $2
                        """,
                        repo_id,
                        f"%{pattern}%"
                    )
                else:
                    chunk_ids = await conn.fetch(
                        """
                        SELECT DISTINCT c.id
                        FROM chunk c
                        JOIN file f ON c.file_id = f.id
                        WHERE f.path LIKE $1
                        """,
                        f"%{pattern}%"
                    )

                for row in chunk_ids:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (entity_id, entity_type, tag_id, confidence, source)
                        VALUES ($1, 'CHUNK', $2, $3, 'AUTO_RULE')
                        ON CONFLICT (entity_id, entity_type, tag_id) DO NOTHING
                        """,
                        row["id"],
                        tag_id,
                        confidence
                    )
                    tags_created += 1

            elif matcher_type == "IMPORT":
                # Match against chunk content containing imports
                # Simple substring match for import statements
                if repo_id:
                    chunk_ids = await conn.fetch(
                        """
                        SELECT DISTINCT c.id
                        FROM chunk c
                        WHERE c.repo_id = $1 AND c.content ILIKE $2
                        """,
                        repo_id,
                        f"%{pattern}%"
                    )
                else:
                    chunk_ids = await conn.fetch(
                        """
                        SELECT DISTINCT c.id
                        FROM chunk c
                        WHERE c.content ILIKE $1
                        """,
                        f"%{pattern}%"
                    )

                for row in chunk_ids:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (entity_id, entity_type, tag_id, confidence, source)
                        VALUES ($1, 'CHUNK', $2, $3, 'AUTO_RULE')
                        ON CONFLICT (entity_id, entity_type, tag_id) DO NOTHING
                        """,
                        row["id"],
                        tag_id,
                        confidence
                    )
                    tags_created += 1

            elif matcher_type == "REGEX":
                # Match against chunk content using regex
                # Need to fetch chunks and apply regex in Python
                if repo_id:
                    chunks = await conn.fetch(
                        "SELECT id, content FROM chunk WHERE repo_id = $1",
                        repo_id
                    )
                else:
                    chunks = await conn.fetch("SELECT id, content FROM chunk")

                regex = re.compile(pattern, re.IGNORECASE)
                for chunk in chunks:
                    if regex.search(chunk["content"]):
                        await conn.execute(
                            """
                            INSERT INTO entity_tag (entity_id, entity_type, tag_id, confidence, source)
                            VALUES ($1, 'CHUNK', $2, $3, 'AUTO_RULE')
                            ON CONFLICT (entity_id, entity_type, tag_id) DO NOTHING
                            """,
                            chunk["id"],
                            tag_id,
                            confidence
                        )
                        tags_created += 1

            elif matcher_type == "SYMBOL":
                # Match against symbol names using regex
                if repo_id:
                    symbols = await conn.fetch(
                        """
                        SELECT s.id, s.name, c.id as chunk_id
                        FROM symbol s
                        JOIN chunk c ON s.id = c.symbol_id
                        WHERE c.repo_id = $1
                        """,
                        repo_id
                    )
                else:
                    symbols = await conn.fetch(
                        """
                        SELECT s.id, s.name, c.id as chunk_id
                        FROM symbol s
                        JOIN chunk c ON s.id = c.symbol_id
                        """
                    )

                regex = re.compile(pattern)
                for symbol in symbols:
                    if regex.search(symbol["name"]):
                        # Tag the chunk containing this symbol
                        await conn.execute(
                            """
                            INSERT INTO entity_tag (entity_id, entity_type, tag_id, confidence, source)
                            VALUES ($1, 'CHUNK', $2, $3, 'AUTO_RULE')
                            ON CONFLICT (entity_id, entity_type, tag_id) DO NOTHING
                            """,
                            symbol["chunk_id"],
                            tag_id,
                            confidence
                        )
                        tags_created += 1

        return tags_created

    finally:
        await conn.close()


async def get_entity_tags(
    entity_id: str,
    entity_type: str,
    database_url: str,
    schema_name: str | None = None
) -> list[dict]:
    """Get all tags for an entity.

    Args:
        entity_id: Entity UUID
        entity_type: "CHUNK", "DOCUMENT", "SYMBOL", or "FILE"
        database_url: Database connection string
        schema_name: Optional schema name for schema isolation

    Returns:
        List of tag dictionaries with name and confidence
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        rows = await conn.fetch(
            """
            SELECT t.name, et.confidence
            FROM entity_tag et
            JOIN tag t ON et.tag_id = t.id
            WHERE et.entity_id = $1 AND et.entity_type = $2
            ORDER BY et.confidence DESC
            """,
            entity_id,
            entity_type
        )

        return [{"name": row["name"], "confidence": row["confidence"]} for row in rows]

    finally:
        await conn.close()
