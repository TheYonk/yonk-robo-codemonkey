# Local Embedding Service

Lightweight CPU-based embedding service using sentence-transformers. Provides an OpenAI-compatible API for generating embeddings without requiring Ollama or external services.

## Models

| Model | Dimensions | Size | Use Case |
|-------|------------|------|----------|
| `all-MiniLM-L6-v2` | 384 | ~80MB | Fast, good for development |
| `all-mpnet-base-v2` | 768 | ~420MB | Better quality, good for production |

## Running with Docker

```bash
# Build
docker build -t robomonkey-embeddings ./embedding-service

# Run
docker run -d -p 8082:8082 --name robomonkey-embeddings robomonkey-embeddings
```

## Running Locally

```bash
cd embedding-service
pip install -r requirements.txt
python main.py
```

## API Endpoints

### Health Check
```bash
curl http://localhost:8082/health
```

### List Models
```bash
curl http://localhost:8082/v1/models
```

### Generate Embeddings
```bash
curl -X POST http://localhost:8082/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "model": "all-MiniLM-L6-v2"}'
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PORT` | 8082 | Port to listen on |
| `DEFAULT_EMBEDDING_MODEL` | all-MiniLM-L6-v2 | Default model if not specified |
| `TRANSFORMERS_CACHE` | /models | Model cache directory |

## Integration with RoboMonkey

Configure in `.env`:
```env
EMBEDDINGS_PROVIDER=openai
EMBEDDINGS_MODEL=all-MiniLM-L6-v2
EMBEDDINGS_BASE_URL=http://localhost:8082
EMBEDDINGS_DIMENSION=384
```

Or in daemon config:
```yaml
embeddings:
  provider: "openai"
  model: "all-MiniLM-L6-v2"
  dimension: 384
  ollama:
    base_url: "http://localhost:8082"
```
