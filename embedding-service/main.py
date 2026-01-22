"""
Local Sentence-Transformers Embedding Service
OpenAI-compatible API for local embeddings

Lightweight alternative to Ollama/vLLM for CPU-based embedding generation.
Models are small and fast, suitable for development and small-scale deployments.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Union
from sentence_transformers import SentenceTransformer
import uvicorn
import os
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RoboMonkey Local Embedding Service",
    version="1.0.0",
    description="Lightweight CPU-based embedding service using sentence-transformers"
)

# Model configuration
# all-MiniLM-L6-v2: Fast, small (80MB), 384 dimensions - good for development
# all-mpnet-base-v2: Better quality (420MB), 768 dimensions - good for production
MODELS = {
    "all-MiniLM-L6-v2": {"dimension": 384, "model": None},
    "all-mpnet-base-v2": {"dimension": 768, "model": None}
}

DEFAULT_MODEL = os.environ.get("DEFAULT_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
MODELS_LOADED = False


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = DEFAULT_MODEL


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: dict


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[dict]


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
    available_models: List[str]
    default_model: str


def load_models():
    """Pre-load all models into memory"""
    global MODELS_LOADED
    cache_dir = os.environ.get("TRANSFORMERS_CACHE", "/models")

    logger.info(f"Loading models from cache: {cache_dir}")

    for model_name in MODELS:
        logger.info(f"Loading model: {model_name}")
        start = time.time()
        MODELS[model_name]["model"] = SentenceTransformer(
            model_name,
            cache_folder=cache_dir
        )
        elapsed = time.time() - start
        logger.info(f"Model {model_name} loaded in {elapsed:.2f}s")

    MODELS_LOADED = True
    logger.info("All models loaded successfully")


@app.on_event("startup")
async def startup_event():
    """Load models on startup"""
    load_models()


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy" if MODELS_LOADED else "loading",
        models_loaded=MODELS_LOADED,
        available_models=list(MODELS.keys()),
        default_model=DEFAULT_MODEL
    )


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """List available models (OpenAI-compatible)"""
    return ModelsResponse(
        data=[
            {
                "id": name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "local",
                "permission": [],
                "root": name,
                "parent": None,
                "dimension": info["dimension"]
            }
            for name, info in MODELS.items()
        ]
    )


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embedding(request: EmbeddingRequest):
    """Create embeddings (OpenAI-compatible API)"""
    if not MODELS_LOADED:
        raise HTTPException(status_code=503, detail="Models still loading")

    model_name = request.model
    if model_name not in MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model_name}. Available: {list(MODELS.keys())}"
        )

    model = MODELS[model_name]["model"]

    # Normalize input to list
    texts = [request.input] if isinstance(request.input, str) else request.input

    # Generate embeddings
    start = time.time()
    embeddings = model.encode(texts, convert_to_numpy=True)
    elapsed = time.time() - start

    logger.debug(f"Generated {len(texts)} embeddings in {elapsed:.3f}s")

    # Build response
    data = [
        EmbeddingData(
            embedding=emb.tolist(),
            index=i
        )
        for i, emb in enumerate(embeddings)
    ]

    return EmbeddingResponse(
        data=data,
        model=model_name,
        usage={
            "prompt_tokens": sum(len(t.split()) for t in texts),
            "total_tokens": sum(len(t.split()) for t in texts)
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("EMBEDDING_PORT", 8082))
    logger.info(f"Starting embedding service on port {port}")
    logger.info(f"Default model: {DEFAULT_MODEL}")
    uvicorn.run(app, host="0.0.0.0", port=port)
