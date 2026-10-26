"""
WanderWall - Demo frame reset (PL-151).

Puts the App Review frame back to a known state after a reviewer session, from
the dashboard's Demo Mode card:

- Save as baseline: copies the albums (photos on the frame), the showing album
  and the settings a reviewer can change into ~/.wanderwall/demo_baseline.
- Reset to baseline: removes demo-paired and Share (contributor) phones, every
  invite and every Koofr upload link; makes each baseline album and its cloud
  folder match the saved photos again; deletes other albums and every other
  KFR_* cloud folder; restores the showing album, frame name, rotation and sync
  interval; turns demo mode on for another 14 days with the same codes.

Only on frames with demo.allowed, and only on a dedicated Koofr account (the
album registry says so) whose login matches the one the baseline was saved
with, because the reset deletes cloud folders.
"""

import asyncio
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from src.config.manager import config_manager
from src.config.settings import get_settings, reload_settings
from src.services import album_service, backup_service, demo_service, frame_registry
from src.services import source_manager as sources
from src.services.display_service import display_service
from src.services.source_manager import PhotoSource
from src.services.sync_service import sync_service
from src.services.systemd_service import VALID_SYNC_INTERVALS, systemd_service, update_sync_timer
from src.storage.devices import device_storage
from src.storage.invites import invite_storage
from src.utils.logging import log_auth_event
from src.utils.rclone import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, rclone_purge, rclone_sync_up

logger = logging.getLogger(__name__)

BASELINE_DIR = Path.home() / ".wanderwall" / "demo_baseline"
BASELINE_FILE = "baseline.yaml"
PICFRAME_CONFIG_PATH = Path.home() / "picframe_data" / "config" / "configuration.yaml"
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
KOOFR_API = "https://app.koofr.net/api/v2.1"
KOOFR_TIMEOUT_SECONDS = 20
KOOFR_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
NAME_RE = re.compile(r"^[a-zA-Z0-9 _\-]{1,50}$")
SYNC_WAIT_SECONDS = 300

# One save or reset at a time
_lock = asyncio.Lock()


class DemoResetError(Exception):
    """A save or reset can't go ahead; `status_code` is the HTTP status to answer with."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --- Checks --------------------------------------------------------------------

def _require_allowed() -> None:
    """Only on the review frame (demo.allowed set by hand)."""
    if not get_settings().demo.allowed:
        raise DemoResetError(403, "Demo reset is only available on a frame with demo.allowed: true.")


def _require_dedicated(koofr_user: Optional[str] = None) -> dict[str, Any]:
    """
    The album registry must say this frame has the Koofr account to itself
    (and, for a reset, the same login as the baseline).

    Returns:
        The registry document
    """
    doc = frame_registry.local_doc()
    if doc["account"] != "dedicated":
        raise DemoResetError(
            409, "The Koofr account isn't marked dedicated to this frame, so the reset won't delete "
                 "cloud folders on it. Use a Koofr account only this frame uses.")
    if koofr_user and doc["koofr_user"] != koofr_user:
        raise DemoResetError(
            409, "The Koofr account changed since the baseline was saved. Save a new baseline first.")
    return doc


async def _wait_for_sync() -> None:
    """Wait for a running sync to finish (a scheduled one may be underway)."""
    for _ in range(SYNC_WAIT_SECONDS):
        if not sync_service._is_syncing:
            return
        await asyncio.sleep(1)
    raise DemoResetError(409, "A sync has been running for 5 minutes. Try again when it has finished.")


async def _sync(source: PhotoSource) -> bool:
    """Sync one album from the cloud, waiting for any other sync first. True on success."""
    for _ in range(3):
        await _wait_for_sync()
        try:
            result = await sync_service.sync_source(
                source_id=source.id, local_path=Path(source.local_path).expanduser(),
                rclone_remote=source.rclone_remote)
            return result.success
        except RuntimeError:  # a scheduled sync started in between
            continue
    return False


# --- Baseline --------------------------------------------------------------------

def _media_files(folder: Path) -> list[Path]:
    """Photos and videos directly in an album folder (regular files only)."""
    if not folder.is_dir():
        return []
    return sorted(
        f for f in folder.iterdir()
        if f.is_file() and not f.is_symlink() and f.suffix.lower() in MEDIA_EXTENSIONS
    )


def baseline_info() -> Optional[dict[str, Any]]:
    """The saved baseline's summary for the dashboard, or None if there isn't one."""
    try:
        data = yaml.safe_load((BASELINE_DIR / BASELINE_FILE).read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("albums"), list):
        return None
    return data


def _copy_baseline(albums: list[tuple[PhotoSource, str]], target: Path) -> int:
    """Copy each album's photos into target/photos/<cloud folder>. Returns the file count."""
    count = 0
    for source, folder in albums:
        dest = target / "photos" / folder
        dest.mkdir(parents=True, exist_ok=True)
        for f in _media_files(Path(source.local_path).expanduser()):
            shutil.copy2(f, dest / f.name)
            count += 1
    return count


async def save_baseline() -> dict[str, Any]:
    """
    Save the frame's current albums, photos, showing album and settings as the demo baseline.

    Returns:
        The saved baseline summary

    Raises:
        DemoResetError: not allowed, account not dedicated, no albums, an album without a
        cloud folder, a sync running, or not enough free space
    """
    _require_allowed()
    async with _lock:
        doc = _require_dedicated()
        settings = get_settings()
        current = sources.source_manager.list_sources()
        albums = []
        for source in current:
            folder = frame_registry._folder_of(source.rclone_remote)
            if not folder:
                raise DemoResetError(409, f"Album '{source.name}' has no cloud folder, so it can't be restored.")
            albums.append((source, folder))
        if not albums:
            raise DemoResetError(409, "There are no albums to save.")
        showing = next((f for s, f in albums if s.id == settings.display.current_source), None)
        if showing is None:
            raise DemoResetError(409, "Show one of the albums on the frame first.")
        await _wait_for_sync()

        size = sum(f.stat().st_size for s, _ in albums for f in _media_files(Path(s.local_path).expanduser()))
        BASELINE_DIR.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(BASELINE_DIR.parent).free < size + backup_service.FREE_SPACE_MARGIN:
            raise DemoResetError(507, "Not enough free space on the frame to save the baseline.")

        new = BASELINE_DIR.with_name(BASELINE_DIR.name + ".new")
        old = BASELINE_DIR.with_name(BASELINE_DIR.name + ".old")
        shutil.rmtree(new, ignore_errors=True)
        try:
            photos = await asyncio.to_thread(_copy_baseline, albums, new)
            data = {
                "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "koofr_user": doc["koofr_user"],
                "frame_name": settings.frame.name,
                "rotation_interval": settings.display.rotation_interval,
                "sync_interval": settings.sync.interval,
                "showing": showing,
                "photos": photos,
                "albums": [
                    {"folder": f, "name": s.name,
                     "photos": len(list((new / "photos" / f).iterdir()))}
                    for s, f in albums
                ],
            }
            (new / BASELINE_FILE).write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
            new.chmod(0o700)
            shutil.rmtree(old, ignore_errors=True)
            if BASELINE_DIR.exists():
                BASELINE_DIR.rename(old)
            new.rename(BASELINE_DIR)
            shutil.rmtree(old, ignore_errors=True)
        except OSError as e:
            shutil.rmtree(new, ignore_errors=True)
            logger.error(f"Failed to save the demo baseline: {e}")
            raise DemoResetError(500, f"Couldn't save the baseline: {e}")

    logger.info(f"Demo baseline saved: {len(albums)} album(s), {photos} photo(s), showing {showing}")
    log_auth_event("DEMO_BASELINE_SAVE", success=True, details={"albums": len(albums), "photos": photos})
    return data


# --- Koofr upload links ------------------------------------------------------------

async def _koofr_login() -> Optional[tuple[str, str]]:
    """The frame's Koofr email and app password, from the rclone config."""
    # The same lookup GET /api/v1/cloud/credentials uses
    from src.api.routes.cloud import _get_rclone_koofr_credentials
    creds = await _get_rclone_koofr_credentials()
    return (creds.email, creds.password) if creds else None


async def _remove_upload_links() -> int:
    """
    Delete every Koofr upload link (receiver) on the account.

    Uses Koofr's REST API with Basic auth and the app password
    (app.koofr.net/api/v2/swagger.json: GET /api/v2.1/receivers,
    DELETE /api/v2.1/mounts/{mountId}/receivers/{receiverId}).

    Returns:
        Number of links deleted

    Raises:
        DemoResetError: no login, or Koofr refused or couldn't be reached
    """
    login = await _koofr_login()
    if not login:
        raise DemoResetError(502, "No Koofr login on this frame.")
    try:
        async with httpx.AsyncClient(auth=login, timeout=KOOFR_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{KOOFR_API}/receivers")
            if resp.status_code != 200:
                raise DemoResetError(502, f"Koofr didn't list the upload links (HTTP {resp.status_code}).")
            deleted = 0
            for r in resp.json().get("receivers", []):
                mount, rid = str(r.get("mountId", "")), str(r.get("id", ""))
                if not (KOOFR_ID_RE.match(mount) and KOOFR_ID_RE.match(rid)):
                    logger.warning(f"Skipping an upload link with an unexpected id: {mount}/{rid}")
                    continue
                d = await client.delete(f"{KOOFR_API}/mounts/{mount}/receivers/{rid}")
                if d.status_code not in (200, 204):
                    raise DemoResetError(502, f"Koofr didn't delete an upload link (HTTP {d.status_code}).")
                deleted += 1
            return deleted
    except httpx.HTTPError as e:
        raise DemoResetError(502, f"Couldn't reach Koofr: {e}")
    except ValueError as e:  # not JSON
        raise DemoResetError(502, f"Unexpected answer from Koofr: {e}")


# --- Settings ----------------------------------------------------------------------

async def _restore_settings(base: dict[str, Any]) -> list[str]:
    """Put back the frame name, rotation and sync interval. Returns what changed."""
    settings = get_settings()
    changed = []
    name = str(base.get("frame_name", ""))
    if NAME_RE.match(name) and settings.frame.name != name:
        config_manager.set("frame.name", name)
        changed.append("frame name")
    rotation = base.get("rotation_interval")
    if isinstance(rotation, int) and 5 <= rotation <= 3600 and settings.display.rotation_interval != rotation:
        config_manager.set("display.rotation_interval", rotation)
        if PICFRAME_CONFIG_PATH.exists():
            try:
                cfg = yaml.safe_load(PICFRAME_CONFIG_PATH.read_text()) or {}
                cfg.setdefault("model", {})["time_delay"] = float(rotation)
                PICFRAME_CONFIG_PATH.write_text(yaml.safe_dump(cfg, default_flow_style=False))
            except (OSError, yaml.YAMLError) as e:
                logger.error(f"Couldn't write the rotation to {PICFRAME_CONFIG_PATH}: {e}")
        await systemd_service.restart("picframe")
        changed.append("rotation")
    interval = base.get("sync_interval")
    if interval in VALID_SYNC_INTERVALS and settings.sync.interval != interval:
        config_manager.set("sync.interval", interval)
        await update_sync_timer(interval)
        changed.append("sync interval")
    reload_settings()
    return changed


# --- Reset -------------------------------------------------------------------------

async def _show(source: PhotoSource) -> None:
    """Show an album on the frame, as POST /display/folder does (without its background sync)."""
    path = Path(source.local_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    if not await display_service.switch_folder(path):
        raise DemoResetError(500, f"Couldn't show album '{source.name}' on the frame.")
    config_manager.set("display.current_source", source.id)
    reload_settings()


async def reset_to_baseline() -> dict[str, Any]:
    """
    Put the demo frame back to the saved baseline (see the module docstring).

    Returns:
        phones_removed, invites_removed, upload_links_removed, albums [{name, photos, synced}],
        albums_deleted, cloud_folders_deleted, settings_restored, demo (demo_status())

    Raises:
        DemoResetError: not allowed, no baseline, account not dedicated or changed, or a
        step failed (the message says which)
    """
    _require_allowed()
    async with _lock:
        base = baseline_info()
        if not base:
            raise DemoResetError(409, "No baseline saved yet. Set the frame up, then Save as Baseline.")
        _require_dedicated(base.get("koofr_user"))
        remote = await frame_registry._koofr_remote()
        if not remote:
            raise DemoResetError(502, "No Koofr cloud storage is set up on this frame.")
        await _wait_for_sync()

        phones = device_storage.remove_demo_and_contributor_devices()
        invites = invite_storage.revoke_all()
        links = await _remove_upload_links()

        # Baseline albums: back on the frame (same cloud folder), same name, cloud = saved photos
        wanted = [a for a in base["albums"] if frame_registry.FOLDER_RE.match(str(a.get("folder", "")))]
        if not wanted:
            raise DemoResetError(409, "The baseline has no albums. Save a new baseline.")
        restored: dict[str, PhotoSource] = {}
        for album in wanted:
            folder = album["folder"]
            source = next((s for s in sources.source_manager.list_sources()
                           if frame_registry._folder_of(s.rclone_remote) == folder), None)
            if source is None:
                source = await asyncio.to_thread(
                    sources.source_manager.create_source, album["name"], f"{remote}:{folder}")
            elif source.name != album["name"]:
                source.name = album["name"]
                sources.source_manager.update_source(source)
            result = await rclone_sync_up(BASELINE_DIR / "photos" / folder, f"{remote}:{folder}")
            if not result.success:
                raise DemoResetError(502, f"Couldn't restore the cloud folder of '{album['name']}': {result.error}")
            restored[folder] = source

        showing = restored.get(base.get("showing")) or next(iter(restored.values()))
        await _show(showing)

        # Everything else goes: albums on the frame, then every other KFR_* folder in the cloud
        deleted = 0
        keep_ids = {s.id for s in restored.values()}
        for source in sources.source_manager.list_sources():
            if source.id not in keep_ids:
                await _wait_for_sync()
                try:
                    album_service.delete_album(source.id)
                except album_service.AlbumDeleteError as e:
                    raise DemoResetError(e.status_code, f"Couldn't delete album '{source.name}': {e.message}")
                deleted += 1
        dirs = await frame_registry.rclone_list_dirs(f"{remote}:")
        if dirs is None:
            raise DemoResetError(502, "Couldn't list the cloud folders.")
        purged = 0
        for folder in sorted(d for d in dirs if frame_registry.FOLDER_RE.match(d) and d not in restored):
            result = await rclone_purge(f"{remote}:{folder}")
            if not result.success:
                raise DemoResetError(502, f"Couldn't delete cloud folder {folder}: {result.error}")
            purged += 1

        albums = []
        for folder, source in restored.items():
            ok = await _sync(source)
            albums.append({"name": source.name, "photos": len(_media_files(Path(source.local_path).expanduser())),
                           "synced": ok})

        changed = await _restore_settings(base)
        demo = demo_service.enable_demo()

    summary = {
        "phones_removed": phones,
        "invites_removed": invites,
        "upload_links_removed": links,
        "albums": albums,
        "albums_deleted": deleted,
        "cloud_folders_deleted": purged,
        "settings_restored": changed,
        "demo": demo,
    }
    logger.info(
        f"Demo frame reset: {phones} phone(s), {invites} invite(s), {links} upload link(s) removed; "
        f"{deleted} album(s) and {purged} cloud folder(s) deleted; restored "
        + ", ".join(f"{a['name']} ({a['photos']})" for a in albums)
        + (f"; settings: {', '.join(changed)}" if changed else "")
    )
    log_auth_event("DEMO_RESET", success=True, details={
        "phones": phones, "invites": invites, "upload_links": links,
        "albums_deleted": deleted, "cloud_folders_deleted": purged,
    })
    return summary
