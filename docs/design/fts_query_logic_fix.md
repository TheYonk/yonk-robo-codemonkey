# FTS Query Logic Fix - OR vs AND

## Problems

### Problem 1: FTS Uses AND Logic Instead of OR

The `doc_search` and FTS functions use `websearch_to_tsquery('simple', query)` which implements **AND logic** by default:

```sql
websearch_to_tsquery('simple', 'salary pool distribution percentile rating')
-- Results in: 'salary' & 'pool' & 'distribution' & 'percentile' & 'rating'
-- Requires ALL terms to match
```

This is too restrictive for most search use cases. Users expect **OR logic** where matching ANY term returns results.

### Problem 2: Document Embeddings Are Not Used

We create embeddings for documents in the `document_embedding` table, but:
- `doc_search` only uses FTS (no vector search)
- `hybrid_search` only searches chunks (not documents)
- `vector_search` only searches chunk_embedding (not document_embedding)

**Result:** Document embeddings are created but never queried, missing semantic search on documentation.

## Root Cause

**Problem 1:** PostgreSQL's `websearch_to_tsquery` mimics web search engine behavior, which defaults to AND for multiple unquoted words. This is documented behavior but unintuitive for most users.

**Problem 2:** The search architecture was designed primarily for code chunks, and document search was added as FTS-only without vector search integration.

## Solutions

### Solution 1: Use OR Logic in FTS

Replace `websearch_to_tsquery` with `plainto_tsquery` which implements OR logic:

```sql
plainto_tsquery('simple', 'salary pool distribution percentile rating')
-- Results in: 'salary' | 'pool' | 'distribution' | 'percentile' | 'rating'
-- Matches ANY term
```

**Files to Update:**
1. `src/yonk_code_robomonkey/retrieval/fts_search.py`:
   - `fts_search_chunks()` - lines 62, 66, 82, 85
   - `fts_search_documents()` - lines 151, 154, 167, 169

### Solution 2: Add Document Vector Search

**Option A (Recommended):** Enhance `doc_search` to use hybrid search on documents

Create a `doc_hybrid_search()` function that:
1. Embeds the query
2. Searches `document_embedding` for vector candidates
3. Searches `document.fts` for FTS candidates (with OR logic)
4. Merges and ranks results (similar to chunk hybrid_search)

**Files to Create/Update:**
1. Create `src/yonk_code_robomonkey/retrieval/doc_hybrid_search.py`
2. Update `src/yonk_code_robomonkey/mcp/tools.py` - make `doc_search` use hybrid search

**Option B:** Extend existing `hybrid_search` to include documents

Modify `hybrid_search()` to optionally search both chunks AND documents:
- Add `search_documents: bool = False` parameter
- When True, also query `document_embedding` and `document.fts`
- Merge document results with chunk results

This is more complex but provides unified search across all content.

### Implementation Details

**Before:**
```sql
WHERE d.fts @@ websearch_to_tsquery('simple', $1)
ORDER BY ts_rank_cd(d.fts, websearch_to_tsquery('simple', $1)) DESC
```

**After:**
```sql
WHERE d.fts @@ plainto_tsquery('simple', $1)
ORDER BY ts_rank_cd(d.fts, plainto_tsquery('simple', $1)) DESC
```

### Future Enhancement (Optional)

Add a `match_mode` parameter to allow users to choose:
- `'any'` (OR logic) - default, uses `plainto_tsquery`
- `'all'` (AND logic) - uses `websearch_to_tsquery`
- `'websearch'` (web-style) - uses `websearch_to_tsquery` with quoted phrases

## Testing

Test queries:
1. `"salary pool distribution"` - should match documents with ANY of these words
2. `"authentication"` - should match auth-related documents
3. Multi-word queries should return results even if not all words match

## Todo List

### Phase 1: Fix FTS AND/OR Logic (Completed ✓)
- [x] Identify the issue (websearch_to_tsquery uses AND logic)
- [x] Identify document vector search gap
- [x] Write design doc
- [x] Create build_or_tsquery() helper function
- [x] Update fts_search_chunks() to use to_tsquery with OR logic
- [x] Update fts_search_documents() to use to_tsquery with OR logic
- [x] Update tools.py and feature_context.py SQL queries
- [x] Fix FTSResult dataclass to include title and path
- [x] Run FTS tests to verify functionality (6/6 passed)
- [x] Test with queries to confirm OR logic works

### Phase 2: Add Document Vector Search (Completed ✓)
- [x] Decide on approach: Use hybrid search (vector + FTS + filters + reranking)
- [x] Create vector_search_documents() for document embeddings
- [x] Create doc_hybrid_search() function that:
  - Runs vector search on document_embedding
  - Runs FTS on document.fts (with OR logic)
  - Merges and reranks results (similar to chunk hybrid_search)
- [x] Update doc_search MCP tool to use hybrid search
- [x] Test document hybrid search with sample queries

## User Requirements

User confirmed they want hybrid search for documents:
1. Vector search (semantic similarity via embeddings)
2. Full-text search (keyword matching with OR logic)
3. Metadata filters
4. Combine results, rerank, and return top K

This matches the existing pattern used for chunk search.

## Implementation Notes

### Phase 1 Implementation (Completed)

**Issue Discovery:**
- Both `websearch_to_tsquery` and `plainto_tsquery` use AND logic by default
- To get OR logic, must use `to_tsquery` with manual ` | ` operators

**Solution Implemented:**
1. Created `build_or_tsquery()` helper function in `fts_search.py`:
   - Splits query on whitespace
   - Joins words with ` | ` operator
   - Example: "salary pool rating" → "salary | pool | rating"

2. Updated all FTS functions to use `to_tsquery('simple', or_query)`:
   - `fts_search_chunks()`
   - `fts_search_documents()`
   - Direct SQL queries in `tools.py` (db_feature_context)
   - Direct SQL queries in `feature_context.py`

3. Fixed `FTSResult` dataclass to include `title` and `path` fields for documents

4. Updated SQL queries in `fts_search_documents()` to SELECT title and path

**Files Modified:**
- `src/yonk_code_robomonkey/retrieval/fts_search.py` - Added build_or_tsquery, updated all functions
- `src/yonk_code_robomonkey/mcp/tools.py` - Updated db_feature_context SQL
- `src/yonk_code_robomonkey/reports/feature_context.py` - Updated feature index and doc search SQL

**Testing Results:**
- All FTS tests pass (6/6)
- OR logic verified: "Python analysis tooling indexing wrestling" matches on partial terms
- AND logic queries now return results when ANY term matches (instead of requiring ALL terms)

**MCP Server Note:**
The MCP server needs to be restarted to pick up these code changes. The functions work correctly when tested directly.

---

### Phase 2 Implementation (Completed)

**Goal:** Add hybrid search (vector + FTS) for documents, matching the pattern used for code chunks.

**Implementation:**

1. **Created `doc_vector_search.py`:**
   - `vector_search_documents()` function
   - Searches `document_embedding` table using pgvector
   - Returns `DocVectorSearchResult` with similarity scores

2. **Created `doc_hybrid_search.py`:**
   - `doc_hybrid_search()` function
   - Combines vector search + FTS search
   - Merges and deduplicates results by document_id
   - Normalizes and combines scores: 55% vector + 45% FTS
   - Returns `DocHybridSearchResult` with explainability fields

3. **Updated `doc_search` MCP tool:**
   - Changed from FTS-only to hybrid search
   - Now embeds query and searches both semantically and textually
   - Returns combined scores with vec_rank, vec_score, fts_rank, fts_score

**Files Created:**
- `src/yonk_code_robomonkey/retrieval/doc_vector_search.py`
- `src/yonk_code_robomonkey/retrieval/doc_hybrid_search.py`

**Files Modified:**
- `src/yonk_code_robomonkey/mcp/tools.py` - Updated doc_search to use hybrid search

**Testing Results:**
- Hybrid search successfully combines vector and FTS results
- Example query "code analysis indexing system":
  - Vector score: 0.2473 (semantic similarity)
  - FTS score: 4.0000 (keyword match)
  - Combined score: 1.0000 (normalized and weighted)

**Benefits:**
- Documents now searchable by semantic meaning, not just keywords
- Better relevance ranking by combining multiple signals
- Consistent search experience across code chunks and documentation
- Full explainability with individual scores for transparency
