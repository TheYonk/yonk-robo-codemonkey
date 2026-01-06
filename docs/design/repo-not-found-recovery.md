# Design: Intelligent Repo Not Found Error Recovery

## Problem Statement

When agents use RoboMonkey tools with an incorrect repository name (typo, wrong format, etc.), they receive a generic "Repository not found" error and immediately give up, falling back to grep/basic tools instead of trying to recover.

**Example:**
```
yonk-code-robomonkey - hybrid_search (repo: "yonk-redo-wrestling-game")
⎿ {"error": "Repository 'yonk-redo-wrestling-game' not found in any schema"}

→ Agent gives up and uses grep instead
```

## Goals

1. **Fuzzy Matching**: When a repo is not found, suggest similar repos using string similarity
2. **Actionable Errors**: Include available repos in error message so agent can make informed decision
3. **Auto-Discovery**: Enable agents to self-recover by providing enough context to retry
4. **Backward Compatible**: Don't break existing error handling

## Design

### 1. Fuzzy Matching Helper

Create `suggest_similar_repos()` in `schema_manager.py`:

```python
from difflib import SequenceMatcher

async def suggest_similar_repos(
    conn: asyncpg.Connection,
    query: str,
    threshold: float = 0.6,
    max_suggestions: int = 3
) -> list[dict]:
    """Find similar repository names using fuzzy string matching.

    Args:
        conn: Database connection
        query: The repo name that wasn't found
        threshold: Similarity threshold (0.0-1.0), default 0.6
        max_suggestions: Maximum suggestions to return

    Returns:
        List of {name, schema, similarity_score} dicts, sorted by score
    """
    all_repos = await list_repo_schemas(conn)

    similarities = []
    for repo in all_repos:
        score = SequenceMatcher(None, query.lower(), repo['repo_name'].lower()).ratio()
        if score >= threshold:
            similarities.append({
                'name': repo['repo_name'],
                'schema': repo['schema_name'],
                'similarity': round(score, 2),
                'file_count': repo['file_count'],
                'last_indexed_at': repo['last_indexed_at']
            })

    # Sort by similarity score descending
    similarities.sort(key=lambda x: x['similarity'], reverse=True)

    return similarities[:max_suggestions]
```

### 2. Enhanced Error Response

Update error handling in tools.py to include suggestions:

```python
async def resolve_repo_with_suggestions(
    conn: asyncpg.Connection,
    repo: str
) -> dict:
    """Resolve repo or return actionable error with suggestions.

    Returns:
        Success: {"repo_id": str, "schema": str}
        Error: {
            "error": str,
            "query": str,
            "suggestions": [{"name": str, "similarity": float, ...}],
            "available_repos": [str],  # if no suggestions found
            "why": str,
            "recovery_hint": str
        }
    """
    try:
        repo_id, schema = await resolve_repo_to_schema(conn, repo)
        return {"repo_id": repo_id, "schema": schema}
    except ValueError:
        # Get suggestions
        suggestions = await suggest_similar_repos(conn, repo)

        if suggestions:
            return {
                "error": f"Repository '{repo}' not found",
                "query": repo,
                "suggestions": suggestions,
                "why": "Repository not found in any schema",
                "recovery_hint": "Did you mean one of the suggested repositories? Or use list_repos to see all available repositories."
            }
        else:
            # No suggestions - list all repos
            all_repos = await list_repo_schemas(conn)
            repo_names = [r['repo_name'] for r in all_repos]

            return {
                "error": f"Repository '{repo}' not found",
                "query": repo,
                "available_repos": repo_names,
                "why": "Repository not found in any schema",
                "recovery_hint": f"Available repositories: {', '.join(repo_names[:5])}{'...' if len(repo_names) > 5 else ''}. Use list_repos for full details."
            }
```

### 3. Update All MCP Tools

Replace the simple error pattern:
```python
# OLD:
try:
    resolved_repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
except ValueError as e:
    return {
        "error": str(e),
        "why": "Repository not found in any schema"
    }
```

With enhanced version:
```python
# NEW:
result = await resolve_repo_with_suggestions(conn, repo)
if "error" in result:
    return result  # Already includes suggestions
resolved_repo_id = result["repo_id"]
schema_name = result["schema"]
```

### 4. Example Enhanced Error Messages

**Case 1: Close typo**
```json
{
  "error": "Repository 'yonk-redo-wrestling-game' not found",
  "query": "yonk-redo-wrestling-game",
  "suggestions": [
    {
      "name": "wrestling-game",
      "similarity": 0.73,
      "file_count": 45,
      "last_indexed_at": "2026-01-03T10:30:00"
    }
  ],
  "why": "Repository not found in any schema",
  "recovery_hint": "Did you mean one of the suggested repositories? Or use list_repos to see all available repositories."
}
```

**Case 2: No similar repos**
```json
{
  "error": "Repository 'foobar' not found",
  "query": "foobar",
  "available_repos": ["wrestling-game", "codegraph-mcp", "my-app"],
  "why": "Repository not found in any schema",
  "recovery_hint": "Available repositories: wrestling-game, codegraph-mcp, my-app. Use list_repos for full details."
}
```

## Implementation Plan

- [x] Design doc complete
- [x] Add `suggest_similar_repos()` to schema_manager.py
- [x] Add `resolve_repo_with_suggestions()` helper to schema_manager.py
- [x] Update all MCP tools in tools.py (25+ error sites updated)
- [x] Add tests for fuzzy matching
- [x] Add test for enhanced error messages
- [ ] Update tool documentation/docstrings (optional - errors are self-documenting)

## Benefits

1. **Agent Self-Recovery**: Agents can see suggestions and retry with correct name
2. **Reduced Frustration**: Clear, actionable error messages
3. **Discovery**: If no suggestions, agents learn about available repos
4. **Better UX**: Matches user expectations from other CLI tools (git, etc.)

## Alternative Approaches Considered

### Auto-Retry with Best Match
- **Pros**: Fully automatic recovery
- **Cons**: Could silently use wrong repo; agent loses control
- **Decision**: Too risky - better to show suggestions and let agent decide

### Chain to list_repos Automatically
- **Pros**: One less step for agent
- **Cons**: MCP tools can't chain to other tools; would need agent to do it
- **Decision**: Not possible in MCP architecture; rely on agent to use list_repos

### Cache Repo List in Memory
- **Pros**: Faster suggestions
- **Cons**: Adds complexity; DB queries are fast enough
- **Decision**: Not needed for v1

## Open Questions

- Should similarity threshold be configurable? (Currently 0.6)
- Should we include repo summaries in suggestions? (Adds tokens but helps agent choose)
- Should we rank by similarity + recency + file_count? (More intelligent ranking)

## Implementation Notes

**Date**: 2026-01-03

### What Was Implemented

1. **`suggest_similar_repos()` function** (schema_manager.py:305-349)
   - Uses Python's `difflib.SequenceMatcher` for fuzzy string matching
   - Default threshold: 0.6 (60% similarity required)
   - Returns top 3 suggestions by default, sorted by similarity score
   - Includes file_count and last_indexed_at metadata for context

2. **`resolve_repo_with_suggestions()` helper** (schema_manager.py:352-418)
   - Wraps `resolve_repo_to_schema` with enhanced error handling
   - On success: Returns `{"repo_id": str, "schema": str}`
   - On error with suggestions: Returns suggestions array with similarity scores
   - On error without suggestions: Returns list of all available repos
   - Always includes `recovery_hint` with actionable guidance

3. **Updated all MCP tools** (tools.py)
   - Replaced old error pattern in 25+ locations
   - Old: Simple `{"error": str(e), "why": "Repository not found"}`
   - New: Rich error response with suggestions or available repos list
   - All tools now use `resolve_repo_with_suggestions()`

4. **Comprehensive test suite** (tests/test_repo_suggestions.py)
   - 9 tests covering: exact match, fuzzy matching, prefix matching, no match, max suggestions
   - Tests both `suggest_similar_repos()` and `resolve_repo_with_suggestions()`
   - Includes integration test for MCP tool error responses
   - All tests passing ✓

### Files Modified

- `src/yonk_code_robomonkey/db/schema_manager.py` (+117 lines)
- `src/yonk_code_robomonkey/mcp/tools.py` (25+ error handlers updated)
- `tests/test_repo_suggestions.py` (new file, 231 lines)
- `docs/design/repo-not-found-recovery.md` (this design doc)

### Example Error Message Before/After

**Before:**
```json
{
  "error": "Repository 'yonk-redo-wrestling-game' not found in any schema",
  "why": "Repository not found in any schema"
}
```

**After (with suggestions):**
```json
{
  "error": "Repository 'yonk-redo-wrestling-game' not found",
  "query": "yonk-redo-wrestling-game",
  "suggestions": [
    {
      "name": "wrestling-game",
      "similarity": 0.73,
      "file_count": 45,
      "last_indexed_at": "2026-01-03T10:30:00"
    }
  ],
  "why": "Repository not found in any schema",
  "recovery_hint": "Did you mean one of the suggested repositories? Or use list_repos to see all available repositories."
}
```

### Performance Considerations

- Fuzzy matching requires calling `list_repo_schemas()` which queries all indexed schemas
- For systems with many repos (100+), this could add ~50-200ms latency to error responses
- Trade-off is acceptable since errors are edge cases and better UX is valuable
- Could add caching if performance becomes an issue

### Known Limitations

1. Similarity threshold (0.6) is hardcoded - could be made configurable if needed
2. Only uses string similarity - doesn't consider semantic similarity (e.g., "game" vs "application")
3. Internal CLI commands and report generators still use old error handling (acceptable)

## Next Steps

After monitoring in production:
1. ✓ ~~Test with real agent scenarios~~ - Tested in test suite
2. Monitor if agents successfully recover vs still giving up in the wild
3. Consider adding repo summaries to suggestions if agents struggle to choose
4. Consider adjusting similarity threshold based on usage patterns
5. Optionally add caching for repo list if performance becomes issue
