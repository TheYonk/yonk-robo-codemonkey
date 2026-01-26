# RoboMonkey Architecture Overview

A comprehensive guide to how RoboMonkey processes code and documentation, enabling intelligent search, analysis, and AI-powered recommendations.

## Table of Contents

- [System Overview](#system-overview)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Indexing Pipeline](#indexing-pipeline)
- [Embedding System](#embedding-system)
- [Search & Retrieval](#search--retrieval)
- [AI-Powered Features](#ai-powered-features)
- [Issue Detection & Recommendations](#issue-detection--recommendations)
- [Integration Points](#integration-points)

---

## System Overview

RoboMonkey is a **local-first code intelligence platform** that indexes codebases and documentation into PostgreSQL with pgvector, providing hybrid retrieval (semantic + keyword search) and AI-powered analysis for LLM coding assistants.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RoboMonkey System                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   Source     │    │  Knowledge   │    │   Database   │                  │
│  │   Code       │    │    Base      │    │  Introspect  │                  │
│  │  (Repos)     │    │   (Docs)     │    │   (Schema)   │                  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                   │                          │
│         ▼                   ▼                   ▼                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Indexing Pipeline                               │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │   │
│  │  │  Scan   │→ │  Parse  │→ │  Chunk  │→ │  Embed  │→ │   Tag   │   │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    PostgreSQL + pgvector                             │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │   │
│  │  │  Files  │  │ Symbols │  │ Chunks  │  │  Edges  │  │  Tags   │   │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │              Vector Embeddings (1536-dim)                   │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Retrieval Engine                                │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │   Vector     │  │   Full-Text  │  │    Graph     │              │   │
│  │  │   Search     │  │    Search    │  │  Traversal   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  │              ↓            ↓               ↓                         │   │
│  │         ┌────────────────────────────────────┐                      │   │
│  │         │       Hybrid Search Merger         │                      │   │
│  │         │  (55% vector + 35% FTS + 10% tag) │                      │   │
│  │         └────────────────────────────────────┘                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        LLM Integration                               │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │  Summaries   │  │   Answers    │  │   Analysis   │              │   │
│  │  │   (small)    │  │   (deep)     │  │   (deep)     │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Access Layer                                   │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │   │
│  │  │ MCP Server │  │  Web API   │  │  Web UI    │  │    CLI     │   │   │
│  │  │  (stdio)   │  │ (FastAPI)  │  │ (port 9832)│  │            │   │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Indexing Engine (`indexer/`)

Parses and extracts structure from source code using tree-sitter.

| Component | Purpose |
|-----------|---------|
| `repo_scanner.py` | Walks directories, honors `.gitignore` |
| `language_detect.py` | Identifies file languages by extension |
| `treesitter/parsers.py` | Language-specific AST parsing |
| `treesitter/extract_symbols.py` | Extracts functions, classes, methods |
| `treesitter/extract_imports.py` | Extracts import statements |
| `treesitter/extract_edges.py` | Builds call graph, inheritance edges |
| `treesitter/chunking.py` | Creates searchable chunks per symbol |

**Supported Languages:**
- Python, JavaScript, TypeScript
- Go, Java, C
- SQL (DDL parsing)

### 2. Embedding System (`embeddings/`)

Converts text into high-dimensional vectors for semantic search.

| Provider | Endpoint | Use Case |
|----------|----------|----------|
| `ollama` | `/api/embeddings` | Local Ollama server |
| `openai` | `/v1/embeddings` | OpenAI, local embedding service |
| `vllm` | `/v1/embeddings` | Local vLLM server |

**Process:**
```
Text Chunk → Embedding Model → 1536-dim Vector → pgvector Storage
```

### 3. Retrieval Engine (`retrieval/`)

Finds relevant code and documentation using multiple search strategies.

| Component | Strategy | Use Case |
|-----------|----------|----------|
| `vector_search.py` | Semantic similarity | "How does auth work?" |
| `fts_search.py` | Keyword matching | "AuthMiddleware" |
| `hybrid_search.py` | Combined (55/35/10) | Best of both worlds |
| `graph_traversal.py` | Call graph walking | Find callers/callees |
| `context_pack.py` | Token budgeting | LLM context building |

### 4. Knowledge Base (`knowledge_base/`)

Indexes external documentation (PDFs, Markdown, HTML) for RAG retrieval.

| Component | Purpose |
|-----------|---------|
| `chunker.py` | Smart chunking with section hierarchy |
| `search.py` | Hybrid search with context expansion |
| `extractors/pdf.py` | PDF parsing with structure preservation |
| `extractors/markdown.py` | Markdown with heading hierarchy |

### 5. LLM Integration (`llm/`)

Two-tier model strategy for different task complexities.

| Model Type | Tasks | Examples |
|------------|-------|----------|
| **Deep** | Complex analysis, synthesis | Code review, comprehensive answers |
| **Small** | Quick tasks, summaries | File summaries, classifications |

### 6. Daemon (`daemon/`)

Background job processor for async operations.

| Worker | Job Type | Operation |
|--------|----------|-----------|
| `summary_worker.py` | `SUMMARIZE_*` | Generate LLM summaries |
| `doc_validity_worker.py` | `DOC_VALIDITY` | Verify documentation claims |
| `semantic_validity_worker.py` | `SEMANTIC_VALIDITY` | Code-doc consistency |
| `watcher.py` | File changes | Incremental reindexing |

---

## Data Flow

### Repository Registration to Search-Ready

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Repository Lifecycle                                   │
└──────────────────────────────────────────────────────────────────────────┘

1. REGISTER                    2. INDEX                      3. EMBED
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ POST /registry  │           │ FULL_INDEX job  │           │ EMBED_MISSING   │
│                 │           │                 │           │                 │
│ • name          │    ───►   │ • Scan files    │    ───►   │ • Batch chunks  │
│ • root_path     │           │ • Parse AST     │           │ • Call embed    │
│ • auto_index    │           │ • Store symbols │           │ • Store vectors │
│ • auto_embed    │           │ • Create chunks │           │ • Build index   │
└─────────────────┘           └─────────────────┘           └─────────────────┘
                                      │
                                      ▼
                              ┌─────────────────┐
                              │  TAG_RULES_SYNC │
                              │                 │
                              │ • Apply rules   │
                              │ • Auto-tag code │
                              │ • Link entities │
                              └─────────────────┘
                                      │
                                      ▼
4. SUMMARIZE                  5. READY
┌─────────────────┐           ┌─────────────────┐
│ SUMMARIZE_*     │           │   Searchable    │
│                 │           │                 │
│ • File summaries│    ───►   │ • Hybrid search │
│ • Symbol docs   │           │ • ask_codebase  │
│ • Module docs   │           │ • Graph queries │
└─────────────────┘           └─────────────────┘
```

---

## Indexing Pipeline

### Stage 1: File Discovery

```python
# repo_scanner.py
scan_repository(path) → list[FileInfo]
  ├── Walk directory tree
  ├── Apply .gitignore rules (pathspec)
  ├── Detect language per file
  └── Return file metadata
```

### Stage 2: AST Parsing

```python
# treesitter/parsers.py
parse_file(path, language) → SyntaxTree
  ├── Load tree-sitter grammar
  ├── Parse source code → AST
  └── Return navigable tree
```

### Stage 3: Symbol Extraction

```python
# treesitter/extract_symbols.py
extract_symbols(tree, language) → list[Symbol]
  ├── Find function/method definitions
  ├── Find class/interface definitions
  ├── Extract FQN (fully qualified name)
  ├── Extract signature, docstring
  └── Record line ranges
```

**Symbol Kinds:**
- `function` - Top-level functions
- `method` - Class methods
- `class` - Class definitions
- `interface` - Interface/protocol definitions
- `module` - Module-level constructs

### Stage 4: Relationship Extraction

```python
# treesitter/extract_edges.py
extract_edges(tree, symbols, language) → list[Edge]
  ├── Find function calls → CALLS edge
  ├── Find imports → IMPORTS edge
  ├── Find class inheritance → INHERITS edge
  ├── Find interface impl → IMPLEMENTS edge
  └── Store evidence spans (line ranges)
```

**Edge Types:**
| Edge | Meaning | Example |
|------|---------|---------|
| `CALLS` | Function invokes function | `main() → process()` |
| `IMPORTS` | File imports module | `auth.py → jwt` |
| `INHERITS` | Class extends class | `Admin → User` |
| `IMPLEMENTS` | Class implements interface | `Handler → Protocol` |

### Stage 5: Chunking

```python
# treesitter/chunking.py
create_chunks(file, symbols) → list[Chunk]
  ├── Create file header chunk (imports, docstring)
  ├── Create chunk per symbol (with context)
  ├── Compute content_hash for dedup
  └── Link chunk to file/symbol
```

**Chunk Structure:**
```
┌─────────────────────────────────────────┐
│ File Header Chunk                       │
│ • Module docstring                      │
│ • Import statements                     │
│ • Global constants                      │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Symbol Chunk: MyClass                   │
│ • Class docstring                       │
│ • Class definition                      │
│ • Method signatures                     │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Symbol Chunk: MyClass.process           │
│ • Method docstring                      │
│ • Full method body                      │
│ • Local context                         │
└─────────────────────────────────────────┘
```

### Stage 6: Auto-Tagging

```python
# tagger/auto_tagger.py
apply_tags(chunk, rules) → list[Tag]
  ├── Match PATH rules (file location)
  ├── Match IMPORT rules (dependencies)
  ├── Match REGEX rules (content patterns)
  ├── Match SYMBOL rules (naming patterns)
  └── Link tags to entities
```

**Tag Categories:**
| Category | Examples | Detection |
|----------|----------|-----------|
| Domain | `auth`, `database`, `api` | Path + imports |
| Pattern | `singleton`, `factory`, `middleware` | Code patterns |
| Quality | `needs-tests`, `deprecated` | Comments, naming |
| Technology | `react`, `django`, `express` | Imports |

---

## Embedding System

### Embedding Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Embedding Pipeline                                │
└─────────────────────────────────────────────────────────────────────────┘

1. COLLECT                     2. DEDUPLICATE                3. BATCH
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ Find unembedded │           │ Check hash      │           │ Group by model  │
│                 │           │                 │           │                 │
│ • Chunks        │    ───►   │ • content_hash  │    ───►   │ • batch_size=32│
│ • Documents     │           │ • Skip if same  │           │ • Parallel req  │
│ • Summaries     │           │ • Mark dirty    │           │ • Rate limit    │
└─────────────────┘           └─────────────────┘           └─────────────────┘
                                                                    │
                                                                    ▼
4. EMBED                       5. STORE                      6. INDEX
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ Call provider   │           │ Insert vectors  │           │ Build/rebuild   │
│                 │           │                 │           │                 │
│ • Ollama        │    ───►   │ • chunk_embed   │    ───►   │ • IVFFlat      │
│ • OpenAI API    │           │ • doc_embed     │           │ • HNSW         │
│ • vLLM          │           │ • summary_embed │           │ • Auto-tune    │
└─────────────────┘           └─────────────────┘           └─────────────────┘
```

### Vector Index Types

| Type | Best For | Trade-offs |
|------|----------|------------|
| **IVFFlat** | < 100K vectors | Fast build, good recall |
| **HNSW** | > 100K vectors | Slower build, better recall |

**Auto-Tuning:**
- IVFFlat `lists` = sqrt(row_count)
- HNSW `m=16`, `ef_construction=64` (defaults)
- Rebuild triggered after 20%+ embeddings change

---

## Search & Retrieval

### Hybrid Search Algorithm

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Hybrid Search                                    │
└─────────────────────────────────────────────────────────────────────────┘

Query: "How does authentication middleware validate tokens?"

1. EMBED QUERY                 2. VECTOR SEARCH              3. FTS SEARCH
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ Embed query     │           │ pgvector        │           │ to_tsquery      │
│ → 1536-dim vec  │    ───►   │ cosine dist     │    ───►   │ websearch mode  │
│                 │           │ top_k=30        │           │ top_k=30        │
└─────────────────┘           └─────────────────┘           └─────────────────┘
                                      │                             │
                                      ▼                             ▼
                              ┌───────────────────────────────────────┐
                              │            MERGE & RANK               │
                              │                                       │
                              │  final_score = 0.55 × vec_norm       │
                              │              + 0.35 × fts_norm       │
                              │              + 0.10 × tag_boost      │
                              │                                       │
                              │  • Deduplicate by chunk_id            │
                              │  • Apply filters (path, lang, tags)   │
                              │  • Sort by final_score DESC           │
                              │  • Return top_k=12                    │
                              └───────────────────────────────────────┘
                                              │
                                              ▼
                              ┌───────────────────────────────────────┐
                              │           EXPLAINABILITY              │
                              │                                       │
                              │  Each result includes:                │
                              │  • vec_rank, vec_score                │
                              │  • fts_rank, fts_score                │
                              │  • matched_tags, tag_boost            │
                              │  • combined score                     │
                              └───────────────────────────────────────┘
```

### Search Modes

| Mode | Algorithm | Best For |
|------|-----------|----------|
| `hybrid` | 55% vector + 35% FTS + 10% tags | General questions |
| `semantic` | 100% vector | Conceptual queries |
| `fts` | 100% full-text | Exact identifiers |

### ask_codebase Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ask_codebase Tool                                 │
└─────────────────────────────────────────────────────────────────────────┘

Question: "How does the authentication system work?"

1. MULTI-SOURCE SEARCH
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   doc_search    │  │  hybrid_search  │  │  symbol_search  │
│                 │  │                 │  │                 │
│ • README.md     │  │ • auth.py       │  │ • AuthMiddleware│
│ • docs/auth.md  │  │ • handlers.py   │  │ • validate()    │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │    AGGREGATE    │
                    │                 │
                    │ • Merge results │
                    │ • Deduplicate   │
                    │ • Rank by score │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
2a. FORMAT: files              2b. FORMAT: prose / both
┌─────────────────┐           ┌─────────────────┐
│ Structured List │           │   LLM Synthesis │
│                 │           │                 │
│ 📄 Docs (2)     │           │ SMALL model:    │
│   • auth.md     │           │   → Summary     │
│   • readme.md   │           │                 │
│                 │           │ DEEP model:     │
│ 📁 Code (5)     │           │   → Answer      │
│   • auth.py     │           │                 │
│     └ AuthMid.. │           │ Context:        │
│   • handlers.py │           │   • Top docs    │
│     └ login()   │           │   • Top code    │
│                 │           │   • Top symbols │
└─────────────────┘           └─────────────────┘
         │                             │
         └──────────────┬──────────────┘
                        ▼
              ┌─────────────────┐
              │     RESPONSE    │
              │                 │
              │ • summary       │
              │ • answer        │
              │ • documentation │
              │ • code_files    │
              │ • symbols       │
              │ • key_files     │
              └─────────────────┘
```

---

## AI-Powered Features

### Dual-Model Strategy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      LLM Model Selection                                 │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │           Task Router               │
                    └──────────────────┬──────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
     ┌────────────────┐      ┌────────────────┐      ┌────────────────┐
     │ Simple Tasks   │      │ Complex Tasks  │      │ Analysis Tasks │
     │                │      │                │      │                │
     │ SMALL MODEL    │      │ DEEP MODEL     │      │ DEEP MODEL     │
     │ (gpt-5-mini)   │      │ (gpt-5.2-codex)│      │ (gpt-5.2-codex)│
     │                │      │                │      │                │
     │ • File summary │      │ • Code answers │      │ • Code review  │
     │ • Quick Q&A    │      │ • Synthesis    │      │ • Feature ctx  │
     │ • Classify     │      │ • Complex Q&A  │      │ • Comprehensive│
     └────────────────┘      └────────────────┘      └────────────────┘
```

### Summary Generation Pipeline

```
File/Symbol/Module → Extract Context → LLM Prompt → Summary → Embed → Store

Summaries provide:
• Human-readable explanations
• Semantic search improvements
• Documentation augmentation
```

### Ask Docs (Knowledge Base RAG)

```
Question → Search KB → Retrieve Chunks → Build Context → LLM → Answer

Features:
• Inline citations [1], [2], [3]
• Confidence scoring (high/medium/low/no_answer)
• Source attribution with page numbers
• Context expansion (surrounding chunks)
```

---

## Issue Detection & Recommendations

### Pattern Scanning

The `pattern_scan` tool performs regex-based code analysis to detect issues.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Pattern Scanning                                   │
└─────────────────────────────────────────────────────────────────────────┘

Pattern: "SELECT\\s+\\*\\s+FROM"

1. FILTER FILES               2. SCAN CONTENT              3. REPORT
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│ Apply filters   │          │ Regex match     │          │ Group by file   │
│                 │          │                 │          │                 │
│ • file_glob     │   ───►   │ • Line number   │   ───►   │ • Match count   │
│ • languages     │          │ • Column        │          │ • Context lines │
│ • max_files     │          │ • Context       │          │ • Locations     │
└─────────────────┘          └─────────────────┘          └─────────────────┘
```

**Common Detection Patterns:**

| Issue | Pattern | Severity |
|-------|---------|----------|
| SELECT * | `SELECT\s+\*\s+FROM` | Warning |
| eval() usage | `eval\s*\(` | Critical |
| Hardcoded passwords | `password\s*=\s*["'][^"']+` | Critical |
| TODO/FIXME | `TODO\|FIXME\|HACK` | Info |
| SQL injection risk | `execute\s*\([^)]*\+` | Critical |

### Migration Assessment

For Oracle-to-PostgreSQL migrations, RoboMonkey provides specialized detection.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Migration Detection                                   │
└─────────────────────────────────────────────────────────────────────────┘

Source Code → Scan for Oracle Constructs → Map to EPAS Features → Report

Oracle Constructs Detected:
• CONNECT BY hierarchical queries
• ROWNUM pseudo-column
• DECODE function
• Oracle packages (DBMS_*)
• PL/SQL syntax

Recommendations Generated:
• Equivalent EPAS syntax
• Migration complexity score
• Documentation references
• Code transformation examples
```

### Index Recommendations

```
GET /api/maintenance/vector-indexes/recommendations

Analysis:
• Row count per embedding table
• Current index type
• Optimal index parameters
• Action needed (rebuild/switch)

Example:
{
  "table": "chunk_embedding",
  "row_count": 50000,
  "current_index_type": "ivfflat",
  "recommended_type": "hnsw",
  "reason": "HNSW provides better recall for 50K+ vectors",
  "needs_action": true
}
```

---

## Integration Points

### MCP Server (Model Context Protocol)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        MCP Integration                                   │
└─────────────────────────────────────────────────────────────────────────┘

LLM Client (Claude, Cline, etc.)
         │
         │ stdio
         ▼
┌─────────────────┐
│   MCP Server    │
│   (server.py)   │
│                 │
│ Tools:          │
│ • hybrid_search │
│ • ask_codebase  │
│ • symbol_lookup │
│ • pattern_scan  │
│ • callers       │
│ • callees       │
│ • doc_search    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Tool Handler  │
│   (tools.py)    │
│                 │
│ • Validate input│
│ • Execute query │
│ • Format output │
└────────┬────────┘
         │
         ▼
    PostgreSQL
```

### Web API (FastAPI)

```
HTTP Client → FastAPI Router → Handler → Database/LLM → Response

Endpoints:
• /api/mcp/tools/{name} - Execute MCP tools via HTTP
• /api/docs/search - Knowledge base search
• /api/docs/ask - RAG Q&A
• /api/registry - Repository management
• /api/stats - Monitoring
```

### CLI

```
$ robomonkey db init          # Initialize database
$ robomonkey db ping          # Test connection
$ robomonkey index --repo .   # Index current directory
```

---

## Configuration

### Key Settings

| Setting | Location | Purpose |
|---------|----------|---------|
| `DATABASE_URL` | `.env` | PostgreSQL connection |
| `EMBEDDINGS_PROVIDER` | `.env` | ollama/openai/vllm |
| `EMBEDDINGS_MODEL` | `.env` | Model name |
| `llm.deep.model` | `daemon.yaml` | Complex task LLM |
| `llm.small.model` | `daemon.yaml` | Simple task LLM |
| `workers.mode` | `daemon.yaml` | single/per_repo/pool |

### Performance Tuning

| Parameter | Default | Effect |
|-----------|---------|--------|
| `VECTOR_TOP_K` | 30 | Initial vector candidates |
| `FTS_TOP_K` | 30 | Initial FTS candidates |
| `FINAL_TOP_K` | 12 | Results returned |
| `CONTEXT_BUDGET_TOKENS` | 12000 | LLM context limit |
| `batch_size` | 32 | Embedding batch size |

---

## Summary

RoboMonkey provides:

1. **Deep Code Understanding** - AST parsing, symbol extraction, call graph building
2. **Hybrid Search** - Combines semantic (vector) and keyword (FTS) search
3. **AI-Powered Answers** - LLM synthesis from multiple sources
4. **Issue Detection** - Pattern scanning, migration assessment
5. **Multi-Modal Integration** - MCP, HTTP API, Web UI, CLI

The system is designed for **local-first operation** - all data stays in your PostgreSQL database, and you control which LLM providers to use.
