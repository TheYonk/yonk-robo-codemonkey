"""Application database call discovery.

Scans code for database-related patterns across:
- Node: pg, knex, sequelize, prisma, typeorm, mysql2
- Python: psycopg2/3, asyncpg, SQLAlchemy, Alembic
- Go: database/sql, pgx, sqlc, gorm, squirrel
- Java: JDBC, JPA/Hibernate, Spring JdbcTemplate, Flyway/Liquibase

Extracts SQL snippets, file paths, framework labels, and tags.
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
import re
from pathlib import Path


@dataclass
class DBCall:
    """Discovered database call."""
    file_path: str
    start_line: int
    end_line: int
    language: str
    framework: str
    sql_snippet: str
    call_type: str  # query, execute, migration, transaction, etc.
    tags: list[str]


# Node patterns
NODE_PATTERNS = {
    # pg library
    r"client\.query\s*\(\s*['\"`]": ("pg", "query"),
    r"pool\.query\s*\(\s*['\"`]": ("pg", "query"),
    r"pool\.connect\s*\(": ("pg", "connection"),

    # knex
    r"knex\s*\(\s*['\"`]": ("knex", "query"),
    r"knex\.raw\s*\(\s*['\"`]": ("knex", "query"),
    r"knex\.schema\s*\.": ("knex", "ddl"),

    # Sequelize
    r"sequelize\.query\s*\(\s*['\"`]": ("sequelize", "query"),
    r"\.sync\s*\(": ("sequelize", "ddl"),

    # TypeORM
    r"getRepository\s*\(": ("typeorm", "orm"),
    r"createQueryBuilder\s*\(": ("typeorm", "query-builder"),

    # Prisma
    r"prisma\.\w+\.": ("prisma", "orm"),
}

# Python patterns
PYTHON_PATTERNS = {
    # psycopg2/3
    r"cursor\.execute\s*\(\s*['\"`]": ("psycopg", "query"),
    r"cursor\.executemany\s*\(\s*['\"`]": ("psycopg", "query"),
    r"conn\.execute\s*\(\s*['\"`]": ("psycopg", "query"),

    # asyncpg
    r"await\s+conn\.fetch\s*\(\s*['\"`]": ("asyncpg", "query"),
    r"await\s+conn\.execute\s*\(\s*['\"`]": ("asyncpg", "query"),
    r"await\s+conn\.fetchval\s*\(\s*['\"`]": ("asyncpg", "query"),

    # SQLAlchemy
    r"session\.execute\s*\(\s*text\s*\(": ("sqlalchemy", "query"),
    r"text\s*\(\s*['\"`]": ("sqlalchemy", "query"),
    r"create_engine\s*\(": ("sqlalchemy", "connection"),

    # Alembic
    r"op\.create_table\s*\(": ("alembic", "migration"),
    r"op\.add_column\s*\(": ("alembic", "migration"),
    r"op\.execute\s*\(\s*['\"`]": ("alembic", "migration"),
}

# Go patterns
GO_PATTERNS = {
    # database/sql
    r"db\.Query\s*\(\s*['\"`]": ("database/sql", "query"),
    r"db\.Exec\s*\(\s*['\"`]": ("database/sql", "execute"),
    r"tx\.Exec\s*\(\s*['\"`]": ("database/sql", "transaction"),

    # pgx
    r"conn\.Query\s*\(\s*ctx": ("pgx", "query"),
    r"pool\.Query\s*\(\s*ctx": ("pgx", "query"),

    # gorm
    r"db\.Raw\s*\(\s*['\"`]": ("gorm", "query"),
    r"db\.Exec\s*\(\s*['\"`]": ("gorm", "execute"),
}

# Java patterns
JAVA_PATTERNS = {
    # JDBC
    r"prepareStatement\s*\(\s*\"": ("jdbc", "query"),
    r"createStatement\s*\(\s*\"": ("jdbc", "query"),
    r"executeQuery\s*\(\s*\"": ("jdbc", "query"),
    r"executeUpdate\s*\(\s*\"": ("jdbc", "execute"),

    # JPA/Hibernate
    r"createNativeQuery\s*\(\s*\"": ("jpa", "query"),
    r"@Query\s*\(\s*\"": ("jpa", "query"),

    # Spring JdbcTemplate
    r"jdbcTemplate\.query\s*\(\s*\"": ("spring-jdbc", "query"),
    r"jdbcTemplate\.update\s*\(\s*\"": ("spring-jdbc", "execute"),

    # Flyway
    r"@FlywayMigration": ("flyway", "migration"),
}


def discover_db_calls(
    file_path: str,
    content: str,
    language: str
) -> list[DBCall]:
    """Discover database calls in a file.

    Args:
        file_path: Path to file
        content: File content
        language: Programming language

    Returns:
        List of discovered DB calls
    """
    calls = []

    # Select patterns based on language
    if language == "javascript" or language == "typescript":
        patterns = NODE_PATTERNS
    elif language == "python":
        patterns = PYTHON_PATTERNS
    elif language == "go":
        patterns = GO_PATTERNS
    elif language == "java":
        patterns = JAVA_PATTERNS
    else:
        return calls

    # Search for patterns
    for pattern, (framework, call_type) in patterns.items():
        for match in re.finditer(pattern, content, re.IGNORECASE):
            # Extract SQL snippet
            sql_snippet = _extract_sql_snippet(content, match.start(), language)

            # Get line number
            line_num = content[:match.start()].count("\n") + 1

            # Determine tags
            tags = _determine_tags(sql_snippet, call_type, framework)

            calls.append(DBCall(
                file_path=file_path,
                start_line=line_num,
                end_line=line_num + sql_snippet.count("\n"),
                language=language,
                framework=framework,
                sql_snippet=sql_snippet[:500],  # Limit length
                call_type=call_type,
                tags=tags
            ))

    return calls


def _extract_sql_snippet(content: str, start_pos: int, language: str) -> str:
    """Extract SQL snippet from match position.

    Args:
        content: File content
        start_pos: Match start position
        language: Programming language

    Returns:
        Extracted SQL snippet
    """
    # Find the opening quote after the match
    quote_chars = ['"', "'", '`']
    quote_start = None
    quote_char = None

    for i in range(start_pos, min(start_pos + 100, len(content))):
        if content[i] in quote_chars:
            quote_start = i
            quote_char = content[i]
            break

    if not quote_start:
        return ""

    # Find closing quote (simple - doesn't handle escapes perfectly)
    quote_end = content.find(quote_char, quote_start + 1)
    if quote_end == -1:
        return ""

    snippet = content[quote_start + 1:quote_end]

    # For template literals in JS/TS, handle multiline
    if language in ("javascript", "typescript") and quote_char == '`':
        # Extract up to 500 chars or closing backtick
        max_end = min(quote_start + 500, len(content))
        for i in range(quote_start + 1, max_end):
            if content[i] == '`' and (i == 0 or content[i-1] != '\\'):
                snippet = content[quote_start + 1:i]
                break

    return snippet.strip()


def _determine_tags(sql_snippet: str, call_type: str, framework: str) -> list[str]:
    """Determine tags for a DB call.

    Args:
        sql_snippet: SQL code snippet
        call_type: Type of call
        framework: Framework name

    Returns:
        List of tags
    """
    tags = ["database"]

    # Framework tag
    if framework:
        tags.append(f"db-{framework}")

    # SQL operation tags
    sql_upper = sql_snippet.upper()

    if any(kw in sql_upper for kw in ["SELECT", "FETCH"]):
        tags.append("dml")
        tags.append("select")

    if any(kw in sql_upper for kw in ["INSERT", "UPDATE", "DELETE"]):
        tags.append("dml")
        if "INSERT" in sql_upper:
            tags.append("insert")
        if "UPDATE" in sql_upper:
            tags.append("update")
        if "DELETE" in sql_upper:
            tags.append("delete")

    if any(kw in sql_upper for kw in ["CREATE", "ALTER", "DROP"]):
        tags.append("ddl")
        tags.append("migrations")

    if any(kw in sql_upper for kw in ["BEGIN", "COMMIT", "ROLLBACK", "TRANSACTION"]):
        tags.append("transactions")

    if any(kw in sql_upper for kw in ["LOCK", "FOR UPDATE", "FOR SHARE"]):
        tags.append("locks")

    if any(kw in sql_upper for kw in ["GRANT", "REVOKE", "ROLE", "USER"]):
        tags.append("auth-db")

    # Migration-specific
    if call_type == "migration":
        tags.append("migrations")

    return list(set(tags))  # Remove duplicates


def scan_repository_for_db_calls(
    repo_root: Path,
    file_list: list[dict[str, Any]]
) -> list[DBCall]:
    """Scan entire repository for database calls.

    Args:
        repo_root: Repository root path
        file_list: List of files with language info

    Returns:
        List of all discovered DB calls
    """
    all_calls = []

    for file_info in file_list:
        file_path = repo_root / file_info["path"]
        language = file_info["language"]

        # Only scan supported languages
        if language not in ("javascript", "typescript", "python", "go", "java"):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            calls = discover_db_calls(str(file_path), content, language)
            all_calls.extend(calls)
        except Exception:
            # Skip files that can't be read
            continue

    return all_calls


def summarize_db_calls(calls: list[DBCall]) -> dict[str, Any]:
    """Summarize discovered database calls.

    Args:
        calls: List of DB calls

    Returns:
        Summary statistics
    """
    total = len(calls)

    # Count by language
    by_language = {}
    for call in calls:
        by_language[call.language] = by_language.get(call.language, 0) + 1

    # Count by framework
    by_framework = {}
    for call in calls:
        by_framework[call.framework] = by_framework.get(call.framework, 0) + 1

    # Count by call type
    by_type = {}
    for call in calls:
        by_type[call.call_type] = by_type.get(call.call_type, 0) + 1

    # Collect unique tags
    all_tags = set()
    for call in calls:
        all_tags.update(call.tags)

    return {
        "total_calls": total,
        "by_language": by_language,
        "by_framework": by_framework,
        "by_type": by_type,
        "unique_tags": sorted(list(all_tags)),
        "sample_calls": [
            {
                "file": call.file_path,
                "line": call.start_line,
                "framework": call.framework,
                "type": call.call_type,
                "snippet": call.sql_snippet[:100]  # First 100 chars
            }
            for call in calls[:10]  # Top 10 samples
        ]
    }
