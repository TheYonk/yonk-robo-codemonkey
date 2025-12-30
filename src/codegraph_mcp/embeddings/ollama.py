"""Ollama embeddings client.

Provides embedding generation via Ollama's /api/embeddings endpoint.
"""
from __future__ import annotations
import httpx
from typing import List


async def ollama_embed(
    texts: list[str],
    model: str,
    base_url: str,
    batch_size: int = 1
) -> list[list[float]]:
    """Generate embeddings using Ollama.

    Args:
        texts: List of texts to embed
        model: Model name (e.g., "nomic-embed-text")
        base_url: Ollama base URL
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
        for text in texts:
            try:
                response = await client.post(
                    f"{base_url.rstrip('/')}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["embedding"])

            except httpx.HTTPError as e:
                raise RuntimeError(f"Ollama embedding failed: {e}")

    return embeddings
