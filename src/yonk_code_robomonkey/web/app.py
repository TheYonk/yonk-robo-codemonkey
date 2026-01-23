"""FastAPI web application for RoboMonkey Admin Panel."""
from __future__ import annotations

import asyncpg
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from yonk_code_robomonkey.config import Settings

# Import routes
from yonk_code_robomonkey.web.routes import repos, tables, mcp_tools, stats, maintenance, sources

# Initialize FastAPI app
app = FastAPI(
    title="RoboMonkey Admin Panel",
    description="Database inspection and MCP tool testing UI",
    version="0.1.0"
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
