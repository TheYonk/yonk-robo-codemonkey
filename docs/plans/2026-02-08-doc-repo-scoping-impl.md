# Knowledge Base Doc Repo-Scoping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow knowledge base documents to be optionally associated with repositories, enabling scoped searches (repo-only, repo+global, or all docs).

**Architecture:** Add nullable `repo_id` foreign key to `doc_source` table. Modify search queries to filter by repo. Auto-discover docs during repo indexing. Add repo info to all search results.

**Tech Stack:** PostgreSQL (DDL migration), Python asyncpg, Pydantic models, FastAPI routes, Click CLI

---

## Task 1: Add repo_id Column to Schema

**Files:**
- Modify: `scripts/init_docs_schema.sql`
- Create: `scripts/migrations/add_doc_source_repo_id.sql`

**Step 1: Write the migration SQL file**

Create `scripts/migrations/add_doc_source_repo_id.sql`:

```sql
-- Migration: Add repo_id to doc_source for repo-scoping
-- Run with: psql $DATABASE_URL -f scripts/migrations/add_doc_source_repo_id.sql

-- Add nullable repo_id column referencing control schema repo table
ALTER TABLE robomonkey_docs.doc_source
ADD COLUMN IF NOT EXISTS repo_id UUID REFERENCES robomonkey_control.repo(id) ON DELETE SET NULL;

-- Index for fast repo filtering
CREATE INDEX IF NOT EXISTS idx_doc_source_repo ON robomonkey_docs.doc_source(repo_id);

-- Verify
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'robomonkey_docs' AND table_name = 'doc_source' AND column_name = 'repo_id';
```

**Step 2: Update init_docs_schema.sql for fresh installs**

Add after line 27 in `scripts/init_docs_schema.sql` (after `updated_at` column):

```sql
    repo_id UUID REFERENCES robomonkey_control.repo(id) ON DELETE SET NULL,
```

And add index after line 173:

```sql
CREATE INDEX IF NOT EXISTS idx_doc_source_repo ON robomonkey_docs.doc_source(repo_id);
```

**Step 3: Verify migration works**

Run: `psql $DATABASE_URL -f scripts/migrations/add_doc_source_repo_id.sql`
Expected: Column added, index created

**Step 4: Commit**

```bash
git add scripts/migrations/add_doc_source_repo_id.sql scripts/init_docs_schema.sql
git commit -m "feat(schema): add repo_id column to doc_source for repo-scoping"
```

---

## Task 2: Update Pydantic Models

**Files:**
- Modify: `src/yonk_code_robomonkey/knowledge_base/models.py`

**Step 1: Add repo fields to DocSource model**

Add to `DocSource` class (after line 60):

```python
    repo_id: Optional[UUID] = None
    repo_name: Optional[str] = None  # Populated from join, not stored
```

**Step 2: Add repo fields to DocChunkResult model**

Add to `DocChunkResult` class (after line 173):

```python
    repo_id: Optional[UUID] = None
    repo_name: str = "global"  # "global" when repo_id is None
```

**Step 3: Add repo filter params to DocSearchParams**

Add to `DocSearchParams` class (after line 149):

```python
    repo_id: Optional[str] = Field(default=None, description="Filter to specific repo UUID or name")
    include_global: bool = Field(default=True, description="Include docs with no repo (global docs)")
```

**Step 4: Add repo fields to DocListItem**

Add to `DocListItem` class (after line 136):

```python
    repo_id: Optional[UUID] = None
    repo_name: str = "global"
```

**Step 5: Add repo field to DocIndexRequest**

Add to `DocIndexRequest` class (after line 106):

```python
    repo: Optional[str] = Field(default=None, description="Associate with repo (name or UUID). None = global doc.")
```

**Step 6: Verify import works**

Run: `source .venv/bin/activate && python -c "from yonk_code_robomonkey.knowledge_base.models import DocSearchParams; print('OK')"`
Expected: OK

**Step 7: Commit**

```bash
git add src/yonk_code_robomonkey/knowledge_base/models.py
git commit -m "feat(models): add repo_id and include_global fields to KB models"
```

---

## Task 3: Update Search Functions with Repo Filtering

**Files:**
- Modify: `src/yonk_code_robomonkey/knowledge_base/search.py`

**Step 1: Add repo filtering helper function**

Add after line 122 (after STOP_WORDS):

```python
def _build_repo_filter(
    repo_id: Optional[str],
    include_global: bool,
    param_idx: int,
    bind_params: list,
) -> tuple[str, int]:
    """Build SQL WHERE clause for repo filtering.

    Args:
        repo_id: UUID string to filter by, or None for all
        include_global: If True, include docs with NULL repo_id
        param_idx: Current parameter index for bind params
        bind_params: List to append bind parameters to

    Returns:
        Tuple of (SQL condition string, updated param_idx)
    """
    if repo_id is None:
        return "TRUE", param_idx

    if include_global:
        # Match specific repo OR global docs
        condition = f"(ds.repo_id = ${param_idx}::uuid OR ds.repo_id IS NULL)"
    else:
        # Match only specific repo
        condition = f"ds.repo_id = ${param_idx}::uuid"

    bind_params.append(repo_id)
    return condition, param_idx + 1
```

**Step 2: Update _vector_search to use repo filter**

In `_vector_search` function (around line 407), add repo filtering. After building `conditions` list, add:

```python
    # Repo filtering
    if params.repo_id is not None:
        repo_condition, param_idx = _build_repo_filter(
            params.repo_id, params.include_global, param_idx, bind_params
        )
        conditions.append(repo_condition)
```

**Step 3: Update _vector_search SQL to include repo info**

Update the SELECT clause (line 441-461) to include repo columns:

```python
    query = f"""
        SELECT
            dc.id as chunk_id,
            dc.content,
            ds.name as source_name,
            ds.doc_type,
            ds.repo_id,
            COALESCE(r.name, 'global') as repo_name,
            dc.section_path,
            dc.heading,
            dc.page_number,
            dc.chunk_index,
            dc.topics,
            dc.oracle_constructs,
            dc.epas_features,
            1 - (dce.embedding <=> $1::vector) as vec_score
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        LEFT JOIN robomonkey_control.repo r ON ds.repo_id = r.id
        JOIN robomonkey_docs.doc_chunk_embedding dce ON dc.id = dce.chunk_id
        WHERE {where_clause}
        ORDER BY dce.embedding <=> $1::vector
        LIMIT $2
    """
```

**Step 4: Update _vector_search result building**

Update the result building loop (line 466-483) to include repo info:

```python
            results.append(DocChunkResult(
                chunk_id=row["chunk_id"],
                content=normalize_whitespace(row["content"]),
                source_document=row["source_name"],
                doc_type=DocType(row["doc_type"]),
                repo_id=row["repo_id"],
                repo_name=row["repo_name"],
                section_path=row["section_path"] or [],
                # ... rest unchanged
            ))
```

**Step 5: Update _keyword_fts_search_weighted similarly**

Apply same changes to `_keyword_fts_search_weighted` (line 516+):
- Add repo filter condition building
- Update SQL to LEFT JOIN repo table
- Add repo_id, repo_name to SELECT
- Update result building

**Step 6: Update _fetch_chunks to include repo info**

Find `_fetch_chunks` function and update its SQL query to include:
```sql
ds.repo_id,
COALESCE(r.name, 'global') as repo_name,
...
LEFT JOIN robomonkey_control.repo r ON ds.repo_id = r.id
```

**Step 7: Update _fts_ilike_search similarly**

Apply same pattern to `_fts_ilike_search` function.

**Step 8: Update _fts_search_with_tsquery similarly**

Apply same pattern to `_fts_search_with_tsquery` function.

**Step 9: Verify search module imports**

Run: `source .venv/bin/activate && python -c "from yonk_code_robomonkey.knowledge_base.search import doc_search; print('OK')"`
Expected: OK

**Step 10: Commit**

```bash
git add src/yonk_code_robomonkey/knowledge_base/search.py
git commit -m "feat(search): add repo filtering to KB search functions"
```

---

## Task 4: Update MCP doc_search Tool

**Files:**
- Modify: `src/yonk_code_robomonkey/mcp/tools.py`
- Modify: `src/yonk_code_robomonkey/mcp/schemas.py`

**Step 1: Update doc_search tool signature**

Find the KB `doc_search` tool (around line 4902) and update:

```python
@tool("doc_search")
async def doc_search(
    query: str,
    doc_types: list[str] | None = None,
    doc_names: list[str] | None = None,
    topics: list[str] | None = None,
    oracle_constructs: list[str] | None = None,
    epas_features: list[str] | None = None,
    top_k: int = 10,
    search_mode: str = "hybrid",
    repo: str | None = None,  # ADD THIS
    include_global: bool = True,  # ADD THIS
) -> dict[str, Any]:
```

**Step 2: Pass repo params to search**

Update the params building (around line 4958):

```python
    # Resolve repo name to UUID if provided
    repo_id = None
    if repo and repo.lower() != "global":
        # Try to resolve repo name/id
        try:
            repo_id = await resolve_repo_id(repo, settings.database_url)
        except Exception as e:
            logger.warning(f"Could not resolve repo '{repo}': {e}")

    params = DocSearchParams(
        query=query,
        doc_types=doc_type_enums,
        doc_names=doc_names,
        topics=topics,
        oracle_constructs=oracle_constructs,
        epas_features=epas_features,
        top_k=top_k,
        search_mode=search_mode,
        repo_id=repo_id,  # ADD
        include_global=include_global,  # ADD
    )
```

**Step 3: Add repo info to response**

Update the response building to include repo info in each chunk result.

**Step 4: Update schema description in schemas.py**

Find `doc_search` in TOOL_SCHEMAS and update inputSchema to include:

```python
                "repo": {
                    "type": "string",
                    "description": "Optional repo name or UUID to scope search. 'global' for global-only. None = search all."
                },
                "include_global": {
                    "type": "boolean",
                    "description": "If true (default), include global docs alongside repo-specific docs when repo is set.",
                    "default": True
                }
```

**Step 5: Update tool description**

Add to the description:

```
SCOPING: By default searches all docs. Set repo to limit to a specific repo's docs. Use include_global=false to exclude global docs when searching a specific repo.
```

**Step 6: Verify MCP module imports**

Run: `source .venv/bin/activate && python -c "from yonk_code_robomonkey.mcp.tools import doc_search; print('OK')"`
Expected: OK

**Step 7: Commit**

```bash
git add src/yonk_code_robomonkey/mcp/tools.py src/yonk_code_robomonkey/mcp/schemas.py
git commit -m "feat(mcp): add repo scoping to doc_search tool"
```

---

## Task 5: Update Web Routes

**Files:**
- Modify: `src/yonk_code_robomonkey/web/routes/docs.py`

**Step 1: Add repo to DocSearchRequest model**

Update `DocSearchRequest` class (around line 48):

```python
class DocSearchRequest(BaseModel):
    # ... existing fields ...
    repo: Optional[str] = Field(default=None, description="Filter to repo (name or UUID). None = all docs.")
    include_global: bool = Field(default=True, description="Include global docs when repo is set")
```

**Step 2: Add repo filter to list_documents endpoint**

Update `list_documents` (line 131) to accept optional repo query param:

```python
@router.get("/")
async def list_documents(repo: Optional[str] = None) -> dict[str, Any]:
```

Update the SQL query to filter by repo:

```python
        # Build repo filter
        repo_filter = ""
        bind_params = []
        if repo and repo.lower() != "global":
            repo_id = await resolve_repo_id_or_none(conn, repo)
            if repo_id:
                repo_filter = "WHERE ds.repo_id = $1"
                bind_params = [repo_id]

        rows = await conn.fetch(f"""
            SELECT
                ds.id, ds.name, ds.doc_type, ds.total_chunks, ds.total_pages,
                ds.status, ds.version, ds.indexed_at, ds.file_size_bytes,
                ds.description, ds.file_path, ds.error_message, ds.repo_id,
                COALESCE(r.name, 'global') as repo_name
            FROM robomonkey_docs.doc_source ds
            LEFT JOIN robomonkey_control.repo r ON ds.repo_id = r.id
            {repo_filter}
            ORDER BY ds.indexed_at DESC NULLS LAST
        """, *bind_params)
```

**Step 3: Add repo info to list response**

Update the document building loop to include:

```python
            doc = {
                # ... existing fields ...
                "repo_id": str(row["repo_id"]) if row["repo_id"] else None,
                "repo_name": row["repo_name"],
            }
```

**Step 4: Update search endpoint to pass repo params**

Update the `/search` endpoint to pass repo params to `doc_search`:

```python
    params = DocSearchParams(
        query=request.query,
        # ... existing ...
        repo_id=resolved_repo_id,
        include_global=request.include_global,
    )
```

**Step 5: Add repo to upload/index endpoints**

Update `DocUploadRequest` and index endpoint to accept `repo` field.

**Step 6: Verify routes import**

Run: `source .venv/bin/activate && python -c "from yonk_code_robomonkey.web.routes.docs import router; print('OK')"`
Expected: OK

**Step 7: Commit**

```bash
git add src/yonk_code_robomonkey/web/routes/docs.py
git commit -m "feat(web): add repo filtering to docs endpoints"
```

---

## Task 6: Add Repo Doc Auto-Discovery

**Files:**
- Create: `src/yonk_code_robomonkey/indexer/doc_discovery.py`
- Modify: `src/yonk_code_robomonkey/indexer/indexer.py`
- Modify: `src/yonk_code_robomonkey/cli/commands.py`

**Step 1: Create doc_discovery module**

Create `src/yonk_code_robomonkey/indexer/doc_discovery.py`:

```python
"""Auto-discovery of documentation files in repositories."""

import logging
from pathlib import Path
from typing import Iterator

import pathspec

logger = logging.getLogger(__name__)

# Default patterns for doc discovery
DOC_INCLUDE_PATTERNS = [
    "README*",
    "CHANGELOG*",
    "*.md",
    "*.rst",
    "*.adoc",
    "docs/**/*.md",
    "docs/**/*.rst",
    "docs/**/*.pdf",
    "doc/**/*.md",
    "doc/**/*.pdf",
]

DOC_EXCLUDE_PATTERNS = [
    "node_modules/**",
    "vendor/**",
    ".git/**",
    "dist/**",
    "build/**",
    "__pycache__/**",
    "*.min.js",
    "*.bundle.js",
    ".venv/**",
    "venv/**",
]


def discover_repo_docs(
    repo_path: str | Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> Iterator[Path]:
    """Discover documentation files in a repository.

    Args:
        repo_path: Path to repository root
        include_patterns: Glob patterns to include (default: DOC_INCLUDE_PATTERNS)
        exclude_patterns: Glob patterns to exclude (default: DOC_EXCLUDE_PATTERNS)

    Yields:
        Path objects for each discovered doc file
    """
    repo_path = Path(repo_path)
    include_patterns = include_patterns or DOC_INCLUDE_PATTERNS
    exclude_patterns = exclude_patterns or DOC_EXCLUDE_PATTERNS

    # Build pathspec for exclusions
    exclude_spec = pathspec.PathSpec.from_lines(
        pathspec.patterns.GitWildMatchPattern,
        exclude_patterns
    )

    # Collect all matching files
    seen = set()
    for pattern in include_patterns:
        for path in repo_path.glob(pattern):
            if path.is_file():
                rel_path = path.relative_to(repo_path)

                # Skip if excluded
                if exclude_spec.match_file(str(rel_path)):
                    continue

                # Skip if already seen
                if str(rel_path) in seen:
                    continue
                seen.add(str(rel_path))

                logger.debug(f"Discovered doc: {rel_path}")
                yield path

    logger.info(f"Discovered {len(seen)} documentation files in {repo_path}")
```

**Step 2: Add --skip-docs flag to CLI**

Update `cli/commands.py` index command (around line 35):

```python
    idx.add_argument("--skip-docs", action="store_true",
                     help="Skip auto-discovery of documentation files")
```

**Step 3: Add doc indexing to index_repository**

Update `indexer/indexer.py` to call doc discovery after code indexing. Add parameter:

```python
async def index_repository(
    repo_path: str,
    repo_name: str,
    database_url: str,
    force_reinit: bool = False,
    skip_docs: bool = False,  # ADD THIS
) -> dict:
```

At the end of the function, after code indexing:

```python
    # Auto-discover and index repo docs if not skipped
    if not skip_docs:
        from .doc_discovery import discover_repo_docs
        from ..knowledge_base.chunker import DocumentChunker
        # ... doc indexing logic
```

**Step 4: Implement doc indexing in index_repository**

Add the actual doc processing logic:

```python
    if not skip_docs:
        doc_count = 0
        from .doc_discovery import discover_repo_docs

        for doc_path in discover_repo_docs(repo_path):
            try:
                # Index doc with repo association
                await index_doc_file(
                    file_path=str(doc_path),
                    database_url=database_url,
                    repo_id=repo_id,  # Associate with this repo
                )
                doc_count += 1
            except Exception as e:
                logger.warning(f"Failed to index doc {doc_path}: {e}")

        result["docs_indexed"] = doc_count
        logger.info(f"Indexed {doc_count} documentation files for repo {repo_name}")
```

**Step 5: Verify module imports**

Run: `source .venv/bin/activate && python -c "from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs; print('OK')"`
Expected: OK

**Step 6: Commit**

```bash
git add src/yonk_code_robomonkey/indexer/doc_discovery.py \
        src/yonk_code_robomonkey/indexer/indexer.py \
        src/yonk_code_robomonkey/cli/commands.py
git commit -m "feat(indexer): add auto-discovery of docs during repo indexing"
```

---

## Task 7: Add --repo Flag to docs index CLI

**Files:**
- Modify: `src/yonk_code_robomonkey/cli/commands.py`

**Step 1: Find or create docs subcommand**

Look for existing `docs` command or add one:

```python
    # Docs commands
    docs = sub.add_parser("docs", help="Document management commands")
    docs_sub = docs.add_subparsers(dest="docs_cmd", required=True)

    docs_index = docs_sub.add_parser("index", help="Index a document")
    docs_index.add_argument("--file", required=True, help="Path to document file")
    docs_index.add_argument("--repo", help="Associate with repo (name or UUID). Omit for global doc.")
    docs_index.add_argument("--name", help="Custom name (defaults to filename)")
    docs_index.add_argument("--type", default="general", help="Document type")
```

**Step 2: Implement docs index handler**

Add handler for the docs index command:

```python
async def handle_docs_index(args, settings):
    """Index a document file with optional repo association."""
    from yonk_code_robomonkey.knowledge_base.chunker import DocumentChunker

    repo_id = None
    if args.repo and args.repo.lower() != "global":
        repo_id = await resolve_repo_id(args.repo, settings.database_url)
        if not repo_id:
            print(f"Error: Repo '{args.repo}' not found")
            return 1

    # Index the document
    result = await index_doc_file(
        file_path=args.file,
        database_url=settings.database_url,
        repo_id=repo_id,
        name=args.name,
        doc_type=args.type,
    )

    print(f"Indexed: {result['name']} ({result['chunks']} chunks)")
    if repo_id:
        print(f"Associated with repo: {args.repo}")
    else:
        print("Stored as global document")
```

**Step 3: Wire up the handler**

In the main command dispatch, add:

```python
    elif args.cmd == "docs":
        if args.docs_cmd == "index":
            asyncio.run(handle_docs_index(args, settings))
```

**Step 4: Verify CLI**

Run: `source .venv/bin/activate && python -m yonk_code_robomonkey.cli.commands docs index --help`
Expected: Shows help with --file and --repo options

**Step 5: Commit**

```bash
git add src/yonk_code_robomonkey/cli/commands.py
git commit -m "feat(cli): add --repo flag to docs index command"
```

---

## Task 8: Write Tests

**Files:**
- Create: `tests/test_doc_repo_scoping.py`

**Step 1: Write test for repo filter SQL building**

```python
import pytest
from yonk_code_robomonkey.knowledge_base.search import _build_repo_filter


def test_repo_filter_none_returns_true():
    """No repo_id means no filtering."""
    bind_params = []
    condition, idx = _build_repo_filter(None, True, 1, bind_params)
    assert condition == "TRUE"
    assert len(bind_params) == 0


def test_repo_filter_with_include_global():
    """repo_id + include_global returns OR condition."""
    bind_params = []
    condition, idx = _build_repo_filter("abc-123", True, 1, bind_params)
    assert "OR ds.repo_id IS NULL" in condition
    assert bind_params == ["abc-123"]


def test_repo_filter_without_include_global():
    """repo_id without include_global returns exact match."""
    bind_params = []
    condition, idx = _build_repo_filter("abc-123", False, 1, bind_params)
    assert "IS NULL" not in condition
    assert "ds.repo_id = $1" in condition
```

**Step 2: Write test for doc discovery**

```python
from pathlib import Path
from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs


def test_discover_repo_docs_finds_markdown(tmp_path):
    """Should find markdown files in repo."""
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/guide.md").write_text("# Guide")

    docs = list(discover_repo_docs(tmp_path))
    assert len(docs) == 2
    names = {d.name for d in docs}
    assert "README.md" in names
    assert "guide.md" in names


def test_discover_repo_docs_excludes_node_modules(tmp_path):
    """Should exclude node_modules."""
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/pkg.md").write_text("# Pkg")
    (tmp_path / "README.md").write_text("# Test")

    docs = list(discover_repo_docs(tmp_path))
    assert len(docs) == 1
    assert docs[0].name == "README.md"
```

**Step 3: Run tests**

Run: `pytest tests/test_doc_repo_scoping.py -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add tests/test_doc_repo_scoping.py
git commit -m "test: add tests for doc repo-scoping feature"
```

---

## Task 9: Integration Test

**Step 1: Run migration on test database**

```bash
psql $DATABASE_URL -f scripts/migrations/add_doc_source_repo_id.sql
```

**Step 2: Verify existing docs still work**

```bash
source .venv/bin/activate
python -c "
import asyncio
from yonk_code_robomonkey.knowledge_base.search import doc_search
from yonk_code_robomonkey.knowledge_base.models import DocSearchParams
from yonk_code_robomonkey.config import Settings

async def test():
    settings = Settings()
    params = DocSearchParams(query='test', top_k=5)
    result = await doc_search(params, settings.database_url)
    print(f'Found {result.total_found} results')
    for chunk in result.chunks[:2]:
        print(f'  - {chunk.source_document}: repo={chunk.repo_name}')

asyncio.run(test())
"
```

Expected: Existing docs show `repo_name='global'`

**Step 3: Test repo-scoped search**

```bash
python -c "
import asyncio
from yonk_code_robomonkey.knowledge_base.search import doc_search
from yonk_code_robomonkey.knowledge_base.models import DocSearchParams
from yonk_code_robomonkey.config import Settings

async def test():
    settings = Settings()
    # Search with fake repo ID (should return only global docs)
    params = DocSearchParams(
        query='test',
        repo_id='00000000-0000-0000-0000-000000000000',
        include_global=True,
        top_k=5
    )
    result = await doc_search(params, settings.database_url)
    print(f'Found {result.total_found} results (global only expected)')

asyncio.run(test())
"
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete doc repo-scoping implementation

- Add repo_id column to doc_source table
- Update search functions with repo filtering
- Add repo info to all search results
- Update MCP doc_search tool with repo/include_global params
- Update web routes with repo filtering
- Add auto-discovery of docs during repo indexing
- Add --repo flag to docs index CLI
- Add --skip-docs flag to index command
"
```
