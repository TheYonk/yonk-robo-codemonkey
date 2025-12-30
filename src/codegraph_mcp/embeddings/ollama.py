import httpx
from codegraph_mcp.config import settings

async def ollama_embed(texts: list[str]) -> list[list[float]]:
    # Ollama supports POST /api/embeddings with {model, prompt}
    # We'll call once per text for now; batch later.
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for t in texts:
            r = await client.post(
                f"{settings.embeddings_base_url.rstrip('/')}/api/embeddings",
                json={"model": settings.embeddings_model, "prompt": t},
            )
            r.raise_for_status()
            data = r.json()
            out.append(data["embedding"])
    return out
