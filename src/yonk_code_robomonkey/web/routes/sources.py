"""Source mount management API routes.

Manages host directory mounts for Docker containers. When RoboMonkey runs in Docker,
this allows mapping host machine directories into the container for indexing.
"""
from __future__ import annotations

import asyncpg
import os
import re
import subprocess
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import Any, Optional

from yonk_code_robomonkey.config import Settings

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateSourceMountRequest(BaseModel):
    """Request to add a new source mount."""
    mount_name: str
    host_path: str
    read_only: bool = True
    enabled: bool = True

    @field_validator('mount_name')
    @classmethod
    def validate_mount_name(cls, v: str) -> str:
        if not v or len(v) < 1:
            raise ValueError('Mount name cannot be empty')
        if len(v) > 100:
            raise ValueError('Mount name too long (max 100 chars)')
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', v):
            raise ValueError('Mount name must start with alphanumeric and contain only alphanumeric, dash, underscore, or dot')
        return v

    @field_validator('host_path')
    @classmethod
    def validate_host_path(cls, v: str) -> str:
        if not v:
            raise ValueError('Host path cannot be empty')
        if not v.startswith('/'):
            raise ValueError('Host path must be absolute (start with /)')
        return v


class UpdateSourceMountRequest(BaseModel):
    """Request to update a source mount."""
    host_path: Optional[str] = None
    read_only: Optional[bool] = None
    enabled: Optional[bool] = None


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/sources")
async def list_source_mounts() -> dict[str, Any]:
    """List all source mounts."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if source_mounts table exists
        has_table = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_control'
                  AND table_name = 'source_mounts'
            )
        """)

        if not has_table:
            return {
                "enabled": False,
                "message": "Source mounts not configured. Run migration 003_add_source_mounts.sql",
                "mounts": []
            }

        mounts = await conn.fetch("""
            SELECT
                id, mount_name, host_path, container_path,
                read_only, enabled, created_at, updated_at
            FROM robomonkey_control.source_mounts
            ORDER BY mount_name
        """)

        return {
            "enabled": True,
            "count": len(mounts),
            "mounts": [
                {
                    "id": str(m["id"]),
                    "mount_name": m["mount_name"],
                    "host_path": m["host_path"],
                    "container_path": m["container_path"],
                    "read_only": m["read_only"],
                    "enabled": m["enabled"],
                    "created_at": m["created_at"].isoformat() if m["created_at"] else None,
                    "updated_at": m["updated_at"].isoformat() if m["updated_at"] else None
                }
                for m in mounts
            ]
        }

    finally:
        await conn.close()


@router.post("/sources")
async def create_source_mount(request: CreateSourceMountRequest) -> dict[str, Any]:
    """Add a new source mount mapping."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if mount_name already exists
        existing = await conn.fetchval("""
            SELECT mount_name FROM robomonkey_control.source_mounts WHERE mount_name = $1
        """, request.mount_name)

        if existing:
            raise HTTPException(status_code=409, detail=f"Mount '{request.mount_name}' already exists")

        # Generate container path
        container_path = f"/sources/{request.mount_name}"

        # Insert the mount
        mount_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.source_mounts
                (mount_name, host_path, container_path, read_only, enabled)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, request.mount_name, request.host_path, container_path,
            request.read_only, request.enabled)

        return {
            "status": "created",
            "id": str(mount_id),
            "mount_name": request.mount_name,
            "host_path": request.host_path,
            "container_path": container_path,
            "message": f"Source mount '{request.mount_name}' created. Run 'Apply Changes' to update Docker."
        }

    finally:
        await conn.close()


@router.get("/sources/{mount_name}")
async def get_source_mount(mount_name: str) -> dict[str, Any]:
    """Get details for a specific source mount."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        mount = await conn.fetchrow("""
            SELECT
                id, mount_name, host_path, container_path,
                read_only, enabled, created_at, updated_at
            FROM robomonkey_control.source_mounts
            WHERE mount_name = $1
        """, mount_name)

        if not mount:
            raise HTTPException(status_code=404, detail=f"Source mount '{mount_name}' not found")

        return {
            "id": str(mount["id"]),
            "mount_name": mount["mount_name"],
            "host_path": mount["host_path"],
            "container_path": mount["container_path"],
            "read_only": mount["read_only"],
            "enabled": mount["enabled"],
            "created_at": mount["created_at"].isoformat() if mount["created_at"] else None,
            "updated_at": mount["updated_at"].isoformat() if mount["updated_at"] else None
        }

    finally:
        await conn.close()


@router.put("/sources/{mount_name}")
async def update_source_mount(mount_name: str, request: UpdateSourceMountRequest) -> dict[str, Any]:
    """Update a source mount."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check exists
        existing = await conn.fetchrow("""
            SELECT id FROM robomonkey_control.source_mounts WHERE mount_name = $1
        """, mount_name)

        if not existing:
            raise HTTPException(status_code=404, detail=f"Source mount '{mount_name}' not found")

        # Build update query dynamically
        updates = []
        params = []
        param_idx = 1

        if request.host_path is not None:
            updates.append(f"host_path = ${param_idx}")
            params.append(request.host_path)
            param_idx += 1

        if request.read_only is not None:
            updates.append(f"read_only = ${param_idx}")
            params.append(request.read_only)
            param_idx += 1

        if request.enabled is not None:
            updates.append(f"enabled = ${param_idx}")
            params.append(request.enabled)
            param_idx += 1

        if not updates:
            return {"status": "unchanged", "mount_name": mount_name, "message": "No changes provided"}

        params.append(mount_name)

        query = f"""
            UPDATE robomonkey_control.source_mounts
            SET {', '.join(updates)}, updated_at = now()
            WHERE mount_name = ${param_idx}
        """

        await conn.execute(query, *params)

        return {
            "status": "updated",
            "mount_name": mount_name,
            "message": f"Source mount '{mount_name}' updated. Run 'Apply Changes' to update Docker."
        }

    finally:
        await conn.close()


@router.delete("/sources/{mount_name}")
async def delete_source_mount(mount_name: str) -> dict[str, Any]:
    """Delete a source mount."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check exists
        existing = await conn.fetchrow("""
            SELECT id, host_path FROM robomonkey_control.source_mounts WHERE mount_name = $1
        """, mount_name)

        if not existing:
            raise HTTPException(status_code=404, detail=f"Source mount '{mount_name}' not found")

        # Delete the mount
        await conn.execute("""
            DELETE FROM robomonkey_control.source_mounts WHERE mount_name = $1
        """, mount_name)

        return {
            "status": "deleted",
            "mount_name": mount_name,
            "message": f"Source mount '{mount_name}' deleted. Run 'Apply Changes' to update Docker."
        }

    finally:
        await conn.close()


@router.post("/sources/apply")
async def apply_source_mounts() -> dict[str, Any]:
    """Regenerate docker-compose.yml with current mounts and restart containers.

    This will:
    1. Generate new docker-compose.yml with all enabled source mounts
    2. Stop running containers
    3. Start containers with new mounts
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all enabled mounts
        mounts = await conn.fetch("""
            SELECT mount_name, host_path, container_path, read_only
            FROM robomonkey_control.source_mounts
            WHERE enabled = true
            ORDER BY mount_name
        """)

        mount_list = [
            {
                "mount_name": m["mount_name"],
                "host_path": m["host_path"],
                "container_path": m["container_path"],
                "read_only": m["read_only"]
            }
            for m in mounts
        ]

    finally:
        await conn.close()

    # Find project root and scripts
    project_root = Path(__file__).parent.parent.parent.parent.parent
    regenerate_script = project_root / "scripts" / "regenerate-compose.sh"

    # Check if regenerate script exists
    if not regenerate_script.exists():
        raise HTTPException(
            status_code=500,
            detail="regenerate-compose.sh script not found. Source mounts require Docker mode."
        )

    try:
        # Run the regenerate script
        result = subprocess.run(
            [str(regenerate_script)],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=120
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to apply mounts: {result.stderr}"
            )

        return {
            "status": "applied",
            "mounts_applied": len(mount_list),
            "mounts": mount_list,
            "message": f"Applied {len(mount_list)} source mount(s). Containers restarted.",
            "output": result.stdout
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="Timeout while applying mounts. Check container status manually."
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="Could not execute regenerate script. Ensure bash is available."
        )


@router.get("/sources/status")
async def get_mount_status() -> dict[str, Any]:
    """Get current mount status - what's configured vs what's actually mounted."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get configured mounts from DB
        db_mounts = await conn.fetch("""
            SELECT mount_name, host_path, container_path, enabled
            FROM robomonkey_control.source_mounts
            ORDER BY mount_name
        """)

        configured = [
            {
                "mount_name": m["mount_name"],
                "host_path": m["host_path"],
                "container_path": m["container_path"],
                "enabled": m["enabled"]
            }
            for m in db_mounts
        ]

    finally:
        await conn.close()

    # Try to get actual mounts from running container
    actual_mounts = []
    container_running = False

    try:
        result = subprocess.run(
            ["docker", "inspect", "robomonkey-postgres", "--format", "{{json .Mounts}}"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            import json
            container_running = True
            mounts_json = json.loads(result.stdout)

            for mount in mounts_json:
                if mount.get("Destination", "").startswith("/sources/"):
                    actual_mounts.append({
                        "host_path": mount.get("Source", ""),
                        "container_path": mount.get("Destination", ""),
                        "read_only": mount.get("RW", True) == False
                    })

    except Exception:
        pass

    # Determine if restart is needed
    enabled_configured = [m for m in configured if m["enabled"]]
    needs_restart = len(enabled_configured) != len(actual_mounts)

    if not needs_restart:
        # Check if paths match
        configured_paths = set((m["host_path"], m["container_path"]) for m in enabled_configured)
        actual_paths = set((m["host_path"], m["container_path"]) for m in actual_mounts)
        needs_restart = configured_paths != actual_paths

    return {
        "container_running": container_running,
        "configured_mounts": configured,
        "actual_mounts": actual_mounts,
        "needs_restart": needs_restart,
        "message": "Restart required to apply changes" if needs_restart else "Mounts are in sync"
    }
