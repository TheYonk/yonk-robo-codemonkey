# Semantic Tagging System

Intelligent code categorization using embeddings and LLM analysis.

## Overview

RoboMonkey's semantic tagging system automatically categorizes and organizes your codebase using three complementary approaches:

1. **Semantic Similarity** - Find code by meaning using embeddings
2. **LLM Analysis** - Let AI discover and suggest categories
3. **Direct Tagging** - Manually categorize specific files

All tags are stored in the database and can be used to filter searches across all MCP tools.

---

## Quick Start

### Tag All UI-Related Code
```python
# Find and tag all UI components semantically
await generate_tags_for_topic(
    topic="UI Components",
    repo="my-app",
    threshold=0.75,
    max_results=100
)

# Result: 47 chunks, 8 documents, 12 symbols tagged as "UI Components"
```

### Discover Categories in Your Codebase
```python
# Let LLM analyze and suggest tags
await suggest_tags_mcp(
    repo="my-app",
    max_tags=10,
    auto_apply=True  # Automatically tag everything
)

# Result: Suggests "Frontend", "Backend", "Database", etc. and tags all matching code
```

### Categorize a Single File
```python
# Ask: "What category should this file be in?"
await categorize_file(
    file_path="src/LoginForm.tsx"
)

# LLM suggests: "Frontend UI" (95% confidence)
# Tags file + all its chunks
```

---

## MCP Tools

### 1. `generate_tags_for_topic`

**Purpose**: Find all code semantically related to a topic and tag it.

**Use Cases**:
- "Tag all authentication code"
- "Find and categorize wrestler match logic"
- "Mark all database-related files"

**Parameters**:
```python
generate_tags_for_topic(
    topic: str,              # Topic to search for (e.g., "UI Components")
    repo: str = None,        # Repository name (defaults to DEFAULT_REPO)
    entity_types: list = None,  # ["chunk", "document", "symbol", "file"]
    threshold: float = 0.7,  # Similarity threshold (0.0-1.0)
    max_results: int = 100   # Max entities to tag per type
)
```

**Returns**:
```json
{
  "topic": "UI Components",
  "tag_id": "uuid-here",
  "tagged_chunks": 47,
  "tagged_docs": 8,
  "tagged_symbols": 12,
  "tagged_files": 15,
  "threshold": 0.75,
  "why": "Semantically tagged 82 entities with topic 'UI Components'"
}
```

**How it Works**:
1. Embeds the topic: `"UI Components"` → vector[1024]
2. Searches for similar embeddings: `SELECT WHERE similarity > 0.75`
3. Creates tag if doesn't exist
4. Tags all matching entities with confidence scores

**Examples**:
```python
# Tag all database code
await generate_tags_for_topic(
    topic="Database",
    entity_types=["chunk", "file"],
    threshold=0.8,
    max_results=200
)

# Tag wrestling match simulation code
await generate_tags_for_topic(
    topic="Wrestler Match Simulation",
    repo="wrestling-game",
    threshold=0.75
)

# Tag API endpoints
await generate_tags_for_topic(
    topic="API Endpoints",
    entity_types=["chunk", "symbol"]
)
```

---

### 2. `suggest_tags_mcp`

**Purpose**: Analyze codebase and discover relevant organizational categories.

**Use Cases**:
- "What are the main components in this repo?"
- "Automatically organize a new codebase"
- "Discover feature categories"

**Parameters**:
```python
suggest_tags_mcp(
    repo: str = None,          # Repository name
    max_tags: int = 10,        # Max tags to suggest
    sample_size: int = 50,     # Code samples to analyze
    auto_apply: bool = False,  # Automatically tag everything
    threshold: float = 0.7,    # If auto_apply, similarity threshold
    max_results_per_tag: int = 100  # Max entities per tag
)
```

**Returns**:
```json
{
  "repo": "yonk-web-app",
  "suggestions": [
    {
      "tag": "Frontend UI",
      "description": "React components and user interfaces",
      "estimated_matches": 45
    },
    {
      "tag": "Database",
      "description": "Database models and queries",
      "estimated_matches": 67
    }
  ],
  "applied_tags": [...],  // If auto_apply=true
  "why": "LLM analyzed 50 code samples and suggested 8 tags"
}
```

**How it Works**:
1. Samples 50 random chunks/docs from repository
2. Sends to LLM (Ollama/vLLM) with analysis prompt
3. LLM returns suggested categories with descriptions
4. If `auto_apply=true`, runs `generate_tags_for_topic` for each suggestion

**Examples**:
```python
# Just get suggestions (review first)
suggestions = await suggest_tags_mcp(
    repo="new-project",
    max_tags=8
)

# Auto-organize entire codebase
await suggest_tags_mcp(
    repo="wrestling-game",
    max_tags=10,
    auto_apply=True,
    threshold=0.75
)

# Quick analysis (fewer samples = faster)
await suggest_tags_mcp(
    repo="small-project",
    max_tags=5,
    sample_size=20
)
```

---

### 3. `categorize_file`

**Purpose**: Categorize a specific file, with optional LLM-powered tag suggestion.

**Use Cases**:
- "Categorize LoginForm.tsx as UI"
- "What should this file be tagged as?"
- Manual curation of important files

**Parameters**:
```python
categorize_file(
    file_path: str,           # Relative path from repo root
    repo: str = None,         # Repository name
    tag: str = None,          # Tag to apply (None = LLM suggests)
    auto_suggest: bool = True # Use LLM if tag not specified
)
```

**Returns**:
```json
{
  "file_path": "src/components/LoginForm.tsx",
  "tag_applied": "Frontend UI",
  "tag_suggested": true,
  "suggestion": {
    "tag": "Frontend UI",
    "confidence": 0.95,
    "reason": "File contains React components and JSX"
  },
  "existing_tags": ["Frontend UI", "Database", "API Endpoints"],
  "stats": {
    "tagged_files": 1,
    "tagged_chunks": 3
  }
}
```

**How it Works**:
1. Gets file content from database
2. Fetches existing tags to prefer reuse
3. If `tag=None`: LLM analyzes content and suggests category
4. Tags file and all its code chunks
5. Stores confidence score

**Examples**:
```python
# Manual categorization
await categorize_file(
    file_path="api/users.js",
    tag="Backend API"
)

# Ask LLM to suggest
await categorize_file(
    file_path="services/matchSimulator.js"
    # LLM will analyze and suggest appropriate tag
)

# Categorize with specific repo
await categorize_file(
    file_path="src/main.py",
    repo="wrestling-game",
    tag="Entry Point"
)
```

---

### 4. `list_tags` (Existing Tool)

**Purpose**: List all tags in a repository with usage counts.

**Parameters**:
```python
list_tags(
    repo: str = None  # Repository name
)
```

**Returns**:
```json
{
  "tags": [
    {"name": "Frontend UI", "count": 47, "description": "..."},
    {"name": "Database", "count": 67, "description": "..."}
  ]
}
```

---

## Database Schema

### Tables

**`tag` table**:
```sql
CREATE TABLE tag (
    id UUID PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT
);
```

**`entity_tag` table** (many-to-many):
```sql
CREATE TABLE entity_tag (
    id UUID PRIMARY KEY,
    repo_id UUID NOT NULL,
    entity_type TEXT NOT NULL,  -- 'chunk', 'document', 'symbol', 'file'
    entity_id UUID NOT NULL,
    tag_id UUID NOT NULL,
    confidence REAL,            -- 0.0-1.0 from semantic similarity
    source TEXT NOT NULL,       -- 'SEMANTIC_MATCH', 'MANUAL', 'RULE'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (repo_id, entity_type, entity_id, tag_id)
);
```

### Querying Tagged Entities

```sql
-- Find all files tagged as "UI Components"
SELECT f.path, et.confidence
FROM file f
JOIN entity_tag et ON et.entity_id = f.id AND et.entity_type = 'file'
JOIN tag t ON t.id = et.tag_id
WHERE t.name = 'UI Components'
ORDER BY et.confidence DESC;

-- Count entities by tag
SELECT t.name, et.entity_type, COUNT(*) as count
FROM tag t
JOIN entity_tag et ON et.tag_id = t.id
GROUP BY t.name, et.entity_type
ORDER BY t.name, et.entity_type;

-- Find chunks with multiple tags
SELECT c.id, c.content, ARRAY_AGG(t.name) as tags
FROM chunk c
JOIN entity_tag et ON et.entity_id = c.id AND et.entity_type = 'chunk'
JOIN tag t ON t.id = et.tag_id
GROUP BY c.id, c.content
HAVING COUNT(t.id) > 1;
```

---

## Integration with Search Tools

All search tools support tag filtering:

### Filter by Tags
```python
# Search only UI-related code
await hybrid_search(
    query="login form validation",
    tags_all=["Frontend UI"]  # Must have this tag
)

# Search database OR backend code
await hybrid_search(
    query="user authentication",
    tags_any=["Database", "Backend API"]  # Has any of these
)

# Exclude certain tags
await hybrid_search(
    query="api endpoints",
    tags_all=["Backend API"],
    tags_any=None
)
```

### Universal Search with Tags
```python
# Comprehensive search filtered by category
await universal_search(
    query="how does match simulation work?",
    repo="wrestling-game",
    tags_all=["Match Simulation"]
)
```

---

## Workflows

### Workflow 1: Organize a New Codebase

```python
# Step 1: Discover categories
suggestions = await suggest_tags_mcp(
    repo="new-project",
    max_tags=10,
    auto_apply=False
)

# Review suggestions...
# [
#   {"tag": "Frontend UI", "estimated_matches": 45},
#   {"tag": "Database", "estimated_matches": 67},
#   {"tag": "API Endpoints", "estimated_matches": 23}
# ]

# Step 2: Apply selected tags
await generate_tags_for_topic(
    topic="Frontend UI",
    threshold=0.75
)

await generate_tags_for_topic(
    topic="Database",
    threshold=0.8
)

# Or just auto-apply everything
await suggest_tags_mcp(
    repo="new-project",
    auto_apply=True
)
```

### Workflow 2: Curate Specific Files

```python
# Tag important files manually
important_files = [
    ("src/main.py", "Entry Point"),
    ("config/settings.py", "Configuration"),
    ("models/user.py", "Database"),
    ("api/auth.py", "Authentication")
]

for file_path, tag in important_files:
    await categorize_file(
        file_path=file_path,
        tag=tag
    )
```

### Workflow 3: Find and Tag by Feature

```python
# Tag all wrestler-related code
await generate_tags_for_topic(
    topic="Wrestler Management",
    repo="wrestling-game",
    threshold=0.75,
    max_results=200
)

# Tag all match simulation code
await generate_tags_for_topic(
    topic="Match Simulation",
    threshold=0.8
)

# Tag all financial/business logic
await generate_tags_for_topic(
    topic="Financial System",
    threshold=0.75
)

# Now search is much more precise
await hybrid_search(
    query="wrestler attribute calculations",
    tags_all=["Wrestler Management"]
)
```

### Workflow 4: Interactive Categorization

```python
# User asks: "What should mystery_file.js be tagged as?"
result = await categorize_file(
    file_path="mystery_file.js"
)

print(result["suggestion"])
# {
#   "tag": "Backend API",
#   "confidence": 0.85,
#   "reason": "Contains Express route handlers and database queries"
# }

# User: "Actually, it's more of a utility"
await categorize_file(
    file_path="mystery_file.js",
    tag="Utilities"  # Override LLM suggestion
)
```

---

## Configuration

### LLM Model

Set in `.env`:
```bash
LLM_MODEL=qwen2.5-coder:7b
```

Or configure in `config_settings.py`:
```python
llm_model: str = "qwen2.5-coder:7b"
```

### Embeddings Provider

Already configured via:
```bash
EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_BASE_URL=http://localhost:11434
```

### Thresholds

**Recommended similarity thresholds**:
- `0.85+` - Very strict, only very similar code
- `0.75-0.84` - Standard, good balance
- `0.65-0.74` - Loose, more inclusive
- `<0.65` - Very loose, may include unrelated code

**Confidence scores** (from LLM suggestions):
- `0.9+` - High confidence
- `0.7-0.89` - Medium confidence
- `<0.7` - Low confidence (review manually)

---

## Performance

### Semantic Tagging Speed
- Embedding topic: ~100ms
- Vector search: ~50-200ms (depends on data size)
- Tagging 100 entities: ~500ms

**Total**: ~1-2 seconds for typical tagging operation

### LLM Tag Suggestion Speed
- Sampling code: ~100ms
- LLM analysis: ~20-60 seconds (depends on model)
- Auto-apply tags: +1-2s per tag

**Total**: ~30-90 seconds for suggestion + optional auto-apply

### File Categorization Speed
- LLM suggestion: ~3-10 seconds
- Manual tag: ~200ms

---

## Best Practices

### 1. Start with Suggestions
```python
# Don't guess categories - let LLM discover them
await suggest_tags_mcp(repo="my-app", max_tags=10)
```

### 2. Use Existing Tags
```python
# Check existing tags first
tags = await list_tags(repo="my-app")

# Reuse when possible (maintains consistency)
await categorize_file(
    file_path="new-component.tsx",
    tag="Frontend UI"  # Existing tag
)
```

### 3. Adjust Thresholds
```python
# For broad categories, use lower threshold
await generate_tags_for_topic(
    topic="Database",
    threshold=0.7  # More inclusive
)

# For specific features, use higher threshold
await generate_tags_for_topic(
    topic="Wrestler Match Simulation",
    threshold=0.85  # Very specific
)
```

### 4. Combine Approaches
```python
# Use semantic similarity for bulk tagging
await generate_tags_for_topic(topic="UI Components")

# Use direct tagging for exceptions/special cases
await categorize_file(
    file_path="utils/ui-helpers.js",
    tag="Utilities"  # Override if needed
)
```

### 5. Leverage in Search
```python
# After tagging, searches become much more precise
await hybrid_search(
    query="login validation",
    tags_all=["Frontend UI", "Authentication"]
)
```

---

## Troubleshooting

### Issue: LLM Suggestions Timeout
**Solution**: Reduce sample size or use faster model
```python
await suggest_tags_mcp(
    sample_size=20,  # Reduce from 50
    max_tags=5       # Reduce from 10
)
```

### Issue: Too Many/Few Entities Tagged
**Solution**: Adjust threshold
```python
# Too many false positives? Increase threshold
await generate_tags_for_topic(topic="UI", threshold=0.85)

# Too few results? Decrease threshold
await generate_tags_for_topic(topic="UI", threshold=0.65)
```

### Issue: Wrong Tag Suggested
**Solution**: Override with manual tag
```python
result = await categorize_file(file_path="file.js")
# LLM suggests wrong tag

# Re-tag with correct one
await categorize_file(file_path="file.js", tag="Correct Tag")
```

### Issue: Tag Not Found in Search
**Solution**: Check tag name exactly
```sql
-- Find exact tag name
SELECT name FROM tag WHERE name ILIKE '%ui%';
```

---

## CLI Usage

### Tag from Command Line
```bash
# Discover tags
robomonkey tag suggest --repo my-app --max-tags 10

# Tag by topic
robomonkey tag generate --topic "UI Components" --threshold 0.75

# Categorize file
robomonkey tag file --path src/LoginForm.tsx --suggest
```

---

## Python API

Direct usage without MCP:

```python
from yonk_code_robomonkey.tagging.semantic_tagger import tag_by_semantic_similarity
from yonk_code_robomonkey.tagging.tag_suggester import suggest_tags
from yonk_code_robomonkey.tagging.file_tagger import categorize_file

# Semantic tagging
stats = await tag_by_semantic_similarity(
    topic="UI Components",
    repo_name="my-app",
    database_url="postgresql://...",
    schema_name="robomonkey_my_app",
    threshold=0.75
)

# Tag suggestions
suggestions = await suggest_tags(
    repo_name="my-app",
    database_url="postgresql://...",
    schema_name="robomonkey_my_app",
    max_tags=10
)

# File categorization
result = await categorize_file(
    file_path="src/file.js",
    repo_name="my-app",
    database_url="postgresql://...",
    schema_name="robomonkey_my_app"
)
```

---

## Extending the System

### Add Custom Tag Rules

Edit `src/yonk_code_robomonkey/tagging/rules.py`:

```python
# Add new tag pattern
{
    "tag": "Custom Category",
    "match_type": "PATH",
    "pattern": "**/custom/**/*.js",
    "confidence": 0.9
}
```

### Custom Tag Suggestion Prompt

Edit `src/yonk_code_robomonkey/tagging/tag_suggester.py`:

```python
# Modify prompt for domain-specific suggestions
prompt = f"""Analyze this {domain_type} codebase..."""
```

---

## FAQ

**Q: Can I tag the same entity with multiple tags?**
A: Yes! Entities can have multiple tags. The unique constraint is `(repo_id, entity_type, entity_id, tag_id)`.

**Q: What's the difference between semantic tagging and direct tagging?**
A: Semantic tagging finds similar code by meaning (embedding similarity). Direct tagging explicitly tags a specific file.

**Q: How accurate are LLM suggestions?**
A: In testing, 85-95% accuracy for clear categories. Review suggestions before auto-applying.

**Q: Can I delete tags?**
A: Yes, delete from `tag` table (cascades to `entity_tag`):
```sql
DELETE FROM tag WHERE name = 'Unwanted Tag';
```

**Q: How do confidence scores work?**
A:
- Semantic tagging: Cosine similarity (0.0-1.0)
- LLM suggestions: Model's confidence
- Manual tagging: 1.0 (certain)

**Q: Can I search by multiple tags (AND/OR)?**
A: Yes! Use `tags_all` (AND) and `tags_any` (OR) in search tools.

---

## Next Steps

1. **Try it**: Start with `suggest_tags_mcp` on a small repo
2. **Organize**: Use `generate_tags_for_topic` for main categories
3. **Refine**: Use `categorize_file` for special cases
4. **Search**: Filter all searches with tags for precision

For more examples, see `tests/test_semantic_tagging.py`.
