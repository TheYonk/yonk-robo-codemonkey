"""vLLM OpenAI-compatible embeddings client.

Provides embedding generation via vLLM's OpenAI-compatible /v1/embeddings endpoint.
"""
from __future__ import annotations
import httpx


async def vllm_embed(
    texts: list[str],
    model: str,
    base_url: str,
    api_key: str,
    batch_size: int = 32
) -> list[list[float]]:
    """Generate embeddings using vLLM (OpenAI-compatible API).

    Args:
        texts: List of texts to embed
        model: Model name
        base_url: vLLM base URL
        api_key: API key for authentication
        batch_size: Maximum texts per request

    Returns:
        List of embedding vectors

    Raises:
        httpx.HTTPError: If API request fails
    """
    if not texts:
        return []

    all_embeddings: list[list[float]] = []

    # Build headers - only add Authorization if api_key is provided
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Process in batches
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            try:
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/embeddings",
                    headers=headers,
                    json={"model": model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()

                # Extract embeddings in order
                batch_embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(batch_embeddings)

            except httpx.HTTPError as e:
                raise RuntimeError(f"vLLM embedding failed: {e}")

    return all_embeddings
