"""Ollama embeddings client.

Provides embedding generation via Ollama's /api/embeddings endpoint.
"""
from __future__ import annotations
import asyncio
import httpx
import logging
from typing import List

logger = logging.getLogger(__name__)


async def ollama_embed(
    texts: list[str],
    model: str,
    base_url: str,
    embedding_dim: int = 1024,
    batch_size: int = 1
) -> list[list[float]]:
    """Generate embeddings using Ollama.

    Args:
        texts: List of texts to embed
        model: Model name (e.g., "snowflake-arctic-embed2:latest")
        base_url: Ollama base URL
        embedding_dim: Embedding dimension (default 1024 for snowflake-arctic-embed2)
        batch_size: Number of texts per request (Ollama processes one at a time)

    Returns:
        List of embedding vectors

    Raises:
        httpx.HTTPError: If API request fails
    """
    if not texts:
        return []

    embeddings: list[list[float]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Ollama API processes one text at a time
        for idx, text in enumerate(texts):
            text_len = len(text)
            text_preview = text[:200] + "..." if len(text) > 200 else text

            logger.debug(f"Embedding text {idx+1}/{len(texts)}: length={text_len}, preview={text_preview!r}")

            # Try with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await client.post(
                        f"{base_url.rstrip('/')}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings.append(data["embedding"])
                    break  # Success, move to next text

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 500 and attempt == max_retries - 1:
                        # Ollama 500 error - skip this text with zero embedding
                        logger.warning(f"Skipping text {idx+1}/{len(texts)} after {max_retries} attempts (len={text_len}): {e}")
                        logger.warning(f"Text preview: {text_preview!r}")
                        # Return zero vector as placeholder
                        embeddings.append([0.0] * embedding_dim)
                        break
                    elif attempt < max_retries - 1:
                        # Retry with exponential backoff
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise

                except httpx.HTTPError as e:
                    error_msg = f"Ollama embedding failed for text {idx+1}/{len(texts)} (len={text_len}): {e}"
                    logger.error(f"{error_msg}\nText preview: {text_preview!r}")
                    raise RuntimeError(error_msg)

    return embeddings
