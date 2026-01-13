"""SQL schema file parser using sqlglot.

Extracts structured metadata from CREATE TABLE, CREATE FUNCTION,
CREATE PROCEDURE, and CREATE TRIGGER statements.
"""
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from typing import Iterator

import sqlglot
from sqlglot import exp


@dataclass
class ParsedColumn:
    """Parsed column definition from CREATE TABLE."""
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    fk_references: str | None = None  # "table.column" or "table(column)"
    comment: str | None = None


@dataclass
class ParsedConstraint:
    """Parsed constraint from CREATE TABLE."""
    name: str | None
    constraint_type: str  # "PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK"
    definition: str
    columns: list[str] = field(default_factory=list)


@dataclass
class ParsedIndex:
    """Parsed index definition."""
    name: str | None
    columns: list[str]
    unique: bool = False
    using: str | None = None  # "btree", "gin", "gist", etc.


@dataclass
class ParsedTable:
    """Parsed CREATE TABLE statement."""
    schema_name: str | None
    table_name: str
    qualified_name: str
    columns: list[ParsedColumn]
    constraints: list[ParsedConstraint] = field(default_factory=list)
    indexes: list[ParsedIndex] = field(default_factory=list)
    create_statement: str = ""
    start_line: int = 0
    end_line: int = 0
    content_hash: str = ""


@dataclass
class ParsedParameter:
    """Parsed parameter for function/procedure."""
    name: str | None
    data_type: str
    mode: str = "IN"  # IN, OUT, INOUT
    default: str | None = None


@dataclass
class ParsedRoutine:
    """Parsed CREATE FUNCTION/PROCEDURE/TRIGGER statement."""
    schema_name: str | None
    routine_name: str
    qualified_name: str
    routine_type: str  # "FUNCTION", "PROCEDURE", "TRIGGER"
    parameters: list[ParsedParameter] = field(default_factory=list)
    return_type: str | None = None
    language: str | None = None  # "plpgsql", "sql", "python"
    volatility: str | None = None  # "VOLATILE", "STABLE", "IMMUTABLE"
    # For triggers
    trigger_table: str | None = None
    trigger_events: list[str] = field(default_factory=list)  # ["INSERT", "UPDATE", "DELETE"]
    trigger_timing: str | None = None  # "BEFORE", "AFTER", "INSTEAD OF"
    create_statement: str = ""
    start_line: int = 0
    end_line: int = 0
    content_hash: str = ""


def detect_sql_dialect(content: str) -> str:
    """Auto-detect SQL dialect from content.

    Looks for dialect-specific patterns to determine the source database.

    Args:
        content: SQL file content

    Returns:
        Detected dialect: "oracle", "postgres", "mysql", "sqlserver", or "postgres" (default)
    """
    content_upper = content.upper()

    # Oracle patterns (check first as it has most distinctive syntax)
    oracle_patterns = [
        r'\bROWNUM\b',
        r'\bCONNECT\s+BY\b',
        r'\bSTART\s+WITH\b',
        r'\bNVL\s*\(',
        r'\bNVL2\s*\(',
        r'\bDECODE\s*\(',
        r'\bFROM\s+DUAL\b',
        r'\bSYSDATE\b',
        r'\bSYSTIMESTAMP\b',
        r'\w+\.NEXTVAL\b',
        r'\w+\.CURRVAL\b',
        r'\bDBMS_\w+',
        r'\bUTL_\w+',
        r'RETURN\s+\w+\s+IS\b',  # Oracle function syntax
        r'RETURN\s+\w+\s+AS\b',
        r'\bPRAGMA\s+',
        r'\bVARCHAR2\b',
        r'\bNUMBER\s*\(',
        r'\bPLS_INTEGER\b',
        r'\bBINARY_DOUBLE\b',
        r'\bBINARY_FLOAT\b',
        r'^\s*/\s*$',  # Oracle statement delimiter on its own line
    ]
    oracle_score = sum(1 for p in oracle_patterns if re.search(p, content, re.IGNORECASE | re.MULTILINE))

    # SQL Server patterns
    sqlserver_patterns = [
        r'\bTOP\s+\d+\b',
        r'\bWITH\s*\(\s*NOLOCK\s*\)',
        r'\bIDENTITY\s*\(',
        r'^\s*GO\s*$',
        r'\bsp_\w+',
        r'\bxp_\w+',
        r'\[@\w+\]',
        r'\bNVARCHAR\b',
        r'\bDATETIME2\b',
    ]
    sqlserver_score = sum(1 for p in sqlserver_patterns if re.search(p, content, re.IGNORECASE | re.MULTILINE))

    # MySQL patterns
    mysql_patterns = [
        r'\bAUTO_INCREMENT\b',
        r'\bLIMIT\s+\d+\s*,\s*\d+',
        r'`\w+`',
        r'\bENGINE\s*=',
        r'\bTINYINT\b',
        r'\bMEDIUMINT\b',
    ]
    mysql_score = sum(1 for p in mysql_patterns if re.search(p, content, re.IGNORECASE | re.MULTILINE))

    # Determine winner
    scores = {
        'oracle': oracle_score,
        'sqlserver': sqlserver_score,
        'mysql': mysql_score,
    }

    max_score = max(scores.values())
    if max_score >= 2:  # Need at least 2 patterns to be confident
        for dialect, score in scores.items():
            if score == max_score:
                return dialect

    return "postgres"  # Default


def parse_sql_file(
    content: str,
    dialect: str = "auto"
) -> tuple[list[ParsedTable], list[ParsedRoutine]]:
    """Parse SQL file and extract all CREATE statements.

    Args:
        content: SQL file content
        dialect: SQL dialect (auto, postgres, oracle, mysql, sqlserver, etc.)
                 If "auto", will attempt to detect from content.

    Returns:
        Tuple of (tables, routines)
    """
    # Auto-detect dialect if requested
    if dialect == "auto":
        dialect = detect_sql_dialect(content)

    tables = []
    routines = []

    # Split into statements while tracking line numbers
    statements = _split_sql_statements(content, dialect)

    for stmt_text, start_line, end_line in statements:
        stmt_upper = stmt_text.strip().upper()

        if stmt_upper.startswith("CREATE TABLE"):
            table = parse_create_table(stmt_text, dialect, start_line, end_line)
            if table:
                tables.append(table)

        elif stmt_upper.startswith(("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")):
            routine = parse_create_routine(stmt_text, "FUNCTION", dialect, start_line, end_line)
            if routine:
                routines.append(routine)

        elif stmt_upper.startswith(("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE")):
            routine = parse_create_routine(stmt_text, "PROCEDURE", dialect, start_line, end_line)
            if routine:
                routines.append(routine)

        elif stmt_upper.startswith(("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER")):
            routine = parse_create_trigger(stmt_text, dialect, start_line, end_line)
            if routine:
                routines.append(routine)

        # Oracle PACKAGE BODY contains multiple routines
        elif stmt_upper.startswith(("CREATE PACKAGE BODY", "CREATE OR REPLACE PACKAGE BODY")):
            pkg_routines = parse_oracle_package_body(stmt_text, dialect, start_line, end_line)
            routines.extend(pkg_routines)

        # Oracle PACKAGE spec (just declarations, but we can extract signatures)
        elif stmt_upper.startswith(("CREATE PACKAGE", "CREATE OR REPLACE PACKAGE")):
            # Package spec contains declarations - we could extract these as signatures
            # but the real implementations are in PACKAGE BODY, so skip spec for now
            pass

    return tables, routines


def parse_create_table(
    statement: str,
    dialect: str = "postgres",
    start_line: int = 0,
    end_line: int = 0
) -> ParsedTable | None:
    """Parse a CREATE TABLE statement.

    Args:
        statement: SQL CREATE TABLE statement
        dialect: SQL dialect
        start_line: Starting line number in source file
        end_line: Ending line number in source file

    Returns:
        ParsedTable or None if parsing fails
    """
    try:
        parsed = sqlglot.parse_one(statement, dialect=dialect)

        if not isinstance(parsed, exp.Create):
            return None

        # Get table name
        table_expr = parsed.this
        if not isinstance(table_expr, (exp.Table, exp.Schema)):
            return None

        # Extract schema and table name
        if isinstance(table_expr, exp.Schema):
            table_info = table_expr.this
        else:
            table_info = table_expr

        table_name = table_info.name if hasattr(table_info, 'name') else str(table_info)
        schema_name = None

        if hasattr(table_info, 'db') and table_info.db:
            schema_name = table_info.db

        qualified_name = f"{schema_name}.{table_name}" if schema_name else table_name

        # Parse columns
        columns = []
        constraints = []
        pk_columns = set()

        # Get the schema expression (contains column definitions)
        schema_expr = parsed.this
        if isinstance(schema_expr, exp.Schema):
            for expr in schema_expr.expressions:
                if isinstance(expr, exp.ColumnDef):
                    col = _parse_column_def(expr)
                    if col:
                        columns.append(col)
                        if col.is_primary_key:
                            pk_columns.add(col.name)

                elif isinstance(expr, (exp.PrimaryKey, exp.ForeignKey, exp.UniqueColumnConstraint)):
                    constraint = _parse_constraint(expr)
                    if constraint:
                        constraints.append(constraint)
                        if isinstance(expr, exp.PrimaryKey):
                            pk_columns.update(constraint.columns)

        # Mark primary key columns
        for col in columns:
            if col.name in pk_columns:
                col.is_primary_key = True

        # Calculate content hash
        content_hash = hashlib.sha256(statement.encode()).hexdigest()[:16]

        return ParsedTable(
            schema_name=schema_name,
            table_name=table_name,
            qualified_name=qualified_name,
            columns=columns,
            constraints=constraints,
            indexes=[],  # Indexes are usually separate statements
            create_statement=statement,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash
        )

    except Exception as e:
        # Fall back to regex-based parsing for edge cases
        return _parse_create_table_fallback(statement, start_line, end_line)


def parse_create_routine(
    statement: str,
    routine_type: str,
    dialect: str = "postgres",
    start_line: int = 0,
    end_line: int = 0
) -> ParsedRoutine | None:
    """Parse a CREATE FUNCTION or CREATE PROCEDURE statement.

    Args:
        statement: SQL CREATE FUNCTION/PROCEDURE statement
        routine_type: "FUNCTION" or "PROCEDURE"
        dialect: SQL dialect
        start_line: Starting line number
        end_line: Ending line number

    Returns:
        ParsedRoutine or None if parsing fails
    """
    try:
        # sqlglot may struggle with complex functions, use regex extraction
        routine_name, schema_name = _extract_routine_name(statement, routine_type)
        if not routine_name:
            return None

        qualified_name = f"{schema_name}.{routine_name}" if schema_name else routine_name

        # Extract parameters
        parameters = _extract_parameters(statement)

        # Extract return type (for functions)
        return_type = None
        if routine_type == "FUNCTION":
            return_type = _extract_return_type(statement)

        # Extract language
        language = _extract_language(statement)

        # Extract volatility
        volatility = _extract_volatility(statement)

        content_hash = hashlib.sha256(statement.encode()).hexdigest()[:16]

        return ParsedRoutine(
            schema_name=schema_name,
            routine_name=routine_name,
            qualified_name=qualified_name,
            routine_type=routine_type,
            parameters=parameters,
            return_type=return_type,
            language=language,
            volatility=volatility,
            create_statement=statement,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash
        )

    except Exception:
        return None


def parse_create_trigger(
    statement: str,
    dialect: str = "postgres",
    start_line: int = 0,
    end_line: int = 0
) -> ParsedRoutine | None:
    """Parse a CREATE TRIGGER statement.

    Args:
        statement: SQL CREATE TRIGGER statement
        dialect: SQL dialect
        start_line: Starting line number
        end_line: Ending line number

    Returns:
        ParsedRoutine or None if parsing fails
    """
    try:
        # Extract trigger name
        name_match = re.search(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\w.]+)',
            statement,
            re.IGNORECASE
        )
        if not name_match:
            return None

        full_name = name_match.group(1).strip('"')
        if '.' in full_name:
            schema_name, trigger_name = full_name.rsplit('.', 1)
        else:
            schema_name = None
            trigger_name = full_name

        qualified_name = f"{schema_name}.{trigger_name}" if schema_name else trigger_name

        # Extract timing (BEFORE, AFTER, INSTEAD OF)
        timing_match = re.search(
            r'\b(BEFORE|AFTER|INSTEAD\s+OF)\b',
            statement,
            re.IGNORECASE
        )
        trigger_timing = timing_match.group(1).upper() if timing_match else None

        # Extract events (INSERT, UPDATE, DELETE)
        events = []
        if re.search(r'\bINSERT\b', statement, re.IGNORECASE):
            events.append("INSERT")
        if re.search(r'\bUPDATE\b', statement, re.IGNORECASE):
            events.append("UPDATE")
        if re.search(r'\bDELETE\b', statement, re.IGNORECASE):
            events.append("DELETE")
        if re.search(r'\bTRUNCATE\b', statement, re.IGNORECASE):
            events.append("TRUNCATE")

        # Extract table name
        table_match = re.search(
            r'\bON\s+(["\w.]+)',
            statement,
            re.IGNORECASE
        )
        trigger_table = table_match.group(1).strip('"') if table_match else None

        content_hash = hashlib.sha256(statement.encode()).hexdigest()[:16]

        return ParsedRoutine(
            schema_name=schema_name,
            routine_name=trigger_name,
            qualified_name=qualified_name,
            routine_type="TRIGGER",
            trigger_table=trigger_table,
            trigger_events=events,
            trigger_timing=trigger_timing,
            create_statement=statement,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash
        )

    except Exception:
        return None


def parse_oracle_package_body(
    statement: str,
    dialect: str = "oracle",
    start_line: int = 0,
    end_line: int = 0
) -> list[ParsedRoutine]:
    """Parse an Oracle PACKAGE BODY and extract all routines within.

    Oracle PACKAGE BODY contains multiple PROCEDURE and FUNCTION definitions
    without the CREATE keyword. Each routine ends with END routine_name;

    Args:
        statement: SQL CREATE PACKAGE BODY statement
        dialect: SQL dialect (should be oracle)
        start_line: Starting line number
        end_line: Ending line number

    Returns:
        List of ParsedRoutine for each procedure/function in the package
    """
    routines = []

    try:
        # Extract package name
        pkg_name_match = re.search(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+BODY\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\w.]+)',
            statement,
            re.IGNORECASE
        )
        if not pkg_name_match:
            return routines

        full_pkg_name = pkg_name_match.group(1).strip('"')
        if '.' in full_pkg_name:
            schema_name, pkg_name = full_pkg_name.rsplit('.', 1)
        else:
            schema_name = None
            pkg_name = full_pkg_name

        # Find the body content after AS/IS
        body_match = re.search(
            r'PACKAGE\s+BODY\s+["\w.]+\s+(?:AS|IS)\s+(.*?)(?:END\s+' + re.escape(pkg_name) + r'\s*;)',
            statement,
            re.IGNORECASE | re.DOTALL
        )
        if not body_match:
            # Try without the END package_name (might be at the very end)
            body_match = re.search(
                r'PACKAGE\s+BODY\s+["\w.]+\s+(?:AS|IS)\s+(.*)',
                statement,
                re.IGNORECASE | re.DOTALL
            )
        if not body_match:
            return routines

        body_content = body_match.group(1)

        # Find all PROCEDURE and FUNCTION definitions in the body
        # Oracle syntax: PROCEDURE name(...) IS|AS ... END name;
        #                FUNCTION name(...) RETURN type IS|AS ... END name;

        # Pattern to find routine headers (simplified - we extract params separately)
        # This just finds the routine type and name, then we parse forward
        routine_header_pattern = re.compile(
            r'(?:^|\s)(PROCEDURE|FUNCTION)\s+(\w+)\s*\(',
            re.IGNORECASE | re.MULTILINE
        )

        # Track line offset within the body
        body_start_offset = statement.find(body_content)
        body_lines_before = statement[:body_start_offset].count('\n')

        for match in routine_header_pattern.finditer(body_content):
            routine_type = match.group(1).upper()
            routine_name = match.group(2)

            # Find balanced closing parenthesis for parameters
            paren_start = match.end() - 1  # Position of opening (
            paren_end = _find_balanced_paren(body_content, paren_start)
            if paren_end == -1:
                continue

            params_str = body_content[paren_start:paren_end + 1]

            # Find RETURN type and IS/AS after parameters
            after_params = body_content[paren_end + 1:]
            return_type = None

            # Check for RETURN clause (functions)
            return_match = re.match(
                r'\s*RETURN\s+(\w+)\s*(?:PIPELINED|DETERMINISTIC|PARALLEL_ENABLE|RESULT_CACHE)?\s*(?:IS|AS)\b',
                after_params,
                re.IGNORECASE
            )
            if return_match:
                return_type = return_match.group(1)
            else:
                # Must be a procedure - check for IS/AS
                is_match = re.match(r'\s*(?:IS|AS)\b', after_params, re.IGNORECASE)
                if not is_match:
                    continue  # Not a valid routine definition

            # Calculate line numbers within the package body
            match_pos = match.start()
            routine_line_offset = body_content[:match_pos].count('\n')
            routine_start_line = start_line + body_lines_before + routine_line_offset

            # Find the END statement for this routine to get end line
            end_pattern = re.compile(
                rf'END\s+{re.escape(routine_name)}\s*;',
                re.IGNORECASE
            )
            end_match = end_pattern.search(body_content, paren_end)
            if end_match:
                routine_end_offset = body_content[:end_match.end()].count('\n')
                routine_end_line = start_line + body_lines_before + routine_end_offset
                # Extract the full routine text
                routine_text = body_content[match.start():end_match.end()]
            else:
                routine_end_line = end_line
                routine_text = body_content[match.start():]

            # Extract parameters
            parameters = _extract_oracle_package_params(params_str)

            # Qualified name includes package
            qualified_name = f"{pkg_name}.{routine_name}"
            if schema_name:
                qualified_name = f"{schema_name}.{qualified_name}"

            content_hash = hashlib.sha256(routine_text.encode()).hexdigest()[:16]

            routines.append(ParsedRoutine(
                schema_name=schema_name,
                routine_name=routine_name,
                qualified_name=qualified_name,
                routine_type=routine_type,
                parameters=parameters,
                return_type=return_type,
                language="plsql",
                create_statement=routine_text.strip(),
                start_line=routine_start_line,
                end_line=routine_end_line,
                content_hash=content_hash
            ))

    except Exception:
        pass

    return routines


def _extract_oracle_package_params(params_str: str) -> list[ParsedParameter]:
    """Extract parameters from Oracle package routine parameter list.

    Handles Oracle-specific syntax like:
        p_name IN VARCHAR2 DEFAULT 'value'
        p_id NUMBER
        p_result OUT NUMBER
    """
    params = []

    # Remove outer parentheses
    params_str = params_str.strip()
    if params_str.startswith('('):
        params_str = params_str[1:]
    if params_str.endswith(')'):
        params_str = params_str[:-1]

    if not params_str.strip():
        return params

    # Split on commas (but not inside parentheses)
    param_parts = _split_outside_parens(params_str, ',')

    for part in param_parts:
        part = part.strip()
        if not part:
            continue

        mode = "IN"
        name = None
        data_type = "unknown"
        default = None

        # Oracle parameter format: name [IN|OUT|IN OUT] type [DEFAULT value]
        tokens = part.split()
        if not tokens:
            continue

        idx = 0

        # First token is usually the name
        name = tokens[idx]
        idx += 1

        # Check for mode
        if idx < len(tokens) and tokens[idx].upper() in ('IN', 'OUT'):
            if tokens[idx].upper() == 'IN' and idx + 1 < len(tokens) and tokens[idx + 1].upper() == 'OUT':
                mode = "INOUT"
                idx += 2
            elif tokens[idx].upper() == 'OUT':
                mode = "OUT"
                idx += 1
            else:
                mode = "IN"
                idx += 1

        # Rest is type (and possibly DEFAULT)
        remaining = ' '.join(tokens[idx:])

        # Check for DEFAULT
        default_match = re.search(r'\bDEFAULT\s+(.+)$', remaining, re.IGNORECASE)
        if default_match:
            default = default_match.group(1).strip()
            remaining = remaining[:default_match.start()].strip()

        # Also check for := which Oracle uses as alternative to DEFAULT
        assign_match = re.search(r':=\s*(.+)$', remaining)
        if assign_match:
            default = assign_match.group(1).strip()
            remaining = remaining[:assign_match.start()].strip()

        if remaining:
            data_type = remaining

        params.append(ParsedParameter(
            name=name,
            data_type=data_type,
            mode=mode,
            default=default
        ))

    return params


# ============================================================================
# Helper Functions
# ============================================================================

def _find_balanced_paren(text: str, start: int) -> int:
    """Find the position of the closing parenthesis that balances the opening one.

    Args:
        text: The text to search in
        start: Position of the opening parenthesis

    Returns:
        Position of the closing parenthesis, or -1 if not found
    """
    if start >= len(text) or text[start] != '(':
        return -1

    depth = 0
    in_string = False
    string_char = None

    for i in range(start, len(text)):
        char = text[i]

        # Handle string literals
        if char in ("'", '"') and not in_string:
            in_string = True
            string_char = char
        elif char == string_char and in_string:
            # Check for escaped quote
            if i + 1 < len(text) and text[i + 1] == string_char:
                continue  # Skip escaped quote
            in_string = False
            string_char = None
        elif not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    return i

    return -1


def _split_sql_statements(content: str, dialect: str = "postgres") -> list[tuple[str, int, int]]:
    """Split SQL content into individual statements with line numbers.

    Handles:
    - Dollar-quoted strings ($$ or $tag$) for PostgreSQL
    - Oracle PL/SQL blocks delimited by / on its own line
    - Standard string literals
    - Comments (-- and /* */)

    Args:
        content: SQL file content
        dialect: SQL dialect (affects delimiter handling)

    Returns:
        List of (statement, start_line, end_line)
    """
    statements = []
    lines = content.split('\n')

    current_stmt = []
    current_start = 1
    in_dollar_quote = False
    dollar_tag = None
    in_plsql_block = False  # Track if we're inside a PL/SQL block

    for line_num, line in enumerate(lines, start=1):
        line_stripped = line.strip()
        line_upper = line_stripped.upper()

        # For Oracle: check if we're starting a PL/SQL block
        if dialect == "oracle" and not in_plsql_block:
            if any(line_upper.startswith(prefix) for prefix in [
                "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION",
                "CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE",
                "CREATE TRIGGER", "CREATE OR REPLACE TRIGGER",
                "CREATE PACKAGE", "CREATE OR REPLACE PACKAGE",
                "CREATE TYPE", "CREATE OR REPLACE TYPE",
                "DECLARE", "BEGIN"
            ]):
                in_plsql_block = True

        # Track dollar-quoted strings (PostgreSQL)
        if dialect == "postgres" and not in_dollar_quote:
            dollar_match = re.search(r'\$(\w*)\$', line)
            if dollar_match:
                in_dollar_quote = True
                dollar_tag = dollar_match.group(1)
                if line.count(f'${dollar_tag}$') >= 2:
                    in_dollar_quote = False
                    dollar_tag = None
        elif dialect == "postgres" and in_dollar_quote:
            if f'${dollar_tag}$' in line:
                in_dollar_quote = False
                dollar_tag = None

        current_stmt.append(line)

        # Check for statement end based on dialect
        statement_complete = False

        if dialect == "oracle":
            # Oracle: / on its own line ends PL/SQL blocks
            if line_stripped == '/':
                if in_plsql_block:
                    # End of PL/SQL block - don't include the / in the statement
                    current_stmt.pop()  # Remove the / line
                    statement_complete = True
                    in_plsql_block = False
            # For non-PL/SQL statements, semicolon still works
            elif not in_plsql_block and ';' in line:
                clean_line = re.sub(r'--.*$', '', line)
                if ';' in clean_line:
                    statement_complete = True
        else:
            # PostgreSQL/MySQL/etc: semicolon ends statements
            if not in_dollar_quote and ';' in line:
                clean_line = re.sub(r'--.*$', '', line)
                if ';' in clean_line:
                    statement_complete = True

        if statement_complete:
            stmt_text = '\n'.join(current_stmt)
            if stmt_text.strip():
                statements.append((stmt_text, current_start, line_num))
            current_stmt = []
            current_start = line_num + 1

    # Handle remaining content
    if current_stmt:
        stmt_text = '\n'.join(current_stmt)
        if stmt_text.strip():
            statements.append((stmt_text, current_start, len(lines)))

    return statements


def _parse_column_def(col_expr: exp.ColumnDef) -> ParsedColumn | None:
    """Parse a column definition expression."""
    try:
        name = col_expr.name

        # Get data type
        data_type = "unknown"
        if col_expr.kind:
            data_type = col_expr.kind.sql()

        nullable = True
        default = None
        is_pk = False
        is_fk = False
        fk_ref = None

        # Check constraints
        for constraint in col_expr.constraints:
            if isinstance(constraint, exp.NotNullColumnConstraint):
                nullable = False
            elif isinstance(constraint, exp.PrimaryKeyColumnConstraint):
                is_pk = True
                nullable = False
            elif isinstance(constraint, exp.DefaultColumnConstraint):
                default = constraint.this.sql() if constraint.this else None
            elif hasattr(constraint, 'kind') and 'REFERENCES' in str(constraint.kind).upper():
                is_fk = True

        return ParsedColumn(
            name=name,
            data_type=data_type,
            nullable=nullable,
            default=default,
            is_primary_key=is_pk,
            is_foreign_key=is_fk,
            fk_references=fk_ref
        )

    except Exception:
        return None


def _parse_constraint(constraint_expr) -> ParsedConstraint | None:
    """Parse a table constraint expression."""
    try:
        name = None
        constraint_type = ""
        columns = []

        if isinstance(constraint_expr, exp.PrimaryKey):
            constraint_type = "PRIMARY KEY"
            columns = [col.name for col in constraint_expr.expressions if hasattr(col, 'name')]

        elif isinstance(constraint_expr, exp.ForeignKey):
            constraint_type = "FOREIGN KEY"
            columns = [col.name for col in constraint_expr.expressions if hasattr(col, 'name')]

        elif isinstance(constraint_expr, exp.UniqueColumnConstraint):
            constraint_type = "UNIQUE"
            columns = [col.name for col in constraint_expr.expressions if hasattr(col, 'name')]

        if not constraint_type:
            return None

        return ParsedConstraint(
            name=name,
            constraint_type=constraint_type,
            definition=constraint_expr.sql(),
            columns=columns
        )

    except Exception:
        return None


def _parse_create_table_fallback(
    statement: str,
    start_line: int = 0,
    end_line: int = 0
) -> ParsedTable | None:
    """Fallback regex-based parser for CREATE TABLE."""
    try:
        # Extract table name
        name_match = re.search(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\w.]+)',
            statement,
            re.IGNORECASE
        )
        if not name_match:
            return None

        full_name = name_match.group(1).strip('"')
        if '.' in full_name:
            schema_name, table_name = full_name.rsplit('.', 1)
        else:
            schema_name = None
            table_name = full_name

        qualified_name = f"{schema_name}.{table_name}" if schema_name else table_name

        # Extract column definitions (basic)
        columns = []
        col_section_match = re.search(r'\(([\s\S]+)\)', statement)
        if col_section_match:
            col_section = col_section_match.group(1)
            # Split on commas but not within parentheses
            col_defs = _split_outside_parens(col_section, ',')

            for col_def in col_defs:
                col_def = col_def.strip()
                if not col_def:
                    continue

                # Skip constraint definitions
                if re.match(r'^\s*(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)\s', col_def, re.IGNORECASE):
                    continue

                # Parse column: name type [constraints]
                parts = col_def.split(None, 2)
                if len(parts) >= 2:
                    col_name = parts[0].strip('"')
                    col_type = parts[1]
                    is_pk = 'PRIMARY KEY' in col_def.upper()
                    nullable = 'NOT NULL' not in col_def.upper() and not is_pk

                    columns.append(ParsedColumn(
                        name=col_name,
                        data_type=col_type,
                        nullable=nullable,
                        is_primary_key=is_pk
                    ))

        content_hash = hashlib.sha256(statement.encode()).hexdigest()[:16]

        return ParsedTable(
            schema_name=schema_name,
            table_name=table_name,
            qualified_name=qualified_name,
            columns=columns,
            constraints=[],
            indexes=[],
            create_statement=statement,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash
        )

    except Exception:
        return None


def _extract_routine_name(statement: str, routine_type: str) -> tuple[str | None, str | None]:
    """Extract routine name and schema from CREATE statement."""
    pattern = rf'CREATE\s+(?:OR\s+REPLACE\s+)?{routine_type}\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\w.]+)'
    match = re.search(pattern, statement, re.IGNORECASE)
    if not match:
        return None, None

    full_name = match.group(1).strip('"')
    if '.' in full_name:
        schema, name = full_name.rsplit('.', 1)
        return name, schema
    return full_name, None


def _extract_parameters(statement: str) -> list[ParsedParameter]:
    """Extract function/procedure parameters."""
    params = []

    # Find parameter list between first ( and matching )
    paren_match = re.search(r'\(([^)]*)\)', statement)
    if not paren_match:
        return params

    param_str = paren_match.group(1).strip()
    if not param_str:
        return params

    # Split parameters
    param_parts = _split_outside_parens(param_str, ',')

    for part in param_parts:
        part = part.strip()
        if not part:
            continue

        # Parse: [mode] [name] type [DEFAULT value]
        mode = "IN"
        name = None
        data_type = "unknown"
        default = None

        # Check for mode
        mode_match = re.match(r'^(IN|OUT|INOUT|VARIADIC)\s+', part, re.IGNORECASE)
        if mode_match:
            mode = mode_match.group(1).upper()
            part = part[mode_match.end():]

        # Check for DEFAULT
        default_match = re.search(r'\bDEFAULT\s+(.+)$', part, re.IGNORECASE)
        if default_match:
            default = default_match.group(1).strip()
            part = part[:default_match.start()].strip()

        # Split remaining into name and type
        tokens = part.split()
        if len(tokens) >= 2:
            name = tokens[0]
            data_type = ' '.join(tokens[1:])
        elif len(tokens) == 1:
            data_type = tokens[0]

        params.append(ParsedParameter(
            name=name,
            data_type=data_type,
            mode=mode,
            default=default
        ))

    return params


def _extract_return_type(statement: str) -> str | None:
    """Extract function return type."""
    match = re.search(
        r'\bRETURNS\s+((?:SETOF\s+)?[\w\s\[\]()]+?)(?:\s+AS\b|\s+LANGUAGE\b|\s+\$|\s*$)',
        statement,
        re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    return None


def _extract_language(statement: str) -> str | None:
    """Extract routine language."""
    match = re.search(r'\bLANGUAGE\s+(\w+)', statement, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def _extract_volatility(statement: str) -> str | None:
    """Extract function volatility."""
    match = re.search(r'\b(VOLATILE|STABLE|IMMUTABLE)\b', statement, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _split_outside_parens(text: str, delimiter: str) -> list[str]:
    """Split text on delimiter but not inside parentheses."""
    parts = []
    current = []
    depth = 0

    for char in text:
        if char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == delimiter and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts
