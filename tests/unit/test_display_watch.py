"""Tests for scripts/display/display_watch.py, the display engine self-repair check (KP-034)."""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "display" / "display_watch.py"
_spec = importlib.util.spec_from_file_location("display_watch", _PATH)
dw = importlib.util.module_from_spec(_spec)
sys.modules["display_watch"] = dw  # dataclasses look the module up
_spec.loader.exec_module(dw)


class World:
    """Fake probes with settable answers; counts restarts."""

    def __init__(self) -> None:
        self.screen = "ready"
        self.active = True
        self.uptime: float | None = 3600.0
        self.answers = True
        self.updating = False
        self.restart_ok = True
        self.restart_calls = 0
        self.clock = 1_000_000.0

    def restart(self) -> bool:
        self.restart_calls += 1
        return self.restart_ok

    def probes(self) -> "dw.Probes":
        return dw.Probes(
            screen_state=lambda: self.screen,
            service_active=lambda: self.active,
            service_uptime=lambda: self.uptime,
            engine_answers=lambda: self.answers,
            engine_update_running=lambda: self.updating,
            restart_service=self.restart,
            now=lambda: self.clock,
        )


@pytest.fixture
def world() -> World:
    return World()


def _checks(state, world: World, n: int) -> list[str]:
    return [dw.check_once(state, world.probes()) for _ in range(n)]


def test_answering_engine_is_ok(world: World) -> None:
    state = dw.WatchState()
    assert dw.check_once(state, world.probes()) == "ok"
    assert state.failures == 0 and world.restart_calls == 0


def test_restarts_after_three_failures_in_a_row(world: World) -> None:
    state = dw.WatchState()
    world.answers = False
    assert _checks(state, world, 3) == ["failing", "failing", "restarted"]
    assert world.restart_calls == 1
    assert state.failures == 0 and len(state.restarts) == 1


def test_one_good_check_resets_the_count(world: World) -> None:
    state = dw.WatchState()
    world.answers = False
    _checks(state, world, 2)
    world.answers = True
    dw.check_once(state, world.probes())
    world.answers = False
    assert _checks(state, world, 2) == ["failing", "failing"]
    assert world.restart_calls == 0


@pytest.mark.parametrize("screen, expected", [("none", "no_screen"), ("asleep", "asleep")])
def test_no_screen_or_asleep_never_restarts(world: World, screen: str, expected: str) -> None:
    """No screen: the launcher is waiting for one, so a silent :9000 is expected (PL-187)."""
    state = dw.WatchState(failures=2)
    world.screen = screen
    world.answers = False
    assert _checks(state, world, 5) == [expected] * 5
    assert world.restart_calls == 0 and state.failures == 0


def test_inactive_service_is_left_to_systemd(world: World) -> None:
    state = dw.WatchState()
    world.active = False
    world.answers = False
    assert _checks(state, world, 4) == ["inactive"] * 4
    assert world.restart_calls == 0


def test_startup_grace(world: World) -> None:
    state = dw.WatchState()
    world.uptime = 30.0
    world.answers = False
    assert _checks(state, world, 4) == ["starting"] * 4
    assert world.restart_calls == 0


def test_engine_update_running_is_skipped(world: World) -> None:
    state = dw.WatchState(failures=2)
    world.updating = True
    world.answers = False
    assert dw.check_once(state, world.probes()) == "skipped_update"
    assert world.restart_calls == 0
    assert state.failures == 2


def test_restart_cap_then_recovery(world: World, caplog: pytest.LogCaptureFixture) -> None:
    """At most 3 restarts in 6 h, then one ERROR and no more; the cap resets when it answers."""
    state = dw.WatchState()
    world.answers = False
    for _ in range(3):
        assert _checks(state, world, 3)[-1] == "restarted"
        world.clock += 600
    with caplog.at_level(logging.ERROR, logger="display_watch"):
        results = _checks(state, world, 6)
    assert results[2] == "capped" and results[5] == "capped"
    assert world.restart_calls == 3
    assert len([r for r in caplog.records if "not restarting" in r.getMessage()]) == 1

    # Six hours later the window has room again: still failing, so the next check restarts
    world.clock += 6 * 3600
    assert dw.check_once(state, world.probes()) == "restarted"
    assert world.restart_calls == 4
    world.answers = True
    assert dw.check_once(state, world.probes()) == "ok"
    assert state.capped_logged is False


def test_failed_restart_is_reported(world: World) -> None:
    state = dw.WatchState()
    world.answers = False
    world.restart_ok = False
    assert _checks(state, world, 3)[-1] == "restart_failed"


def test_state_round_trip_and_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "display_watch.json"
    state = dw.WatchState(failures=2, restarts=[1.0, 2.5], capped_logged=True)
    state.save(path)
    assert (path.stat().st_mode & 0o777) == 0o600
    loaded = dw.WatchState.load(path)
    assert (loaded.failures, loaded.restarts, loaded.capped_logged) == (2, [1.0, 2.5], True)

    path.write_text("{not json")
    assert dw.WatchState.load(path) == dw.WatchState()
    assert dw.WatchState.load(tmp_path / "missing.json") == dw.WatchState()


def test_engine_lock_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """real_engine_update_running sees update_engine.sh's flock."""
    import fcntl

    lock = tmp_path / "engine.lock"
    monkeypatch.setattr(dw, "ENGINE_LOCK", lock)
    assert dw.real_engine_update_running() is False
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert dw.real_engine_update_running() is True
    assert dw.real_engine_update_running() is False
