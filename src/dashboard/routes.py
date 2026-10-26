"""
WanderWall - Dashboard Routes.

Server-rendered pages for the web dashboard.
Uses Jinja2 templates.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import APIRouter, Query, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from src.utils.network import get_lan_ip, get_tailscale_ip, get_wifi_ssid
from src.utils import thumbnails
from src.config.settings import get_settings, reload_settings
from src.config.manager import config_manager
from src.services.source_manager import source_manager
from src.services.sync_service import sync_service
from src.services.systemd_service import systemd_service, update_sync_timer, update_sleep_timers, VALID_SYNC_INTERVALS
from src.services.display_service import display_service
from src.services.update_service import (
    SaveUpdateScheduleRequest,
    apply_update_and_restart,
    get_current_branch,
    get_local_commit,
    get_local_version,
    get_update_status,
    run_update_check,
    save_update_schedule,
)
from src.services.status_service import (
    get_current_source,
    get_photo_counts,
    determine_sync_status,
    get_disk_capacity,
    PICTURES_PATH,
)
from src.storage.devices import device_storage
from src.auth.pairing import generate_pairing_code
from src.utils.qr_generator import generate_qr_data_url
from src.utils.rclone import count_local_files, rclone_count, rclone_list_remotes, _validate_filename_raw
from src.services import photo_tools_service as photo_tools
from src.services import backup_service
from src.services.party_service import enable_party, disable_party
from src.services import album_service, demo_reset_service, demo_service, frame_registry, power_service, recovery_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Log files location
LOGS_DIR = Path.home() / ".wanderwall" / "logs"

# In-memory overrides for manual light testing (reset to None to resume normal behavior)
_light_overrides: dict = {}  # keys: "sync_status", "wifi_connected"

# Picframe config file location
PICFRAME_CONFIG_PATH = Path.home() / "picframe_data" / "config" / "configuration.yaml"


def _format_last_checked(iso_str: str | None) -> str:
    """Format an ISO datetime string as a human-friendly string."""
    if not iso_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-d %b %Y at %-I:%M %p")
    except Exception:
        return iso_str


WANDERWALL_APP_CONFIG = Path.home() / ".wanderwall" / "config.yaml"


def _get_koofr_user() -> str:
    """Return the stored Koofr email, or empty string if not configured."""
    try:
        if WANDERWALL_APP_CONFIG.exists():
            with open(WANDERWALL_APP_CONFIG) as f:
                config = yaml.safe_load(f) or {}
            return config.get("sync", {}).get("koofr_user", "").strip()
    except Exception:
        pass
    return ""


def _get_koofr_pass() -> str:
    """Return the stored plain Koofr password, or empty string."""
    try:
        if WANDERWALL_APP_CONFIG.exists():
            with open(WANDERWALL_APP_CONFIG) as f:
                config = yaml.safe_load(f) or {}
            return config.get("sync", {}).get("koofr_pass", "").strip()
    except Exception:
        pass
    return ""


def _is_koofr_configured() -> bool:
    """Return True if cloud sync is configured on this frame.

    Checks three signals in order:
    1. state.yaml has koofr_configured=true (explicit Phase 6 first-run completion)
    2. config.yaml has sync.koofr_user (Koofr credentials saved via dashboard)
    3. Any enabled source already has an rclone_remote (pre-existing sync config)
    """
    try:
        # 1. Explicit Phase 6 state flag
        state_path = Path("/var/lib/wanderwall/state.yaml")
        if state_path.exists():
            with open(state_path) as f:
                state = yaml.safe_load(f) or {}
            if state.get("koofr_configured"):
                return True

        if not WANDERWALL_APP_CONFIG.exists():
            return False

        with open(WANDERWALL_APP_CONFIG) as f:
            config = yaml.safe_load(f) or {}

        # 2. Koofr credentials saved via dashboard
        if config.get("sync", {}).get("koofr_user", "").strip():
            return True

        # 3. Any enabled source already has a cloud remote (pre-existing config)
        sources_path = Path.home() / ".wanderwall" / "sources.yaml"
        if sources_path.exists():
            with open(sources_path) as f:
                sources_data = yaml.safe_load(f) or {}
            for source in sources_data.get("sources", []):
                if source.get("enabled") and source.get("rclone_remote", "").strip():
                    return True

    except Exception:
        pass
    return False


async def _validate_koofr_credentials(user: str, password: str) -> tuple[bool, str, str]:
    """
    Test Koofr credentials using a temporary rclone config.

    Returns (is_valid, error_message, obscured_password).
    """
    # Obscure the password
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "obscure", password,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return False, "Failed to process Koofr password.", ""
        obscured = stdout.decode().strip()
    except asyncio.TimeoutError:
        return False, "Credential check timed out.", ""
    except FileNotFoundError:
        return False, "rclone is not installed.", ""

    config_content = (
        "[koofr-test]\n"
        "type = koofr\n"
        f"user = {user}\n"
        f"password = {obscured}\n"
    )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False, dir="/tmp"
        ) as f:
            f.write(config_content)
            tmp_path = f.name
        os.chmod(tmp_path, 0o600)

        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsd", "koofr-test:", "--config", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=20)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "Koofr connection timed out. Check your internet connection."

        if proc.returncode == 0:
            logger.info(f"Koofr credentials validated for '{user}'")
            return True, "", obscured
        return False, "Could not connect to Koofr. Check your email and password.", ""

    except Exception as e:
        logger.error(f"Koofr validation error: {e}")
        return False, "Failed to validate Koofr credentials.", ""
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def _get_picframe_config() -> dict:
    """Read picframe configuration.yaml file."""
    if PICFRAME_CONFIG_PATH.exists():
        try:
            with open(PICFRAME_CONFIG_PATH) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to read picframe config: {e}")
    return {}


# Kept under the old names; the shared versions live in src/utils/network.py
_get_tailscale_ip = get_tailscale_ip
_get_lan_ip = get_lan_ip
_get_wifi_ssid = get_wifi_ssid


def _is_wifi_connected() -> bool:
    """Return True if the frame has a non-loopback network connection."""
    return bool(_get_lan_ip())



def _pairing_url() -> str:
    """URL the app should pair with: the Funnel URL, else the Tailscale IP, else ""."""
    url = get_settings().frame.funnel_url or ""
    if not url:
        ts_ip = _get_tailscale_ip()
        if ts_ip:
            url = f"http://{ts_ip}:8000"
    return url


def _demo_qr_codes(demo: dict) -> dict:
    """QR data URLs for the two demo codes (same payload as normal pairing QRs), or {} when off."""
    url = _pairing_url()
    if not (demo["allowed"] and demo["enabled"] and url):
        return {}
    name = get_settings().frame.name
    return {
        "admin": generate_qr_data_url(url=url, code=demo["admin_code"], frame_name=name),
        "contributor": generate_qr_data_url(url=url, code=demo["contributor_code"], frame_name=name),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """
    Dashboard home page.

    Shows status overview: file counts, sync state, service health.
    """
    demo_service.expire_if_due()
    settings = get_settings()
    demo = demo_service.demo_status()

    # Get current source info (shared logic)
    current_source_id, current_source = get_current_source()
    sources = source_manager.list_sources()

    # Count photos (local only for initial page render)
    local_count = 0
    if current_source:
        local_count = count_local_files(current_source.local_path)

    # Determine sync status (shared logic)
    sync_status = determine_sync_status(local_count, 0)

    # Get service statuses
    services = await systemd_service.list_services()

    # Get storage capacity (shared logic)
    capacity = get_disk_capacity(PICTURES_PATH)

    # Get rotation interval from picframe config
    picframe_config = _get_picframe_config()
    rotation_interval = int(picframe_config.get("model", {}).get("time_delay", 30))
    fade_time = float(picframe_config.get("model", {}).get("fade_time", 2.0))
    pf_log_level = picframe_config.get("model", {}).get("log_level", "WARNING")

    # Get update status for Settings tab card
    local_commit = await get_local_commit()
    local_version = await get_local_version()
    update_branch = await get_current_branch()

    # If the frame is already at the "available" commit, the update was applied — clear stale state
    update_last_result = settings.updates.last_result
    update_available_commit = settings.updates.available_commit
    if update_last_result == "update_available" and update_available_commit and update_available_commit == local_commit:
        update_last_result = "up_to_date"
        update_available_commit = None

    context = {
        "request": request,
        "frame_name": settings.frame.name,
        "frame_id": settings.frame.id,
        "current_source": current_source.name if current_source else "Unknown",
        "current_source_id": current_source_id,
        "sources": sources,
        "local_count": local_count,
        "remote_count": 0,
        "sync_status": sync_status,
        "is_syncing": sync_service._is_syncing,
        "services": services,
        "storage_used": capacity["used_gb"],
        "storage_total": capacity["total_gb"],
        "storage_percent": capacity["percent_used"],
        "rotation_interval": rotation_interval,
        "fade_time": fade_time,
        "sync_interval": settings.sync.interval,
        "log_level": pf_log_level,
        "funnel_url": settings.frame.funnel_url or "",
        "tailscale_ip": _get_tailscale_ip(),
        "api_port": 8000,
        # Update check card context
        "update_auto_check": settings.updates.auto_check,
        "update_auto_apply": settings.updates.auto_apply,
        "update_frequency": settings.updates.frequency,
        "update_day": settings.updates.day,
        "update_check_time": settings.updates.check_time,
        "update_last_checked": _format_last_checked(settings.updates.last_checked),
        "update_last_result": update_last_result,
        "update_available_commit": update_available_commit,
        "update_local_commit": local_commit,
        "update_local_version": local_version,
        "update_branch": update_branch,
        "koofr_configured": _is_koofr_configured(),
        "koofr_user": _get_koofr_user(),
        "has_sources": len(sources) > 0,
        "lan_ip": _get_lan_ip(),
        "wifi_ssid": _get_wifi_ssid(),
        "party_mode": settings.display.party_mode,
        "sleep_enabled": settings.display.sleep_enabled,
        "sleep_time": settings.display.sleep_time,
        "wake_time": settings.display.wake_time,
        "demo": demo,
        "registry": frame_registry.banner(),
        "demo_qr": _demo_qr_codes(demo),
        "demo_baseline": demo_reset_service.baseline_info() if demo["allowed"] else None,
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.post("/devices/{device_id}/revoke")
async def revoke_device(device_id: str):
    """Revoke a paired device (AJAX endpoint)."""
    # Validate device_id format
    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        return {"ok": False, "error": "Invalid device ID"}

    device = device_storage.get_device(device_id)
    if not device:
        return {"ok": False, "error": "Device not found"}

    # Check if this is the last admin
    if device.role == "admin" and device_storage.count_admins() <= 1:
        return {"ok": False, "error": "Cannot revoke the last admin device"}

    success = device_storage.remove_device(device_id)
    if success:
        logger.info(f"Device '{device.name}' ({device_id}) revoked via dashboard")
        return {"ok": True}
    else:
        return {"ok": False, "error": "Failed to revoke device"}


@router.post("/pairing/generate")
async def generate_pairing_endpoint():
    """Generate a new pairing code (AJAX endpoint)."""
    settings = get_settings()
    pairing_code = generate_pairing_code()

    if pairing_code:
        url = _pairing_url()
        if not url:
            return {"error": "No address available — set funnel_url in config or ensure Tailscale is running"}
        qr_data_url = generate_qr_data_url(
            url=url,
            code=pairing_code.code,
            frame_name=settings.frame.name,
        )
        return {
            "code": pairing_code.code,
            "qr_data_url": qr_data_url,
            "expires_at": pairing_code.expires_at.isoformat(),
        }
    else:
        return {"error": "Rate limit exceeded"}


@router.get("/api/logs")
async def get_logs(lines: int = 100, log_type: str = "ops"):
    """
    Get recent log entries.

    Args:
        lines: Number of lines to return
        log_type: "ops" or "security"
    """
    logs = _read_log_file(log_type, lines)
    return {"logs": logs, "log_type": log_type}


def _read_log_file(log_type: str, lines: int = 100) -> list[str]:
    """Read log file and return recent lines."""
    if log_type == "security":
        log_file = LOGS_DIR / "security.log"
    else:
        log_file = LOGS_DIR / "wanderwall.log"

    if not log_file.exists():
        return []

    try:
        with open(log_file, "r") as f:
            all_lines = f.readlines()
        # Return last N lines, reversed (newest first)
        return [line.strip() for line in all_lines[-lines:]][::-1]
    except Exception:
        return []


def _last_matching_timestamp(log_file: Path, needle: str) -> str | None:
    """
    Find the timestamp of the last log line containing the needle string.

    Expects log format: "YYYY-MM-DD HH:MM:SS ..."
    """
    if not log_file.exists():
        return None

    last_line = None
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if needle.lower() in line.lower():
                    last_line = line
    except Exception:
        return None

    if not last_line:
        return None

    # Extract timestamp from start of line (first 19 chars: "YYYY-MM-DD HH:MM:SS")
    ts_str = last_line[:19]
    try:
        datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return ts_str
    except ValueError:
        return None


def _get_last_sync_time() -> str | None:
    """Get timestamp of last sync from systemd timer stamp or logs."""
    # First check systemd timer stamp file (most reliable)
    stamp_file = Path.home() / ".local" / "share" / "systemd" / "timers" / "stamp-wanderwall-sync.timer"
    if stamp_file.exists():
        try:
            mtime = stamp_file.stat().st_mtime
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Fallback to log file
    log_file = LOGS_DIR / "wanderwall.log"
    return _last_matching_timestamp(log_file, "sync") or \
           _last_matching_timestamp(log_file, "rclone")


async def _get_last_restart_time() -> str | None:
    """Get timestamp of last service restart from systemd."""
    latest = None
    for svc in ("picframe", "wanderwall-api"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "show", f"{svc}.service",
                "--property=ActiveEnterTimestamp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            line = stdout.decode().strip()
            # Format: ActiveEnterTimestamp=Wed 2026-02-11 14:28:23 MST
            if "=" in line:
                ts_str = line.split("=", 1)[1].strip()
                if ts_str:
                    # Parse systemd timestamp (e.g. "Wed 2026-02-11 14:28:23 MST")
                    # Strip day name and timezone for parsing
                    parts = ts_str.split()
                    if len(parts) >= 4:
                        dt = datetime.strptime(
                            f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S"
                        )
                        if latest is None or dt > latest:
                            latest = dt
        except Exception:
            continue
    return latest.strftime("%Y-%m-%d %H:%M:%S") if latest else None


# Dashboard sync trigger (no auth required on LAN)
@router.post("/sync")
async def trigger_sync():
    """Trigger a sync from the dashboard."""
    settings = get_settings()
    current_source_id = settings.display.current_source

    # Find the active source
    source = source_manager.get_source(current_source_id) if current_source_id else None

    if not source or not source.rclone_remote:
        # Fall back to first enabled source with a remote
        sources = source_manager.list_sources()
        syncable = [s for s in sources if s.enabled and s.rclone_remote]
        if not syncable:
            return {"error": "No albums have cloud sync configured. Complete Koofr setup first."}
        source = syncable[0]

    if sync_service._is_syncing:
        return {"error": "Sync already in progress"}

    async def run_sync_with_logging():
        """Run sync and update timestamp/logs."""
        logger.info(f"Starting sync for source '{source.id}' from {source.rclone_remote}")
        try:
            await sync_service.sync_source(
                source_id=source.id,
                local_path=Path(source.local_path).expanduser(),
                rclone_remote=source.rclone_remote,
            )
            logger.info(f"Sync completed for source '{source.id}'")
        except Exception as e:
            logger.error(f"Sync failed for source '{source.id}': {e}")

        # Update the systemd timer stamp file to reflect manual sync
        stamp_file = Path.home() / ".local" / "share" / "systemd" / "timers" / "stamp-wanderwall-sync.timer"
        try:
            stamp_file.parent.mkdir(parents=True, exist_ok=True)
            stamp_file.touch()
        except Exception as e:
            logger.warning(f"Failed to update sync stamp file: {e}")

    # Run sync in background
    asyncio.create_task(run_sync_with_logging())

    return {"status": "started", "source": source.id}


# Dashboard folder switch (no auth required on LAN)
@router.post("/switch-source")
async def switch_source(source_id: str = Form(...)):
    """Switch the display source from the dashboard."""
    source = source_manager.get_source(source_id)
    if not source:
        return RedirectResponse(url="/?error=source_not_found", status_code=303)

    source_path = Path(source.local_path).expanduser()
    if not source_path.exists():
        source_path.mkdir(parents=True, exist_ok=True)

    success = await display_service.switch_folder(source_path)
    if success:
        config_manager.set("display.current_source", source_id)
        reload_settings()  # Clear cached settings
        return RedirectResponse(url="/?switched=1", status_code=303)
    else:
        return RedirectResponse(url="/?error=switch_failed", status_code=303)


async def _check_tailscale() -> str:
    """Return 'running' if Tailscale is connected, else 'stopped' or 'unknown'."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tailscale", "status", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        import json as _json
        data = _json.loads(stdout)
        return "running" if data.get("BackendState") == "Running" else "stopped"
    except Exception:
        return "unknown"


@router.get("/dashboard/status")
async def get_dashboard_status():
    """
    Get dashboard status as JSON for AJAX updates.

    Returns sync status, file counts, service status, storage info.
    """
    demo_service.expire_if_due()

    # Get current source info (shared logic)
    current_source_id, current_source = get_current_source()

    # Count photos (shared logic - uses rclone_count instead of manual subprocess)
    local_count, remote_count = await get_photo_counts(current_source)

    # Determine sync status (shared logic)
    sync_status = determine_sync_status(local_count, remote_count)

    # Get service statuses
    services = await systemd_service.list_services()
    services_data = [
        {"name": s.name, "active": s.active, "status": s.status}
        for s in services
    ]

    # Get additional health check statuses in parallel
    sync_timer_svc, lights_svc, api_svc, tailscale_status = await asyncio.gather(
        systemd_service.get_status("wanderwall-sync.timer"),
        systemd_service.get_status("wanderwall-lights"),
        systemd_service.get_status("wanderwall-api"),
        _check_tailscale(),
    )

    # Get storage capacity (shared logic)
    capacity = get_disk_capacity(PICTURES_PATH)

    # Get last sync/restart times
    last_sync = _get_last_sync_time()
    last_restart = await _get_last_restart_time()

    # Calculate next sync time from last sync + interval
    next_sync = None
    if last_sync:
        try:
            settings = get_settings()
            last_dt = datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")
            next_dt = last_dt + timedelta(seconds=settings.sync.interval)
            next_sync = next_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    return {
        "sync_status": _light_overrides.get("sync_status", sync_status),
        "local_count": local_count,
        "remote_count": remote_count,
        "current_source": current_source.name if current_source else "Unknown",
        "services": services_data,
        "storage_used": capacity["used_gb"],
        "storage_total": capacity["total_gb"],
        "storage_percent": capacity["percent_used"],
        "last_sync": last_sync,
        "next_sync": next_sync,
        "last_restart": last_restart,
        "koofr_configured": _is_koofr_configured(),
        "has_sources": len(source_manager.list_sources()) > 0,
        "rotation_interval": get_settings().display.rotation_interval,
        "wifi_connected": _light_overrides.get("wifi_connected", _is_wifi_connected()),
        "sync_timer_status": sync_timer_svc.status if sync_timer_svc else "unknown",
        "lights_status":     lights_svc.status     if lights_svc     else "unknown",
        "api_health_status": api_svc.status         if api_svc         else "unknown",
        "tailscale_status":  tailscale_status,
        "demo": demo_service.demo_status(),
        "registry": frame_registry.banner(),
    }


@router.post("/dashboard/koofr-setup")
async def koofr_setup(request: Request):
    """
    Save and validate Koofr credentials. Step 2 of first-run setup.

    Validates credentials live via rclone before writing anything.
    On success, saves to ~/.wanderwall/config.yaml and returns 200.
    """
    data = await request.json()
    koofr_user = str(data.get("koofr_user", "")).strip()
    koofr_pass = str(data.get("koofr_pass", "")).strip()

    import re as _re
    EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    if not EMAIL_RE.match(koofr_user):
        return {"success": False, "error": "Invalid Koofr email address."}
    if not koofr_pass:
        return {"success": False, "error": "Koofr password is required."}

    valid, error_msg, obscured_pass = await _validate_koofr_credentials(koofr_user, koofr_pass)
    if not valid:
        return {"success": False, "error": error_msg}

    # Write credentials to config.yaml
    try:
        config: dict = {}
        if WANDERWALL_APP_CONFIG.exists():
            with open(WANDERWALL_APP_CONFIG) as f:
                config = yaml.safe_load(f) or {}
        config.setdefault("sync", {}).update({
            "koofr_user": koofr_user,
            "koofr_pass": koofr_pass,
        })
        tmp = WANDERWALL_APP_CONFIG.with_suffix(".tmp")
        with open(tmp, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        tmp.chmod(0o600)
        tmp.rename(WANDERWALL_APP_CONFIG)
        logger.info(f"Koofr credentials saved for '{koofr_user}'")
    except Exception as e:
        logger.error(f"Failed to save Koofr config: {e}")
        return {"success": False, "error": "Failed to save credentials. Please try again."}

    # Create permanent rclone remote using the obscured password from validation
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "config", "create", "koofr", "koofr",
            "user", koofr_user, "password", obscured_pass,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            logger.info("Koofr rclone remote created successfully")
        else:
            logger.error(f"rclone config create failed: {stderr.decode().strip()}")
    except Exception as e:
        logger.error(f"Failed to create rclone remote: {e}")

    # Mark koofr_configured in state.yaml so watchdog won't regenerate setup image
    _set_koofr_configured()

    # Restore original no_pictures.jpg if setup image was generated by watchdog
    _restore_setup_image()

    # Backfill rclone_remote on sources created before Koofr was configured
    updated = source_manager.backfill_remotes()
    logger.info(f"Backfilled {len(updated)} source(s): {updated}")

    return {"success": True, "backfilled": len(updated)}


def _set_koofr_configured() -> None:
    """Set koofr_configured=true in /var/lib/wanderwall/state.yaml."""
    state_path = Path("/var/lib/wanderwall/state.yaml")
    try:
        state: dict = {}
        if state_path.exists():
            with open(state_path) as f:
                state = yaml.safe_load(f) or {}
        state["koofr_configured"] = True
        tmp = state_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            yaml.safe_dump(state, f, default_flow_style=False)
        tmp.replace(state_path)
        logger.info("state.yaml: koofr_configured set to true")
    except PermissionError:
        logger.error(
            "state.yaml is not writable by the API user — "
            "fix with: sudo bash scripts/setup/install_setup.sh"
        )
    except Exception as e:
        logger.warning(f"Could not update state.yaml koofr_configured: {e}")


def _restore_setup_image() -> None:
    """Restore the original no_pictures.jpg from backup if present."""
    no_pictures = Path.home() / "picframe_data" / "data" / "no_pictures.jpg"
    backup = Path.home() / "picframe_data" / "data" / "no_pictures.setup-backup"
    if backup.exists():
        import shutil
        try:
            shutil.copy2(str(backup), str(no_pictures))
            backup.unlink()
            logger.info("Restored original no_pictures.jpg after Koofr setup")
        except Exception as e:
            logger.warning(f"Could not restore no_pictures.jpg: {e}")


# Preview of the photo on the frame (PL-174). Pi3D's /current_image converts a HEIC
# to JPEG on every request and sends the HEIC's size as Content-Length, so HEIC
# previews took 2-4 s and arrived cut short or failed. /current_image_original sends
# the file as is, with its name; we take the name and serve our own cached thumbnail.
PI3D_URL = "http://localhost:9000"
PREVIEW_SIZE = (560, 560)  # the dashboard shows it at 280 CSS px
# The body is read so Pi3D's server doesn't hit a broken pipe; stop after this (videos)
PREVIEW_MAX_DRAIN = 64 * 1024 * 1024


def _filename_from_disposition(header: str) -> Optional[str]:
    """File name from Pi3D's Content-Disposition (prefers the UTF-8 filename*)."""
    m = re.search(r"filename\*=utf-8''([^;]+)", header, re.IGNORECASE)
    if m:
        return urllib.parse.unquote(m.group(1).strip())
    m = re.search(r'filename="([^"]*)"', header)
    return m.group(1) if m else None


async def _pi3d_current_filename() -> Optional[str]:
    """Name of the photo Pi3D is showing, or None when Pi3D doesn't answer."""
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{PI3D_URL}/current_image_original", timeout=5.0) as resp:
                if resp.status_code != 200:
                    return None
                name = _filename_from_disposition(resp.headers.get("content-disposition", ""))
                drained = 0
                async for chunk in resp.aiter_raw():
                    drained += len(chunk)
                    if drained > PREVIEW_MAX_DRAIN:
                        break
                return name
    except httpx.HTTPError:
        return None


def _find_current_photo(filename: Optional[str]) -> Optional[tuple[str, Path]]:
    """Album id and path of a photo by name: the showing album first, then the others."""
    if not filename or not _validate_filename_raw(filename):
        return None
    current = get_settings().display.current_source
    sources = sorted(source_manager.list_sources(), key=lambda s: s.id != current)
    for source in sources:
        root = Path(source.local_path).expanduser()
        local_file = root / filename
        if not local_file.is_file():
            continue
        try:
            local_file.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        return source.id, local_file
    return None


@router.get("/current-image/info")
async def get_current_image_info():
    """Which photo the frame is showing; the dashboard polls this. LAN-only."""
    return {"filename": await _pi3d_current_filename()}


@router.get("/current-image")
async def get_current_image(filename: Optional[str] = None):
    """
    Thumbnail of the photo on the frame (or of `filename`, as named by /current-image/info).

    Falls back to Pi3D's own image for videos and files outside the albums.
    """
    name = filename or await _pi3d_current_filename()
    found = _find_current_photo(name)
    if found:
        source_id, local_file = found
        try:
            jpeg_bytes = await thumbnails.get_thumbnail(
                local_file, source_id, name, PREVIEW_SIZE, quality=80, prefix="preview_"
            )
            return Response(content=jpeg_bytes, media_type="image/jpeg")
        except Exception as exc:
            logger.warning(f"Preview failed for {name}: {exc}")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{PI3D_URL}/current_image", timeout=5.0)
    except httpx.HTTPError:
        return Response(status_code=503)
    if resp.status_code != 200:
        return Response(status_code=503)
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))


# LAN-only service restart (no auth required - protected by LAN middleware)
ALLOWED_SERVICES = {"picframe", "wanderwall-api"}


@router.post("/services/{service_name}/restart")
async def restart_service_from_dashboard(service_name: str):
    """
    Restart a service from the dashboard.

    LAN-only endpoint, no JWT auth required.
    """
    if service_name not in ALLOWED_SERVICES:
        return {"error": f"Service '{service_name}' not allowed"}

    try:
        success = await systemd_service.restart(service_name)
        if success:
            logger.info(f"Service {service_name} restarted successfully via dashboard")
            return {"ok": True, "service": service_name}
        else:
            logger.error(f"Failed to restart service {service_name}")
            return {"ok": False, "error": "Restart failed"}
    except Exception as e:
        logger.error(f"Error restarting service {service_name}: {e}")
        return {"ok": False, "error": str(e)}


# =============================================================================
# LAN-only Source Management API (no JWT auth - protected by LAN middleware)
# =============================================================================


class CreateSourceRequest(BaseModel):
    """Request to create a new photo source."""
    name: str


class ListDirsRequest(BaseModel):
    """Request to list remote directories."""
    remote: str
    path: str = ""


@router.get("/api/devices")
async def list_devices_api():
    """
    List paired devices as JSON for dashboard AJAX.

    LAN-only endpoint, no JWT auth required.
    """
    devices = device_storage.list_devices()
    admin_count = device_storage.count_admins()

    result = []
    for device in devices:
        result.append({
            "id": device.id,
            "name": device.name,
            "role": device.role,
            "paired_at": device.paired_at.astimezone().strftime("%Y-%m-%d %H:%M") if device.paired_at else None,
            "last_seen": device.last_seen.astimezone().strftime("%Y-%m-%d %H:%M") if device.last_seen else None,
        })

    return {
        "devices": result,
        "admin_count": admin_count,
        "device_count": len(result),
    }


@router.get("/api/sources")
async def list_sources_api():
    """
    List all configured sources for the dashboard.

    LAN-only endpoint, no JWT auth required.
    """
    settings = get_settings()
    current_source_id = settings.display.current_source
    sources = source_manager.list_sources()

    async def _get_counts(source):
        local = count_local_files(source.local_path)
        remote = 0
        if source.rclone_remote:
            try:
                remote = await asyncio.wait_for(rclone_count(source.rclone_remote), timeout=10)
            except (asyncio.TimeoutError, Exception):
                remote = -1
        return local, remote

    counts = await asyncio.gather(*[_get_counts(s) for s in sources])

    result = []
    for source, (local_count, remote_count) in zip(sources, counts):
        result.append({
            "id": source.id,
            "label": source.name,
            "remote": source.rclone_remote or "",
            "path": source.local_path,
            "enabled": source.enabled,
            "active": source.id == current_source_id,
            "photo_count": local_count,
            "remote_count": remote_count,
        })

    return {"sources": result}


@router.post("/api/sources/create")
async def create_source_api(request: CreateSourceRequest):
    """
    Create a new photo source from the dashboard.

    LAN-only endpoint, no JWT auth required.
    """
    if not request.name.strip():
        return {"ok": False, "error": "Name is required"}

    try:
        source = source_manager.create_source(name=request.name.strip())
        logger.info(f"Created source '{source.id}' via dashboard")
        return {"ok": True, "source_id": source.id}
    except Exception as e:
        logger.error(f"Failed to create source: {e}")
        return {"ok": False, "error": str(e)}


class DeleteSourceRequest(BaseModel):
    """Request to delete a source."""
    source_id: str


@router.post("/api/sources/delete")
async def delete_source_api(request: DeleteSourceRequest):
    """
    Delete a photo source from the dashboard.

    Deletes the album's photos on the frame too (PL-147); the cloud folder and
    backups are kept. LAN-only endpoint, no JWT auth required.
    """
    try:
        result = album_service.delete_album(request.source_id)
    except album_service.AlbumDeleteError as e:
        return {"ok": False, "error": e.message}
    logger.info(f"Deleted album '{request.source_id}' via dashboard")
    return {"ok": True, **result}


@router.get("/api/rclone/remotes")
async def list_rclone_remotes():
    """
    List configured rclone remotes.

    LAN-only endpoint, no JWT auth required.
    """
    try:
        remotes = await rclone_list_remotes()
        # Return with trailing colon as v3 expects
        return {"ok": True, "remotes": [f"{r}:" for r in remotes]}
    except Exception as e:
        logger.error(f"Failed to list rclone remotes: {e}")
        return {"ok": False, "error": str(e), "remotes": []}


@router.post("/api/rclone/list-dirs")
async def list_remote_dirs(request: ListDirsRequest):
    """
    List directories in an rclone remote.

    LAN-only endpoint, no JWT auth required.
    """
    # Validate remote name
    remote_name = request.remote.rstrip(":")
    if not re.match(r"^[a-zA-Z0-9_-]+$", remote_name):
        return {"ok": False, "error": "Invalid remote name", "dirs": []}

    # Build full path
    full_path = f"{remote_name}:{request.path}" if request.path else f"{remote_name}:"

    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsf", full_path, "--dirs-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or "Failed to list directories"
            return {"ok": False, "error": error_msg, "dirs": []}

        # Parse directory names
        dirs = []
        for line in stdout.decode().strip().split("\n"):
            line = line.strip().rstrip("/")
            if not request.path and line == ".picframe":
                continue  # frames' album registries (frame_registry), not photos
            if line:
                # Check for invalid characters (like leading/trailing spaces)
                trimmed = line.strip()
                if trimmed != line:
                    dirs.append({
                        "name": line,
                        "valid": False,
                        "trimmed_name": trimmed,
                        "reason": "Name has leading/trailing spaces"
                    })
                else:
                    dirs.append({"name": line, "valid": True})

        return {"ok": True, "dirs": dirs}

    except FileNotFoundError:
        return {"ok": False, "error": "rclone not installed", "dirs": []}
    except Exception as e:
        logger.error(f"Failed to list remote dirs: {e}")
        return {"ok": False, "error": str(e), "dirs": []}


@router.get("/api/local/list-dirs")
async def list_local_dirs():
    """
    List directories in ~/Pictures for local storage selection.

    LAN-only endpoint, no JWT auth required.
    """
    pictures_path = Path.home() / "Pictures"
    base_path = str(pictures_path)

    if not pictures_path.exists():
        return {"ok": True, "dirs": [], "base_path": base_path}

    try:
        dirs = [
            {"name": d.name, "path": str(d)}
            for d in sorted(pictures_path.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]
        return {"ok": True, "dirs": dirs, "base_path": base_path}
    except Exception as e:
        logger.error(f"Failed to list local dirs: {e}")
        return {"ok": False, "error": str(e), "dirs": [], "base_path": base_path}


class FrameLiveRequest(BaseModel):
    """Request to switch active source."""
    target_dir: str


@router.post("/api/frame-live")
async def frame_live(request: FrameLiveRequest):
    """
    Switch to a different photo source and trigger sync.

    LAN-only endpoint, no JWT auth required.
    """
    # Find source by path
    sources = source_manager.list_sources()
    target_source = None
    for source in sources:
        if source.local_path == request.target_dir:
            target_source = source
            break

    if not target_source:
        return {"ok": False, "error": "Album not found for path"}

    target_path = Path(request.target_dir)
    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    try:
        # Switch display folder
        success = await display_service.switch_folder(target_path)
        if not success:
            return {"ok": False, "error": "Failed to switch folder"}

        # Update config
        config_manager.set("display.current_source", target_source.id)
        reload_settings()  # Clear cached settings

        # Trigger sync if remote configured
        sync_triggered = False
        if target_source.rclone_remote and not sync_service._is_syncing:
            asyncio.create_task(
                sync_service.sync_source(
                    source_id=target_source.id,
                    local_path=target_path,
                    rclone_remote=target_source.rclone_remote,
                )
            )
            sync_triggered = True

        logger.info(f"Switched to source '{target_source.id}' via dashboard")
        return {"ok": True, "sync_triggered": sync_triggered}

    except Exception as e:
        logger.error(f"Failed to switch source: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/config/test-remote")
async def test_remote_connection(request: dict):
    """
    Test rclone remote connection.

    LAN-only endpoint, no JWT auth required.
    """
    remote = request.get("remote", "")
    if not remote:
        return {"ok": False, "error": "No remote specified"}

    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsf", remote, "--max-depth", "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            # Count files/dirs
            lines = [l for l in stdout.decode().strip().split("\n") if l.strip()]
            return {"ok": True, "file_count": len(lines)}
        else:
            error_msg = stderr.decode().strip() or "Connection failed"
            return {"ok": False, "error": error_msg}

    except FileNotFoundError:
        return {"ok": False, "error": "rclone not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class SaveSettingsRequest(BaseModel):
    """Request to save frame settings."""
    frame_name: str
    rotation_interval: int
    sync_interval: int
    fade_time: float = Field(ge=0.5, le=30.0, description="Cross-fade duration in seconds (0.5 to 30)")

    @field_validator("sync_interval")
    @classmethod
    def must_be_valid_interval(cls, v: int) -> int:
        if v not in VALID_SYNC_INTERVALS:
            raise ValueError(f"sync_interval must be one of {sorted(VALID_SYNC_INTERVALS)}")
        return v


class PartyModeRequest(BaseModel):
    """Request to enable or disable party mode."""
    enabled: bool


@router.post("/api/settings")
async def save_settings_api(request: SaveSettingsRequest):
    """
    Save frame settings from the dashboard.

    LAN-only endpoint, no JWT auth required.
    Writes to picframe's configuration.yaml and restarts if needed.
    """
    try:
        # Read current picframe config
        if PICFRAME_CONFIG_PATH.exists():
            with open(PICFRAME_CONFIG_PATH) as f:
                picframe_config = yaml.safe_load(f) or {}
        else:
            logger.error(f"Picframe config not found: {PICFRAME_CONFIG_PATH}")
            return {"ok": False, "error": "Display config file not found"}

        # Check if rotation interval or fade_time is changing
        current_delay = picframe_config.get("model", {}).get("time_delay", 30)
        current_fade = picframe_config.get("model", {}).get("fade_time", 2.0)
        rotation_changed = float(current_delay) != float(request.rotation_interval)
        fade_changed = float(current_fade) != float(request.fade_time)

        # Update picframe config
        if "model" not in picframe_config:
            picframe_config["model"] = {}
        picframe_config["model"]["time_delay"] = float(request.rotation_interval)
        picframe_config["model"]["fade_time"] = float(request.fade_time)

        # Write picframe config
        with open(PICFRAME_CONFIG_PATH, "w") as f:
            yaml.safe_dump(picframe_config, f, default_flow_style=False)

        logger.info(f"Picframe config saved: time_delay={request.rotation_interval}, fade_time={request.fade_time}")

        # Also save to v4 dashboard config
        settings = get_settings()
        current_sync_interval = settings.sync.interval
        config_manager.set("frame.name", request.frame_name)
        config_manager.set("display.rotation_interval", request.rotation_interval)
        config_manager.set("sync.interval", request.sync_interval)
        reload_settings()

        # Restart picframe if rotation interval or fade_time changed
        restarted = False
        if rotation_changed or fade_changed:
            logger.info("Rotation interval changed, restarting picframe service")
            restarted = await systemd_service.restart("picframe")
            if restarted:
                logger.info("Picframe service restarted successfully")
            else:
                logger.warning("Failed to restart picframe service")

        # Update systemd sync timer if interval changed
        if request.sync_interval != current_sync_interval:
            await update_sync_timer(request.sync_interval)

        return {"ok": True, "restarted": restarted}
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return {"ok": False, "error": str(e)}


VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


class LogLevelRequest(BaseModel):
    """Request to change the log level."""
    log_level: str

    @field_validator("log_level")
    @classmethod
    def must_be_valid_level(cls, v: str) -> str:
        if v.upper() not in VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {sorted(VALID_LOG_LEVELS)}")
        return v.upper()


@router.post("/api/settings/log-level")
async def save_log_level(request: LogLevelRequest):
    """
    Update log level without touching other frame settings.

    LAN-only endpoint, no JWT auth required.
    """
    try:
        config_manager.set("logging.level", request.log_level)
        reload_settings()
        return {"ok": True, "log_level": request.log_level}
    except Exception as e:
        logger.error(f"Failed to save log level: {e}")
        return {"ok": False, "error": str(e)}


class SleepScheduleRequest(BaseModel):
    """Request to save the display sleep schedule."""
    enabled: bool
    sleep_time: str
    wake_time: str


@router.post("/api/settings/sleep-schedule")
async def save_sleep_schedule(request: SleepScheduleRequest):
    """
    Save display sleep schedule.

    LAN-only endpoint, no JWT auth required.
    """
    config_manager.set("display.sleep_enabled", request.enabled)
    config_manager.set("display.sleep_time", request.sleep_time)
    config_manager.set("display.wake_time", request.wake_time)
    reload_settings()
    success = await update_sleep_timers(request.enabled, request.sleep_time, request.wake_time)
    if not success:
        return {"success": False, "message": "Settings saved but failed to update systemd timers"}
    if request.enabled:
        msg = f"Sleep schedule enabled: off at {request.sleep_time}, on at {request.wake_time}"
    else:
        msg = "Sleep schedule disabled"
    return {"success": True, "message": msg}


@router.post("/dashboard/test-lights")
async def test_lights(request: Request):
    """
    Set in-memory light overrides for manual testing.

    Body: {"sync_status": "error"|"match"|null, "wifi_connected": true|false|null}
    Passing null removes the override and restores real behavior.
    LAN-only endpoint, no JWT auth required.
    """
    body = await request.json()
    if "sync_status" in body:
        if body["sync_status"] is None:
            _light_overrides.pop("sync_status", None)
        else:
            _light_overrides["sync_status"] = body["sync_status"]
    if "wifi_connected" in body:
        if body["wifi_connected"] is None:
            _light_overrides.pop("wifi_connected", None)
        else:
            _light_overrides["wifi_connected"] = body["wifi_connected"]
    return {"ok": True, "overrides": _light_overrides}


class DemoModeRequest(BaseModel):
    """Request to turn demo mode on or off."""
    enabled: bool


@router.post("/api/settings/demo")
async def toggle_demo_mode(request: DemoModeRequest):
    """
    Turn demo mode (reusable reviewer pairing codes, PL-015) on or off.

    On: codes work for 14 days. Off: codes stop and demo-paired devices are revoked.
    Only on frames with demo.allowed: true. LAN-only endpoint, no JWT auth required.
    """
    try:
        if request.enabled:
            demo_service.enable_demo()
            return {"ok": True, "demo": demo_service.demo_status()}
        revoked = demo_service.disable_demo()
        return {"ok": True, "revoked": revoked, "demo": demo_service.demo_status()}
    except demo_service.DemoNotAllowedError as e:
        return JSONResponse(status_code=403, content={"ok": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Failed to toggle demo mode: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/settings/demo/regenerate")
async def regenerate_demo_codes():
    """
    Replace both demo codes and restart the 14 days. Already-paired demo phones stay paired.

    Only on frames with demo.allowed: true. LAN-only endpoint, no JWT auth required.
    """
    try:
        return {"ok": True, "demo": demo_service.regenerate_demo_codes()}
    except demo_service.DemoNotAllowedError as e:
        return JSONResponse(status_code=403, content={"ok": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Failed to regenerate demo codes: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/settings/demo/baseline")
async def save_demo_baseline():
    """
    Save the frame's albums, photos, showing album and settings as the demo baseline (PL-151).

    Only on frames with demo.allowed and a dedicated Koofr account. LAN-only endpoint, no JWT auth required.
    """
    try:
        return {"ok": True, "baseline": await demo_reset_service.save_baseline()}
    except demo_reset_service.DemoResetError as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": e.message})
    except Exception as e:
        logger.error(f"Failed to save the demo baseline: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/settings/demo/reset")
async def reset_demo_frame():
    """
    Put the demo frame back to its baseline (PL-151): phones, invites, upload links,
    albums and cloud folders, settings; demo mode on for 14 more days.

    Only on frames with demo.allowed and a dedicated Koofr account. LAN-only endpoint, no JWT auth required.
    """
    try:
        return {"ok": True, **await demo_reset_service.reset_to_baseline()}
    except demo_reset_service.DemoResetError as e:
        logger.error(f"Demo frame reset stopped: {e.message}")
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": e.message})
    except Exception as e:
        logger.error(f"Demo frame reset failed: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/system/reboot")
async def reboot_frame_dashboard(request: Request):
    """
    Reboot the frame a few seconds from now (PL-142). LAN-only endpoint, no JWT auth required.
    """
    if not await power_service.reboot_available():
        return {"ok": False, "error": power_service.NOT_SET_UP_MESSAGE}
    client_ip = request.client.host if request.client else None
    power_service.schedule_reboot("dashboard", ip=client_ip)
    return {"ok": True, "delay_seconds": power_service.REBOOT_DELAY_SECONDS}


@router.post("/api/settings/party")
async def toggle_party_mode(request: PartyModeRequest):
    """
    Enable or disable party mode.

    Party mode stops cloud sync and WiFi watchdog so the frame runs as a
    standalone local slideshow. LAN-only endpoint, no JWT auth required.
    """
    try:
        settings = get_settings()
        if request.enabled:
            result = await enable_party()
            logger.info("Party mode enabled")
        else:
            result = await disable_party(settings.sync.interval)
            logger.info("Party mode disabled")

        config_manager.set("display.party_mode", request.enabled)
        reload_settings()

        return {"ok": result["ok"], "party_mode": request.enabled, **result}
    except Exception as e:
        logger.error(f"Failed to toggle party mode: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/api/updates/settings")
async def get_update_settings():
    """
    Get current update configuration and last check result.

    LAN-only endpoint, no JWT auth required.
    """
    return await get_update_status()


@router.post("/api/updates/check")
async def check_for_updates_api():
    """
    Trigger an immediate update check.

    LAN-only endpoint, no JWT auth required.
    """
    return await run_update_check()


@router.post("/api/updates/schedule")
async def save_update_schedule_api(request: SaveUpdateScheduleRequest):
    """
    Save update schedule configuration.

    LAN-only endpoint, no JWT auth required.
    """
    return save_update_schedule(request)


# =============================================================================
# LAN-only Thumbnail API (no JWT auth - protected by LAN middleware)
# Serves thumbnails for the Tools tab. Accepts filenames with special chars
# (Google Photos IDs, spaces) that the JWT thumbnail endpoint rejects.
# =============================================================================

DASH_THUMB_SIZE = (128, 128)


@router.get("/api/thumbnail/{source_id}")
async def dashboard_thumbnail(source_id: str, filename: str = Query(...)):
    """Return a JPEG thumbnail for any photo in a source. LAN-only, no JWT."""
    if not _validate_filename_raw(filename):
        return Response(status_code=400)
    source = source_manager.get_source(source_id)
    if not source:
        return Response(status_code=404)
    local_file = Path(source.local_path).expanduser() / filename
    if not local_file.is_file():
        return Response(status_code=404)
    try:
        local_file.resolve().relative_to(Path(source.local_path).expanduser().resolve())
    except ValueError:
        return Response(status_code=400)

    try:
        jpeg_bytes = await thumbnails.get_thumbnail(
            local_file, source_id, filename, DASH_THUMB_SIZE, quality=70, prefix="dash_"
        )
        return Response(content=jpeg_bytes, media_type="image/jpeg")
    except Exception as exc:
        logger.warning(f"Thumbnail failed for {filename}: {exc}")
        return Response(status_code=500)


# =============================================================================
# LAN-only Photo Tools API (no JWT auth - protected by LAN middleware)
# Same service layer as /api/v1/sources/{id}/tools/* — no duplication.
# =============================================================================


@router.get("/api/tools/{source_id}/scan/files")
async def tools_scan_files(source_id: str):
    """List all files in a source with EXIF dates. LAN-only, no JWT."""
    try:
        result = photo_tools.scan_files(source_id)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools scan_files error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/{source_id}/scan/filenames")
async def tools_scan_filenames(source_id: str):
    """Scan for filename issues. LAN-only, no JWT."""
    try:
        result = photo_tools.scan_filenames(source_id)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools scan_filenames error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/apply/filenames")
async def tools_apply_filenames(source_id: str, request: dict):
    """Apply filename fixes. LAN-only, no JWT."""
    fixes_raw = request.get("fixes", [])
    try:
        fixes = [photo_tools.FilenameFix(**f) for f in fixes_raw]
        result = await photo_tools.apply_filenames(source_id, fixes)
        return {"ok": True, **result.model_dump()}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools apply_filenames error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/{source_id}/scan/duplicates")
async def tools_scan_duplicates(source_id: str):
    """Scan for exact duplicates. LAN-only, no JWT."""
    try:
        result = photo_tools.scan_duplicates(source_id)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools scan_duplicates error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/apply/duplicates")
async def tools_apply_duplicates(source_id: str, request: dict):
    """Delete selected duplicates. LAN-only, no JWT."""
    to_delete = request.get("to_delete", [])
    if not to_delete:
        return {"ok": False, "error": "to_delete list is empty"}
    try:
        result = await photo_tools.apply_duplicates(source_id, to_delete)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools apply_duplicates error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/{source_id}/scan/videos")
async def tools_scan_videos(source_id: str):
    """Scan for video files. LAN-only, no JWT."""
    try:
        result = photo_tools.scan_videos(source_id)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools scan_videos error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/apply/videos")
async def tools_apply_videos(source_id: str, request: dict):
    """Delete selected video files. LAN-only, no JWT."""
    to_delete = request.get("to_delete", [])
    if not to_delete:
        return {"ok": False, "error": "to_delete list is empty"}
    try:
        result = await photo_tools.apply_videos(source_id, to_delete)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools apply_videos error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/{source_id}/scan/corrupt")
async def tools_scan_corrupt(source_id: str):
    """Find empty or undecodable photos (PL-127). LAN-only, no JWT."""
    try:
        result = await asyncio.to_thread(photo_tools.scan_corrupt, source_id)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools scan_corrupt error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/apply/corrupt")
async def tools_apply_corrupt(source_id: str, request: dict):
    """Delete the chosen unreadable photos, cloud first (PL-127). LAN-only, no JWT."""
    to_delete = request.get("to_delete", [])
    if not to_delete:
        return {"ok": False, "error": "to_delete list is empty"}
    try:
        result = await photo_tools.apply_corrupt(source_id, to_delete)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools apply_corrupt error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/rotate")
async def tools_rotate(source_id: str, request: dict):
    """Rotate photos: {"items": [{"filename", "rotate": left|right|180|auto}]} (PL-126). LAN-only, no JWT."""
    try:
        items = [photo_tools.RotateItem(**i) for i in request.get("items", [])]
    except Exception:
        return {"ok": False, "error": "items must be a list of {filename, rotate}"}
    if not items:
        return {"ok": False, "error": "items list is empty"}
    try:
        result = await photo_tools.rotate_photos(source_id, items)
        return {"ok": True, **result.model_dump()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools rotate error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/{source_id}/rename")
async def tools_rename_file(source_id: str, request: dict):
    """Rename a single file by name (cloud-first). LAN-only, no JWT."""
    original = (request.get("original") or "").strip()
    proposed = (request.get("proposed") or "").strip()
    if not original or not proposed:
        return {"ok": False, "error": "original and proposed are required"}
    if not _validate_filename_raw(original) or not _validate_filename_raw(proposed):
        return {"ok": False, "error": "Invalid filename"}
    if original == proposed:
        return {"ok": False, "error": "Original and new name are the same"}
    try:
        result = await photo_tools.rename_file(source_id, original, proposed)
        if result.succeeded:
            return {"ok": True}
        err = result.failed[0]["error"] if result.failed else "Rename failed"
        return {"ok": False, "error": err}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"tools rename_file error: {exc}")
        return {"ok": False, "error": str(exc)}


class DeleteBackupRequest(BaseModel):
    """Request body for deleting a backup archive."""
    filename: str


@router.get("/api/tools/backup/all")
async def list_all_backups():
    """Every backup on the frame, deleted albums' too, newest first. LAN-only, no JWT."""
    try:
        return {"ok": True, "backups": recovery_service.list_all_backups()}
    except Exception as exc:
        logger.error("backup list-all error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/backup/all/create")
async def create_frame_backup():
    """Back up every album into one whole-frame archive. LAN-only, no JWT."""
    try:
        result = await backup_service.create_frame_backup(
            source_manager.list_sources(), get_settings().frame.name, frame_registry.board_serial())
        return {"ok": True, **result}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("backup create-all error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/backup/download/{filename}")
async def download_backup(filename: str):
    """Download a backup archive to the computer (keep a copy off the frame). LAN-only, no JWT."""
    try:
        path = backup_service.backup_path(filename)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except FileNotFoundError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    return FileResponse(path, media_type="application/gzip", filename=path.name)


@router.post("/api/tools/backup/delete")
async def delete_backup_by_name(body: DeleteBackupRequest):
    """Delete any backup archive by filename (a deleted album's too). LAN-only, no JWT."""
    try:
        backup_service.delete_backup_file(body.filename)
        return {"ok": True}
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("backup delete error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/api/tools/backup/{source_id}/list")
async def list_source_backups(source_id: str):
    """List existing tar.gz backups for a source. LAN-only, no JWT."""
    source = source_manager.get_source(source_id)
    if not source:
        return {"ok": False, "error": "Album not found"}
    try:
        backups = backup_service.list_backups(source_id)
        return {"ok": True, "backups": backups}
    except Exception as exc:
        logger.error("backup list error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/backup/{source_id}/create")
async def create_source_backup(source_id: str):
    """Create a tar.gz backup of the source's local photos. LAN-only, no JWT."""
    source = source_manager.get_source(source_id)
    if not source:
        return {"ok": False, "error": "Album not found"}
    try:
        result = await backup_service.create_backup(source_id, source.local_path)
        return {"ok": True, **result}
    except Exception as exc:
        logger.error("backup create error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/api/tools/backup/{source_id}/delete")
async def delete_source_backup(source_id: str, body: DeleteBackupRequest):
    """Delete a backup archive. LAN-only, no JWT."""
    source = source_manager.get_source(source_id)
    if not source:
        return {"ok": False, "error": "Album not found"}
    try:
        backup_service.delete_backup(source_id, body.filename)
        return {"ok": True}
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("backup delete error: %s", exc)
        return {"ok": False, "error": str(exc)}


# --- Recover albums (PL-147 follow-up) ---------------------------------------

class RecoverCloudRequest(BaseModel):
    """Re-add an album from an unused cloud folder (allow_unclaimed: shared-account warning accepted)."""
    folder: str
    name: str
    allow_unclaimed: bool = False


class FrameSwapRequest(BaseModel):
    """Answer to "did this SD card move to a new Pi?" (moved) or was it copied (not moved)."""
    moved: bool


class TakeOverRequest(BaseModel):
    """Take over another frame's albums; confirm_name is needed if it checked in within 24 h."""
    serial: str
    confirm_name: str = ""


class RestoreBackupRequest(BaseModel):
    """Restore a backup into an existing album (target_id) or a new one (new_name)."""
    filename: str
    target_id: Optional[str] = None
    new_name: Optional[str] = None


@router.get("/api/albums/recoverable")
async def list_recoverable():
    """
    This frame's deleted albums in the cloud, unclaimed cloud folders, other
    frames on the cloud account, and every backup (deleted albums' too).

    The cloud part can fail on its own (no Koofr, offline); backups are still listed.
    LAN-only, no JWT.
    """
    try:
        cloud = await recovery_service.list_recoverable_cloud_folders()
        cloud_error = None
    except recovery_service.RecoveryError as e:
        cloud = {"cloud": [], "unclaimed": [], "unclaimed_needs_confirm": True, "frames": []}
        cloud_error = e.message
    return {"ok": True, **cloud, "cloud_error": cloud_error, "backups": recovery_service.list_all_backups()}


@router.post("/api/albums/recover-cloud")
async def recover_cloud_album(body: RecoverCloudRequest):
    """Re-add an album pointed at an unused cloud folder, then sync it. LAN-only, no JWT."""
    try:
        return {"ok": True, **await recovery_service.recover_from_cloud(body.folder, body.name, body.allow_unclaimed)}
    except recovery_service.RecoveryError as e:
        return {"ok": False, "error": e.message}


@router.post("/api/albums/frame-swap")
async def frame_swap(body: FrameSwapRequest):
    """Confirm whether this SD card moved to a new Pi or was copied. LAN-only, no JWT."""
    try:
        return {"ok": True, **await frame_registry.resolve_swap(body.moved)}
    except frame_registry.RegistryError as e:
        return {"ok": False, "error": e.message}


@router.post("/api/albums/take-over")
async def take_over_frame(body: TakeOverRequest):
    """Take over another frame's albums (new board, fresh SD card). LAN-only, no JWT."""
    try:
        return {"ok": True, **await frame_registry.take_over(body.serial, body.confirm_name)}
    except frame_registry.RegistryError as e:
        return {"ok": False, "error": e.message}


@router.post("/api/albums/undo-takeover")
async def undo_takeover():
    """Clear another Pi's takeover of this frame. LAN-only, no JWT."""
    try:
        return {"ok": True, **await frame_registry.undo_takeover()}
    except frame_registry.RegistryError as e:
        return {"ok": False, "error": e.message}


@router.post("/api/albums/restore-backup")
async def restore_backup_api(body: RestoreBackupRequest):
    """Restore a backup's photos into an album (and its cloud folder). LAN-only, no JWT."""
    try:
        return {"ok": True, **await recovery_service.restore_backup(body.filename, body.target_id, body.new_name)}
    except recovery_service.RecoveryError as e:
        return {"ok": False, "error": e.message}


ARCHIVE_MAGIC = {b"PK\x03\x04": ".zip", b"\x1f\x8b": ".tar.gz"}


@router.post("/api/albums/upload-archive")
async def upload_archive(request: Request, target_id: Optional[str] = None, new_name: Optional[str] = None):
    """
    Upload a .zip or .tar.gz of photos and add them to an album (and its cloud folder).

    The raw request body is the archive. It's streamed to ~/Pictures/backups (not
    /tmp, which can be RAM) and always deleted afterwards. LAN-only, no JWT.
    """
    length = int(request.headers.get("content-length") or 0)
    if length <= 0:
        return {"ok": False, "error": "No file received."}
    if length > recovery_service.MAX_UPLOAD_BYTES:
        return {"ok": False, "error": f"The file is too big; the limit is {recovery_service.MAX_UPLOAD_BYTES // 1024 ** 3} GB."}
    backup_service.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if length > shutil.disk_usage(backup_service.BACKUPS_DIR).free - recovery_service.FREE_SPACE_MARGIN:
        return {"ok": False, "error": "Not enough free space on the frame for this file."}

    incoming = backup_service.BACKUPS_DIR / f".incoming-{uuid.uuid4().hex}"
    try:
        received = 0
        with open(incoming, "wb") as f:
            async for chunk in request.stream():
                received += len(chunk)
                if received > recovery_service.MAX_UPLOAD_BYTES:
                    return {"ok": False, "error": "The file is too big."}
                f.write(chunk)
        with open(incoming, "rb") as f:
            head = f.read(4)
        if not any(head.startswith(magic) for magic in ARCHIVE_MAGIC):
            return {"ok": False, "error": "That isn't a .zip or .tar.gz file."}

        # A whole-frame backup restores every album; the album choice doesn't apply
        if await asyncio.to_thread(recovery_service.frame_manifest_or_error, incoming):
            return {"ok": True, **await recovery_service.restore_frame_backup(incoming)}
        source = await recovery_service.resolve_target(target_id, new_name)
        result = await recovery_service.restore_into_album(source, incoming)
        return {"ok": True, **result}
    except recovery_service.RecoveryError as e:
        return {"ok": False, "error": e.message}
    finally:
        incoming.unlink(missing_ok=True)


@router.post("/api/updates/apply")
async def apply_update_api():
    """
    Apply available updates by running git pull.

    LAN-only endpoint, no JWT auth required.
    """
    return await apply_update_and_restart("dashboard")


@router.post("/api/cloud/test")
async def test_cloud_connection():
    """
    Test the Koofr rclone connection.

    If the rclone remote is missing but credentials are stored in config,
    auto-creates the remote and backfills sources before testing.
    LAN-only endpoint, no JWT auth required.
    """
    koofr_user = _get_koofr_user()
    if not koofr_user:
        return {"ok": False, "error": "Koofr not configured — enter credentials and save first."}

    # Check if rclone remote exists; create it from stored credentials if not
    remotes = await rclone_list_remotes()
    if "koofr" not in remotes:
        koofr_pass = _get_koofr_pass()
        if not koofr_pass:
            return {"ok": False, "error": "Koofr password not found in config — re-enter credentials and save."}

        try:
            obscure_proc = await asyncio.create_subprocess_exec(
                "rclone", "obscure", koofr_pass,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(obscure_proc.communicate(), timeout=5)
            if obscure_proc.returncode != 0:
                return {"ok": False, "error": "Failed to process stored password."}
            obscured = stdout.decode().strip()
        except Exception as e:
            return {"ok": False, "error": f"rclone obscure failed: {e}"}

        try:
            create_proc = await asyncio.create_subprocess_exec(
                "rclone", "config", "create", "koofr", "koofr",
                "user", koofr_user, "password", obscured,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(create_proc.communicate(), timeout=15)
            if create_proc.returncode != 0:
                return {"ok": False, "error": f"Failed to create rclone remote: {stderr.decode().strip()}"}
            logger.info("Koofr rclone remote auto-created during test")
        except Exception as e:
            return {"ok": False, "error": f"rclone config create failed: {e}"}

        # Backfill sources now that the remote exists
        updated = source_manager.backfill_remotes()
        if updated:
            logger.info(f"Backfilled sources during test: {updated}")

    # Test the live connection
    try:
        test_proc = await asyncio.create_subprocess_exec(
            "rclone", "lsd", "koofr:",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(test_proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Connection timed out — check your internet connection."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if test_proc.returncode == 0:
        sources_with_remote = sum(1 for s in source_manager.list_sources() if s.rclone_remote)
        _set_koofr_configured()
        _restore_setup_image()
        return {
            "ok": True,
            "message": f"Connected to Koofr successfully. {sources_with_remote} album(s) ready to sync.",
        }
    return {"ok": False, "error": f"Koofr connection failed: {stderr.decode().strip() or 'unknown error'}"}
