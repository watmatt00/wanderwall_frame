"""
WanderWall API - Folder Management Routes.

Manages photo sources/folders:
- GET /folders: List all photo sources
- POST /folders: Create a new photo source
- GET /folders/{id}: Get folder details
- PATCH /folders/{id}: Rename a folder (display name only)
- DELETE /folders/{id}: Delete a folder
- POST /folders/{id}/sync: Trigger sync for a folder
- GET /folders/{id}/sync/status: Get sync status for a folder
- POST /folders/sync/all: Sync all enabled sources
- GET /folders/remotes: List available rclone remotes
"""

import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from src.api.dependencies import require_admin
from src.config.settings import get_settings
from src.services import album_service
from src.services.source_manager import source_manager
from src.services.sync_service import sync_service
from src.services.cloud_count_cache import cloud_count_cache
from src.utils.rclone import SyncStatus, count_local_files, get_sync_status, rclone_list_remotes


router = APIRouter(prefix="/folders", tags=["folders"])


class PhotoSourceResponse(BaseModel):
    """A photo source configuration."""
    id: str
    name: str
    local_path: str
    rclone_remote: Optional[str]
    enabled: bool
    photo_count: int


class FolderItem(BaseModel):
    """A folder item matching mobile app FrameFolder model."""
    id: str
    name: str
    path: str
    photo_count: int
    remote_path: Optional[str] = None


class FoldersListResponse(BaseModel):
    """Wrapped response for GET /folders, matching mobile FoldersResponse."""
    folders: list[FolderItem]
    current_source: str


class CreateFolderRequest(BaseModel):
    """Request to create a new photo source."""
    name: str
    rclone_remote: Optional[str] = None


class RenameFolderRequest(BaseModel):
    """Request to rename a photo source. Only the display name changes."""
    name: str = Field(..., max_length=50)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        """Trim and reject empty names or control characters."""
        v = v.strip()
        if not v:
            raise ValueError("Name can't be empty")
        if any(unicodedata.category(c).startswith("C") for c in v):
            raise ValueError("Name can't contain control characters")
        return v


class SyncStatusResponse(BaseModel):
    """Sync status response."""
    is_syncing: bool
    current_source: Optional[str]
    local_count: int
    remote_count: int
    sync_status: str
    message: str


class SyncTriggerResponse(BaseModel):
    """Response after triggering sync."""
    message: str
    source_id: str


@router.get("", response_model=FoldersListResponse)
async def list_folders(admin=Depends(require_admin)):
    """
    List all configured photo sources.

    Returns wrapped response with folders list and current_source ID.
    """
    settings = get_settings()
    sources = source_manager.list_sources()
    folders = []
    for source in sources:
        photo_count = count_local_files(source.local_path)
        # Extract cloud path from rclone remote (e.g. "kfr_tkframe:KFR_tkframe" → "/KFR_tkframe")
        remote_path = None
        if source.rclone_remote and ":" in source.rclone_remote:
            cloud_path = source.rclone_remote.split(":", 1)[1]
            remote_path = f"/{cloud_path}" if not cloud_path.startswith("/") else cloud_path
        folders.append(FolderItem(
            id=source.id,
            name=source.name,
            path=source.local_path,
            photo_count=photo_count,
            remote_path=remote_path,
        ))
    return FoldersListResponse(
        folders=folders,
        current_source=settings.display.current_source,
    )


@router.post("", response_model=PhotoSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(request: CreateFolderRequest, admin=Depends(require_admin)):
    """
    Create a new photo source.

    If rclone_remote is provided, sets up sync from that remote.
    """
    source = source_manager.create_source(
        name=request.name,
        rclone_remote=request.rclone_remote,
    )

    photo_count = count_local_files(source.local_path)

    return PhotoSourceResponse(
        id=source.id,
        name=source.name,
        local_path=source.local_path,
        rclone_remote=source.rclone_remote,
        enabled=source.enabled,
        photo_count=photo_count,
    )


class RemoteInfo(BaseModel):
    """An rclone remote."""
    name: str


@router.get("/remotes", response_model=list[RemoteInfo])
async def list_remotes(admin=Depends(require_admin)):
    """
    List available rclone remotes.

    Returns remotes configured in the system's rclone config.
    Declared before /{source_id} so "remotes" isn't taken as an album id (PL-167).
    """
    remotes = await rclone_list_remotes()
    return [RemoteInfo(name=name) for name in remotes]


@router.get("/{source_id}", response_model=PhotoSourceResponse)
async def get_folder(source_id: str, admin=Depends(require_admin)):
    """
    Get a specific photo source by ID.
    """
    source = source_manager.get_source(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found",
        )

    photo_count = count_local_files(source.local_path)

    return PhotoSourceResponse(
        id=source.id,
        name=source.name,
        local_path=source.local_path,
        rclone_remote=source.rclone_remote,
        enabled=source.enabled,
        photo_count=photo_count,
    )


@router.patch("/{source_id}", response_model=PhotoSourceResponse)
async def rename_folder(
    source_id: str, request: RenameFolderRequest, admin=Depends(require_admin)
):
    """
    Rename a photo source.

    Only the display name changes. The source id, local folder and cloud
    folder stay the same, so syncing and the current display are unaffected.
    """
    source = source_manager.get_source(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found",
        )

    renamed = source.model_copy(update={"name": request.name})
    if not source_manager.update_source(renamed):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rename source '{source_id}'",
        )

    return PhotoSourceResponse(
        id=renamed.id,
        name=renamed.name,
        local_path=renamed.local_path,
        rclone_remote=renamed.rclone_remote,
        enabled=renamed.enabled,
        photo_count=count_local_files(renamed.local_path),
    )


class DeleteFolderResponse(BaseModel):
    """Result of deleting an album (PL-147)."""
    deleted: str
    name: str
    photos_removed: int
    local_folder_removed: bool
    cloud_folder: Optional[str] = None
    error: Optional[str] = None


@router.delete("/{source_id}", response_model=DeleteFolderResponse)
async def delete_folder(source_id: str, admin=Depends(require_admin)):
    """
    Delete an album and its photos on the frame (PL-147).

    The cloud folder and backups are kept. Refused (409) for the album that's
    showing or syncing; 404 for an unknown album.
    """
    try:
        return DeleteFolderResponse(**album_service.delete_album(source_id))
    except album_service.AlbumDeleteError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/{source_id}/sync/status", response_model=SyncStatusResponse)
async def get_folder_sync_status(source_id: str, admin=Depends(require_admin)):
    """
    Get sync status for a specific folder.

    Returns local vs remote file counts and sync state.
    """
    source = source_manager.get_source(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found",
        )

    local_count = count_local_files(source.local_path)
    remote_count = 0
    sync_status_str = "unknown"
    message = "No remote configured"

    if source.rclone_remote:
        status_result = await get_sync_status(source.rclone_remote, source.local_path)
        if status_result.status != SyncStatus.ERROR:
            # A live count the app asked for: keep it for status requests too
            cloud_count_cache.store(source.rclone_remote, status_result.remote_count)
        remote_count = status_result.remote_count
        local_count = status_result.local_count
        sync_status_str = status_result.status.value
        message = status_result.message

    return SyncStatusResponse(
        is_syncing=sync_service._is_syncing,
        current_source=sync_service._current_source,
        local_count=local_count,
        remote_count=remote_count,
        sync_status=sync_status_str,
        message=message,
    )


async def _run_sync(source_id: str, local_path: str, rclone_remote: str):
    """Background task to run sync."""
    await sync_service.sync_source(
        source_id=source_id,
        local_path=Path(local_path),
        rclone_remote=rclone_remote,
    )


@router.post("/{source_id}/sync", response_model=SyncTriggerResponse)
async def trigger_folder_sync(
    source_id: str,
    background_tasks: BackgroundTasks,
    admin=Depends(require_admin),
):
    """
    Trigger sync for a specific folder.

    Sync runs in the background. Use GET /folders/{id}/sync/status to check progress.
    """
    source = source_manager.get_source(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found",
        )

    if not source.rclone_remote:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source '{source_id}' has no remote configured",
        )

    if sync_service._is_syncing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sync already in progress for '{sync_service._current_source}'",
        )

    background_tasks.add_task(
        _run_sync,
        source_id,
        source.local_path,
        source.rclone_remote,
    )

    return SyncTriggerResponse(
        message=f"Sync started for '{source_id}'",
        source_id=source_id,
    )


class SyncAllResponse(BaseModel):
    """Response after triggering sync for all sources."""
    message: str
    sources_queued: list[str]


@router.post("/sync/all", response_model=SyncAllResponse)
async def trigger_sync_all(
    background_tasks: BackgroundTasks,
    admin=Depends(require_admin),
):
    """
    Trigger sync for all enabled sources with remotes configured.

    Sources are synced sequentially in the background.
    """
    if sync_service._is_syncing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sync already in progress for '{sync_service._current_source}'",
        )

    sources = source_manager.list_sources()
    syncable = [s for s in sources if s.enabled and s.rclone_remote]

    if not syncable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No sources with remotes configured",
        )

    async def sync_all_sources():
        for source in syncable:
            try:
                await sync_service.sync_source(
                    source_id=source.id,
                    local_path=Path(source.local_path),
                    rclone_remote=source.rclone_remote,
                )
            except RuntimeError:
                pass

    background_tasks.add_task(sync_all_sources)

    return SyncAllResponse(
        message=f"Sync started for {len(syncable)} sources",
        sources_queued=[s.id for s in syncable],
    )
