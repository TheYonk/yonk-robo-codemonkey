"""Summary generator using local LLMs.

Generates file, symbol, and module summaries using Ollama or vLLM.
"""
from __future__ import annotations
import httpx
import asyncpg
from dataclasses import dataclass


@dataclass
class SummaryResult:
    """Result of a summary generation."""
    summary: str
    success: bool
    error: str | None = None


async def generate_file_summary(
    file_id: str,
    database_url: str,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2:3b",
    llm_base_url: str = "http://localhost:11434",
    schema_name: str | None = None
) -> SummaryResult:
    """Generate a summary for a file.

    Args:
        file_id: File UUID
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: Base URL for LLM endpoint
        schema_name: Schema name to use (if None, uses default)

    Returns:
        SummaryResult with generated summary
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get file content and metadata
        row = await conn.fetchrow(
            """
            SELECT f.path, f.language, STRING_AGG(c.content, E'\n\n') as full_content
            FROM file f
            LEFT JOIN chunk c ON c.file_id = f.id
            WHERE f.id = $1
            GROUP BY f.id, f.path, f.language
            """,
            file_id
        )

        if not row:
            return SummaryResult(summary="", success=False, error="File not found")

        file_path = row["path"]
        language = row["language"]
        content = row["full_content"] or ""

        # Truncate content if too long (approx 3000 tokens = 12000 chars)
        if len(content) > 12000:
            content = content[:12000] + "\n... (truncated)"

        # Generate summary using LLM
        prompt = f"""Summarize this {language} file ({file_path}) in 2-3 sentences. Focus on what the code does and its main responsibilities.

Content:
{content}

Summary:"""

        summary = await _call_llm(
            prompt=prompt,
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url
        )

        if summary:
            return SummaryResult(summary=summary.strip(), success=True)
        else:
            return SummaryResult(summary="", success=False, error="LLM returned empty response")

    finally:
        await conn.close()


async def generate_symbol_summary(
    symbol_id: str,
    database_url: str,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2:3b",
    llm_base_url: str = "http://localhost:11434",
    schema_name: str | None = None
) -> SummaryResult:
    """Generate a summary for a symbol.

    Args:
        symbol_id: Symbol UUID
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: Base URL for LLM endpoint
        schema_name: Schema name to use (if None, uses default)

    Returns:
        SummaryResult with generated summary
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get symbol content
        row = await conn.fetchrow(
            """
            SELECT s.fqn, s.name, s.kind, s.signature, s.docstring, c.content
            FROM symbol s
            LEFT JOIN chunk c ON c.symbol_id = s.id
            WHERE s.id = $1
            ORDER BY c.start_line
            LIMIT 1
            """,
            symbol_id
        )

        if not row:
            return SummaryResult(summary="", success=False, error="Symbol not found")

        fqn = row["fqn"]
        kind = row["kind"]
        signature = row["signature"] or ""
        docstring = row["docstring"] or ""
        content = row["content"] or ""

        # Truncate content if too long
        if len(content) > 6000:
            content = content[:6000] + "\n... (truncated)"

        # Generate summary using LLM
        prompt = f"""Summarize this {kind} ({fqn}) in 1-2 sentences. Focus on what it does and its purpose.

Signature: {signature}
Docstring: {docstring}

Code:
{content}

Summary:"""

        summary = await _call_llm(
            prompt=prompt,
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url
        )

        if summary:
            return SummaryResult(summary=summary.strip(), success=True)
        else:
            return SummaryResult(summary="", success=False, error="LLM returned empty response")

    finally:
        await conn.close()


async def generate_module_summary(
    repo_id: str,
    module_path: str,
    database_url: str,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2:3b",
    llm_base_url: str = "http://localhost:11434",
    schema_name: str | None = None
) -> SummaryResult:
    """Generate a summary for a module/directory.

    Args:
        repo_id: Repository UUID
        module_path: Module path (e.g. "src/api")
        database_url: Database connection string
        llm_provider: LLM provider ('ollama' or 'vllm')
        llm_model: Model name
        llm_base_url: Base URL for LLM endpoint
        schema_name: Schema name to use (if None, uses default)

    Returns:
        SummaryResult with generated summary
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search_path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get files in module
        rows = await conn.fetch(
            """
            SELECT path, language
            FROM file
            WHERE repo_id = $1 AND path LIKE $2
            ORDER BY path
            LIMIT 20
            """,
            repo_id, f"{module_path}%"
        )

        if not rows:
            return SummaryResult(summary="", success=False, error="No files found in module")

        file_list = "\n".join(f"- {row['path']} ({row['language']})" for row in rows)

        # Generate summary using LLM
        prompt = f"""Summarize this module/directory ({module_path}) in 2-3 sentences. Focus on the overall purpose and organization.

Files in module:
{file_list}

Summary:"""

        summary = await _call_llm(
            prompt=prompt,
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url
        )

        if summary:
            return SummaryResult(summary=summary.strip(), success=True)
        else:
            return SummaryResult(summary="", success=False, error="LLM returned empty response")

    finally:
        await conn.close()


async def _call_llm(
    prompt: str,
    provider: str,
    model: str,
    base_url: str
) -> str | None:
    """Call LLM to generate text.

    Args:
        prompt: Prompt to send to LLM
        provider: LLM provider ('ollama' or 'vllm')
        model: Model name
        base_url: Base URL for LLM endpoint

    Returns:
        Generated text or None on error
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if provider == "ollama":
                # Ollama generate API
                response = await client.post(
                    f"{base_url.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 200
                        }
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "")

            elif provider == "vllm":
                # vLLM OpenAI-compatible completions API
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/completions",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "max_tokens": 200,
                        "temperature": 0.3
                    }
                )
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("text", "")
                return None

            else:
                return None

    except Exception as e:
        print(f"LLM call failed: {e}")
        return None
