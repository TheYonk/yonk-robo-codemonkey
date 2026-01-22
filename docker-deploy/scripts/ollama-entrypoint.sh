#!/bin/bash
# Ollama entrypoint script
# Starts Ollama server and pulls required models

set -e

# Models to pull (passed via environment variables)
EMBEDDINGS_MODEL="${EMBEDDINGS_MODEL:-snowflake-arctic-embed2:latest}"
LLM_MODEL="${LLM_MODEL:-}"

echo "Starting Ollama server..."
# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "ERROR: Ollama failed to start after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "  Waiting... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done
echo "Ollama is ready!"

# Pull embedding model
if [ -n "$EMBEDDINGS_MODEL" ]; then
    echo "Pulling embeddings model: $EMBEDDINGS_MODEL"
    if ollama pull "$EMBEDDINGS_MODEL"; then
        echo "Successfully pulled $EMBEDDINGS_MODEL"
    else
        echo "WARNING: Failed to pull $EMBEDDINGS_MODEL"
    fi
fi

# Pull LLM model if specified
if [ -n "$LLM_MODEL" ]; then
    echo "Pulling LLM model: $LLM_MODEL"
    if ollama pull "$LLM_MODEL"; then
        echo "Successfully pulled $LLM_MODEL"
    else
        echo "WARNING: Failed to pull $LLM_MODEL"
    fi
fi

echo "Model setup complete. Ollama is running."

# Wait for Ollama process to keep container alive
wait $OLLAMA_PID
