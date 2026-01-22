"""Pre-download models for offline use during Docker build"""
from sentence_transformers import SentenceTransformer
import os

CACHE_DIR = os.environ.get("TRANSFORMERS_CACHE", "/models")

models = [
    "all-MiniLM-L6-v2",    # 384 dimensions, ~80MB, fast
    "all-mpnet-base-v2"    # 768 dimensions, ~420MB, better quality
]

for model_name in models:
    print(f"Downloading {model_name}...")
    SentenceTransformer(model_name, cache_folder=CACHE_DIR)
    print(f"Downloaded {model_name}")

print("All models downloaded successfully")
