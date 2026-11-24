"""
Unit tests: album folders saved as `~/Pictures/<id>` (PL-211).

mnbframe's albums were typed in by hand from the v3 -> v4 upgrade doc with `~`
paths, and the preview on the frame (POST /display/spotlight) 404'd because it
built Path(local_path) without expanduser(). Albums now always load as full
paths, and the API rewrites a `~` sources.yaml once at startup.
"""

from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.dependencies import require_admin
from src.api.routes import display
from src.services.source_manager import PhotoSource, SourceManager

TILDE_SOURCES = {
    "sources": [
        {"id": "kfr_mnbframe", "name": "mnbframe", "local_path": "~/Pictures/kfr_mnbframe",
         "rclone_remote": "kfr-mnbframe:kfr_mnbframe", "enabled": True},
        {"id": "LVRK", "name": "Lawson", "local_path": "~/Pictures/LVRK",
         "rclone_remote": "kfr-mnbframe:LVRK", "enabled": True},
    ]
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """HOME points at tmp_path, so expanduser() gives tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _write(path, data):
    path.write_text(yaml.safe_dump(data, default_flow_style=False))


# ── PhotoSource ──────────────────────────────────────────────────────────────

def test_tilde_path_loads_as_full_path(home):
    s = PhotoSource(id="a", name="A", local_path="~/Pictures/a")
    assert s.local_path == f"{home}/Pictures/a"


def test_full_path_unchanged(home):
    s = PhotoSource(id="a", name="A", local_path="/home/pi/Pictures/a")
    assert s.local_path == "/home/pi/Pictures/a"


def test_manager_returns_full_paths_before_any_rewrite(home):
    path = home / "sources.yaml"
    _write(path, TILDE_SOURCES)
    mgr = SourceManager(path)
    assert mgr.get_source("LVRK").local_path == f"{home}/Pictures/LVRK"
    assert "~" in path.read_text()  # loading alone doesn't touch the file


# ── expand_saved_paths (API startup) ─────────────────────────────────────────

def test_startup_rewrite_expands_file_once(home):
    path = home / "sources.yaml"
    _write(path, TILDE_SOURCES)
    mgr = SourceManager(path)

    assert mgr.expand_saved_paths() == ["kfr_mnbframe", "LVRK"]
    saved = yaml.safe_load(path.read_text())["sources"]
    assert [s["local_path"] for s in saved] == [
        f"{home}/Pictures/kfr_mnbframe", f"{home}/Pictures/LVRK",
    ]
    # Everything else kept
    assert [(s["id"], s["name"], s["rclone_remote"], s["enabled"]) for s in saved] == [
        ("kfr_mnbframe", "mnbframe", "kfr-mnbframe:kfr_mnbframe", True),
        ("LVRK", "Lawson", "kfr-mnbframe:LVRK", True),
    ]

    before = path.read_text()
    assert mgr.expand_saved_paths() == []  # second start: nothing to do
    assert path.read_text() == before


def test_startup_rewrite_leaves_full_paths_alone(home):
    path = home / "sources.yaml"
    _write(path, {"sources": [
        {"id": "a", "name": "A", "local_path": "/home/pi/Pictures/a", "enabled": True},
    ]})
    before = path.read_text()
    calls = []
    mgr = SourceManager(path)
    mgr.add_listener(calls.append)
    assert mgr.expand_saved_paths() == []
    assert path.read_text() == before
    assert calls == []


def test_startup_rewrite_no_file(home):
    assert SourceManager(home / "missing.yaml").expand_saved_paths() == []


def test_startup_rewrite_leaves_unreadable_file_alone(home):
    path = home / "sources.yaml"
    path.write_text("sources: [unclosed\n  local_path: ~/x")
    before = path.read_text()
    assert SourceManager(path).expand_saved_paths() == []
    assert path.read_text() == before


def test_startup_rewrite_survives_save_error(home, monkeypatch):
    path = home / "sources.yaml"
    _write(path, TILDE_SOURCES)
    mgr = SourceManager(path)

    def boom(_sources):
        raise OSError("read-only file system")

    monkeypatch.setattr(mgr, "_save_sources", boom)
    assert mgr.expand_saved_paths() == []


# ── The preview itself ───────────────────────────────────────────────────────

@pytest.fixture
def spotlight(home, monkeypatch):
    """POST /display/spotlight against a `~` album, with the display and config mocked."""
    path = home / "sources.yaml"
    _write(path, TILDE_SOURCES)
    album = home / "Pictures" / "kfr_mnbframe"
    album.mkdir(parents=True)
    (album / "photo.jpg").write_bytes(b"jpeg")

    monkeypatch.setattr(display, "source_manager", SourceManager(path))
    monkeypatch.setattr(display, "SPOTLIGHT_DIR", home / "Pictures" / "spotlight")
    settings = SimpleNamespace(display=SimpleNamespace(current_source="kfr_mnbframe"))
    monkeypatch.setattr(display, "get_settings", lambda: settings)
    monkeypatch.setattr(display.config_manager, "set", lambda *a, **k: None)
    monkeypatch.setattr(display, "reload_settings", lambda: None)

    calls = []

    async def no_sleep(_s):
        return None

    async def switch(p):
        calls.append(("switch", str(p)))
        return True

    async def pause():
        calls.append(("pause",))

    async def resume():
        calls.append(("resume",))

    monkeypatch.setattr(display.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(display.display_service, "switch_folder", switch)
    monkeypatch.setattr(display.display_service, "pause", pause)
    monkeypatch.setattr(display.display_service, "resume", resume)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    yield home, calls
    app.dependency_overrides.pop(require_admin, None)


def _preview(filename):
    """POST /display/spotlight for a photo in the `~` album, for 1 s."""
    body = {"source_id": "kfr_mnbframe", "filename": filename, "duration_seconds": 1}
    return TestClient(app).post("/api/v1/display/spotlight", json=body)


def test_spotlight_works_for_tilde_album(spotlight):
    home, calls = spotlight
    r = _preview("photo.jpg")
    assert r.status_code == 200, r.text
    # Shown from the spotlight folder, then restored to the album's full path
    assert calls[0] == ("switch", f"{home}/Pictures/spotlight")
    assert ("switch", f"{home}/Pictures/kfr_mnbframe") in calls


def test_spotlight_still_404s_for_missing_photo(spotlight):
    r = _preview("nope.jpg")
    assert r.status_code == 404
