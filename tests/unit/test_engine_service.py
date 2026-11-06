"""Tests for src/services/engine_service.py: engine status and Upgrade button (KP-014, KP-015)."""

from pathlib import Path

import pytest

from src.services import engine_service as es


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake home with a repo holding the pin."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    repo = tmp_path / "wanderwall_frame"
    (repo / "scripts" / "setup").mkdir(parents=True)
    (repo / "scripts" / "setup" / "picframe-requirements.txt").write_text(
        "# pin\npicframe==2026.4.22\nnumpy==2.4.4\n"
    )
    (repo / "scripts" / "setup" / "update_engine.sh").write_text("#!/bin/bash\n")
    monkeypatch.setattr(es, "get_repo_path", lambda: repo)
    (tmp_path / ".wanderwall").mkdir()
    return tmp_path


def _engine(
    home: Path, version: str, folder: str = "venv_picframe", py: str = "python3.11"
) -> Path:
    site = home / folder / "lib" / py / "site-packages"
    (site / f"picframe-{version}.dist-info").mkdir(parents=True)
    (site / "numpy-2.4.4.dist-info").mkdir()
    return home / folder


def test_pinned_version(home: Path) -> None:
    assert es.pinned_version() == "2026.4.22"


@pytest.mark.parametrize("content", ["numpy==1\n", "picframe>=2026\n", "picframe==latest\n"])
def test_pinned_version_rejects_bad_pin(home: Path, content: str) -> None:
    es.requirements_path().write_text(content)
    assert es.pinned_version() is None


def test_installed_version_through_symlink(home: Path) -> None:
    target = _engine(home, "2024.11.1", folder="venv_picframe-2024.11.1")
    (home / "venv_picframe").symlink_to(target)
    assert es.installed_version() == "2024.11.1"


def test_installed_version_missing(home: Path) -> None:
    assert es.installed_version() is None


def test_clear_hold_keeps_other_lines(home: Path) -> None:
    path = es.engine_state_path()
    path.write_text("# header\nupgrade: hold\nlast_result: 'on_hold'\n")
    assert es.clear_hold() is True
    assert path.read_text() == "# header\nlast_result: 'on_hold'\n"
    assert (path.stat().st_mode & 0o777) == 0o600
    assert es.clear_hold() is False


def test_clear_hold_without_file(home: Path) -> None:
    assert es.clear_hold() is False


@pytest.mark.asyncio
async def test_status_on_hold_v4_frame(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _engine(home, "2024.9.24")
    es.engine_state_path().write_text(
        "upgrade: hold\nlast_result: 'on_hold'\nmessage: 'kept'\nlast_run: '2026-11-06 10:00:00'\n"
    )

    async def not_running() -> bool:
        return False

    monkeypatch.setattr(es, "upgrade_running", not_running)
    status = await es.get_engine_status()
    assert status == {
        "installed_version": "2024.9.24",
        "pinned_version": "2026.4.22",
        "matches_pin": False,
        "on_hold": True,
        "running": False,
        "last_result": "on_hold",
        "last_run": "2026-11-06 10:00:00",
        "message": "kept",
        "previous_version": None,
    }


@pytest.mark.asyncio
async def test_status_matches_pin_without_state_file(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _engine(home, "2026.4.22", py="python3.13")

    async def not_running() -> bool:
        return False

    monkeypatch.setattr(es, "upgrade_running", not_running)
    status = await es.get_engine_status()
    assert (
        status["matches_pin"] is True
        and status["on_hold"] is False
        and status["last_result"] is None
    )


@pytest.mark.asyncio
async def test_start_upgrade_clears_hold_and_starts_unit(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    es.engine_state_path().write_text("upgrade: hold\n")
    calls: list[tuple] = []

    async def fake_run(*args: str, timeout: float = 15) -> tuple[int, str]:
        calls.append(args)
        if args[:2] == ("systemctl", "--user"):
            return 3, "inactive"
        return 0, ""

    monkeypatch.setattr(es, "_run", fake_run)
    result = await es.start_engine_upgrade("dashboard")
    assert result["ok"] is True
    assert "upgrade: hold" not in es.engine_state_path().read_text()
    run = [c for c in calls if c[0] == "systemd-run"][0]
    assert "--unit=wanderwall-engine-update" in run and "--user" in run
    assert run[-1].endswith("scripts/setup/update_engine.sh")


@pytest.mark.asyncio
async def test_start_upgrade_refused_while_running(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    es.engine_state_path().write_text("upgrade: hold\n")

    async def running() -> bool:
        return True

    monkeypatch.setattr(es, "upgrade_running", running)
    result = await es.start_engine_upgrade("dashboard")
    assert result["ok"] is False and "already running" in result["error"]
    assert "upgrade: hold" in es.engine_state_path().read_text()  # hold untouched


@pytest.mark.asyncio
async def test_start_upgrade_reports_systemd_run_failure(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run(*args: str, timeout: float = 15) -> tuple[int, str]:
        if args[:2] == ("systemctl", "--user"):
            return 3, ""
        return 1, "Failed to start transient service unit"

    monkeypatch.setattr(es, "_run", fake_run)
    result = await es.start_engine_upgrade("dashboard")
    assert result["ok"] is False and "transient" in result["error"]
