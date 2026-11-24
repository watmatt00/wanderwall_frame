"""
WanderWall - Source Manager.

Manages photo sources (folders) and their configurations.
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, field_validator
import yaml

logger = logging.getLogger(__name__)

# Default sources config location
SOURCES_PATH = Path.home() / ".wanderwall" / "sources.yaml"


class PhotoSource(BaseModel):
    """A photo source configuration."""
    id: str
    name: str
    local_path: str
    rclone_remote: Optional[str] = None
    enabled: bool = True

    @field_validator("local_path")
    @classmethod
    def expand_home(cls, v: str) -> str:
        """
        Store the album folder as a full path (PL-211).

        Albums written by hand (the v3 -> v4 upgrade doc) say `~/Pictures/<id>`, and
        `install.sh --from-v4` copies them as is. Code that builds `Path(local_path)`
        without expanduser() then looks for a folder named `~` (the preview 404'd on
        mnbframe), so every PhotoSource carries the expanded path.
        """
        return str(Path(v).expanduser()) if v.startswith("~") else v


def free_cloud_folder(base: str, taken: set[str]) -> str:
    """
    KFR_<base>, or KFR_<base>_2, _3… so a new album never shares a cloud folder (PL-165).

    The Koofr account can be shared by several frames, and rclone mkdir succeeds
    on a folder that exists, so a plain KFR_<id> could be another frame's album.
    `taken` holds the folder names already in the cloud (compared case-insensitively);
    the chosen name is added to it.
    """
    base = re.sub(r"[^A-Za-z0-9_]", "_", base)[:60] or "album"
    lowered = {t.lower() for t in taken}
    folder, n = f"KFR_{base}", 1
    while folder.lower() in lowered:
        n += 1
        folder = f"KFR_{base}_{n}"
    taken.add(folder)
    return folder


def list_cloud_folders(remote_name: str) -> Optional[set[str]]:
    """Folder names at the top of a remote (e.g. "koofr"), or None if the cloud couldn't be listed."""
    try:
        result = subprocess.run(
            ["rclone", "lsjson", f"{remote_name}:", "--dirs-only"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Failed to list cloud folders: {result.stderr.strip()}")
            return None
        return {e["Name"] for e in json.loads(result.stdout or "[]") if e.get("IsDir")}
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logger.error(f"Failed to list cloud folders: {e}")
        return None


def find_koofr_remote() -> Optional[str]:
    """
    Name of the first rclone remote of type Koofr (e.g. "kfr_tkframe"), or None.
    """
    result = subprocess.run(
        ["rclone", "listremotes"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        logger.warning("Failed to list rclone remotes")
        return None

    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.endswith(":"):
            candidate = line[:-1]
            type_result = subprocess.run(
                ["rclone", "config", "show", candidate],
                capture_output=True, text=True, timeout=10,
            )
            if "koofr" in type_result.stdout.lower():
                return candidate
    return None


class SourceManager:
    """
    Manages photo source configurations.

    Sources are stored in ~/.wanderwall/sources.yaml.
    """

    def __init__(self, sources_path: Path = SOURCES_PATH):
        self._path = sources_path
        self._listeners: list[Callable[[list["PhotoSource"]], None]] = []

    def add_listener(self, listener: Callable[[list["PhotoSource"]], None]) -> None:
        """Call `listener(sources)` after every save (add, rename, delete…)."""
        self._listeners.append(listener)

    def _load_sources(self) -> list[PhotoSource]:
        """Load sources from YAML file."""
        if not self._path.exists():
            return []

        try:
            with open(self._path) as f:
                data = yaml.safe_load(f) or {}
            return [PhotoSource(**s) for s in data.get("sources", [])]
        except Exception as e:
            logger.error(f"Failed to load sources: {e}")
            return []

    def expand_saved_paths(self) -> list[str]:
        """
        Rewrite sources.yaml once if it still holds `~` album paths (PL-211).

        Loading already expands them (PhotoSource.expand_home); this makes the file
        match, so the saved data is the same on every frame. Returns the album ids
        it changed (empty when there was nothing to do or the file is unreadable).
        """
        if not self._path.exists():
            return []
        try:
            with open(self._path) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Failed to read sources for path check: {e}")
            return []
        changed = [
            str(s.get("id")) for s in data.get("sources", [])
            if isinstance(s, dict) and str(s.get("local_path", "")).startswith("~")
        ]
        if not changed:
            return []
        sources = self._load_sources()
        if not sources:
            return []  # unreadable entries: leave the file alone
        try:
            self._save_sources(sources)
        except OSError as e:  # the API must start anyway; loading still expands the paths
            logger.error(f"Failed to save expanded album paths: {e}")
            return []
        logger.info(f"Album paths expanded from ~ to full paths (PL-211): {changed}")
        return changed

    def _save_sources(self, sources: list[PhotoSource]):
        """Save sources to YAML file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {"sources": [s.model_dump() for s in sources]}

        # Atomic write: a crash mid-write can't leave a truncated sources file
        temp_path = self._path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        temp_path.replace(self._path)

        for listener in self._listeners:
            try:
                listener(sources)
            except Exception as e:  # a listener must never undo or block the save
                logger.error(f"Sources listener failed: {e}")

    def list_sources(self) -> list[PhotoSource]:
        """
        List all configured photo sources.

        Returns:
            List of PhotoSource configurations
        """
        return self._load_sources()

    def get_source(self, source_id: str) -> Optional[PhotoSource]:
        """
        Get a specific source by ID.

        Args:
            source_id: Source identifier

        Returns:
            PhotoSource if found, None otherwise
        """
        sources = self._load_sources()
        for source in sources:
            if source.id == source_id:
                return source
        return None

    def create_source(
        self,
        name: str,
        rclone_remote: Optional[str] = None,
    ) -> PhotoSource:
        """
        Create a new photo source.

        If rclone_remote is not provided, auto-configures one using the
        first available Koofr rclone remote and creates the cloud folder.

        Args:
            name: Human-readable name
            rclone_remote: Optional rclone remote specification

        Returns:
            The created PhotoSource
        """
        sources = self._load_sources()

        # Generate ID from name
        source_id = name.lower().replace(" ", "_")
        # Sanitize: only allow alphanumeric and underscores
        source_id = re.sub(r"[^a-z0-9_]", "_", source_id)

        # Ensure unique ID
        existing_ids = {s.id for s in sources}
        if source_id in existing_ids:
            counter = 2
            while f"{source_id}_{counter}" in existing_ids:
                counter += 1
            source_id = f"{source_id}_{counter}"

        # Create local path
        local_path = Path.home() / "Pictures" / source_id
        local_path.mkdir(parents=True, exist_ok=True)

        # Auto-configure rclone remote if not provided
        if not rclone_remote:
            rclone_remote = self._auto_configure_remote(source_id)

        source = PhotoSource(
            id=source_id,
            name=name,
            local_path=str(local_path),
            rclone_remote=rclone_remote,
            enabled=True,
        )

        sources.append(source)
        self._save_sources(sources)

        logger.info(f"Created source '{source_id}': {local_path}, remote: {rclone_remote}")
        return source

    def _auto_configure_remote(self, source_id: str) -> Optional[str]:
        """
        Auto-configure an rclone remote for a new source.

        Finds the first Koofr rclone remote and creates a new cloud folder
        named KFR_<source_id>, or KFR_<source_id>_2… if that exists: an
        existing folder may be another frame's album on a shared account, or
        this frame's deleted one (kept for Recover Albums). If the cloud can't
        be listed, no folder is set up rather than risk sharing one (PL-165).

        Args:
            source_id: The source identifier

        Returns:
            rclone remote string (e.g. "kfr_tkframe:KFR_source_id") or None
        """
        try:
            remote_name = find_koofr_remote()
            if not remote_name:
                logger.warning("No Koofr rclone remote found")
                return None

            existing = list_cloud_folders(remote_name)
            if existing is None:
                logger.error(f"No cloud folder set up for '{source_id}': couldn't list the cloud")
                return None
            cloud_folder = free_cloud_folder(source_id, existing)
            rclone_remote = f"{remote_name}:{cloud_folder}"

            mkdir_result = subprocess.run(
                ["rclone", "mkdir", rclone_remote],
                capture_output=True, text=True, timeout=30,
            )
            if mkdir_result.returncode != 0:
                logger.error(f"Failed to create cloud folder: {mkdir_result.stderr}")
                return None

            logger.info(f"Auto-configured remote: {rclone_remote}")
            return rclone_remote

        except Exception as e:
            logger.error(f"Failed to auto-configure remote: {e}")
            return None

    def delete_source(self, source_id: str) -> bool:
        """
        Delete a photo source configuration.

        Note: Does not delete the local files.

        Args:
            source_id: Source to delete

        Returns:
            True if source was deleted
        """
        sources = self._load_sources()
        original_count = len(sources)

        sources = [s for s in sources if s.id != source_id]

        if len(sources) < original_count:
            self._save_sources(sources)
            logger.info(f"Deleted source '{source_id}'")
            return True

        return False

    def backfill_remotes(self) -> list[str]:
        """Set rclone_remote on sources that were created before Koofr was configured."""
        updated = []
        sources = self._load_sources()
        for source in sources:
            if source.enabled and not source.rclone_remote:
                remote = self._auto_configure_remote(source.id)
                if remote:
                    source.rclone_remote = remote
                    updated.append(source.id)
        if updated:
            self._save_sources(sources)
            logger.info(f"Backfilled rclone_remote for sources: {updated}")
        return updated

    def update_source(self, source: PhotoSource) -> bool:
        """
        Update an existing source configuration.

        Args:
            source: Updated source configuration

        Returns:
            True if source was updated
        """
        sources = self._load_sources()

        for i, s in enumerate(sources):
            if s.id == source.id:
                sources[i] = source
                self._save_sources(sources)
                logger.info(f"Updated source '{source.id}'")
                return True

        return False


# Global manager instance
source_manager = SourceManager()
