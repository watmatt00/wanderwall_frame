"""
WanderWall - Cloud photo count cache (Koofr polling plan, Part A, KP-001..006).

Status requests (the indicator lights every 10 s, open dashboard tabs every 15 s, the app) used
to run `rclone size` against Koofr on every call: ~12k process starts and ~25k DNS lookups per
frame per day (docs/test_runs/2026-11-03_dns_baseline.md). They now read this cache instead.

When the count is refreshed:
- after every successful sync (sync_service.sync_source), so it follows whatever sync timer is
  actually running: interval 0 or party mode (timer stopped) means no automatic counts;
- after a manual change to the cloud (upload, delete, rename, rotate, purge...): the rclone write
  helpers call `mark_changed()`, and the next status read recounts once (a batch of 200 renames
  costs one count);
- when the active album changes (a manual action), on the next status read;
- when an album has never been counted, on the next status read, but only while the sync timer runs;
- when a live count is made elsewhere (Albums tab, the app's per-folder sync status): `store()`.

The cache is saved to ~/.wanderwall/cloud_counts.yaml (atomic write) so restarts and updates
keep it.
"""

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

import yaml

from src.config.settings import get_settings
from src.utils.rclone import add_cloud_change_listener, rclone_try_count

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".wanderwall" / "cloud_counts.yaml"
COUNT_TIMEOUT_SECONDS = 15
# After a failed count, wait this long before trying again (the lights poll every 10 s)
RETRY_AFTER_SECONDS = 60


def _norm(remote: str) -> str:
    """Remote spec without trailing slashes ("koofr:KFR_x/" -> "koofr:KFR_x")."""
    return remote.rstrip("/")


def _related(a: str, b: str) -> bool:
    """True when one remote path is the other or contains it ("koofr:A" and "koofr:A/x.jpg")."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def sync_timer_running() -> bool:
    """Whether automatic syncs (and so automatic counts) are on: interval > 0, not party mode."""
    settings = get_settings()
    return settings.sync.interval > 0 and not settings.display.party_mode


class CloudCountCache:
    """Per-album cloud photo counts, refreshed by syncs and manual changes, never by polling."""

    def __init__(self, path: Path = CACHE_PATH) -> None:
        """Create an empty cache backed by `path` (loaded on first use)."""
        self.path = path
        self._entries: dict[str, dict] = {}
        self._pending: set[str] = set()  # changed cloud paths not matching a counted album yet
        self._last_active: str | None = None
        self._loaded = False
        self._locks: dict[str, asyncio.Lock] = {}
        self._failed_at: dict[str, float] = {}

    # --- persistence -------------------------------------------------------------------------

    def _load(self) -> None:
        """Read the saved cache once; a missing or unreadable file starts empty."""
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            data = yaml.safe_load(self.path.read_text()) or {}
            entries = data.get("counts") or {}
            for remote, entry in entries.items():
                valid = isinstance(entry, dict) and isinstance(entry.get("count"), int)
                if isinstance(remote, str) and valid:
                    self._entries[_norm(remote)] = {
                        "count": entry["count"],
                        "checked_at": entry.get("checked_at"),
                        "stale": bool(entry.get("stale", False)),
                    }
            active = data.get("last_active")
            self._last_active = _norm(active) if isinstance(active, str) else None
            pending = data.get("pending") or []
            self._pending = {_norm(p) for p in pending if isinstance(p, str)}
        except (OSError, yaml.YAMLError, AttributeError) as e:
            logger.warning(f"Cloud count cache unreadable, starting empty: {e}")
            self._entries, self._pending, self._last_active = {}, set(), None

    def _save(self) -> None:
        """Write the cache atomically (temp file in the same folder, then rename)."""
        data = {
            "counts": self._entries,
            "last_active": self._last_active,
            "pending": sorted(self._pending),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cloud_counts.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as e:
            logger.warning(f"Failed to save cloud count cache: {e}")

    # --- updates -----------------------------------------------------------------------------

    def store(self, remote: str, count: int) -> None:
        """Record a fresh count for an album (clears its stale flag and any pending change)."""
        self._load()
        key = _norm(remote)
        self._entries[key] = {
            "count": int(count),
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stale": False,
        }
        self._pending = {p for p in self._pending if not _related(p, key)}
        self._failed_at.pop(key, None)
        self._save()

    def mark_changed(self, remote_path: str) -> None:
        """A manual action changed the cloud at `remote_path`: recount it on the next read."""
        self._load()
        path = _norm(remote_path)
        hit = False
        for key, entry in self._entries.items():
            if _related(path, key):
                entry["stale"] = True
                self._failed_at.pop(key, None)
                hit = True
        if not hit:
            self._pending.add(path)
        self._save()

    # --- reads -------------------------------------------------------------------------------

    def get(self, remote: str) -> int | None:
        """The cached count for an album, or None if it was never counted. Never runs rclone."""
        self._load()
        entry = self._entries.get(_norm(remote))
        return entry["count"] if entry else None

    def checked_at(self, remote: str) -> str | None:
        """When the album was last counted ("YYYY-MM-DD HH:MM:SS", local time), or None."""
        self._load()
        entry = self._entries.get(_norm(remote))
        return entry.get("checked_at") if entry else None

    def _needs_count(self, key: str, active_changed: bool) -> bool:
        """Whether a status read may count this album now (rules in the module docstring)."""
        failed = self._failed_at.get(key)
        if failed is not None and time.monotonic() - failed < RETRY_AFTER_SECONDS:
            return False
        entry = self._entries.get(key)
        if entry is None:
            return active_changed or bool(self._pending_for(key)) or sync_timer_running()
        return entry["stale"] or active_changed or bool(self._pending_for(key))

    def _pending_for(self, key: str) -> set[str]:
        """Pending changed paths that belong to this album."""
        return {p for p in self._pending if _related(p, key)}

    async def count_for_status(self, remote: str) -> int | None:
        """
        Count for a status request: the cached value, recounted once only when the rules allow it.

        Returns None when the album has no count yet and may not be counted now.
        """
        self._load()
        key = _norm(remote)
        active_changed = self._last_active is not None and self._last_active != key
        if self._last_active != key:
            self._last_active = key
            self._save()
        if not self._needs_count(key, active_changed):
            return self.get(key)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another request may have counted while this one waited
            entry = self._entries.get(key)
            fresh = entry is not None and not entry["stale"] and not self._pending_for(key)
            if fresh and not active_changed:
                return entry["count"]
            try:
                count = await asyncio.wait_for(rclone_try_count(key), timeout=COUNT_TIMEOUT_SECONDS)
            except TimeoutError:
                count = None
            if count is None:
                self._failed_at[key] = time.monotonic()
                logger.warning(f"Cloud count for {key} failed; keeping the cached value")
                return self.get(key)
            self.store(key, count)
            logger.info(f"Cloud count for {key}: {count}")
            return count

    async def refresh(self, remote: str) -> int | None:
        """Count now and store it (after a sync). Keeps the old value if the count fails."""
        key = _norm(remote)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                count = await asyncio.wait_for(rclone_try_count(key), timeout=COUNT_TIMEOUT_SECONDS)
            except TimeoutError:
                count = None
            if count is None:
                logger.warning(f"Cloud count after sync failed for {key}; keeping the cached value")
                return self.get(key)
            self.store(key, count)
            return count


cloud_count_cache = CloudCountCache()

# The rclone write helpers report every manual cloud change here
add_cloud_change_listener(cloud_count_cache.mark_changed)
