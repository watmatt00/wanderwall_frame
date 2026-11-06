#!/usr/bin/env python3
"""
WanderWall - display engine self-repair check (KP-034).

Run once a minute by wanderwall-display-watch.timer. When picframe.service is active, a
screen is on and the engine's HTTP API (:9000) stops answering for FAILURES_BEFORE_RESTART
checks in a row, it restarts picframe.service and logs it to wanderwall.log. At most
MAX_RESTARTS restarts in RESTART_WINDOW, so a broken engine doesn't loop; after that it logs
one ERROR and waits until the engine answers again.

It does nothing while:
- no screen is connected or the display is asleep (the launcher waits for a screen, PL-187),
- picframe.service isn't active (systemd's own Restart= handles that),
- the service started less than STARTUP_GRACE ago,
- an engine update holds ~/.wanderwall/engine.lock (update_engine.sh).

Standard library only: it runs with the system python3, like the indicator lights.
State: ~/.wanderwall/display_watch.json (written atomically).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

FAILURES_BEFORE_RESTART = 3
MAX_RESTARTS = 3
RESTART_WINDOW = 6 * 3600  # seconds
STARTUP_GRACE = 120  # seconds after picframe.service starts
PROBE_TIMEOUT = 5  # seconds per HTTP check
HEALTH_URL = "http://localhost:9000/"
SERVICE = "picframe.service"

HOME = Path(os.environ.get("WW_HOME", str(Path.home())))
WW_DIR = HOME / ".wanderwall"
STATE_PATH = WW_DIR / "display_watch.json"
ENGINE_LOCK = WW_DIR / "engine.lock"
LOG_PATH = WW_DIR / "logs" / "wanderwall.log"
SCREEN_LIB = Path(__file__).resolve().parent / "screen_lib.sh"

logger = logging.getLogger("display_watch")


@dataclass
class WatchState:
    """What the check remembers between runs."""

    failures: int = 0
    restarts: list[float] = field(default_factory=list)
    capped_logged: bool = False

    @classmethod
    def load(cls, path: Path) -> WatchState:
        """Read the state file; a missing or unreadable file starts fresh."""
        try:
            data = json.loads(path.read_text())
            return cls(
                failures=int(data.get("failures", 0)),
                restarts=[float(t) for t in data.get("restarts", [])],
                capped_logged=bool(data.get("capped_logged", False)),
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        """Write the state file atomically (temp file + rename), mode 600."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(
                    {
                        "failures": self.failures,
                        "restarts": self.restarts,
                        "capped_logged": self.capped_logged,
                    },
                    f,
                )
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


@dataclass
class Probes:
    """The outside world, injectable for tests."""

    screen_state: Callable[[], str]
    service_active: Callable[[], bool]
    service_uptime: Callable[[], float | None]
    engine_answers: Callable[[], bool]
    engine_update_running: Callable[[], bool]
    restart_service: Callable[[], bool]
    now: Callable[[], float] = time.time


def check_once(state: WatchState, probes: Probes) -> str:
    """
    Run one check and update state in place.

    Returns:
        A short word for what happened (for tests and the journal): skipped_update,
        no_screen, asleep, inactive, starting, ok, failing, restarted, restart_failed, capped
    """
    if probes.engine_update_running():
        return "skipped_update"

    screen = probes.screen_state()
    if screen != "ready":
        state.failures = 0
        return "no_screen" if screen == "none" else "asleep"

    if not probes.service_active():
        state.failures = 0
        return "inactive"

    uptime = probes.service_uptime()
    if uptime is not None and uptime < STARTUP_GRACE:
        state.failures = 0
        return "starting"

    if probes.engine_answers():
        if state.failures or state.capped_logged:
            logger.info("Display engine answers again on %s", HEALTH_URL)
        state.failures = 0
        state.capped_logged = False
        return "ok"

    state.failures += 1
    if state.failures < FAILURES_BEFORE_RESTART:
        return "failing"

    now = probes.now()
    state.restarts = [t for t in state.restarts if now - t < RESTART_WINDOW]
    if len(state.restarts) >= MAX_RESTARTS:
        if not state.capped_logged:
            logger.error(
                "Display engine not answering on %s, but not restarting: "
                "%d restarts in the last %d h already "
                "(journalctl --user -u picframe)",
                HEALTH_URL,
                len(state.restarts),
                RESTART_WINDOW // 3600,
            )
            state.capped_logged = True
        return "capped"

    logger.warning(
        "Display engine not answering on %s for %d checks in a row; restarting %s",
        HEALTH_URL,
        state.failures,
        SERVICE,
    )
    state.failures = 0
    state.restarts.append(now)
    if probes.restart_service():
        logger.info("Service %s restarted successfully by the display check", SERVICE)
        return "restarted"
    logger.error("Failed to restart %s (systemctl --user restart)", SERVICE)
    return "restart_failed"


# ── Real probes ──────────────────────────────────────────────────────────────


def _systemctl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run systemctl --user with explicit arguments (no shell)."""
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def real_screen_state() -> str:
    """Ask scripts/display/screen_lib.sh, the same check the launcher uses."""
    try:
        out = subprocess.run(
            ["bash", "-c", 'source "$1" && screen_state', "screen_state", str(SCREEN_LIB)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "ready"  # can't tell: fall through to the engine check
    state = out.stdout.strip()
    return state if state in ("none", "asleep", "ready") else "ready"


def real_service_active() -> bool:
    """True when picframe.service is active."""
    try:
        return _systemctl("is-active", "--quiet", SERVICE).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def real_service_uptime() -> float | None:
    """Seconds since picframe.service last became active, or None if unknown."""
    try:
        out = _systemctl("show", SERVICE, "--property=ActiveEnterTimestampMonotonic", "--value")
        usec = int(out.stdout.strip() or "0")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if usec <= 0:
        return None
    return time.monotonic() - usec / 1_000_000


def real_engine_answers() -> bool:
    """True when the engine's HTTP API answers with a 2xx."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=PROBE_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def real_engine_update_running() -> bool:
    """True while update_engine.sh holds its lock."""
    try:
        with open(ENGINE_LOCK, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def real_restart_service() -> bool:
    """Restart picframe.service; True on success."""
    try:
        return _systemctl("restart", SERVICE, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _setup_logging() -> None:
    """Log to the journal (stdout) and append to wanderwall.log in the app's format."""
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    logger.setLevel(logging.INFO)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_PATH)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Can't write %s: %s", LOG_PATH, exc)


def main() -> int:
    """One check: load state, check, save state."""
    _setup_logging()
    state = WatchState.load(STATE_PATH)
    probes = Probes(
        screen_state=real_screen_state,
        service_active=real_service_active,
        service_uptime=real_service_uptime,
        engine_answers=real_engine_answers,
        engine_update_running=real_engine_update_running,
        restart_service=real_restart_service,
    )
    result = check_once(state, probes)
    try:
        state.save(STATE_PATH)
    except OSError as exc:
        logger.error("Failed to save %s: %s", STATE_PATH, exc)
        return 1
    print(f"display check: {result}")
    return 0 if result != "restart_failed" else 1


if __name__ == "__main__":
    sys.exit(main())
