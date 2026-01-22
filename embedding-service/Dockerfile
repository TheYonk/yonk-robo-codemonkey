FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first (smaller image)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create model cache directory
RUN mkdir -p /models
ENV TRANSFORMERS_CACHE=/models

# Pre-download models during build
COPY download_models.py .
RUN python download_models.py

# Copy application code
COPY main.py .

EXPOSE 8082

ENV EMBEDDING_PORT=8082
ENV DEFAULT_EMBEDDING_MODEL=all-MiniLM-L6-v2

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8082/health')" || exit 1

CMD ["python", "main.py"]
