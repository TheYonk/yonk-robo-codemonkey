"""Database schema extraction from Postgres.

Connects to a target Postgres database and extracts:
- Server version and configuration
- Schemas, tables, columns, constraints, indexes
- Views, materialized views
- Functions, procedures, triggers
- Types, enums, domains
- Extensions
- Sequences
- Migration history (if present)
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass, field
import asyncpg


@dataclass
class DBSchema:
    """Complete database schema information."""
    # Server info
    version: str
    database: str
    user: str

    # Schemas
    schemas: list[dict[str, Any]] = field(default_factory=list)

    # Objects
    tables: list[dict[str, Any]] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    materialized_views: list[dict[str, Any]] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    triggers: list[dict[str, Any]] = field(default_factory=list)
    sequences: list[dict[str, Any]] = field(default_factory=list)
    types: list[dict[str, Any]] = field(default_factory=list)
    enums: list[dict[str, Any]] = field(default_factory=list)
    domains: list[dict[str, Any]] = field(default_factory=list)
    extensions: list[dict[str, Any]] = field(default_factory=list)

    # Constraints and indexes
    constraints: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)

    # Migrations
    migration_tables: list[dict[str, Any]] = field(default_factory=list)


async def extract_db_schema(
    target_db_url: str,
    schemas: list[str] | None = None
) -> DBSchema:
    """Extract complete schema from target database.

    Args:
        target_db_url: Connection string to target database
        schemas: Optional list of schemas to include (default: all non-system)

    Returns:
        DBSchema with all extracted information
    """
    conn = await asyncpg.connect(dsn=target_db_url)

    try:
        # Server info
        version = await conn.fetchval("SELECT version()")
        database = await conn.fetchval("SELECT current_database()")
        user = await conn.fetchval("SELECT current_user")

        schema_info = DBSchema(
            version=version,
            database=database,
            user=user
        )

        # Get schemas
        schema_info.schemas = await _extract_schemas(conn, schemas)
        schema_names = [s["name"] for s in schema_info.schemas]

        # Extract all objects
        schema_info.tables = await _extract_tables(conn, schema_names)
        schema_info.views = await _extract_views(conn, schema_names)
        schema_info.materialized_views = await _extract_materialized_views(conn, schema_names)
        schema_info.functions = await _extract_functions(conn, schema_names)
        schema_info.triggers = await _extract_triggers(conn, schema_names)
        schema_info.sequences = await _extract_sequences(conn, schema_names)
        schema_info.types = await _extract_types(conn, schema_names)
        schema_info.enums = await _extract_enums(conn, schema_names)
        schema_info.domains = await _extract_domains(conn, schema_names)
        schema_info.extensions = await _extract_extensions(conn)
        schema_info.constraints = await _extract_constraints(conn, schema_names)
        schema_info.indexes = await _extract_indexes(conn, schema_names)
        schema_info.migration_tables = await _detect_migration_tables(conn)

        return schema_info

    finally:
        await conn.close()


async def _extract_schemas(
    conn: asyncpg.Connection,
    filter_schemas: list[str] | None
) -> list[dict[str, Any]]:
    """Extract schema list."""
    query = """
        SELECT
            nspname as name,
            pg_catalog.pg_get_userbyid(nspowner) as owner,
            obj_description(oid, 'pg_namespace') as description
        FROM pg_namespace
        WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        AND nspname NOT LIKE 'pg_temp_%'
        AND nspname NOT LIKE 'pg_toast_temp_%'
    """

    if filter_schemas:
        query += f" AND nspname = ANY($1::text[])"
        rows = await conn.fetch(query, filter_schemas)
    else:
        rows = await conn.fetch(query)

    return [dict(r) for r in rows]


async def _extract_tables(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract tables with columns."""
    tables = await conn.fetch("""
        SELECT
            t.table_schema as schema,
            t.table_name as name,
            obj_description((quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass, 'pg_class') as description,
            pg_size_pretty(pg_total_relation_size((quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass)) as size
        FROM information_schema.tables t
        WHERE t.table_schema = ANY($1::text[])
        AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_schema, t.table_name
    """, schemas)

    result = []
    for table in tables:
        # Get columns for this table
        columns = await conn.fetch("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                is_nullable,
                column_default,
                is_identity,
                identity_generation
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """, table["schema"], table["name"])

        result.append({
            "schema": table["schema"],
            "name": table["name"],
            "description": table["description"],
            "size": table["size"],
            "columns": [dict(c) for c in columns]
        })

    return result


async def _extract_views(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract views."""
    views = await conn.fetch("""
        SELECT
            schemaname as schema,
            viewname as name,
            definition
        FROM pg_views
        WHERE schemaname = ANY($1::text[])
        ORDER BY schemaname, viewname
    """, schemas)

    return [dict(v) for v in views]


async def _extract_materialized_views(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract materialized views."""
    mviews = await conn.fetch("""
        SELECT
            schemaname as schema,
            matviewname as name,
            definition,
            hasindexes,
            ispopulated
        FROM pg_matviews
        WHERE schemaname = ANY($1::text[])
        ORDER BY schemaname, matviewname
    """, schemas)

    return [dict(m) for m in mviews]


async def _extract_functions(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract functions and procedures."""
    functions = await conn.fetch("""
        SELECT
            n.nspname as schema,
            p.proname as name,
            pg_get_function_arguments(p.oid) as arguments,
            pg_get_function_result(p.oid) as return_type,
            l.lanname as language,
            CASE p.provolatile
                WHEN 'i' THEN 'IMMUTABLE'
                WHEN 's' THEN 'STABLE'
                WHEN 'v' THEN 'VOLATILE'
            END as volatility,
            p.prosecdef as security_definer,
            p.proleakproof as leakproof,
            CASE p.proparallel
                WHEN 's' THEN 'SAFE'
                WHEN 'r' THEN 'RESTRICTED'
                WHEN 'u' THEN 'UNSAFE'
            END as parallel,
            p.procost as cost,
            p.prorows as rows,
            pg_get_functiondef(p.oid) as definition
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_language l ON l.oid = p.prolang
        WHERE n.nspname = ANY($1::text[])
        ORDER BY n.nspname, p.proname
    """, schemas)

    return [dict(f) for f in functions]


async def _extract_triggers(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract triggers."""
    triggers = await conn.fetch("""
        SELECT
            n.nspname as schema,
            t.tgname as name,
            c.relname as table_name,
            pg_get_triggerdef(t.oid) as definition,
            t.tgenabled as enabled
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY($1::text[])
        AND NOT t.tgisinternal
        ORDER BY n.nspname, c.relname, t.tgname
    """, schemas)

    return [dict(t) for t in triggers]


async def _extract_sequences(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract sequences."""
    sequences = await conn.fetch("""
        SELECT
            n.nspname as schema,
            c.relname as name,
            pg_get_serial_sequence(n.nspname || '.' || t.relname, a.attname) as owned_by
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'a'
        LEFT JOIN pg_class t ON t.oid = d.refobjid
        LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE c.relkind = 'S'
        AND n.nspname = ANY($1::text[])
        ORDER BY n.nspname, c.relname
    """, schemas)

    return [dict(s) for s in sequences]


async def _extract_types(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract custom types."""
    types = await conn.fetch("""
        SELECT
            n.nspname as schema,
            t.typname as name,
            CASE t.typtype
                WHEN 'b' THEN 'BASE'
                WHEN 'c' THEN 'COMPOSITE'
                WHEN 'd' THEN 'DOMAIN'
                WHEN 'e' THEN 'ENUM'
                WHEN 'p' THEN 'PSEUDO'
                WHEN 'r' THEN 'RANGE'
            END as type_kind
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = ANY($1::text[])
        AND t.typtype IN ('b', 'c', 'd', 'e', 'r')
        ORDER BY n.nspname, t.typname
    """, schemas)

    return [dict(t) for t in types]


async def _extract_enums(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract enum types with values."""
    enums = await conn.fetch("""
        SELECT
            n.nspname as schema,
            t.typname as name,
            ARRAY_AGG(e.enumlabel ORDER BY e.enumsortorder) as values
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE n.nspname = ANY($1::text[])
        GROUP BY n.nspname, t.typname
        ORDER BY n.nspname, t.typname
    """, schemas)

    return [dict(e) for e in enums]


async def _extract_domains(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract domain types."""
    domains = await conn.fetch("""
        SELECT
            n.nspname as schema,
            t.typname as name,
            format_type(t.typbasetype, t.typtypmod) as base_type,
            t.typnotnull as not_null,
            t.typdefault as default_value
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = ANY($1::text[])
        AND t.typtype = 'd'
        ORDER BY n.nspname, t.typname
    """, schemas)

    return [dict(d) for d in domains]


async def _extract_extensions(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Extract installed extensions."""
    extensions = await conn.fetch("""
        SELECT
            extname as name,
            extversion as version,
            n.nspname as schema
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        ORDER BY extname
    """)

    return [dict(e) for e in extensions]


async def _extract_constraints(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract constraints (PK, FK, UK, CHECK)."""
    constraints = await conn.fetch("""
        SELECT
            n.nspname as schema,
            c.conname as name,
            cl.relname as table_name,
            CASE c.contype
                WHEN 'p' THEN 'PRIMARY KEY'
                WHEN 'u' THEN 'UNIQUE'
                WHEN 'f' THEN 'FOREIGN KEY'
                WHEN 'c' THEN 'CHECK'
            END as constraint_type,
            pg_get_constraintdef(c.oid) as definition
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = ANY($1::text[])
        ORDER BY n.nspname, cl.relname, c.conname
    """, schemas)

    return [dict(c) for c in constraints]


async def _extract_indexes(
    conn: asyncpg.Connection,
    schemas: list[str]
) -> list[dict[str, Any]]:
    """Extract indexes."""
    indexes = await conn.fetch("""
        SELECT
            n.nspname as schema,
            i.relname as name,
            t.relname as table_name,
            am.amname as method,
            pg_get_indexdef(i.oid) as definition,
            ix.indisunique as is_unique,
            ix.indisprimary as is_primary
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_am am ON am.oid = i.relam
        WHERE n.nspname = ANY($1::text[])
        ORDER BY n.nspname, t.relname, i.relname
    """, schemas)

    return [dict(i) for i in indexes]


async def _detect_migration_tables(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Detect common migration framework tables."""
    migration_patterns = [
        ("flyway_schema_history", "Flyway"),
        ("schema_version", "Flyway (old)"),
        ("databasechangelog", "Liquibase"),
        ("alembic_version", "Alembic"),
        ("_prisma_migrations", "Prisma"),
        ("schema_migrations", "Rails/ActiveRecord"),
        ("knex_migrations", "Knex"),
        ("migrations", "Generic")
    ]

    detected = []
    for table_pattern, framework in migration_patterns:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = $1
            )
        """, table_pattern)

        if exists:
            # Get row count
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table_pattern}")
            detected.append({
                "table": table_pattern,
                "framework": framework,
                "migration_count": count
            })

    return detected
