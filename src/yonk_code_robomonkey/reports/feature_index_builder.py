"""Feature index builder.

Builds and maintains a searchable index of features/concepts from:
- Tag distribution
- Module and file summaries
- Documentation headings
- Symbol clusters
"""
from __future__ import annotations
from typing import Any
from collections import defaultdict
import asyncpg
import re
from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema, schema_context


async def build_feature_index(
    repo_id: str,
    database_url: str,
    regenerate: bool = False
) -> dict[str, Any]:
    """Build or update feature index for a repository.

    Args:
        repo_id: Repository UUID
        database_url: Database connection string
        regenerate: Force regeneration even if exists

    Returns:
        Stats about features indexed
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Resolve repo_id to schema
        try:
            resolved_repo_id, schema_name = await resolve_repo_to_schema(conn, repo_id)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo_id}",
                "why": str(e)
            }

        # Use the resolved repo_id (in case a name was passed)
        repo_id = resolved_repo_id

        async with schema_context(conn, schema_name):
            # Check if index exists
            if not regenerate:
                existing_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM feature_index WHERE repo_id = $1",
                    repo_id
                )

                if existing_count > 0:
                    return {
                        "success": True,
                        "features_count": existing_count,
                        "regenerated": False,
                        "why": "Feature index already exists. Use regenerate=true to rebuild."
                    }

            # Delete existing features if regenerating
            if regenerate:
                await conn.execute(
                    "DELETE FROM feature_index WHERE repo_id = $1",
                    repo_id
                )

            features = []

            # 1. Extract features from tags
            tag_features = await _extract_from_tags(conn, repo_id)
            features.extend(tag_features)

            # 2. Extract features from module summaries
            module_features = await _extract_from_modules(conn, repo_id)
            features.extend(module_features)

            # 3. Extract features from documentation headings
            doc_features = await _extract_from_docs(conn, repo_id)
            features.extend(doc_features)

            # 4. Deduplicate and merge features
            merged_features = _merge_features(features)

            # 5. Insert features
            for feature in merged_features:
                await conn.execute(
                    """
                    INSERT INTO feature_index (repo_id, name, description, evidence, source)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (repo_id, name) DO UPDATE SET
                        description = EXCLUDED.description,
                        evidence = EXCLUDED.evidence,
                        source = EXCLUDED.source,
                        updated_at = now()
                    """,
                    repo_id,
                    feature["name"],
                    feature["description"],
                    feature["evidence"],
                    feature["source"]
                )

        return {
            "success": True,
            "features_count": len(merged_features),
            "regenerated": regenerate,
            "sources": {
                "tags": len(tag_features),
                "modules": len(module_features),
                "docs": len(doc_features)
            }
        }

    finally:
        await conn.close()


async def _extract_from_tags(
    conn: asyncpg.Connection,
    repo_id: str
) -> list[dict[str, Any]]:
    """Extract features from tag distribution."""
    tags = await conn.fetch(
        """
        SELECT t.name, t.description, COUNT(DISTINCT et.entity_id) as usage_count,
               ARRAY_AGG(DISTINCT et.entity_type) as entity_types
        FROM entity_tag et
        JOIN tag t ON t.id = et.tag_id
        WHERE et.repo_id = $1
        GROUP BY t.id, t.name, t.description
        HAVING COUNT(DISTINCT et.entity_id) >= 3
        ORDER BY usage_count DESC
        """,
        repo_id
    )

    features = []
    for tag in tags:
        # Get sample files
        sample_files = await conn.fetch(
            """
            SELECT f.path
            FROM entity_tag et
            JOIN tag t ON t.id = et.tag_id
            JOIN file f ON f.id = et.entity_id
            WHERE et.repo_id = $1 AND et.entity_type = 'file' AND t.name = $2
            LIMIT 10
            """,
            repo_id, tag["name"]
        )

        features.append({
            "name": tag["name"],
            "description": tag["description"] or f"Files and symbols tagged with '{tag['name']}'",
            "evidence": {
                "tag": tag["name"],
                "usage_count": tag["usage_count"],
                "entity_types": tag["entity_types"],
                "sample_files": [f["path"] for f in sample_files]
            },
            "source": "GENERATED"
        })

    return features


async def _extract_from_modules(
    conn: asyncpg.Connection,
    repo_id: str
) -> list[dict[str, Any]]:
    """Extract features from module summaries."""
    modules = await conn.fetch(
        """
        SELECT module_path, summary
        FROM module_summary
        WHERE repo_id = $1
        ORDER BY module_path
        """,
        repo_id
    )

    features = []
    for module in modules:
        module_path = module["module_path"]
        summary = module["summary"]

        # Extract module name (last component)
        module_name = module_path.split("/")[-1] if "/" in module_path else module_path

        # Get files in this module
        file_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM file
            WHERE repo_id = $1 AND path LIKE $2
            """,
            repo_id, f"{module_path}%"
        )

        if file_count >= 2:  # Only include modules with multiple files
            features.append({
                "name": module_name,
                "description": summary or f"Module: {module_path}",
                "evidence": {
                    "module_path": module_path,
                    "file_count": file_count,
                    "summary": summary
                },
                "source": "GENERATED"
            })

    return features


async def _extract_from_docs(
    conn: asyncpg.Connection,
    repo_id: str
) -> list[dict[str, Any]]:
    """Extract features from documentation headings."""
    docs = await conn.fetch(
        """
        SELECT path, title, content
        FROM document
        WHERE repo_id = $1 AND type = 'DOC_FILE'
        ORDER BY path
        """,
        repo_id
    )

    features = []
    for doc in docs:
        # Extract headings from markdown
        headings = _extract_headings(doc["content"])

        for heading in headings[:10]:  # Top 10 headings per doc
            # Clean heading text
            clean_heading = re.sub(r'[^\w\s-]', '', heading).strip()

            if len(clean_heading) < 3 or len(clean_heading) > 50:
                continue

            features.append({
                "name": clean_heading.lower(),
                "description": f"Topic from documentation: {doc['path']}",
                "evidence": {
                    "doc_path": doc["path"],
                    "heading": heading,
                    "doc_title": doc["title"]
                },
                "source": "GENERATED"
            })

    return features


def _extract_headings(content: str) -> list[str]:
    """Extract headings from markdown content."""
    headings = []

    # Match markdown headings (## Heading)
    for match in re.finditer(r'^#{1,6}\s+(.+)$', content, re.MULTILINE):
        headings.append(match.group(1).strip())

    return headings


def _merge_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate features by name."""
    feature_map = {}

    for feature in features:
        name = feature["name"].lower()

        if name in feature_map:
            # Merge evidence
            existing = feature_map[name]

            # Combine descriptions (prefer longer one)
            if len(feature["description"]) > len(existing["description"]):
                existing["description"] = feature["description"]

            # Merge evidence arrays
            for key, value in feature["evidence"].items():
                if key not in existing["evidence"]:
                    existing["evidence"][key] = value
                elif isinstance(value, list) and isinstance(existing["evidence"][key], list):
                    existing["evidence"][key].extend(value)
        else:
            feature_map[name] = feature

    return list(feature_map.values())
