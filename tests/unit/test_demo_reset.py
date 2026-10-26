"""
Unit tests: demo frame reset (PL-151) — Save as Baseline, then Reset to Baseline
after a reviewer changed albums, photos, settings, phones and invites. The Koofr
account, rclone, the display and sync are faked.
"""

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from filelock import FileLock
from fastapi.testclient import TestClient

from src.api.app import app
from src.auth import jwt_handler
from src.auth.models import Device
from src.config import settings as settings_mod
from src.config.manager import config_manager
from src.services import album_service, demo_reset_service as dr, demo_service, frame_registry
from src.services import source_manager as sm
from src.services.display_service import display_service
from src.services.source_manager import PhotoSource, SourceManager
from src.services.sync_service import sync_service
from src.services.systemd_service import systemd_service
from src.storage.devices import device_storage
from src.storage.invites import invite_storage
from src.utils import rclone, thumbnails

LAN = ("192.168.1.50", 50000)
USER = "apple@example.com"


@pytest.fixture
def frame(tmp_path, monkeypatch):
    """
    Isolated config, devices, invites and ~/Pictures; a fake dedicated Koofr
    account (cloud: folder → {file: bytes}); albums Demo (showing, 2 photos) and Family (1).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "demo": {"allowed": True},
        "frame": {"name": "tkframe"},
        "display": {"current_source": "demo", "rotation_interval": 30},
        "sync": {"interval": 900},
    }))
    monkeypatch.setattr(config_manager, "_path", config_path)
    monkeypatch.setattr(config_manager, "_lock", FileLock(tmp_path / "config.lock"))
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", config_path)
    original_from_yaml = settings_mod.Settings.from_yaml.__func__
    monkeypatch.setattr(settings_mod.Settings, "from_yaml",
                        classmethod(lambda cls, path=config_path: original_from_yaml(cls, path)))
    settings_mod.reload_settings()

    monkeypatch.setattr(device_storage, "_path", tmp_path / "devices.json")
    monkeypatch.setattr(device_storage, "_lock", FileLock(tmp_path / "devices.lock"))
    monkeypatch.setattr(invite_storage, "_path", tmp_path / "invites.json")
    monkeypatch.setattr(invite_storage, "_lock", FileLock(tmp_path / "invites.lock"))
    monkeypatch.setattr(jwt_handler, "SECRET_PATH", tmp_path / "jwt_secret")

    pictures = tmp_path / "Pictures"
    monkeypatch.setattr(album_service, "PICTURES_DIR", pictures)
    monkeypatch.setattr(thumbnails, "THUMB_CACHE_DIR", tmp_path / "thumbs")
    monkeypatch.setattr(dr, "BASELINE_DIR", tmp_path / ".wanderwall" / "demo_baseline")
    monkeypatch.setattr(dr, "PICFRAME_CONFIG_PATH", tmp_path / "picframe.yaml")
    monkeypatch.setattr(sync_service, "_is_syncing", False)
    monkeypatch.setattr(sync_service, "_current_source", None)

    state = SimpleNamespace(cloud={}, registry={"account": "dedicated", "koofr_user": USER},
                            links=2, shown=[], restarted=[], timer=[], tmp=tmp_path, pictures=pictures)

    async def sync_up(local_dir, remote):
        state.cloud[remote.split(":", 1)[1]] = {f.name: f.read_bytes() for f in Path(local_dir).iterdir()}
        return rclone.RcloneResult(success=True)

    async def purge(remote):
        state.cloud.pop(remote.split(":", 1)[1], None)
        return rclone.RcloneResult(success=True)

    async def list_dirs(remote):
        return list(state.cloud)

    async def koofr_remote():
        return "kfr"

    async def sync_source(source_id, local_path, rclone_remote):
        local_path.mkdir(parents=True, exist_ok=True)
        files = state.cloud.get(rclone_remote.split(":", 1)[1], {})
        for f in local_path.iterdir():
            if f.name not in files:
                f.unlink()
        for name, data in files.items():
            (local_path / name).write_bytes(data)
        return SimpleNamespace(success=True)

    async def switch_folder(path, restart_service=True):
        state.shown.append(Path(path).name)
        return True

    async def restart(name):
        state.restarted.append(name)
        return True

    async def timer(interval):
        state.timer.append(interval)
        return True

    async def upload_links():
        n, state.links = state.links, 0
        return n

    monkeypatch.setattr(dr, "rclone_sync_up", sync_up)
    monkeypatch.setattr(dr, "rclone_purge", purge)
    monkeypatch.setattr(frame_registry, "rclone_list_dirs", list_dirs)
    monkeypatch.setattr(frame_registry, "_koofr_remote", koofr_remote)
    monkeypatch.setattr(frame_registry, "local_doc",
                        lambda: {**frame_registry._new_doc("1000000002343a2b"), **state.registry})
    monkeypatch.setattr(sync_service, "sync_source", sync_source)
    monkeypatch.setattr(display_service, "switch_folder", switch_folder)
    monkeypatch.setattr(systemd_service, "restart", restart)
    monkeypatch.setattr(dr, "update_sync_timer", timer)
    monkeypatch.setattr(dr, "_remove_upload_links", upload_links)

    manager = SourceManager(tmp_path / "sources.yaml")
    monkeypatch.setattr(sm, "source_manager", manager)
    state.manager = manager
    _album(state, "demo", "Demo", {"a.jpg": b"A", "b.heic": b"B"})
    _album(state, "family", "Family", {"c.jpg": b"C"})
    yield state
    settings_mod.get_settings.cache_clear()


def _album(state, sid, name, photos):
    """An album on the frame and its cloud folder, both holding `photos`."""
    folder = state.pictures / sid
    folder.mkdir(parents=True, exist_ok=True)
    for fname, data in photos.items():
        (folder / fname).write_bytes(data)
    state.cloud[f"KFR_{sid}"] = dict(photos)
    state.manager._save_sources(state.manager.list_sources() + [
        PhotoSource(id=sid, name=name, local_path=str(folder), rclone_remote=f"kfr:KFR_{sid}")])


def _device(device_id, role="admin", demo=False):
    device_storage.add_device(Device(id=device_id, name=device_id, role=role, demo=demo,
                                     paired_at=datetime.now(timezone.utc)))


def _run(coro):
    return asyncio.run(coro)


# --- Save and reset ------------------------------------------------------------------

def test_reset_puts_the_frame_back(frame):
    saved = _run(dr.save_baseline())
    assert saved["photos"] == 3 and saved["showing"] == "KFR_demo"
    assert [(a["name"], a["photos"]) for a in saved["albums"]] == [("Demo", 2), ("Family", 1)]

    # The reviewer: new album shown, Family deleted, Demo renamed with a photo added and one removed,
    # an old cloud folder, settings changed, phones and an invite
    _album(frame, "reviewer", "Reviewer", {"r.jpg": b"R"})
    config_manager.set("display.current_source", "reviewer")
    settings_mod.reload_settings()
    album_service.delete_album("family")
    demo = frame.manager.get_source("demo")
    demo.name = "Renamed"
    frame.manager.update_source(demo)
    (frame.pictures / "demo" / "a.jpg").unlink()
    del frame.cloud["KFR_demo"]["a.jpg"]
    frame.cloud["KFR_demo"]["new.jpg"] = b"N"
    frame.cloud["KFR_left_over"] = {"x.jpg": b"X"}
    config_manager.update({"frame": {"name": "Hacked"}, "display": {"rotation_interval": 10}, "sync": {"interval": 300}})
    settings_mod.reload_settings()
    codes = demo_service.enable_demo()
    _device("owner")
    _device("reviewer-phone", demo=True)
    _device("share-phone", role="contributor")
    invite_storage.create_invite()

    result = _run(dr.reset_to_baseline())

    assert {s.rclone_remote: s.name for s in frame.manager.list_sources()} == {
        "kfr:KFR_demo": "Demo", "kfr:KFR_family": "Family"}
    assert frame.cloud == {"KFR_demo": {"a.jpg": b"A", "b.heic": b"B"}, "KFR_family": {"c.jpg": b"C"}}
    family = next(s for s in frame.manager.list_sources() if s.rclone_remote == "kfr:KFR_family")
    assert sorted(p.name for p in Path(family.local_path).iterdir()) == ["c.jpg"]
    assert sorted(p.name for p in (frame.pictures / "demo").iterdir()) == ["a.jpg", "b.heic"]
    assert not (frame.pictures / "reviewer").exists()
    settings = settings_mod.get_settings()
    assert settings.display.current_source == "demo" and frame.shown[-1] == "demo"
    assert (settings.frame.name, settings.display.rotation_interval, settings.sync.interval) == ("tkframe", 30, 900)
    assert frame.restarted == ["picframe"] and frame.timer == [900]
    assert [d.id for d in device_storage.list_devices()] == ["owner"]
    assert invite_storage.list_invites() == []
    assert settings.demo.enabled and settings.demo.admin_code == codes["admin_code"]
    assert result["demo"]["days_left"] == 14
    assert (result["phones_removed"], result["invites_removed"], result["upload_links_removed"]) == (2, 1, 2)
    assert (result["albums_deleted"], result["cloud_folders_deleted"]) == (1, 2)  # KFR_reviewer, KFR_left_over
    assert [(a["name"], a["photos"], a["synced"]) for a in result["albums"]] == [("Demo", 2, True), ("Family", 1, True)]
    assert result["settings_restored"] == ["frame name", "rotation", "sync interval"]


def test_reset_twice_changes_nothing_more(frame):
    _run(dr.save_baseline())
    _run(dr.reset_to_baseline())
    again = _run(dr.reset_to_baseline())
    assert (again["albums_deleted"], again["cloud_folders_deleted"], again["settings_restored"]) == (0, 0, [])
    assert set(frame.cloud) == {"KFR_demo", "KFR_family"}


def test_saving_again_replaces_the_baseline(frame):
    _run(dr.save_baseline())
    (frame.pictures / "family" / "d.jpg").write_bytes(b"D")
    _run(dr.save_baseline())
    assert [a["photos"] for a in dr.baseline_info()["albums"]] == [2, 2]
    assert not dr.BASELINE_DIR.with_name("demo_baseline.new").exists()
    assert not dr.BASELINE_DIR.with_name("demo_baseline.old").exists()


# --- Refusals ---------------------------------------------------------------------------

@pytest.mark.parametrize("registry, message", [
    ({"account": "shared", "koofr_user": USER}, "isn't marked dedicated"),
    ({"account": "dedicated", "koofr_user": "other@example.com"}, "Koofr account changed"),
])
def test_reset_refuses_shared_or_other_account(frame, registry, message):
    _run(dr.save_baseline())
    frame.registry = registry
    _device("reviewer-phone", demo=True)
    with pytest.raises(dr.DemoResetError, match=message):
        _run(dr.reset_to_baseline())
    assert len(device_storage.list_devices()) == 1  # nothing touched


def test_not_allowed_without_demo_allowed(frame):
    config_manager.set("demo.allowed", False)
    settings_mod.reload_settings()
    with pytest.raises(dr.DemoResetError) as e:
        _run(dr.save_baseline())
    assert e.value.status_code == 403


def test_save_refuses_album_without_cloud_folder(frame):
    frame.manager._save_sources(frame.manager.list_sources() + [
        PhotoSource(id="local", name="Local", local_path=str(frame.pictures / "local"), rclone_remote=None)])
    with pytest.raises(dr.DemoResetError, match="no cloud folder"):
        _run(dr.save_baseline())


def test_reset_without_baseline_over_the_dashboard(frame):
    r = TestClient(app, client=LAN).post("/api/settings/demo/reset")
    assert r.status_code == 409
    assert r.json() == {"ok": False, "error": "No baseline saved yet. Set the frame up, then Save as Baseline."}


# --- Koofr upload links ------------------------------------------------------------------

def test_upload_links_deleted_through_koofr_api(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers["authorization"]))
        if request.method == "GET":
            return httpx.Response(200, json={"mounts": {}, "receivers": [
                {"id": "11111111-1111-1111-1111-111111111111", "mountId": "m-1"},
                {"id": "22222222-2222-2222-2222-222222222222", "mountId": "m-1"},
                {"id": "../../user", "mountId": "m-1"},
            ]})
        return httpx.Response(204)

    async def login():
        return (USER, "app-pass")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dr, "_koofr_login", login)
    monkeypatch.setattr(dr.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    assert _run(dr._remove_upload_links()) == 2
    basic = "Basic " + base64.b64encode(f"{USER}:app-pass".encode()).decode()
    assert calls == [
        ("GET", "/api/v2.1/receivers", basic),
        ("DELETE", "/api/v2.1/mounts/m-1/receivers/11111111-1111-1111-1111-111111111111", basic),
        ("DELETE", "/api/v2.1/mounts/m-1/receivers/22222222-2222-2222-2222-222222222222", basic),
    ]


def test_upload_links_koofr_refusal_is_an_error(monkeypatch):
    async def login():
        return (USER, "wrong")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dr, "_koofr_login", login)
    monkeypatch.setattr(dr.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(401)), **kw))
    with pytest.raises(dr.DemoResetError, match="HTTP 401"):
        _run(dr._remove_upload_links())


# --- rclone guards ------------------------------------------------------------------------

def test_rclone_never_syncs_or_purges_the_account_root(tmp_path):
    assert rclone._is_remote_subfolder("kfr:KFR_demo")
    for root in ("kfr:", "kfr:/", "/local", "kfr"):
        assert not rclone._is_remote_subfolder(root)
    assert not _run(rclone.rclone_sync_up(tmp_path, "kfr:")).success
    assert not _run(rclone.rclone_purge("kfr:/")).success


def test_dashboard_card_shows_the_baseline(frame):
    client = TestClient(app, client=LAN)
    page = client.get("/").text
    assert "No baseline saved yet." in page and 'id="btn-demo-reset" style="margin-left:0.5rem;" disabled' in page
    _run(dr.save_baseline())
    page = client.get("/").text
    assert "2 albums" in page and "(Demo: 2, Family: 1)" in page
    assert 'id="btn-demo-reset" style="margin-left:0.5rem;" >' in page
