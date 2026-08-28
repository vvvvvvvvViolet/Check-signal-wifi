"""Check Signal WiFi - application entrypoint.

Runs as a local service on the surveying machine: it needs the host's own radio
and routing table, so it is not something you deploy centrally.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import dashboard, diagnosis, heatmap, history, monitor, nettest, report, scanner
from .api import settings as settings_api
from .config import BASE_DIR
from .db import init_db
from .services.monitor import engine
from .wifi import get_adapter

logging.basicConfig(
    level=os.environ.get("CSW_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("check-signal-wifi")

FRONTEND_DIST = Path(os.environ.get("CSW_FRONTEND_DIST", BASE_DIR / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    adapter = get_adapter()
    log.info("WiFi backend: %s", adapter.name)
    if adapter.name == "mock":
        log.warning("Using the SIMULATED WiFi backend - readings are not from real hardware")
    yield
    if engine.is_running:
        await engine.stop()


app = FastAPI(
    title="Check Signal WiFi",
    description=(
        "WiFi monitoring, site survey and coverage heatmap for factory and "
        "warehouse networks."
    ),
    version=__version__,
    lifespan=lifespan,
)

# The UI is served from the same origin in production; the permissive list is
# for `vite dev` on 5173 during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    dashboard,
    monitor,
    scanner,
    heatmap,
    nettest,
    diagnosis,
    history,
    report,
    settings_api,
):
    app.include_router(module.router)


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    adapter = get_adapter()
    return {
        "status": "ok",
        "version": __version__,
        "wifi_backend": adapter.name,
        "simulated": adapter.name == "mock",
        "monitor": engine.status(),
    }


# ------------------------------------------------------------ static UI
if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """Serve the built SPA, letting client-side routing own every non-API path."""
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / path).resolve()
        if (
            path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def no_ui() -> dict:
        return {
            "message": (
                "API is running but the UI has not been built. "
                "Run `npm install && npm run build` in ./frontend, or use the "
                "Vite dev server on http://localhost:5173."
            ),
            "docs": "/docs",
        }
