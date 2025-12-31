#!/usr/bin/env python3
"""
Direct embedding script for schema-aware repositories.

Usage:
    python scripts/embed_repo_direct.py <repo_name> <schema_name>

Example:
    python scripts/embed_repo_direct.py pg_go_app codegraph_pg_go_app
"""
import asyncio
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonk_code_robomonkey.embeddings.embedder import embed_repo


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/embed_repo_direct.py <repo_name> <schema_name>")
        print("Example: python scripts/embed_repo_direct.py pg_go_app codegraph_pg_go_app")
        sys.exit(1)

    repo_name = sys.argv[1]
    schema_name = sys.argv[2]

    print(f"Starting embeddings for {repo_name} (schema: {schema_name})")
    print("=" * 60)

    # Import settings to show configuration
    from yonk_code_robomonkey.config import settings
    print(f"Using model: {settings.embeddings_model}")
    print(f"Max chunk length: {settings.max_chunk_length} chars")
    print(f"Batch size: {settings.embedding_batch_size}")
    print(f"Embedding dimensions: {settings.embeddings_dimension}")
    print("=" * 60)

    try:
        stats = await embed_repo(
            repo_name=repo_name,
            schema_name=schema_name,
            only_missing=True
            # All other settings use config defaults
        )

        print("\n" + "=" * 60)
        print("EMBEDDINGS COMPLETE!")
        print(f"  Chunks embedded: {stats['chunks_embedded']}")
        print(f"  Chunks skipped: {stats['chunks_skipped']}")
        print(f"  Docs embedded: {stats['docs_embedded']}")
        print(f"  Docs skipped: {stats['docs_skipped']}")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
