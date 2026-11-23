"""
WanderWall API - FastAPI Application.

This is the main FastAPI application that provides:
- REST API endpoints for mobile app (JWT authenticated)
- Web dashboard for LAN access (no auth)
- Health and version endpoints

See docs/SPECIFICATION.md for full API documentation.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# API route imports
from src.api.routes import auth, pairing, status, devices, services, display, folders, contributors, cloud, settings, logs, photos, contributor, tools, updates, system

# Dashboard routes
from src.dashboard import routes as dashboard_routes

# Middleware
from src.api.middleware import LANOnlyMiddleware, UploadSizeLimitMiddleware
from src.api.routes.contributor import MAX_UPLOAD_BYTES
from src.services.recovery_service import MAX_UPLOAD_BYTES as RECOVERY_MAX_UPLOAD_BYTES

# Update service
from src.services.update_service import start_update_scheduler
from src.services import demo_service, frame_registry
from src.services.systemd_service import reconcile_sleep_timers
from src.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start background tasks on startup."""
    asyncio.create_task(start_update_scheduler())
    demo_service.expire_if_due()
    frame_registry.start()
    display = get_settings().display
    asyncio.create_task(
        reconcile_sleep_timers(display.sleep_enabled, display.sleep_time, display.wake_time)
    )
    yield


app = FastAPI(
    title="WanderWall API",
    description="Secure mobile management for Raspberry Pi picture frames",
    version="5.0.0",
    lifespan=lifespan,
)

# Deny non-local clients everything except /api/v1/*, /health and /version
app.add_middleware(LANOnlyMiddleware)

# Refuse oversized contributor uploads before the body is spooled (PL-060).
# 1 MB on top of the file limit covers the multipart framing.
app.add_middleware(
    UploadSizeLimitMiddleware,
    path_prefix="/api/v1/contributor/upload/",
    max_body_bytes=MAX_UPLOAD_BYTES + 1024 * 1024,
)

# Dashboard "Upload a .zip" for album recovery: up to 16 GB archives, e.g. a whole-frame backup (LAN only)
app.add_middleware(
    UploadSizeLimitMiddleware,
    path_prefix="/api/albums/upload-archive",
    max_body_bytes=RECOVERY_MAX_UPLOAD_BYTES + 1024 * 1024,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/version")
async def version():
    """API version endpoint."""
    return {"version": "5.0.0", "api": "wanderwall"}


# Include dashboard routes (LAN only, no auth)
app.include_router(dashboard_routes.router)

# Include API routes with /api/v1 prefix (JWT authenticated via mobile app)
app.include_router(pairing.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(status.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(services.router, prefix="/api/v1")
app.include_router(display.router, prefix="/api/v1")
app.include_router(folders.router, prefix="/api/v1")
app.include_router(contributors.router, prefix="/api/v1")
app.include_router(cloud.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")
app.include_router(photos.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(contributor.router, prefix="/api/v1")
app.include_router(updates.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")

# Mount static files for dashboard
static_dir = Path(__file__).parent.parent / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
