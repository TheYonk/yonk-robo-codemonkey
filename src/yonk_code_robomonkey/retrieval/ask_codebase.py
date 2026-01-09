"""Ask Codebase - Intelligent question answering over code and documentation.

Orchestrates multiple search strategies and formats results for LLM consumption.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from typing import Optional

from yonk_code_robomonkey.embeddings.ollama import ollama_embed
from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed


@dataclass
class DocumentResult:
    """Documentation search result."""
    file_path: str
    title: str
    summary: str
    relevance_score: float
    line_range: Optional[tuple[int, int]] = None
    document_id: Optional[str] = None  # UUID for validity lookups


@dataclass
class CodeResult:
    """Code file search result."""
    file_path: str
    snippet: str
    line_range: tuple[int, int]
    language: str
    relevance_score: float
    context: Optional[str] = None  # Surrounding context


@dataclass
class SymbolResult:
    """Symbol search result."""
    name: str
    kind: str  # function, class, method, etc.
    file_path: str
    line: int
    signature: Optional[str]
    description: Optional[str]
    relevance_score: float


@dataclass
class SummaryResult:
    """Summary search result."""
    summary_type: str  # "file", "module", or "symbol"
    name: str  # File path, module path, or symbol name
    summary: str
    relevance_score: float
    file_path: Optional[str] = None  # For symbol summaries


@dataclass
class CodebaseAnswer:
    """Complete answer to a codebase question."""
    question: str
    repo_name: str

    # Results by category
    documentation: list[DocumentResult]
    code_files: list[CodeResult]
    symbols: list[SymbolResult]

    # Summary results (high-level explanations)
    file_summaries: list[SummaryResult]
    module_summaries: list[SummaryResult]
    symbol_summaries: list[SummaryResult]

    # Synthesized summary
    summary: str
    key_files: list[str]  # Most relevant files to examine
    suggested_actions: list[str]  # What to do next

    # Metadata
    total_results_found: int
    search_strategies_used: list[str]


async def ask_codebase(
    question: str,
    repo_name: str,
    database_url: str,
    schema_name: str,
    embeddings_provider: str = "ollama",
    embeddings_model: str = "nomic-embed-text",
    embeddings_base_url: str = "http://localhost:11434",
    embeddings_api_key: str = "",
    top_docs: int = 3,
    top_code: int = 5,
    top_symbols: int = 5,
    use_llm_summary: bool = True,
    use_vector_search: bool = True
) -> CodebaseAnswer:
    """Answer a natural language question about the codebase.

    Orchestrates multiple search strategies:
    1. Documentation search (vector + FTS for conceptual understanding)
    2. Code search (vector + FTS for implementation details)
    3. Symbol search (FTS for specific functions/classes)
    4. LLM synthesis (for coherent answer)

    Args:
        question: Natural language question (e.g., "how does authentication work?")
        repo_name: Repository to search
        database_url: Database connection string
        schema_name: Schema name for repo
        embeddings_provider: "ollama" or "vllm"
        embeddings_model: Model name for embeddings
        embeddings_base_url: Provider base URL
        embeddings_api_key: API key (for vLLM)
        top_docs: Number of documentation results to return
        top_code: Number of code file results to return
        top_symbols: Number of symbol results to return
        use_llm_summary: Whether to generate LLM summary
        use_vector_search: Whether to use vector search (default True)

    Returns:
        CodebaseAnswer with structured results and summary
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Set search path
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Step 0: Embed query for vector search (if enabled)
        query_embedding = None
        if use_vector_search:
            if embeddings_provider == "ollama":
                embeddings = await ollama_embed([question], embeddings_model, embeddings_base_url)
            elif embeddings_provider == "vllm":
                embeddings = await vllm_embed([question], embeddings_model, embeddings_base_url, embeddings_api_key)
            else:
                raise ValueError(f"Invalid embeddings provider: {embeddings_provider}")
            query_embedding = embeddings[0]

        # Step 1: Search documentation (vector + FTS)
        doc_results = await _search_documentation(conn, question, top_docs, query_embedding)

        # Step 2: Search code (vector + FTS)
        code_results = await _search_code(conn, question, top_code, query_embedding)

        # Step 3: Search symbols (FTS only - symbols don't have embeddings)
        symbol_results = await _search_symbols(conn, question, top_symbols)

        # Step 4: Search summaries (FTS only - summaries don't have embeddings yet)
        file_summaries, module_summaries, symbol_summaries = await _search_summaries(conn, question, top_k=3)

        # Step 5: Extract key files (from all result sources)
        key_files = _extract_key_files(doc_results, code_results, symbol_results)

        # Step 6: Generate summary (if LLM enabled)
        if use_llm_summary:
            summary = await _generate_summary(question, doc_results, code_results, symbol_results)
            suggested_actions = _suggest_actions(question, doc_results, code_results, symbol_results)
        else:
            summary = _create_basic_summary(doc_results, code_results, symbol_results)
            suggested_actions = []

        total_results = (len(doc_results) + len(code_results) + len(symbol_results) +
                        len(file_summaries) + len(module_summaries) + len(symbol_summaries))
        strategies_used = []
        if doc_results:
            strategies_used.append("documentation_search")
        if code_results:
            strategies_used.append("hybrid_code_search")
        if symbol_results:
            strategies_used.append("symbol_search")
        if file_summaries or module_summaries or symbol_summaries:
            strategies_used.append("summary_search")

        return CodebaseAnswer(
            question=question,
            repo_name=repo_name,
            documentation=doc_results,
            code_files=code_results,
            symbols=symbol_results,
            file_summaries=file_summaries,
            module_summaries=module_summaries,
            symbol_summaries=symbol_summaries,
            summary=summary,
            key_files=key_files[:10],  # Top 10 most relevant files
            suggested_actions=suggested_actions,
            total_results_found=total_results,
            search_strategies_used=strategies_used
        )

    finally:
        await conn.close()


async def _search_documentation(
    conn: asyncpg.Connection,
    query: str,
    top_k: int,
    query_embedding: list[float] | None = None
) -> list[DocumentResult]:
    """Search documentation using vector similarity + FTS.

    Args:
        conn: Database connection
        query: Search query
        top_k: Number of results
        query_embedding: Optional query embedding for vector search

    Returns:
        List of DocumentResult objects
    """
    doc_results_map = {}  # document_id -> DocumentResult

    # Vector search (if embedding provided)
    if query_embedding:
        # Convert embedding to pgvector format
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        vector_results = await conn.fetch("""
            SELECT
                d.id,
                d.title,
                d.content,
                f.path,
                (de.embedding <=> $1::vector) as distance,
                1.0 / (1.0 + (de.embedding <=> $1::vector)) as similarity
            FROM document d
            JOIN document_embedding de ON d.id = de.document_id
            LEFT JOIN file f ON d.file_id = f.id
            ORDER BY de.embedding <=> $1::vector
            LIMIT $2
        """, vec_str, top_k * 2)  # Get extra for merging

        for row in vector_results:
            content = row['content'] or ""
            summary = content[:200] + "..." if len(content) > 200 else content

            doc_results_map[row['id']] = DocumentResult(
                file_path=row['path'] or "(embedded doc)",
                title=row['title'] or "Untitled",
                summary=summary,
                relevance_score=float(row['similarity']),
                document_id=str(row['id'])
            )

    # FTS search (always run for broader coverage)
    # Use OR logic for flexibility - split query into words and OR them together
    query_words = query.split()
    # Filter out very short words (like "a", "or", "the")
    meaningful_words = [w for w in query_words if len(w) >= 3]
    if meaningful_words:
        # Join with OR for flexible matching
        or_query = " OR ".join(meaningful_words)
    else:
        or_query = query

    fts_results = await conn.fetch("""
        SELECT
            d.id,
            d.title,
            d.content,
            f.path,
            ts_rank_cd(d.fts, websearch_to_tsquery('english', $1)) as rank
        FROM document d
        LEFT JOIN file f ON d.file_id = f.id
        WHERE d.fts @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k * 2)  # Get extra for merging

    for row in fts_results:
        doc_id = row['id']
        content = row['content'] or ""
        summary = content[:200] + "..." if len(content) > 200 else content
        fts_score = float(row['rank'])

        if doc_id in doc_results_map:
            # Merge scores (vector + FTS)
            doc_results_map[doc_id].relevance_score = (
                doc_results_map[doc_id].relevance_score * 0.6 + fts_score * 0.4
            )
        else:
            doc_results_map[doc_id] = DocumentResult(
                file_path=row['path'] or "(embedded doc)",
                title=row['title'] or "Untitled",
                summary=summary,
                relevance_score=fts_score,
                document_id=str(doc_id)
            )

    # Sort by relevance and return top_k
    sorted_results = sorted(
        doc_results_map.values(),
        key=lambda x: x.relevance_score,
        reverse=True
    )

    return sorted_results[:top_k]


async def _search_code(
    conn: asyncpg.Connection,
    query: str,
    top_k: int,
    query_embedding: list[float] | None = None
) -> list[CodeResult]:
    """Search code using hybrid vector + FTS search.

    Args:
        conn: Database connection
        query: Search query
        top_k: Number of results
        query_embedding: Optional query embedding for vector search

    Returns:
        List of CodeResult objects (deduplicated by file)
    """
    chunk_results_map = {}  # chunk_id -> (CodeResult, score)

    # Vector search (if embedding provided)
    if query_embedding:
        # Convert embedding to pgvector format
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        vector_results = await conn.fetch("""
            SELECT
                c.id,
                c.content,
                c.start_line,
                c.end_line,
                f.path,
                f.language,
                s.name as symbol_name,
                s.kind as symbol_kind,
                (ce.embedding <=> $1::vector) as distance,
                1.0 / (1.0 + (ce.embedding <=> $1::vector)) as similarity
            FROM chunk c
            JOIN chunk_embedding ce ON c.id = ce.chunk_id
            JOIN file f ON c.file_id = f.id
            LEFT JOIN symbol s ON c.symbol_id = s.id
            ORDER BY ce.embedding <=> $1::vector
            LIMIT $2
        """, vec_str, top_k * 3)  # Get extra for deduplication

        for row in vector_results:
            chunk_id = row['id']
            content = row['content'] or ""
            snippet = content[:300] + "..." if len(content) > 300 else content

            context = None
            if row['symbol_name']:
                context = f"{row['symbol_kind']} {row['symbol_name']}"

            chunk_results_map[chunk_id] = (
                CodeResult(
                    file_path=row['path'],
                    snippet=snippet,
                    line_range=(row['start_line'], row['end_line']),
                    language=row['language'] or "unknown",
                    relevance_score=float(row['similarity']),
                    context=context
                ),
                float(row['similarity'])
            )

    # FTS search (always run for broader coverage)
    # Use OR logic for flexibility - split query into words and OR them together
    query_words = query.split()
    # Filter out very short words (like "a", "or", "the")
    meaningful_words = [w for w in query_words if len(w) >= 3]
    if meaningful_words:
        # Join with OR for flexible matching
        or_query = " OR ".join(meaningful_words)
    else:
        or_query = query

    fts_results = await conn.fetch("""
        SELECT
            c.id,
            c.content,
            c.start_line,
            c.end_line,
            f.path,
            f.language,
            s.name as symbol_name,
            s.kind as symbol_kind,
            ts_rank_cd(c.fts, websearch_to_tsquery('english', $1)) as rank
        FROM chunk c
        JOIN file f ON c.file_id = f.id
        LEFT JOIN symbol s ON c.symbol_id = s.id
        WHERE c.fts @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k * 3)  # Get extra for deduplication

    for row in fts_results:
        chunk_id = row['id']
        content = row['content'] or ""
        snippet = content[:300] + "..." if len(content) > 300 else content
        fts_score = float(row['rank'])

        context = None
        if row['symbol_name']:
            context = f"{row['symbol_kind']} {row['symbol_name']}"

        if chunk_id in chunk_results_map:
            # Merge scores (vector + FTS)
            existing_result, vec_score = chunk_results_map[chunk_id]
            merged_score = vec_score * 0.6 + fts_score * 0.4
            existing_result.relevance_score = merged_score
            chunk_results_map[chunk_id] = (existing_result, merged_score)
        else:
            result = CodeResult(
                file_path=row['path'],
                snippet=snippet,
                line_range=(row['start_line'], row['end_line']),
                language=row['language'] or "unknown",
                relevance_score=fts_score,
                context=context
            )
            chunk_results_map[chunk_id] = (result, fts_score)

    # Sort by score and deduplicate by file (keep highest-ranked chunk per file)
    sorted_chunks = sorted(
        chunk_results_map.values(),
        key=lambda x: x[1],
        reverse=True
    )

    seen_files = set()
    code_results = []

    for result, _ in sorted_chunks:
        if result.file_path not in seen_files:
            seen_files.add(result.file_path)
            code_results.append(result)

            if len(code_results) >= top_k:
                break

    return code_results


async def _search_symbols(conn: asyncpg.Connection, query: str, top_k: int) -> list[SymbolResult]:
    """Search symbols (functions, classes) using FTS on names and docstrings.

    Args:
        conn: Database connection
        query: Search query
        top_k: Number of results

    Returns:
        List of SymbolResult objects
    """
    # Use OR logic for flexibility - split query into words and OR them together
    query_words = query.split()
    # Filter out very short words (like "a", "or", "the")
    meaningful_words = [w for w in query_words if len(w) >= 3]
    if meaningful_words:
        # Join with OR for flexible matching
        or_query = " OR ".join(meaningful_words)
    else:
        or_query = query

    # Search symbol names and signatures
    results = await conn.fetch("""
        SELECT
            s.name,
            s.kind,
            s.signature,
            s.docstring,
            s.start_line,
            f.path,
            -- Rank by name match (higher weight) + signature match
            ts_rank_cd(to_tsvector('english', s.name || ' ' || COALESCE(s.signature, '')),
                       websearch_to_tsquery('english', $1)) as rank
        FROM symbol s
        JOIN file f ON s.file_id = f.id
        WHERE to_tsvector('english', s.name || ' ' || COALESCE(s.signature, ''))
              @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k)

    symbol_results = []
    for row in results:
        # Extract description from docstring (first line)
        docstring = row['docstring'] or ""
        description = docstring.split('\n')[0] if docstring else None
        if description and len(description) > 100:
            description = description[:100] + "..."

        symbol_results.append(SymbolResult(
            name=row['name'],
            kind=row['kind'],
            file_path=row['path'],
            line=row['start_line'],
            signature=row['signature'],
            description=description,
            relevance_score=float(row['rank'])
        ))

    return symbol_results


async def _search_summaries(
    conn: asyncpg.Connection,
    query: str,
    top_k: int = 3
) -> tuple[list[SummaryResult], list[SummaryResult], list[SummaryResult]]:
    """Search file, module, and symbol summaries using FTS.

    Args:
        conn: Database connection
        query: Search query
        top_k: Number of results per summary type

    Returns:
        Tuple of (file_summaries, module_summaries, symbol_summaries)
    """
    # Use OR logic for flexibility
    query_words = query.split()
    meaningful_words = [w for w in query_words if len(w) >= 3]
    if meaningful_words:
        or_query = " OR ".join(meaningful_words)
    else:
        or_query = query

    # Search file summaries
    file_summary_results = await conn.fetch("""
        SELECT
            fs.summary,
            f.path,
            ts_rank_cd(to_tsvector('english', fs.summary), websearch_to_tsquery('english', $1)) as rank
        FROM file_summary fs
        JOIN file f ON fs.file_id = f.id
        WHERE to_tsvector('english', fs.summary) @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k)

    file_summaries = [
        SummaryResult(
            summary_type="file",
            name=row['path'],
            summary=row['summary'],
            relevance_score=float(row['rank']),
            file_path=row['path']
        )
        for row in file_summary_results
    ]

    # Search module summaries
    module_summary_results = await conn.fetch("""
        SELECT
            ms.module_path,
            ms.summary,
            ts_rank_cd(to_tsvector('english', ms.summary), websearch_to_tsquery('english', $1)) as rank
        FROM module_summary ms
        WHERE to_tsvector('english', ms.summary) @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k)

    module_summaries = [
        SummaryResult(
            summary_type="module",
            name=row['module_path'],
            summary=row['summary'],
            relevance_score=float(row['rank'])
        )
        for row in module_summary_results
    ]

    # Search symbol summaries
    symbol_summary_results = await conn.fetch("""
        SELECT
            ss.summary,
            s.name,
            s.kind,
            f.path,
            ts_rank_cd(to_tsvector('english', ss.summary), websearch_to_tsquery('english', $1)) as rank
        FROM symbol_summary ss
        JOIN symbol s ON ss.symbol_id = s.id
        JOIN file f ON s.file_id = f.id
        WHERE to_tsvector('english', ss.summary) @@ websearch_to_tsquery('english', $1)
        ORDER BY rank DESC
        LIMIT $2
    """, or_query, top_k)

    symbol_summaries = [
        SummaryResult(
            summary_type="symbol",
            name=f"{row['kind']} {row['name']}",
            summary=row['summary'],
            relevance_score=float(row['rank']),
            file_path=row['path']
        )
        for row in symbol_summary_results
    ]

    return file_summaries, module_summaries, symbol_summaries


def _extract_key_files(
    docs: list[DocumentResult],
    code: list[CodeResult],
    symbols: list[SymbolResult]
) -> list[str]:
    """Extract and rank key files from all results.

    Args:
        docs: Documentation results
        code: Code results
        symbols: Symbol results

    Returns:
        List of file paths, ordered by relevance
    """
    file_scores = {}

    # Score from documentation (highest weight)
    for i, doc in enumerate(docs):
        score = doc.relevance_score * (len(docs) - i) * 3.0  # Higher weight for docs
        file_scores[doc.file_path] = file_scores.get(doc.file_path, 0) + score

    # Score from code results
    for i, code_file in enumerate(code):
        score = code_file.relevance_score * (len(code) - i) * 2.0
        file_scores[code_file.file_path] = file_scores.get(code_file.file_path, 0) + score

    # Score from symbols
    for i, sym in enumerate(symbols):
        score = sym.relevance_score * (len(symbols) - i) * 1.5
        file_scores[sym.file_path] = file_scores.get(sym.file_path, 0) + score

    # Sort by score descending
    sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
    return [f[0] for f in sorted_files]


async def _generate_summary(
    question: str,
    docs: list[DocumentResult],
    code: list[CodeResult],
    symbols: list[SymbolResult]
) -> str:
    """Generate LLM-based summary of findings.

    TODO: Integrate with Ollama/vLLM to generate natural language summary

    Args:
        question: Original question
        docs: Documentation results
        code: Code results
        symbols: Symbol results

    Returns:
        Natural language summary
    """
    # For now, return a structured text summary
    # Later: call LLM with context
    return _create_basic_summary(docs, code, symbols)


def _create_basic_summary(
    docs: list[DocumentResult],
    code: list[CodeResult],
    symbols: list[SymbolResult]
) -> str:
    """Create basic text summary without LLM.

    Args:
        docs: Documentation results
        code: Code results
        symbols: Symbol results

    Returns:
        Basic text summary
    """
    parts = []

    if docs:
        parts.append(f"Found {len(docs)} relevant documentation files")
    if code:
        parts.append(f"{len(code)} code files")
    if symbols:
        parts.append(f"{len(symbols)} relevant symbols (functions/classes)")

    if not parts:
        return "No relevant results found in the codebase."

    summary = "Found " + ", ".join(parts) + "."

    # Add top doc if available
    if docs:
        summary += f" Key documentation: {docs[0].title}"

    # Add top symbol if available
    if symbols:
        summary += f" Main implementation: {symbols[0].kind} {symbols[0].name}"

    return summary


def _suggest_actions(
    question: str,
    docs: list[DocumentResult],
    code: list[CodeResult],
    symbols: list[SymbolResult]
) -> list[str]:
    """Suggest next actions based on results.

    Args:
        question: Original question
        docs: Documentation results
        code: Code results
        symbols: Symbol results

    Returns:
        List of suggested action strings
    """
    suggestions = []

    if docs:
        suggestions.append(f"Read documentation: {docs[0].file_path}")

    if symbols:
        suggestions.append(f"Examine {symbols[0].kind}: {symbols[0].name} in {symbols[0].file_path}:{symbols[0].line}")

    if code and len(code) > 1:
        suggestions.append(f"Review implementation across {len(code)} files")

    if not (docs or code or symbols):
        suggestions.append("Try broadening your search query")

    return suggestions


def format_answer_for_display(answer: CodebaseAnswer) -> str:
    """Format CodebaseAnswer as human-readable text.

    Args:
        answer: CodebaseAnswer object

    Returns:
        Formatted text suitable for display
    """
    lines = []
    lines.append(f"# Question: {answer.question}")
    lines.append(f"Repository: {answer.repo_name}")
    lines.append(f"Total results: {answer.total_results_found}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append(answer.summary)
    lines.append("")

    # Documentation
    if answer.documentation:
        lines.append("## 📚 Documentation")
        for i, doc in enumerate(answer.documentation, 1):
            lines.append(f"\n### {i}. {doc.title}")
            lines.append(f"**File**: `{doc.file_path}`")
            lines.append(f"**Relevance**: {doc.relevance_score:.2f}")
            lines.append(f"\n{doc.summary}")

    # Code Files
    if answer.code_files:
        lines.append("\n## 💻 Code Files")
        for i, code in enumerate(answer.code_files, 1):
            lines.append(f"\n### {i}. {code.file_path}")
            lines.append(f"**Lines**: {code.line_range[0]}-{code.line_range[1]}")
            lines.append(f"**Language**: {code.language}")
            if code.context:
                lines.append(f"**Context**: {code.context}")
            lines.append(f"**Relevance**: {code.relevance_score:.2f}")
            lines.append(f"\n```{code.language}")
            lines.append(code.snippet)
            lines.append("```")

    # Symbols
    if answer.symbols:
        lines.append("\n## 🔧 Key Symbols")
        for i, sym in enumerate(answer.symbols, 1):
            lines.append(f"\n### {i}. {sym.name}")
            lines.append(f"**Type**: {sym.kind}")
            lines.append(f"**Location**: `{sym.file_path}:{sym.line}`")
            if sym.signature:
                lines.append(f"**Signature**: `{sym.signature}`")
            if sym.description:
                lines.append(f"**Description**: {sym.description}")
            lines.append(f"**Relevance**: {sym.relevance_score:.2f}")

    # File Summaries
    if answer.file_summaries:
        lines.append("\n## 📄 File Summaries")
        for i, fs in enumerate(answer.file_summaries, 1):
            lines.append(f"\n### {i}. {fs.name}")
            lines.append(f"**Relevance**: {fs.relevance_score:.2f}")
            lines.append(f"\n{fs.summary}")

    # Module Summaries
    if answer.module_summaries:
        lines.append("\n## 📁 Module Summaries")
        for i, ms in enumerate(answer.module_summaries, 1):
            lines.append(f"\n### {i}. {ms.name}")
            lines.append(f"**Relevance**: {ms.relevance_score:.2f}")
            lines.append(f"\n{ms.summary}")

    # Symbol Summaries
    if answer.symbol_summaries:
        lines.append("\n## 🔍 Symbol Summaries")
        for i, ss in enumerate(answer.symbol_summaries, 1):
            lines.append(f"\n### {i}. {ss.name}")
            if ss.file_path:
                lines.append(f"**Location**: `{ss.file_path}`")
            lines.append(f"**Type**: {ss.summary_type}")
            lines.append(f"**Relevance**: {ss.relevance_score:.2f}")
            lines.append(f"\n{ss.summary}")

    # Key Files
    if answer.key_files:
        lines.append("\n## 📁 Key Files to Examine")
        for file in answer.key_files[:5]:  # Top 5
            lines.append(f"- `{file}`")

    # Suggested Actions
    if answer.suggested_actions:
        lines.append("\n## 🎯 Suggested Next Steps")
        for action in answer.suggested_actions:
            lines.append(f"- {action}")

    return "\n".join(lines)
