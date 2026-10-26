"""
WanderWall API - Software Update Routes.

Check for, schedule, and apply frame software updates from the mobile app.
The LAN dashboard has equivalent unauthenticated routes under /api/updates/*.
While demo mode is on, the app can check but not apply or schedule (PL-150).
"""

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import require_admin
from src.auth.jwt_handler import TokenClaims
from src.services.update_service import (
    DEMO_LOCKED_MESSAGE,
    SaveUpdateScheduleRequest,
    apply_update_and_restart,
    get_update_status,
    run_update_check,
    save_update_schedule,
    updates_locked,
)

router = APIRouter(prefix="/updates", tags=["updates"])


def _refuse_if_locked() -> None:
    """403 with a message the app shows, while demo mode is on (PL-150)."""
    if updates_locked():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_LOCKED_MESSAGE)


@router.get("/settings")
async def get_update_settings(
    admin: TokenClaims = Depends(require_admin),
) -> dict:
    """Get update schedule settings, last check result, and installed version."""
    return await get_update_status()


@router.post("/check")
async def check_for_updates(
    admin: TokenClaims = Depends(require_admin),
) -> dict:
    """Trigger an immediate update check."""
    return await run_update_check()


@router.post("/schedule")
async def save_schedule(
    request: SaveUpdateScheduleRequest,
    admin: TokenClaims = Depends(require_admin),
) -> dict:
    """Save update schedule settings. Refused while demo mode is on."""
    _refuse_if_locked()
    return save_update_schedule(request)


@router.post("/apply")
async def apply_update(
    admin: TokenClaims = Depends(require_admin),
) -> dict:
    """Apply available updates (git pull) and restart the API. Refused while demo mode is on."""
    _refuse_if_locked()
    return await apply_update_and_restart("app")
