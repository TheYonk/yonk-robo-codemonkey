import httpx
from codegraph_mcp.config import settings

async def vllm_embed(texts: list[str]) -> list[list[float]]:
    # OpenAI-compatible: POST /v1/embeddings with {model, input}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{settings.vllm_base_url.rstrip('/')}/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            json={"model": settings.embeddings_model, "input": texts},
        )
        r.raise_for_status()
        data = r.json()
        # data["data"] is list with "embedding"
        return [row["embedding"] for row in data["data"]]
