"""
Unit tests: software updates on the demo frame (PL-150). While demo mode is on,
the app can check but not apply or schedule; the LAN dashboard still can.
"""

from datetime import datetime, timezone

import pytest
import yaml
from filelock import FileLock
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.routes import updates as update_routes
from src.auth import jwt_handler
from src.auth.models import Device
from src.config import settings as settings_mod
from src.config.manager import config_manager
from src.services import demo_service, update_service
from src.storage.devices import device_storage

LAN = ("192.168.1.50", 50000)
SCHEDULE = {"auto_check": True, "auto_apply": True, "frequency": "daily", "day": 0, "check_time": "03:00"}


@pytest.fixture
def frame(tmp_path, monkeypatch):
    """Isolated config and devices, demo.allowed, an admin token, and git faked."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"demo": {"allowed": True}}))
    monkeypatch.setattr(config_manager, "_path", config_path)
    monkeypatch.setattr(config_manager, "_lock", FileLock(tmp_path / "config.lock"))
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", config_path)
    original_from_yaml = settings_mod.Settings.from_yaml.__func__
    monkeypatch.setattr(settings_mod.Settings, "from_yaml",
                        classmethod(lambda cls, path=config_path: original_from_yaml(cls, path)))
    settings_mod.reload_settings()
    monkeypatch.setattr(device_storage, "_path", tmp_path / "devices.json")
    monkeypatch.setattr(device_storage, "_lock", FileLock(tmp_path / "devices.lock"))
    monkeypatch.setattr(jwt_handler, "SECRET_PATH", tmp_path / "jwt_secret")
    device_storage.add_device(Device(id="admin1", name="admin1", role="admin", paired_at=datetime.now(timezone.utc)))
    token = jwt_handler.create_token(device_id="admin1", device_name="admin1", role="admin", frame_id="f")

    applied = []

    async def apply_and_restart(source):
        applied.append(source)
        return {"ok": True, "output": "Already up to date.", "error": None}

    async def check():
        return {"ok": True, "up_to_date": True, "error": None}

    monkeypatch.setattr(update_routes, "apply_update_and_restart", apply_and_restart)
    monkeypatch.setattr(update_routes, "run_update_check", check)
    yield {"headers": {"Authorization": f"Bearer {token}"}, "applied": applied}
    settings_mod.get_settings.cache_clear()


def _app(frame, path, body=None):
    return TestClient(app, client=LAN).post(f"/api/v1/updates/{path}", json=body or {}, headers=frame["headers"])


def test_app_cannot_apply_or_schedule_while_demo_is_on(frame):
    demo_service.enable_demo()
    for path, body in (("apply", None), ("schedule", SCHEDULE)):
        r = _app(frame, path, body)
        assert r.status_code == 403
        assert r.json()["detail"] == update_service.DEMO_LOCKED_MESSAGE
    assert frame["applied"] == []
    assert settings_mod.get_settings().updates.auto_apply is False


def test_app_can_still_check_while_demo_is_on(frame):
    demo_service.enable_demo()
    r = _app(frame, "check")
    assert r.status_code == 200 and r.json()["up_to_date"] is True


def test_app_updates_work_when_demo_is_off(frame):
    demo_service.enable_demo()
    demo_service.disable_demo()
    assert _app(frame, "apply").json()["ok"] is True
    assert _app(frame, "schedule", SCHEDULE).json() == {"ok": True}
    assert frame["applied"] == ["app"]


def test_locked_only_with_demo_allowed_and_on(frame):
    assert update_service.updates_locked() is False  # allowed, not on
    demo_service.enable_demo()
    assert update_service.updates_locked() is True
    config_manager.set("demo.allowed", False)
    settings_mod.reload_settings()
    assert update_service.updates_locked() is False


def test_dashboard_can_still_schedule_while_demo_is_on(frame):
    demo_service.enable_demo()
    r = TestClient(app, client=LAN).post("/api/updates/schedule", json=SCHEDULE)
    assert r.json() == {"ok": True}
