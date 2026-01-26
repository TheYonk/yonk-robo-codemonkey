"""
Feature extraction from documentation.

Extracts documented features like:
- Oracle packages/functions (DBMS_OUTPUT, UTL_FILE, etc.)
- SQL constructs (CONNECT BY, ROWNUM, etc.)
- EPAS features (dblink_ora, EDB*Plus, etc.)
- Configuration parameters
- Migration patterns
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFeature:
    """A feature extracted from documentation."""
    name: str
    feature_type: str  # package, function, procedure, syntax, datatype, parameter
    category: str  # oracle, epas, postgres, migration
    description: Optional[str] = None
    signature: Optional[str] = None
    epas_support: Optional[str] = None  # full, partial, unsupported, workaround
    postgres_equivalent: Optional[str] = None
    example_usage: Optional[str] = None
    chunk_ids: list[UUID] = field(default_factory=list)
    mention_count: int = 1
    first_seen_page: Optional[int] = None


# Oracle packages and their common functions
ORACLE_PACKAGES = {
    "DBMS_OUTPUT": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for displaying output from PL/SQL blocks, subprograms, packages, and triggers. Commonly used for debugging by writing messages to a buffer that can be read by the client.",
        "functions": ["PUT_LINE", "PUT", "NEW_LINE", "GET_LINE", "GET_LINES", "ENABLE", "DISABLE"],
    },
    "DBMS_LOB": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for manipulating Large Objects (LOBs) including BLOBs, CLOBs, NCLOBs, and BFILEs. Provides operations like read, write, append, copy, trim, and compare.",
        "functions": ["SUBSTR", "INSTR", "GETLENGTH", "READ", "WRITE", "APPEND", "COPY", "TRIM", "ERASE"],
    },
    "DBMS_SQL": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for dynamic SQL execution. Allows parsing and executing SQL statements built at runtime, with full control over bind variables and cursor management.",
        "functions": ["OPEN_CURSOR", "PARSE", "BIND_VARIABLE", "EXECUTE", "FETCH_ROWS", "CLOSE_CURSOR"],
    },
    "DBMS_UTILITY": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Utility package providing miscellaneous functions including error stack formatting, time measurement, name resolution, and comma-separated list parsing.",
        "functions": ["FORMAT_ERROR_BACKTRACE", "FORMAT_ERROR_STACK", "GET_TIME", "COMMA_TO_TABLE"],
    },
    "DBMS_SCHEDULER": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Advanced job scheduling package supporting complex schedules, job chains, event-based scheduling, and resource management. More feature-rich than DBMS_JOB.",
        "functions": ["CREATE_JOB", "DROP_JOB", "ENABLE", "DISABLE", "RUN_JOB", "STOP_JOB"],
    },
    "DBMS_JOB": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for scheduling and managing recurring jobs. Allows submitting PL/SQL blocks to run at specified intervals. Simpler than DBMS_SCHEDULER.",
        "functions": ["SUBMIT", "REMOVE", "CHANGE", "WHAT", "NEXT_DATE", "INTERVAL", "BROKEN", "RUN"],
    },
    "UTL_FILE": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for reading and writing operating system text files from PL/SQL. Files must be in directories defined by the DBA.",
        "functions": ["FOPEN", "FCLOSE", "PUT", "PUT_LINE", "GET_LINE", "NEW_LINE", "FFLUSH", "IS_OPEN"],
    },
    "UTL_HTTP": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Package for making HTTP callouts from PL/SQL. Supports GET/POST requests, headers, cookies, and authentication.",
        "functions": ["REQUEST", "REQUEST_PIECES", "BEGIN_REQUEST", "SET_HEADER", "GET_RESPONSE"],
    },
    "UTL_MAIL": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "unsupported",
        "description": "Package for sending email from PL/SQL including attachments. Requires SMTP server configuration.",
        "functions": ["SEND", "SEND_ATTACH_RAW", "SEND_ATTACH_VARCHAR2"],
    },
    "DBMS_CRYPTO": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Package for encrypting and decrypting data using industry-standard algorithms (AES, DES, 3DES). Also provides hashing (MD5, SHA) and MAC functions.",
        "functions": ["ENCRYPT", "DECRYPT", "HASH", "MAC", "RANDOMBYTES"],
    },
    "DBMS_RANDOM": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for generating random numbers and strings. Useful for testing, sampling, and cryptographic applications.",
        "functions": ["VALUE", "STRING", "NORMAL", "SEED", "INITIALIZE", "TERMINATE"],
    },
    "DBMS_LOCK": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for user-defined locks and sleep functionality. Allows coordination between sessions and timed waits.",
        "functions": ["SLEEP", "REQUEST", "RELEASE", "CONVERT", "ALLOCATE_UNIQUE"],
    },
    "DBMS_PIPE": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for inter-session communication via named pipes. Allows asynchronous message passing between database sessions.",
        "functions": ["PACK_MESSAGE", "UNPACK_MESSAGE", "SEND_MESSAGE", "RECEIVE_MESSAGE", "CREATE_PIPE"],
    },
    "DBMS_ALERT": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for asynchronous notification between sessions. Sessions can register interest in named alerts and wait for signals.",
        "functions": ["REGISTER", "REMOVE", "SIGNAL", "WAITANY", "WAITONE"],
    },
    "DBMS_AQ": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Advanced Queuing package for message queuing operations. Provides enqueue and dequeue operations with various delivery modes.",
        "functions": ["ENQUEUE", "DEQUEUE", "LISTEN"],
    },
    "DBMS_AQADM": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Advanced Queuing administration package for creating and managing queue tables, queues, and queue subscribers.",
        "functions": ["CREATE_QUEUE", "DROP_QUEUE", "START_QUEUE", "STOP_QUEUE", "CREATE_QUEUE_TABLE"],
    },
    "DBMS_SESSION": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Package for managing session settings including roles, NLS parameters, SQL trace, and package state.",
        "functions": ["SET_ROLE", "SET_NLS", "SET_SQL_TRACE", "RESET_PACKAGE"],
    },
    "DBMS_PROFILER": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "full",
        "description": "Package for profiling PL/SQL code execution. Collects timing statistics for each line of code to identify performance bottlenecks.",
        "functions": ["START_PROFILER", "STOP_PROFILER", "FLUSH_DATA", "PAUSE_PROFILER", "RESUME_PROFILER"],
    },
    "DBMS_RLS": {
        "category": "oracle",
        "feature_type": "package",
        "epas_support": "partial",
        "description": "Row Level Security (Virtual Private Database) package. Allows defining security policies that automatically add predicates to queries.",
        "functions": ["ADD_POLICY", "DROP_POLICY", "ENABLE_POLICY", "REFRESH_POLICY"],
    },
}

# Oracle SQL syntax constructs
ORACLE_SYNTAX = {
    "CONNECT BY": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "WITH RECURSIVE", "description": "Hierarchical query clause for traversing tree-structured data. Used with START WITH to define the root and PRIOR to navigate parent-child relationships."},
    "START WITH": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "WITH RECURSIVE", "description": "Specifies the root row(s) of a hierarchical query. Used with CONNECT BY to build tree traversals."},
    "PRIOR": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "WITH RECURSIVE", "description": "Operator in hierarchical queries that refers to the parent row. PRIOR column_name references the column value from the parent."},
    "LEVEL": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "WITH RECURSIVE depth", "description": "Pseudocolumn returning the depth level in a hierarchical query (1 for root, 2 for children, etc.)."},
    "ROWNUM": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "ROW_NUMBER() OVER() or LIMIT", "description": "Pseudocolumn assigning sequential numbers to rows as they are retrieved. Commonly used for limiting results (WHERE ROWNUM <= N)."},
    "ROWID": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "ctid", "description": "Pseudocolumn containing the physical address of a row. Useful for identifying and accessing specific rows quickly."},
    "DECODE": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "CASE WHEN", "description": "Function providing if-then-else logic. DECODE(expr, search1, result1, search2, result2, ..., default) compares expr to search values."},
    "NVL": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "COALESCE", "description": "Null-value substitution function. NVL(expr1, expr2) returns expr2 if expr1 is NULL, otherwise expr1."},
    "NVL2": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "CASE WHEN IS NOT NULL", "description": "Extended null check. NVL2(expr1, expr2, expr3) returns expr2 if expr1 is NOT NULL, otherwise expr3."},
    "SYSDATE": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "CURRENT_TIMESTAMP", "description": "Returns the current date and time of the database server as a DATE value."},
    "SYSTIMESTAMP": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "CURRENT_TIMESTAMP", "description": "Returns the current date and time with fractional seconds and timezone as a TIMESTAMP WITH TIME ZONE."},
    "DUAL": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "No FROM clause", "description": "Special one-row, one-column table used for selecting system values or expressions (SELECT SYSDATE FROM DUAL)."},
    "MERGE INTO": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "INSERT ON CONFLICT or MERGE (PG15+)", "description": "Combines INSERT and UPDATE in a single statement. Matches rows and updates them, or inserts if no match found (upsert)."},
    "(+)": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "LEFT/RIGHT JOIN", "description": "Oracle outer join operator. Place (+) on the deficient side to include unmatched rows (legacy syntax, prefer ANSI joins)."},
    "OUTER JOIN (+)": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "LEFT/RIGHT/FULL OUTER JOIN", "description": "Oracle's legacy outer join syntax using (+) operator. Should be migrated to ANSI JOIN syntax."},
    "MINUS": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "EXCEPT", "description": "Set operation returning rows in the first query that are not in the second query."},
    "LISTAGG": {"category": "oracle", "feature_type": "function", "epas_support": "partial", "postgres_equivalent": "STRING_AGG", "description": "Aggregate function that concatenates values from multiple rows into a single string with a delimiter."},
    "XMLAGG": {"category": "oracle", "feature_type": "function", "epas_support": "partial", "postgres_equivalent": "XMLAGG or STRING_AGG", "description": "Aggregate function that concatenates XML fragments from multiple rows into a single XML document."},
    "WM_CONCAT": {"category": "oracle", "feature_type": "function", "epas_support": "unsupported", "postgres_equivalent": "STRING_AGG", "description": "Undocumented Oracle function for string aggregation. Deprecated - use LISTAGG instead."},
    "TO_DATE": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "TO_DATE", "description": "Converts a string to a DATE using a format mask. TO_DATE('2024-01-15', 'YYYY-MM-DD')."},
    "TO_CHAR": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "TO_CHAR", "description": "Converts dates, numbers, or other types to a formatted string using a format mask."},
    "TO_NUMBER": {"category": "oracle", "feature_type": "function", "epas_support": "full", "postgres_equivalent": "TO_NUMBER or ::numeric", "description": "Converts a string to a number using an optional format mask. TO_NUMBER('1,234.56', '9,999.99')."},
}

# Oracle PL/SQL constructs
ORACLE_PLSQL = {
    "BULK COLLECT": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Fetches multiple rows into a collection in a single operation, significantly improving performance over row-by-row processing."},
    "FORALL": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Executes a DML statement for all elements in a collection in a single context switch, dramatically improving bulk operation performance."},
    "REF CURSOR": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "REFCURSOR", "description": "Cursor variable that can be passed between programs. Allows dynamic association with different queries at runtime."},
    "SYS_REFCURSOR": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "REFCURSOR", "description": "Predefined weak REF CURSOR type that can reference any query result set. Commonly used for returning result sets from procedures."},
    "AUTONOMOUS_TRANSACTION": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Pragma that creates an independent transaction within another transaction. Commits/rollbacks in the autonomous transaction don't affect the parent."},
    "PRAGMA": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Compiler directive that provides instructions to the PL/SQL compiler (e.g., AUTONOMOUS_TRANSACTION, EXCEPTION_INIT, RESTRICT_REFERENCES)."},
    "EXCEPTION_INIT": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Pragma that associates an exception name with an Oracle error number, allowing named exception handling for specific errors."},
    "RAISE_APPLICATION_ERROR": {"category": "oracle", "feature_type": "procedure", "epas_support": "full", "description": "Raises a user-defined exception with a custom error number (-20000 to -20999) and message. Used to communicate errors to calling applications."},
    "EXECUTE IMMEDIATE": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Executes a dynamically constructed SQL or PL/SQL statement. Supports bind variables with USING clause and output with INTO clause."},
    "OPEN FOR": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Associates a cursor variable with a query. OPEN cursor_var FOR select_statement allows dynamic query assignment."},
    "TYPE ... IS TABLE OF": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Declares a collection type (nested table or associative array). Elements are accessed by index and can be used with BULK COLLECT."},
    "TYPE ... IS RECORD": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Declares a composite data type with named fields. Similar to a struct, used to group related data elements."},
    "%TYPE": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Anchored declaration that copies the datatype of a column or variable. v_name employees.name%TYPE ensures type consistency."},
    "%ROWTYPE": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "description": "Anchored declaration that creates a record matching a table or cursor row structure. Simplifies working with complete rows."},
    "DETERMINISTIC": {"category": "oracle", "feature_type": "syntax", "epas_support": "full", "postgres_equivalent": "IMMUTABLE", "description": "Function hint indicating the function always returns the same result for the same inputs. Enables caching and optimization."},
    "PIPELINED": {"category": "oracle", "feature_type": "syntax", "epas_support": "partial", "description": "Table function modifier that returns rows iteratively as they are produced, enabling parallel execution and reduced memory usage."},
}

# Oracle data types
ORACLE_DATATYPES = {
    "VARCHAR2": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "VARCHAR"},
    "NUMBER": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "NUMERIC"},
    "PLS_INTEGER": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "INTEGER"},
    "BINARY_INTEGER": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "INTEGER"},
    "LONG": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "TEXT"},
    "LONG RAW": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "BYTEA"},
    "RAW": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "BYTEA"},
    "CLOB": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "TEXT"},
    "BLOB": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "BYTEA"},
    "NCLOB": {"category": "oracle", "feature_type": "datatype", "epas_support": "full", "postgres_equivalent": "TEXT"},
    "XMLTYPE": {"category": "oracle", "feature_type": "datatype", "epas_support": "partial", "postgres_equivalent": "XML"},
    "SDO_GEOMETRY": {"category": "oracle", "feature_type": "datatype", "epas_support": "unsupported", "postgres_equivalent": "PostGIS geometry"},
}

# EPAS-specific features
EPAS_FEATURES = {
    "dblink_ora": {"category": "epas", "feature_type": "package", "epas_support": "full", "description": "EPAS extension enabling connections to Oracle databases. Allows querying Oracle tables and executing Oracle procedures from EPAS."},
    "EDB*Plus": {"category": "epas", "feature_type": "tool", "epas_support": "full", "description": "SQL*Plus-compatible command-line tool for EPAS. Supports Oracle SQL*Plus scripts and commands for easier migration."},
    "edbplus": {"category": "epas", "feature_type": "tool", "epas_support": "full", "description": "Command-line executable for EDB*Plus. Provides SQL*Plus compatibility for interactive SQL and scripting."},
    "SPL": {"category": "epas", "feature_type": "language", "epas_support": "full", "description": "Stored Procedure Language - EPAS's Oracle-compatible procedural language. Supports Oracle PL/SQL syntax and constructs."},
    "edb_redwood_date": {"category": "epas", "feature_type": "parameter", "epas_support": "full", "description": "When enabled, DATE type includes time component like Oracle. Default PostgreSQL DATE is date-only."},
    "edb_redwood_raw_names": {"category": "epas", "feature_type": "parameter", "epas_support": "full", "description": "When enabled, unquoted identifiers are stored in uppercase like Oracle. PostgreSQL default is lowercase."},
    "edb_stmt_level_tx": {"category": "epas", "feature_type": "parameter", "epas_support": "full", "description": "Enables Oracle-style statement-level transaction isolation. Failed statements don't abort the entire transaction."},
    "oracle_home": {"category": "epas", "feature_type": "parameter", "epas_support": "full", "description": "Points to Oracle client installation for dblink_ora connections. Required for Oracle database connectivity."},
    "edb_dynatune": {"category": "epas", "feature_type": "parameter", "epas_support": "full", "description": "Dynamic tuning parameter that automatically adjusts memory settings based on available system resources."},
    "edb_data_redaction": {"category": "epas", "feature_type": "feature", "epas_support": "full", "description": "Data masking feature that redacts sensitive data at query time based on policies. Similar to Oracle Data Redaction."},
    "edb_audit": {"category": "epas", "feature_type": "feature", "epas_support": "full", "description": "Enhanced auditing capabilities compatible with Oracle audit configuration. Logs database activities for compliance."},
    "EDB Postgres Advanced Server": {"category": "epas", "feature_type": "product", "epas_support": "full", "description": "Enterprise PostgreSQL distribution with Oracle compatibility features. Includes SPL, Oracle packages, and migration tools."},
    "Migration Toolkit": {"category": "epas", "feature_type": "tool", "epas_support": "full", "description": "EDB tool for migrating schema and data from Oracle, SQL Server, MySQL, and Sybase to PostgreSQL/EPAS."},
    "MTK": {"category": "epas", "feature_type": "tool", "epas_support": "full", "description": "Abbreviation for Migration Toolkit. Command-line tool for automated database migration to EPAS."},
}


class FeatureExtractor:
    """Extracts documented features from document chunks."""

    def __init__(self):
        # Build regex patterns for efficient matching
        self._package_pattern = self._build_package_pattern()
        self._syntax_pattern = self._build_syntax_pattern()
        self._plsql_pattern = self._build_plsql_pattern()
        self._datatype_pattern = self._build_datatype_pattern()
        self._epas_pattern = self._build_epas_pattern()

    def _build_package_pattern(self) -> re.Pattern:
        """Build regex pattern for Oracle packages."""
        package_names = "|".join(re.escape(name) for name in ORACLE_PACKAGES.keys())
        return re.compile(rf"\b({package_names})(?:\.(\w+))?\b", re.IGNORECASE)

    def _build_syntax_pattern(self) -> re.Pattern:
        """Build regex pattern for Oracle syntax constructs."""
        # Sort by length (longest first) to match longer patterns first
        syntax_names = sorted(ORACLE_SYNTAX.keys(), key=len, reverse=True)
        escaped = "|".join(re.escape(name) for name in syntax_names)
        return re.compile(rf"\b({escaped})\b", re.IGNORECASE)

    def _build_plsql_pattern(self) -> re.Pattern:
        """Build regex pattern for PL/SQL constructs."""
        plsql_names = sorted(ORACLE_PLSQL.keys(), key=len, reverse=True)
        escaped = "|".join(re.escape(name) for name in plsql_names)
        return re.compile(rf"\b({escaped})\b", re.IGNORECASE)

    def _build_datatype_pattern(self) -> re.Pattern:
        """Build regex pattern for Oracle datatypes."""
        datatype_names = "|".join(re.escape(name) for name in ORACLE_DATATYPES.keys())
        return re.compile(rf"\b({datatype_names})\b", re.IGNORECASE)

    def _build_epas_pattern(self) -> re.Pattern:
        """Build regex pattern for EPAS features."""
        epas_names = sorted(EPAS_FEATURES.keys(), key=len, reverse=True)
        escaped = "|".join(re.escape(name) for name in epas_names)
        return re.compile(rf"\b({escaped})\b", re.IGNORECASE)

    def extract_features(
        self,
        chunks: list[dict],  # List of chunk dicts with 'id', 'content', 'page_number'
    ) -> list[ExtractedFeature]:
        """Extract features from a list of document chunks.

        Args:
            chunks: List of chunk dictionaries with 'id', 'content', 'page_number' keys

        Returns:
            List of ExtractedFeature objects
        """
        # Track features by (name, feature_type) for deduplication
        features: dict[tuple[str, str], ExtractedFeature] = {}

        for chunk in chunks:
            chunk_id = chunk.get("id")
            content = chunk.get("content", "")
            page_number = chunk.get("page_number")

            # Extract Oracle packages and their functions
            for match in self._package_pattern.finditer(content):
                package_name = match.group(1).upper()
                function_name = match.group(2)

                pkg_info = ORACLE_PACKAGES.get(package_name, {})

                if function_name:
                    # Package.Function reference
                    full_name = f"{package_name}.{function_name.upper()}"
                    key = (full_name, "function")
                    if key not in features:
                        features[key] = ExtractedFeature(
                            name=full_name,
                            feature_type="function",
                            category=pkg_info.get("category", "oracle"),
                            description=f"Function in {package_name} package. {pkg_info.get('description', '')}",
                            epas_support=pkg_info.get("epas_support"),
                            chunk_ids=[chunk_id] if chunk_id else [],
                            first_seen_page=page_number,
                        )
                    else:
                        features[key].mention_count += 1
                        if chunk_id and chunk_id not in features[key].chunk_ids:
                            features[key].chunk_ids.append(chunk_id)
                else:
                    # Just package reference
                    key = (package_name, "package")
                    if key not in features:
                        features[key] = ExtractedFeature(
                            name=package_name,
                            feature_type="package",
                            category=pkg_info.get("category", "oracle"),
                            description=pkg_info.get("description"),
                            epas_support=pkg_info.get("epas_support"),
                            chunk_ids=[chunk_id] if chunk_id else [],
                            first_seen_page=page_number,
                        )
                    else:
                        features[key].mention_count += 1
                        if chunk_id and chunk_id not in features[key].chunk_ids:
                            features[key].chunk_ids.append(chunk_id)

            # Extract Oracle syntax constructs
            for match in self._syntax_pattern.finditer(content):
                name = match.group(1).upper()
                info = ORACLE_SYNTAX.get(name, {})
                key = (name, info.get("feature_type", "syntax"))
                if key not in features:
                    features[key] = ExtractedFeature(
                        name=name,
                        feature_type=info.get("feature_type", "syntax"),
                        category=info.get("category", "oracle"),
                        description=info.get("description"),
                        epas_support=info.get("epas_support"),
                        postgres_equivalent=info.get("postgres_equivalent"),
                        chunk_ids=[chunk_id] if chunk_id else [],
                        first_seen_page=page_number,
                    )
                else:
                    features[key].mention_count += 1
                    if chunk_id and chunk_id not in features[key].chunk_ids:
                        features[key].chunk_ids.append(chunk_id)

            # Extract PL/SQL constructs
            for match in self._plsql_pattern.finditer(content):
                name = match.group(1).upper()
                info = ORACLE_PLSQL.get(name, {})
                key = (name, info.get("feature_type", "syntax"))
                if key not in features:
                    features[key] = ExtractedFeature(
                        name=name,
                        feature_type=info.get("feature_type", "syntax"),
                        category=info.get("category", "oracle"),
                        description=info.get("description"),
                        epas_support=info.get("epas_support"),
                        postgres_equivalent=info.get("postgres_equivalent"),
                        chunk_ids=[chunk_id] if chunk_id else [],
                        first_seen_page=page_number,
                    )
                else:
                    features[key].mention_count += 1
                    if chunk_id and chunk_id not in features[key].chunk_ids:
                        features[key].chunk_ids.append(chunk_id)

            # Extract Oracle datatypes
            for match in self._datatype_pattern.finditer(content):
                name = match.group(1).upper()
                info = ORACLE_DATATYPES.get(name, {})
                key = (name, "datatype")
                if key not in features:
                    features[key] = ExtractedFeature(
                        name=name,
                        feature_type="datatype",
                        category=info.get("category", "oracle"),
                        description=info.get("description"),
                        epas_support=info.get("epas_support"),
                        postgres_equivalent=info.get("postgres_equivalent"),
                        chunk_ids=[chunk_id] if chunk_id else [],
                        first_seen_page=page_number,
                    )
                else:
                    features[key].mention_count += 1
                    if chunk_id and chunk_id not in features[key].chunk_ids:
                        features[key].chunk_ids.append(chunk_id)

            # Extract EPAS features
            for match in self._epas_pattern.finditer(content):
                name = match.group(1)
                # Normalize the name
                for epas_name in EPAS_FEATURES.keys():
                    if name.lower() == epas_name.lower():
                        name = epas_name
                        break
                info = EPAS_FEATURES.get(name, {})
                key = (name, info.get("feature_type", "feature"))
                if key not in features:
                    features[key] = ExtractedFeature(
                        name=name,
                        feature_type=info.get("feature_type", "feature"),
                        category=info.get("category", "epas"),
                        description=info.get("description"),
                        epas_support=info.get("epas_support"),
                        chunk_ids=[chunk_id] if chunk_id else [],
                        first_seen_page=page_number,
                    )
                else:
                    features[key].mention_count += 1
                    if chunk_id and chunk_id not in features[key].chunk_ids:
                        features[key].chunk_ids.append(chunk_id)

        # Sort features by mention count (most mentioned first)
        result = list(features.values())
        result.sort(key=lambda f: (-f.mention_count, f.name))

        logger.info(f"Extracted {len(result)} unique features from {len(chunks)} chunks")
        return result
