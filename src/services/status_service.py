"""
WanderWall - Status Service.

Shared status logic used by both API and dashboard routes.
Consolidates source resolution, photo counting, sync status,
and disk capacity calculations.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

from src.config.settings import get_settings
from src.services.source_manager import source_manager, PhotoSource
from src.services.sync_service import sync_service
from src.services.cloud_count_cache import cloud_count_cache
from src.utils.rclone import count_local_files

logger = logging.getLogger(__name__)

# Default path for capacity checks
PICTURES_PATH = Path.home() / "Pictures"


def get_current_source() -> tuple[str, Optional[PhotoSource]]:
    """
    Get the current active source ID and object.

    Returns:
        Tuple of (source_id, PhotoSource or None)
    """
    settings = get_settings()
    current_source_id = settings.display.current_source
    sources = source_manager.list_sources()
    current_source = next((s for s in sources if s.id == current_source_id), None)
    return current_source_id, current_source


async def get_photo_counts(source: Optional[PhotoSource]) -> tuple[int, Optional[int]]:
    """
    Get local and cloud photo counts for a source.

    The cloud count comes from the cloud count cache (src/services/cloud_count_cache.py), which
    runs rclone only after syncs, manual cloud changes and album switches, never on every poll.

    Args:
        source: The photo source to count, or None

    Returns:
        Tuple of (local_count, remote_count). remote_count is None when the album has no cloud
        count yet (e.g. sync interval 0 before any manual action); responses send it as 0.
    """
    if not source:
        return 0, 0

    local_count = count_local_files(source.local_path)

    if not source.rclone_remote:
        return local_count, 0
    try:
        remote_count = await cloud_count_cache.count_for_status(source.rclone_remote)
    except (OSError, ValueError, RuntimeError) as e:
        logger.warning(f"Cloud count cache failed for {source.rclone_remote}: {e}")
        remote_count = cloud_count_cache.get(source.rclone_remote)

    return local_count, remote_count


def determine_sync_status(local_count: int, remote_count: Optional[int]) -> str:
    """
    Determine sync status from counts and sync service state.

    Returns:
        Status string: "syncing", "error", "match", "mismatch", "unknown" (no cloud count yet) or "idle"
    """
    if sync_service._is_syncing:
        return "syncing"
    if sync_service._last_sync and not sync_service._last_sync.success:
        return "error"
    if remote_count is None:
        return "unknown"
    if local_count == remote_count and remote_count > 0:
        return "match"
    if remote_count > 0 and local_count != remote_count:
        return "mismatch"
    return "idle"


def get_last_sync_time() -> Optional[str]:
    """
    Get the ISO timestamp of the last sync, if any.

    Returns:
        ISO format string or None
    """
    if sync_service._last_sync and hasattr(sync_service._last_sync, 'completed_at'):
        return sync_service._last_sync.completed_at.isoformat()
    return None


def get_disk_capacity(path: Path = PICTURES_PATH) -> dict:
    """
    Get disk capacity for a path.

    Args:
        path: Path to check capacity for

    Returns:
        Dict with total_gb, used_gb, available_gb, percent_used, and byte values
    """
    try:
        usage = shutil.disk_usage(path)
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        available_gb = usage.free / (1024**3)
        percent_used = (usage.used / usage.total) * 100 if usage.total > 0 else 0
        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "available_gb": round(available_gb, 2),
            "percent_used": round(percent_used, 1),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        }
    except Exception:
        return {
            "total_gb": 0, "used_gb": 0, "available_gb": 0, "percent_used": 0,
            "total_bytes": 0, "used_bytes": 0, "free_bytes": 0,
        }
