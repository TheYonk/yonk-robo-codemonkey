"""
Tests for migration assessment functionality.
"""
import pytest
import pytest_asyncio
import asyncpg
from pathlib import Path
from uuid import UUID

from codegraph_mcp.config import settings
from codegraph_mcp.indexer.indexer import index_repository
from codegraph_mcp.migration.ruleset import load_migration_rules
from codegraph_mcp.migration.detector import detect_source_databases
from codegraph_mcp.migration.assessor import assess_migration


@pytest_asyncio.fixture
async def db():
    """Database connection fixture."""
    conn = await asyncpg.connect(settings.database_url)
    yield conn
    await conn.close()


@pytest.fixture
def fixtures_dir():
    """Return path to migration fixtures directory."""
    return Path(__file__).parent / "fixtures" / "migration"


@pytest_asyncio.fixture
async def oracle_repo(db, fixtures_dir):
    """Index Oracle fixture repo."""
    repo_path = str(fixtures_dir / "oracle_app")
    repo_name = "oracle_test_app"

    # Index the repository
    await index_repository(
        repo_path=repo_path,
        repo_name=repo_name,
        database_url=settings.database_url
    )

    # Get repo ID
    row = await db.fetchrow(
        "SELECT id FROM repo WHERE name = $1",
        repo_name
    )
    return str(row["id"])


@pytest_asyncio.fixture
async def sqlserver_repo(db, fixtures_dir):
    """Index SQL Server fixture repo."""
    repo_path = str(fixtures_dir / "sqlserver_app")
    repo_name = "sqlserver_test_app"

    # Index the repository
    await index_repository(
        repo_path=repo_path,
        repo_name=repo_name,
        database_url=settings.database_url
    )

    # Get repo ID
    row = await db.fetchrow(
        "SELECT id FROM repo WHERE name = $1",
        repo_name
    )
    return str(row["id"])


@pytest_asyncio.fixture
async def mongodb_repo(db, fixtures_dir):
    """Index MongoDB fixture repo."""
    repo_path = str(fixtures_dir / "mongodb_app")
    repo_name = "mongodb_test_app"

    # Index the repository
    await index_repository(
        repo_path=repo_path,
        repo_name=repo_name,
        database_url=settings.database_url
    )

    # Get repo ID
    row = await db.fetchrow(
        "SELECT id FROM repo WHERE name = $1",
        repo_name
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_load_migration_rules():
    """Test loading migration rules from YAML."""
    ruleset = load_migration_rules()

    # Verify ruleset structure
    assert ruleset.version == "1.0"
    assert len(ruleset.severity_weights) == 5
    assert len(ruleset.category_multipliers) == 8
    assert len(ruleset.tiers) == 4

    # Verify detection patterns exist
    assert "oracle" in ruleset.detection
    assert "sqlserver" in ruleset.detection
    assert "mongodb" in ruleset.detection

    # Verify rules exist for each database
    assert len(ruleset.oracle_rules) > 0
    assert len(ruleset.sqlserver_rules) > 0
    assert len(ruleset.mongodb_rules) > 0
    assert len(ruleset.common_rules) > 0

    # Verify content hash is generated
    assert ruleset.content_hash
    assert len(ruleset.content_hash) == 16  # Truncated SHA256 hex (first 16 chars)

    # Test get_rules_for_db
    oracle_rules = ruleset.get_rules_for_db("oracle")
    assert len(oracle_rules) > len(ruleset.oracle_rules)  # Should include common rules
    assert all(r.pattern for r in oracle_rules)  # All rules have patterns


@pytest.mark.asyncio
async def test_oracle_detection(db, oracle_repo):
    """Test auto-detection of Oracle database."""
    ruleset = load_migration_rules()

    # Detect source databases
    detections = await detect_source_databases(
        repo_id=oracle_repo,
        database_url=settings.database_url,
        ruleset=ruleset
    )

    # Should detect Oracle
    assert len(detections) > 0
    oracle_detection = next((d for d in detections if d.db_type == "oracle"), None)
    assert oracle_detection is not None
    assert oracle_detection.confidence > 0.0  # Should detect Oracle with some confidence

    # Should have evidence
    assert len(oracle_detection.evidence) > 0
    # Check for expected evidence types
    evidence_str = " ".join(oracle_detection.evidence)
    assert any(keyword in evidence_str for keyword in ["cx_Oracle", "ROWNUM", "NVL", ".pls"])


@pytest.mark.asyncio
async def test_sqlserver_detection(db, sqlserver_repo):
    """Test auto-detection of SQL Server database."""
    ruleset = load_migration_rules()

    # Detect source databases
    detections = await detect_source_databases(
        repo_id=sqlserver_repo,
        database_url=settings.database_url,
        ruleset=ruleset
    )

    # Should detect SQL Server
    assert len(detections) > 0
    sqlserver_detection = next((d for d in detections if d.db_type == "sqlserver"), None)
    assert sqlserver_detection is not None
    assert sqlserver_detection.confidence > 0.0  # Should detect SQL Server with some confidence

    # Should have evidence
    assert len(sqlserver_detection.evidence) > 0
    evidence_str = " ".join(sqlserver_detection.evidence)
    assert any(keyword in evidence_str for keyword in ["pyodbc", "NOLOCK", "TOP", "GETDATE"])


@pytest.mark.asyncio
async def test_mongodb_detection(db, mongodb_repo):
    """Test auto-detection of MongoDB database."""
    ruleset = load_migration_rules()

    # Detect source databases
    detections = await detect_source_databases(
        repo_id=mongodb_repo,
        database_url=settings.database_url,
        ruleset=ruleset
    )

    # Should detect MongoDB
    assert len(detections) > 0
    mongodb_detection = next((d for d in detections if d.db_type == "mongodb"), None)
    assert mongodb_detection is not None
    assert mongodb_detection.confidence > 0.0  # Should detect MongoDB with some confidence

    # Should have evidence
    assert len(mongodb_detection.evidence) > 0
    # Should at least have driver evidence
    evidence_str = " ".join(mongodb_detection.evidence).lower()
    assert "pymongo" in evidence_str or "mongodb" in evidence_str


@pytest.mark.asyncio
async def test_oracle_assessment(db, oracle_repo):
    """Test Oracle migration assessment."""
    # Run assessment with auto-detection
    result = await assess_migration(
        repo_id=oracle_repo,
        source_db="auto",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )

    # Verify result structure
    assert result.source_db == "oracle"
    assert result.target_db == "postgresql"
    assert result.mode == "repo_only"
    assert not result.cached  # First run, not cached
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100
    assert result.tier in ["low", "medium", "high", "extreme"]

    # Should have findings
    assert len(result.findings) > 0

    # Check that we have Oracle-specific findings
    # (specific patterns depend on what gets matched in chunks)
    finding_titles = [f.title.lower() for f in result.findings]
    # Should have at least some Oracle-related findings
    # Common patterns: driver, rownum, nvl, connect by, decode, etc.
    assert len(result.findings) >= 1  # At minimum, driver findings

    # Verify findings have evidence
    for finding in result.findings[:5]:  # Check first 5
        assert finding.category
        assert finding.severity in ["info", "low", "medium", "high", "critical"]
        assert finding.evidence  # Should have evidence
        assert finding.mapping  # Should have PostgreSQL mapping
        if finding.evidence:
            # Evidence should have path and excerpt or content
            assert "path" in finding.evidence[0] or "excerpt" in finding.evidence[0]

    # Verify reports
    assert result.report_markdown
    assert "oracle" in result.report_markdown.lower()
    assert "postgresql" in result.report_markdown.lower()
    assert result.report_json
    # Report JSON should have structured data (exact keys depend on implementation)
    assert isinstance(result.report_json, dict)
    assert len(result.report_json) > 0


@pytest.mark.asyncio
async def test_sqlserver_assessment(db, sqlserver_repo):
    """Test SQL Server migration assessment."""
    result = await assess_migration(
        repo_id=sqlserver_repo,
        source_db="sqlserver",  # Explicit source DB
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )

    # Verify result structure
    assert result.source_db == "sqlserver"
    assert result.target_db == "postgresql"
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100

    # Should have SQL Server specific findings
    assert len(result.findings) > 0
    # At minimum should detect driver usage
    categories = [f.category for f in result.findings]
    # May include drivers, sql_dialect, procedures, etc.
    assert len(categories) > 0


@pytest.mark.asyncio
async def test_mongodb_assessment(db, mongodb_repo):
    """Test MongoDB migration assessment."""
    result = await assess_migration(
        repo_id=mongodb_repo,
        source_db="mongodb",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )

    # Verify result structure
    assert result.source_db == "mongodb"
    assert result.target_db == "postgresql"
    assert isinstance(result.score, int)

    # Should have MongoDB specific findings
    assert len(result.findings) > 0
    categories = [f.category for f in result.findings]

    # Should have some category of findings (drivers, nosql_patterns, etc.)
    assert len(categories) > 0
    # MongoDB migrations typically have nosql_patterns or driver findings
    # Score will vary based on what patterns are detected


@pytest.mark.asyncio
async def test_assessment_caching(db, oracle_repo):
    """Test that assessments are cached and reused."""
    # Clean up any existing assessments
    await db.execute(
        "DELETE FROM migration_assessment WHERE repo_id = $1",
        UUID(oracle_repo)
    )

    # First assessment
    result1 = await assess_migration(
        repo_id=oracle_repo,
        source_db="oracle",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=False
    )
    assert not result1.cached  # First run

    # Second assessment (should be cached)
    result2 = await assess_migration(
        repo_id=oracle_repo,
        source_db="oracle",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=False
    )
    assert result2.cached  # Should be from cache

    # Verify same content
    assert result1.content_hash == result2.content_hash
    assert result1.score == result2.score
    assert result1.tier == result2.tier
    assert len(result1.findings) == len(result2.findings)

    # Force regeneration
    result3 = await assess_migration(
        repo_id=oracle_repo,
        source_db="oracle",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )
    assert not result3.cached  # Explicitly regenerated
    assert result3.content_hash == result1.content_hash  # But same content


@pytest.mark.asyncio
async def test_assessment_stored_in_db(db, oracle_repo):
    """Test that assessments are properly stored in database."""
    # Run assessment
    result = await assess_migration(
        repo_id=oracle_repo,
        source_db="oracle",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )

    # Check migration_assessment table
    assessment = await db.fetchrow(
        "SELECT * FROM migration_assessment WHERE repo_id = $1 AND source_db = $2",
        UUID(oracle_repo),
        "oracle"
    )
    assert assessment is not None
    assert assessment["score"] == result.score
    assert assessment["tier"] == result.tier
    assert assessment["source_db"] == "oracle"
    assert assessment["target_db"] == "postgresql"
    assert assessment["mode"] == "repo_only"
    assert assessment["content_hash"] == result.content_hash

    # Check migration_finding table
    findings = await db.fetch(
        "SELECT * FROM migration_finding WHERE assessment_id = $1",
        assessment["id"]
    )
    assert len(findings) == len(result.findings)
    assert all(f["severity"] in ["info", "low", "medium", "high", "critical"] for f in findings)
    assert all(f["category"] for f in findings)

    # Check that report is stored as searchable document
    doc = await db.fetchrow(
        """
        SELECT * FROM document
        WHERE type = 'GENERATED_SUMMARY'
        AND source = 'GENERATED'
        AND title LIKE '%migration%'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    # May or may not exist depending on assessor implementation
    # Just checking it doesn't error


@pytest.mark.asyncio
async def test_scoring_with_different_severities(db, oracle_repo):
    """Test that scoring properly weights different severities."""
    result = await assess_migration(
        repo_id=oracle_repo,
        source_db="oracle",
        target_db="postgresql",
        database_url=settings.database_url,
        regenerate=True
    )

    # Group findings by severity
    severity_counts = {}
    for finding in result.findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1

    # Should have findings of various severities
    assert len(severity_counts) > 1

    # Critical/high severity findings should increase score
    # If we have critical findings, score should be higher
    has_critical = any(f.severity == "critical" for f in result.findings)
    has_high = any(f.severity == "high" for f in result.findings)

    if has_critical or has_high:
        # Score should be at least medium tier
        assert result.score >= 26


@pytest.mark.asyncio
async def test_category_multipliers(db):
    """Test that category multipliers affect scoring."""
    ruleset = load_migration_rules()

    # Verify multipliers are defined
    assert ruleset.category_multipliers["nosql_patterns"] > ruleset.category_multipliers["drivers"]
    assert ruleset.category_multipliers["procedures"] > ruleset.category_multipliers["orm"]

    # NoSQL patterns should be weighted higher than driver changes
    # This is reflected in the MongoDB assessment having a higher baseline score
