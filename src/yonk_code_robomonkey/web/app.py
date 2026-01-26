"""FastAPI web application for RoboMonkey Admin Panel."""
from __future__ import annotations

import asyncpg
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from yonk_code_robomonkey.config import Settings

# Import routes
from yonk_code_robomonkey.web.routes import repos, tables, mcp_tools, stats, maintenance, sources, docs

logger = logging.getLogger(__name__)


async def run_migrations():
    """Run database migrations on startup."""
    settings = Settings()

    try:
        print("Connecting to database for migrations...")
        conn = await asyncpg.connect(dsn=settings.database_url, timeout=10)

        # Check if robomonkey_docs schema exists
        docs_schema_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'robomonkey_docs'
            )
        """)

        if docs_schema_exists:
            # Check for missing tables and create them
            missing_tables = []
            required_tables = ['doc_source', 'doc_chunk', 'doc_chunk_embedding',
                              'doc_summary', 'doc_feature', 'doc_cross_reference']

            for table in required_tables:
                exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'robomonkey_docs'
                        AND table_name = $1
                    )
                """, table)
                if not exists:
                    missing_tables.append(table)

            if missing_tables:
                print(f"Missing tables detected: {missing_tables}")
                # Run the full schema script to create missing tables
                schema_script = Path(__file__).resolve().parents[3] / "scripts" / "init_docs_schema.sql"
                if schema_script.exists():
                    print(f"Running schema script: {schema_script}")
                    schema_sql = schema_script.read_text()
                    # Execute the schema - it uses IF NOT EXISTS so safe to re-run
                    await conn.execute(schema_sql)
                    print(f"Created missing tables: {missing_tables}")
                else:
                    print(f"Warning: Schema script not found at {schema_script}")

            # Run column migrations for existing tables
            migrations = [
                # Add chunks_expected column to doc_source
                ("doc_source.chunks_expected", """
                    ALTER TABLE robomonkey_docs.doc_source
                    ADD COLUMN IF NOT EXISTS chunks_expected INT
                """),
                # Add stop_requested column to doc_source
                ("doc_source.stop_requested", """
                    ALTER TABLE robomonkey_docs.doc_source
                    ADD COLUMN IF NOT EXISTS stop_requested BOOLEAN DEFAULT FALSE
                """),
            ]

            for name, sql in migrations:
                try:
                    await conn.execute(sql)
                    print(f"Migration applied: {name}")
                except Exception as e:
                    # Column might already exist or other non-critical error
                    logger.debug(f"Migration skipped ({name}): {e}")

            # Reset any stuck "processing" documents to "stopped" on startup
            try:
                stuck_result = await conn.execute("""
                    UPDATE robomonkey_docs.doc_source
                    SET status = 'stopped', stop_requested = FALSE
                    WHERE status = 'processing'
                """)
                # stuck_result is like "UPDATE 3" - extract the count
                if stuck_result and stuck_result.startswith("UPDATE "):
                    stuck_count = int(stuck_result.split()[1])
                    if stuck_count > 0:
                        print(f"Reset {stuck_count} stuck processing document(s) to 'stopped'")
            except Exception as e:
                # Columns might not exist yet
                logger.debug(f"Could not reset stuck documents: {e}")

        await conn.close()
        print("Database migrations completed")
        logger.info("Database migrations completed")

    except Exception as e:
        print(f"Migration check failed (non-fatal): {e}")
        logger.warning(f"Migration check failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    print("RoboMonkey Web UI starting up...")
    logger.info("RoboMonkey Web UI starting up...")
    await run_migrations()
    print("Startup complete, server ready")
    yield
    # Shutdown
    print("RoboMonkey Web UI shutting down...")
    logger.info("RoboMonkey Web UI shutting down...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="RoboMonkey Admin Panel",
    description="Database inspection and MCP tool testing UI",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get base directory
BASE_DIR = Path(__file__).parent

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include routers
app.include_router(repos.router, prefix="/api", tags=["repositories"])
app.include_router(tables.router, prefix="/api", tags=["database"])
app.include_router(mcp_tools.router, prefix="/api/mcp", tags=["mcp-tools"])
app.include_router(stats.router, prefix="/api/stats", tags=["statistics"])
app.include_router(maintenance.router, prefix="/api/maintenance", tags=["maintenance"])
app.include_router(sources.router, prefix="/api", tags=["sources"])
app.include_router(docs.router, prefix="/api/docs", tags=["knowledge-base"])


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Repository dashboard homepage."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/repos", response_class=HTMLResponse)
async def repos_management(request: Request):
    """Repository management page."""
    return templates.TemplateResponse("repos.html", {"request": request})


@app.get("/explorer", response_class=HTMLResponse)
async def database_explorer(request: Request):
    """Database explorer page."""
    return templates.TemplateResponse("explorer.html", {"request": request})


@app.get("/tools", response_class=HTMLResponse)
async def mcp_tool_tester(request: Request):
    """MCP tool tester page."""
    return templates.TemplateResponse("tools.html", {"request": request})


@app.get("/stats", response_class=HTMLResponse)
async def performance_stats(request: Request):
    """Performance monitoring page."""
    return templates.TemplateResponse("stats.html", {"request": request})


@app.get("/sources", response_class=HTMLResponse)
async def source_mounts_page(request: Request):
    """Source mounts management page."""
    return templates.TemplateResponse("sources.html", {"request": request})


@app.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base_page(request: Request):
    """Knowledge base management page."""
    return templates.TemplateResponse("knowledge_base.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    settings = Settings()

    # Check database connection
    try:
        conn = await asyncpg.connect(dsn=settings.database_url)
        await conn.execute("SELECT 1")
        await conn.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "database": db_status,
        "version": "0.1.0"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "path": str(request.url)
        }
    )


def run_server(host: str = "0.0.0.0", port: int = 9832):
    """Run the web server using uvicorn."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import os
    port = int(os.getenv("WEB_UI_PORT", "9832"))
    host = os.getenv("WEB_UI_HOST", "0.0.0.0")
    print(f"Starting RoboMonkey Web UI on http://{host}:{port}")
    run_server(host=host, port=port)
