"""
WanderWall API - Status Routes.

Provides frame status information:
- GET /status: Full status including capacity, sync state, service health
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.dependencies import require_admin
from src.config.settings import get_settings
from src.services.sync_service import sync_service
from src.utils.network import check_remote_access, get_lan_ip, get_tailscale_ip, get_wifi_ssid
from src.services.status_service import (
    get_current_source,
    get_photo_counts,
    determine_sync_status,
    get_last_sync_time,
    get_disk_capacity,
    PICTURES_PATH,
)

router = APIRouter(tags=["status"])


class ServiceStatus(BaseModel):
    """Status of a systemd service."""
    name: str
    display_name: str
    active: bool
    status: str  # "running", "stopped", "unknown"
    can_restart: bool


class SyncStatusInfo(BaseModel):
    """Status of photo sync."""
    last_sync: Optional[str]
    status: str  # "match", "mismatch", "syncing", "error", "idle"
    local_count: int
    remote_count: int
    is_syncing: bool
    current_source: Optional[str]


class CapacityInfo(BaseModel):
    """Storage capacity information."""
    total_gb: float
    used_gb: float
    available_gb: float
    percent_used: float
    total_bytes: int
    used_bytes: int
    free_bytes: int


class NetworkInfo(BaseModel):
    """How the frame can be reached (empty string when unknown)."""
    lan_ip: str
    tailscale_ip: str
    funnel_url: str
    # Connection lights in the app (newer frames only)
    local_connected: bool = False
    wifi_ssid: str = ""
    remote_access: Optional[bool] = None  # None = no Funnel URL configured


class FrameStatus(BaseModel):
    """Complete frame status response."""
    frame_id: str
    frame_name: str
    current_source: str
    photo_count: int
    services: list[ServiceStatus]
    sync: SyncStatusInfo
    capacity: CapacityInfo
    network: Optional[NetworkInfo] = None


SERVICE_DISPLAY_NAMES = {
    "picframe.service": "WanderWall Display",
    "wanderwall-api.service": "WanderWall API",
    "wanderwall-sync.service": "WanderWall Sync",
}


def _map_service_status(systemctl_status: str) -> str:
    """Map systemctl status strings to mobile-friendly values."""
    if systemctl_status == "active":
        return "running"
    elif systemctl_status == "inactive":
        return "stopped"
    return "unknown"


async def _get_service_status(service_name: str) -> ServiceStatus:
    """Get status of a systemd user service."""
    display_name = SERVICE_DISPLAY_NAMES.get(service_name, service_name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "is-active", service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw_status = stdout.decode().strip()
        active = raw_status == "active"
        return ServiceStatus(
            name=service_name,
            display_name=display_name,
            active=active,
            status=_map_service_status(raw_status),
            can_restart=True,
        )
    except Exception:
        return ServiceStatus(
            name=service_name,
            display_name=display_name,
            active=False,
            status="unknown",
            can_restart=True,
        )


@router.get("/status", response_model=FrameStatus)
async def get_status(admin=Depends(require_admin)):
    """
    Get comprehensive frame status.

    Returns service health, sync status, capacity, and current configuration.
    """
    settings = get_settings()

    # Get service statuses
    services = await asyncio.gather(
        _get_service_status("picframe.service"),
        _get_service_status("wanderwall-api.service"),
    )

    # Get current source and photo counts (shared logic)
    current_source_id, current_source = get_current_source()
    photo_count, remote_count = await get_photo_counts(current_source)

    # Determine sync status (shared logic)
    sync_status = determine_sync_status(photo_count, remote_count)

    # Get capacity (shared logic)
    capacity_data = get_disk_capacity(PICTURES_PATH)
    capacity = CapacityInfo(**capacity_data)

    # Addresses for the app's connection info (tailscale call is a blocking subprocess)
    funnel_url = settings.frame.funnel_url or ""
    lan_ip, tailscale_ip, wifi_ssid, remote_access = await asyncio.gather(
        asyncio.to_thread(get_lan_ip),
        asyncio.to_thread(get_tailscale_ip),
        asyncio.to_thread(get_wifi_ssid),
        asyncio.to_thread(check_remote_access, funnel_url),
    )
    network = NetworkInfo(
        lan_ip=lan_ip,
        tailscale_ip=tailscale_ip,
        funnel_url=funnel_url,
        local_connected=bool(lan_ip),
        wifi_ssid=wifi_ssid,
        remote_access=remote_access,
    )

    return FrameStatus(
        frame_id=settings.frame.id,
        frame_name=settings.frame.name,
        current_source=current_source_id,
        photo_count=photo_count,
        services=list(services),
        sync=SyncStatusInfo(
            last_sync=get_last_sync_time(),
            status=sync_status,
            local_count=photo_count,
            # Always a number: the app decodes remote_count as a required Int (FrameStatus.swift)
            remote_count=remote_count if remote_count is not None else 0,
            is_syncing=sync_service._is_syncing,
            current_source=sync_service._current_source,
        ),
        capacity=capacity,
        network=network,
    )
