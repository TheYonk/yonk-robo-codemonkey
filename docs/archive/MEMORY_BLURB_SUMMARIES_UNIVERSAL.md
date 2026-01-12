# Add to CLAUDE.md - Universal Search & Summaries

## Universal Search - Maximum Coverage + LLM Analysis

**`universal_search(query, repo, deep_mode=true)`**

The most comprehensive search tool. Runs 3 strategies in parallel (hybrid + docs + semantic), then uses LLM to synthesize an intelligent answer.

**Use when:**
- "How does authentication work end-to-end?"
- "Tell me everything about payment processing"
- Complex topics needing multiple angles
- Want LLM to explain findings, not just return chunks

**Returns:** Top results + **LLM-generated summary** explaining how it all works

**Trade-off:** Slower than `hybrid_search`, but most thorough understanding

---

## Summaries - Cached LLM Documentation

**`file_summary(file_id)`** - "What does this file do?"
**`symbol_summary(symbol_id)`** - "What does this function do?"
**`module_summary(repo, module_path)`** - "What's in this directory?"

Pre-generated AI explanations of code components, cached in database.

**Benefits:**
- Faster than reading code
- Cached (generated once, reused forever)
- Context-aware (includes relationships)
- Multi-level (file → module → repo)

**Use for:**
- Quick orientation
- Understanding module structure
- Documentation lookup
- Complementing search results

---

## Quick Decision Guide

**Need specific code?** → `hybrid_search` (fast, targeted)
**Understanding complex topic?** → `universal_search` (thorough + LLM explanation)
**"What does this do?"** → Summaries (instant cached explanations)
**Architecture overview?** → `comprehensive_review` (entire codebase analysis)

## Example Workflow

```python
# 1. Understand a complex feature
result = universal_search("how does authentication work", "my-backend")
# Returns: LLM summary + relevant code

# 2. Get details on key files
summary = file_summary(result.top_files[0])
# Returns: Purpose, components, dependencies, usage

# 3. Understand the module
module = module_summary("my-backend", "auth/")
# Returns: Module purpose, files, responsibilities
```
