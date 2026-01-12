# RoboMonkey Features - Quick Blurbs for Claude Memory

## Universal Search - The Most Comprehensive Search

**`universal_search(query, repo, deep_mode=true)`**

**What it does:**
Runs THREE search strategies in parallel, then uses an LLM to synthesize results:
1. Hybrid search (vector + full-text + tags)
2. Documentation search (README, docs)
3. Pure semantic search (vector similarity only)

**When to use:**
- Complex questions requiring maximum coverage
- "Tell me everything about authentication in this codebase"
- Exploring unfamiliar code areas
- When single-strategy searches miss relevant results
- Need an intelligent summary, not just raw results

**Key difference from hybrid_search:**
- **hybrid_search**: Fast, returns ranked chunks (good for specific code searches)
- **universal_search**: Thorough, runs 3 searches + LLM analysis (good for understanding complex topics)

**Returns:**
```json
{
  "total_results_found": 45,
  "strategies_used": ["hybrid", "doc", "semantic"],
  "top_results": [...],
  "top_files": [...],
  "llm_summary": "This codebase implements authentication using JWT tokens.
                  The main entry point is AuthService.login() in auth/service.py.
                  Sessions are stored in Redis. Key files: auth/service.py,
                  middleware/auth.py, models/user.py..."
}
```

**Trade-off:** Slower than single searches (3x searches + LLM call), but provides the most comprehensive understanding.

**Example:**
```python
# Simple search - fast, targeted
hybrid_search("authentication", "my-backend")

# Complex topic - comprehensive, with LLM analysis
universal_search("how does authentication work end-to-end", "my-backend", deep_mode=True)
```

---

## Summaries - Cached LLM Explanations

**Tools:**
- `file_summary(file_id)` - Summary of a file's purpose and contents
- `symbol_summary(symbol_id)` - Summary of a function/class
- `module_summary(repo, module_path)` - Summary of a directory/module

**What they are:**
Pre-generated LLM explanations of code components, cached in the database.
Think of them as "documentation written by an AI that read all your code."

**How they're generated:**
1. Automatically during indexing (optional)
2. On-demand when requested with `generate=true`
3. Incrementally by background daemon

**When to use:**
- Quick orientation: "What does this file do?"
- Understanding modules: "What's in the auth/ directory?"
- Function documentation: "What does this function do?"
- Faster than re-reading code

**Structure of summaries:**
```
File Summary (auth/service.py):
├─ Purpose: "Handles user authentication and session management"
├─ Key Components: ["AuthService class", "login()", "logout()", "verify_token()"]
├─ Dependencies: ["Redis for sessions", "JWT library", "User model"]
└─ Usage: "Called by API endpoints in routes/auth.py"

Symbol Summary (AuthService.login):
├─ What it does: "Validates credentials and creates a new session"
├─ Parameters: username (str), password (str)
├─ Returns: JWT token string or raises AuthError
├─ Side effects: "Creates session in Redis, logs login event"
└─ Called by: ["POST /api/login endpoint", "OAuth callback handler"]

Module Summary (auth/):
├─ Purpose: "Authentication and authorization subsystem"
├─ Files: [service.py, models.py, middleware.py, utils.py]
├─ Responsibilities: ["User login/logout", "Token validation", "Permission checks"]
└─ Integration: "Used by all API routes, enforced in middleware"
```

**Benefits:**
- **Faster than reading code** - Get the gist without parsing
- **Cached** - Generated once, reused many times
- **Context-aware** - Includes how components relate to each other
- **Multi-level** - File → Module → Repository understanding

**Combine with search:**
```python
# Find authentication code
results = hybrid_search("authentication", "my-backend")

# Get summary of the top file
top_file_id = results[0]["file_id"]
summary = file_summary(top_file_id)

# Understand the whole auth module
module = module_summary("my-backend", "auth/")
```

**Cost consideration:**
Summaries are LLM-generated, so they consume API tokens during generation.
However, they're cached permanently and reused, making them cost-effective
for frequently accessed code.

---

## Quick Comparison

| Feature | Speed | Coverage | Use Case |
|---------|-------|----------|----------|
| `hybrid_search` | Fast | Targeted | Find specific code |
| `universal_search` | Slow | Comprehensive | Understand complex topics |
| `file_summary` | Instant* | Single file | "What does this file do?" |
| `module_summary` | Instant* | Directory | "What's in this module?" |
| `comprehensive_review` | Slow | Entire repo | Architecture overview |

*If already cached; slower if generating for first time

---

## Pro Tips

**For exploration workflows:**
```python
# 1. Architecture overview
comprehensive_review("my-backend")

# 2. Deep dive into a feature
universal_search("how does payment processing work", "my-backend")

# 3. Understand key files
file_summary(file_id)  # For files found in step 2

# 4. Trace through code
symbol_context(fqn="PaymentService.process", repo="my-backend")
```

**For targeted searches:**
```python
# Fast, specific code finding
hybrid_search("database connection pool", "my-backend")

# Get context on found symbol
symbol_summary(symbol_id)
```

**Universal search is best for:**
- "How does X work?"
- "Show me everything about Y"
- Understanding cross-cutting concerns
- Learning a new codebase

**Summaries are best for:**
- Quick orientation without reading code
- Documentation lookup
- Understanding module organization
- Complementing search results
