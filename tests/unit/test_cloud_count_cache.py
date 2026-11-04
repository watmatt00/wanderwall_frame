"""
Unit tests for the cloud count cache (Koofr polling plan, Part A: KP-001..007).

Status requests must never start rclone on their own; counts come from syncs, manual cloud changes,
album switches and (only while the sync timer runs) a first count for an album never counted.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from src.services import cloud_count_cache as ccc
from src.services import status_service
from src.services.cloud_count_cache import CloudCountCache
from src.utils import rclone

ALBUM = "koofr:KFR_frame"
OTHER = "koofr:KFR_other"


class FakeCounter:
    """Stands in for rclone_try_count: records calls, returns a set value (None = failure)."""

    def __init__(self, value=5, delay=0.0):
        self.value = value
        self.delay = delay
        self.calls: list[str] = []

    async def __call__(self, remote):
        self.calls.append(remote)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.value


@pytest.fixture
def counter(monkeypatch):
    """Replace the rclone count used by the cache."""
    fake = FakeCounter()
    monkeypatch.setattr(ccc, "rclone_try_count", fake)
    return fake


@pytest.fixture
def timer(monkeypatch):
    """Control the sync interval and party mode the cache sees."""
    state = SimpleNamespace(interval=900, party=False)
    monkeypatch.setattr(ccc, "get_settings", lambda: SimpleNamespace(
        sync=SimpleNamespace(interval=state.interval),
        display=SimpleNamespace(party_mode=state.party),
    ))
    return state


@pytest.fixture
def cache(tmp_path, counter, timer):
    """A cache backed by a temp file."""
    return CloudCountCache(path=tmp_path / "cloud_counts.yaml")


async def test_cached_value_served_without_rclone(cache, counter):
    cache.store(ALBUM, 7)
    for _ in range(50):  # the lights poll every 10 s; dashboards every 15 s
        assert await cache.count_for_status(ALBUM) == 7
    assert counter.calls == []


async def test_first_count_once_while_timer_runs(cache, counter):
    assert await cache.count_for_status(ALBUM) == 5
    assert await cache.count_for_status(ALBUM) == 5
    assert counter.calls == [ALBUM]


@pytest.mark.parametrize("interval,party", [(0, False), (900, True)])
async def test_no_automatic_count_when_sync_is_off(cache, counter, timer, interval, party):
    timer.interval, timer.party = interval, party
    assert await cache.count_for_status(ALBUM) is None
    assert counter.calls == []
    assert status_service.determine_sync_status(3, None) == "unknown"


async def test_manual_change_recounts_once_for_a_batch(cache, counter):
    cache.store(ALBUM, 7)
    for i in range(200):  # e.g. the Filename Cleaner renaming 200 files
        cache.mark_changed(f"{ALBUM}/IMG_{i:04d}.jpg")
    assert await cache.count_for_status(ALBUM) == 5
    assert await cache.count_for_status(ALBUM) == 5
    assert counter.calls == [ALBUM]


async def test_manual_change_counts_even_with_sync_off(cache, counter, timer):
    timer.interval = 0
    cache.mark_changed(f"{ALBUM}/new.jpg")  # album never counted: kept as a pending change
    assert await cache.count_for_status(ALBUM) == 5
    assert counter.calls == [ALBUM]
    assert cache._pending == set()  # the pending change was used up by that count
    assert await cache.count_for_status(ALBUM) == 5
    assert counter.calls == [ALBUM]  # and nothing more is counted automatically


async def test_change_to_other_album_leaves_this_one(cache, counter):
    cache.store(ALBUM, 7)
    cache.store(OTHER, 2)
    cache.mark_changed(f"{OTHER}/x.jpg")
    assert await cache.count_for_status(ALBUM) == 7
    assert counter.calls == []


async def test_purge_of_parent_marks_album(cache, counter):
    cache.store("koofr:KFR_a/sub", 4)
    cache.mark_changed("koofr:KFR_a")
    assert await cache.count_for_status("koofr:KFR_a/sub") == 5


async def test_album_switch_recounts_even_with_sync_off(cache, counter, timer):
    cache.store(ALBUM, 7)
    cache.store(OTHER, 2)
    assert await cache.count_for_status(ALBUM) == 7  # first read sets the active album
    timer.interval = 0
    assert await cache.count_for_status(OTHER) == 5  # switch = manual action: count now
    assert await cache.count_for_status(OTHER) == 5
    assert counter.calls == [OTHER]


async def test_failed_count_keeps_value_and_backs_off(cache, counter):
    cache.store(ALBUM, 7)
    cache.mark_changed(ALBUM)
    counter.value = None  # rclone fails
    assert await cache.count_for_status(ALBUM) == 7
    assert await cache.count_for_status(ALBUM) == 7
    assert counter.calls == [ALBUM]  # no retry within RETRY_AFTER_SECONDS


async def test_concurrent_reads_count_once(cache, counter):
    counter.delay = 0.05
    cache.mark_changed(f"{ALBUM}/a.jpg")
    results = await asyncio.gather(*[cache.count_for_status(ALBUM) for _ in range(5)])
    assert results == [5] * 5
    assert counter.calls == [ALBUM]


async def test_refresh_after_sync_stores(cache, counter):
    counter.value = 12
    assert await cache.refresh(ALBUM) == 12
    assert cache.get(ALBUM) == 12
    counter.value = None
    assert await cache.refresh(ALBUM) == 12  # failure keeps the old value


async def test_saved_and_reloaded_without_false_switch(tmp_path, counter, timer):
    path = tmp_path / "cloud_counts.yaml"
    first = CloudCountCache(path=path)
    first.store(ALBUM, 9)
    assert await first.count_for_status(ALBUM) == 9

    second = CloudCountCache(path=path)  # e.g. after an API restart or update
    assert await second.count_for_status(ALBUM) == 9
    assert counter.calls == []
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not list(tmp_path.glob(".cloud_counts.*.tmp"))  # atomic write left no temp file


async def test_corrupt_file_starts_empty(tmp_path, counter, timer):
    path = tmp_path / "cloud_counts.yaml"
    path.write_text("counts: [unclosed\n")
    cache = CloudCountCache(path=path)
    assert cache.get(ALBUM) is None
    assert await cache.count_for_status(ALBUM) == 5
    assert yaml.safe_load(path.read_text())["counts"][ALBUM]["count"] == 5


async def test_trailing_slash_is_same_album(cache, counter):
    cache.store(ALBUM + "/", 3)
    assert await cache.count_for_status(ALBUM) == 3
    assert counter.calls == []


# --- wiring into the rest of the frame ---------------------------------------------------------


async def test_photo_counts_use_cache_not_rclone(monkeypatch, tmp_path, counter, timer):
    cache = CloudCountCache(path=tmp_path / "c.yaml")
    cache.store(ALBUM, 4)
    monkeypatch.setattr(status_service, "cloud_count_cache", cache)
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"x")
    source = SimpleNamespace(local_path=str(photos), rclone_remote=ALBUM)
    assert await status_service.get_photo_counts(source) == (1, 4)
    assert counter.calls == []


async def test_rclone_write_helpers_report_changes(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(rclone, "_cloud_change_listeners", [seen.append])

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        return Proc()

    monkeypatch.setattr(rclone.asyncio, "create_subprocess_exec", fake_exec)
    await rclone.rclone_deletefile(ALBUM, "a.jpg")
    await rclone.rclone_movefile(ALBUM, "a.jpg", "b.jpg")
    await rclone.rclone_deletefile_raw(ALBUM, "c d.jpg")
    await rclone.rclone_movefile_raw(ALBUM, "c d.jpg", "e.jpg")
    await rclone.rclone_copyto(Path("/tmp/x.jpg"), f"{ALBUM}/x.jpg")
    await rclone.rclone_copy_dir(Path("/tmp"), ALBUM)
    assert seen == [ALBUM, ALBUM, ALBUM, ALBUM, f"{ALBUM}/x.jpg", ALBUM]


async def test_rclone_try_count_tells_failure_from_zero(monkeypatch):
    class Proc:
        def __init__(self, rc, out):
            self.returncode, self.out = rc, out

        async def communicate(self):
            return self.out, b"boom"

    results = iter([Proc(0, b'{"count": 0, "bytes": 0}'), Proc(1, b""), Proc(0, b"not json")])

    async def fake_exec(*args, **kwargs):
        return next(results)

    monkeypatch.setattr(rclone.asyncio, "create_subprocess_exec", fake_exec)
    assert await rclone.rclone_try_count(ALBUM) == 0
    assert await rclone.rclone_try_count(ALBUM) is None
    assert await rclone.rclone_try_count(ALBUM) is None
    assert await rclone.rclone_try_count("bad remote") is None


async def test_successful_sync_refreshes_count(monkeypatch, tmp_path):
    from src.services import sync_service as sync_mod

    refreshed: list[str] = []

    async def fake_sync(src, dest):
        return rclone.RcloneResult(success=True, files_transferred=1)

    async def fake_refresh(remote):
        refreshed.append(remote)
        return 1

    monkeypatch.setattr(sync_mod, "rclone_sync", fake_sync)
    monkeypatch.setattr(sync_mod.cloud_count_cache, "refresh", fake_refresh)
    monkeypatch.setattr(sync_mod.frame_registry, "maybe_heartbeat", lambda: None)
    svc = sync_mod.SyncService()
    await svc.sync_source("frame", tmp_path, ALBUM)
    assert refreshed == [ALBUM]

    async def failing_sync(src, dest):
        return rclone.RcloneResult(success=False, error="network")

    monkeypatch.setattr(sync_mod, "rclone_sync", failing_sync)
    await svc.sync_source("frame", tmp_path, ALBUM)
    assert refreshed == [ALBUM]  # a failed sync doesn't count


def test_status_api_sends_zero_and_unknown_without_count(monkeypatch):
    """The app decodes sync.remote_count as a required Int: it must never be null."""
    from src.api.app import app
    from src.api.dependencies import require_admin
    from src.api.routes import status

    async def fake_service(name):
        return status.ServiceStatus(
            name=name, display_name=name, active=True, status="running", can_restart=True
        )

    async def fake_counts(source):
        return 3, None

    monkeypatch.setattr(status, "_get_service_status", fake_service)
    monkeypatch.setattr(status, "get_current_source", lambda: ("frame", None))
    monkeypatch.setattr(status, "get_photo_counts", fake_counts)
    monkeypatch.setattr(status, "get_last_sync_time", lambda: None)
    monkeypatch.setattr(status, "get_disk_capacity", lambda path: {
        "total_gb": 1.0, "used_gb": 0.5, "available_gb": 0.5, "percent_used": 50.0,
        "total_bytes": 1, "used_bytes": 1, "free_bytes": 1,
    })
    monkeypatch.setattr(status, "get_lan_ip", lambda: "")
    monkeypatch.setattr(status, "get_tailscale_ip", lambda: "")
    monkeypatch.setattr(status, "get_wifi_ssid", lambda: "")
    monkeypatch.setattr(status, "check_remote_access", lambda url: False)
    monkeypatch.setattr(status, "get_settings", lambda: SimpleNamespace(frame=SimpleNamespace(
        id="f1", name="bfframe", funnel_url="")))
    monkeypatch.setattr(status_service.sync_service, "_is_syncing", False)
    monkeypatch.setattr(status_service.sync_service, "_last_sync", None)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    try:
        r = TestClient(app).get("/api/v1/status")
    finally:
        app.dependency_overrides.pop(require_admin, None)

    assert r.status_code == 200, r.text
    sync = r.json()["sync"]
    assert sync["remote_count"] == 0
    assert isinstance(sync["remote_count"], int)
    assert sync["status"] == "unknown"
