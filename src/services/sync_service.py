"""
WanderWall - Sync Service.

Handles photo synchronization from cloud sources using rclone.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.services import frame_registry
from src.services.cloud_count_cache import cloud_count_cache
from src.utils.rclone import rclone_sync, rclone_count

logger = logging.getLogger(__name__)


class SyncResult(BaseModel):
    """Result of a sync operation."""
    source_id: str
    started_at: datetime
    completed_at: datetime
    success: bool
    files_transferred: int
    files_deleted: int
    error: Optional[str] = None


class SyncStatus(BaseModel):
    """Current sync status."""
    is_syncing: bool
    current_source: Optional[str]
    last_sync: Optional[SyncResult]
    local_count: int
    remote_count: int


class SyncService:
    """
    Manages photo synchronization.

    Coordinates rclone operations and tracks sync state.
    """

    def __init__(self):
        self._is_syncing = False
        self._current_source: Optional[str] = None
        self._last_sync: Optional[SyncResult] = None

    async def sync_source(
        self,
        source_id: str,
        local_path: Path,
        rclone_remote: str,
    ) -> SyncResult:
        """
        Sync a photo source from remote to local.

        Args:
            source_id: Identifier for this source
            local_path: Local directory path
            rclone_remote: rclone remote specification (e.g., "koofr:folder")

        Returns:
            SyncResult with operation details
        """
        if self._is_syncing:
            raise RuntimeError("Sync already in progress")

        self._is_syncing = True
        self._current_source = source_id
        started_at = datetime.now(timezone.utc)

        try:
            logger.info(f"Starting sync for source '{source_id}'")

            # Ensure local path exists
            local_path.mkdir(parents=True, exist_ok=True)

            # Run sync
            result = await rclone_sync(rclone_remote, str(local_path))

            completed_at = datetime.now(timezone.utc)

            sync_result = SyncResult(
                source_id=source_id,
                started_at=started_at,
                completed_at=completed_at,
                success=result.success,
                files_transferred=result.files_transferred,
                files_deleted=result.files_deleted,
                error=result.error,
            )

            if sync_result.success:
                logger.info(
                    f"Sync complete for '{source_id}': "
                    f"{sync_result.files_transferred} transferred"
                )
                # The only automatic cloud count: once per sync, so it follows the running sync
                # timer (none at interval 0 or in party mode). Status requests read this value.
                await cloud_count_cache.refresh(rclone_remote)
            else:
                logger.error(f"Sync failed for '{source_id}': {sync_result.error}")

            self._last_sync = sync_result
            return sync_result

        finally:
            self._is_syncing = False
            self._current_source = None
            frame_registry.maybe_heartbeat()

    async def get_status(
        self,
        local_path: Path,
        rclone_remote: Optional[str],
    ) -> SyncStatus:
        """
        Get current sync status including file counts.

        Args:
            local_path: Local directory to count
            rclone_remote: Optional remote to count

        Returns:
            Current sync status
        """
        # Count local files
        local_count = sum(1 for _ in local_path.rglob("*") if _.is_file())

        # Count remote files if remote is configured
        remote_count = 0
        if rclone_remote:
            try:
                remote_count = await rclone_count(rclone_remote)
            except Exception as e:
                logger.warning(f"Failed to count remote files: {e}")

        return SyncStatus(
            is_syncing=self._is_syncing,
            current_source=self._current_source,
            last_sync=self._last_sync,
            local_count=local_count,
            remote_count=remote_count,
        )


# Global service instance
sync_service = SyncService()
