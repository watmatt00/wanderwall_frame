"""
Unit tests: display sleep timers are rebuilt from config at API startup (PL-210).

A v4 -> v5 reinstall kept `display.sleep_enabled: true` in config but left no
wanderwall-sleep/wake units, so night mode never ran. reconcile_sleep_timers() runs at
startup and repairs that, and leaves a matching setup alone. systemctl is faked.
"""

import asyncio

import pytest

from src.services import systemd_service as svc


class FakeSystemctl:
    """Stands in for asyncio.create_subprocess_exec("systemctl", "--user", ...)."""

    def __init__(self) -> None:
        self.enabled: set[str] = set()
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args, **kwargs):
        assert args[:2] == ("systemctl", "--user"), args
        verb, *rest = args[2:]
        self.calls.append((verb, *rest))
        out = b""
        if verb == "enable":
            self.enabled.add(rest[-1])
        elif verb == "disable":
            self.enabled.discard(rest[-1])
        elif verb == "is-enabled":
            out = b"enabled\n" if rest[0] in self.enabled else b"disabled\n"
        elif verb == "is-active":
            out = b"active\n" if rest[0] in self.enabled else b"inactive\n"
        return _Proc(out)

    def changes(self) -> list[tuple[str, ...]]:
        """Calls that change something (not the is-enabled / is-active checks)."""
        return [c for c in self.calls if c[0] not in ("is-enabled", "is-active")]


class _Proc:
    def __init__(self, out: bytes) -> None:
        self.returncode = 0
        self._out = out

    async def communicate(self):
        return self._out, b""


@pytest.fixture
def frame(tmp_path, monkeypatch):
    """Unit dir and helper path under tmp_path; systemctl faked."""
    unit_dir = tmp_path / ".config" / "systemd" / "user"
    helper = tmp_path / ".local" / "bin" / "wanderwall-display"
    monkeypatch.setattr(svc, "_SLEEP_TIMER_DIR", unit_dir)
    monkeypatch.setattr(svc, "_DISPLAY_HELPER_PATH", helper)
    fake = FakeSystemctl()
    monkeypatch.setattr(svc.asyncio, "create_subprocess_exec", fake)
    return unit_dir, helper, fake


def _run(enabled: bool, sleep: str = "22:00", wake: str = "06:00") -> str:
    return asyncio.run(svc.reconcile_sleep_timers(enabled, sleep, wake))


def test_missing_units_are_rebuilt(frame):
    """The mnbframe/kframe case: schedule on in config, no units, no helper."""
    unit_dir, helper, fake = frame
    assert _run(True) == "repaired"
    assert "OnCalendar=*-*-* 22:00:00" in (unit_dir / "wanderwall-sleep.timer").read_text()
    assert "OnCalendar=*-*-* 06:00:00" in (unit_dir / "wanderwall-wake.timer").read_text()
    assert (unit_dir / "wanderwall-sleep.service").is_file()
    assert (unit_dir / "wanderwall-wake.service").is_file()
    assert helper.read_text() == svc._DISPLAY_HELPER
    assert helper.stat().st_mode & 0o777 == 0o755
    assert fake.enabled == {"wanderwall-sleep.timer", "wanderwall-wake.timer"}
    assert ("daemon-reload",) in fake.changes()


def test_matching_setup_is_left_alone(frame):
    """A normal API start must not rewrite or re-enable anything."""
    _, _, fake = frame
    assert _run(True) == "repaired"
    fake.calls.clear()
    assert _run(True) == "ok"
    assert fake.changes() == []


def test_changed_time_in_config_is_applied(frame):
    unit_dir, _, fake = frame
    _run(True, sleep="22:00")
    assert _run(True, sleep="21:15") == "repaired"
    assert "OnCalendar=*-*-* 21:15:00" in (unit_dir / "wanderwall-sleep.timer").read_text()


def test_disabled_timer_is_re_enabled(frame):
    """Files fine, but a timer was disabled (by hand or a failed save)."""
    _, _, fake = frame
    _run(True)
    fake.enabled.discard("wanderwall-wake.timer")
    fake.calls.clear()
    assert _run(True) == "repaired"
    assert ("enable", "--now", "wanderwall-wake.timer") in fake.changes()


def test_missing_helper_only_is_rebuilt(frame):
    _, helper, _ = frame
    _run(True)
    helper.unlink()
    assert _run(True) == "repaired"
    assert helper.is_file()


def test_schedule_off_and_no_units_does_nothing(frame):
    _, _, fake = frame
    assert _run(False) == "ok"
    assert fake.calls == []


def test_schedule_off_but_timers_on_are_turned_off(frame):
    _, _, fake = frame
    _run(True)
    fake.calls.clear()
    assert _run(False) == "disabled"
    assert fake.enabled == set()
    assert ("disable", "--now", "wanderwall-sleep.timer") in fake.changes()


def test_schedule_off_and_timers_already_off_does_nothing(frame):
    _, _, fake = frame
    _run(True)
    asyncio.run(svc.update_sleep_timers(False, "22:00", "06:00"))
    fake.calls.clear()
    assert _run(False) == "ok"
    assert fake.changes() == []


def test_bad_time_in_config_fails_without_writing(frame):
    unit_dir, _, fake = frame
    assert _run(True, sleep="25:99x") == "failed"
    assert not (unit_dir / "wanderwall-sleep.timer").exists()
    assert fake.enabled == set()


def test_save_and_startup_write_the_same_files(frame):
    """The save path and the startup check agree, so a save is never 'repaired' next start."""
    _, _, fake = frame
    assert asyncio.run(svc.update_sleep_timers(True, "22:00", "07:00")) is True
    fake.calls.clear()
    assert _run(True, wake="07:00") == "ok"
    assert fake.changes() == []


def test_api_startup_runs_the_check_with_config_values(monkeypatch):
    """lifespan passes the saved display schedule to reconcile_sleep_timers."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from src.api import app as app_module

    seen = []

    async def fake_reconcile(enabled, sleep_time, wake_time):
        seen.append((enabled, sleep_time, wake_time))
        return "ok"

    async def no_scheduler():
        return None

    display = SimpleNamespace(sleep_enabled=True, sleep_time="22:00", wake_time="06:00")
    monkeypatch.setattr(app_module, "reconcile_sleep_timers", fake_reconcile)
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(display=display))
    monkeypatch.setattr(app_module, "start_update_scheduler", no_scheduler)
    monkeypatch.setattr(app_module.demo_service, "expire_if_due", lambda: None)
    monkeypatch.setattr(app_module.frame_registry, "start", lambda: None)

    with TestClient(app_module.app) as client:
        client.get("/health")
    assert seen == [(True, "22:00", "06:00")]
