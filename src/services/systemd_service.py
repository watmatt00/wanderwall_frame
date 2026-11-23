"""
WanderWall - systemd Service Control.

Wrapper for controlling systemd user services.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Whitelist of services that can be controlled
ALLOWED_SERVICES = frozenset({"picframe", "wanderwall-api", "wanderwall-lights", "wanderwall-sync.timer"})

# Allowed sync intervals in seconds (0 = disabled)
VALID_SYNC_INTERVALS = frozenset({0, 300, 600, 900, 1800, 2700, 3600, 7200, 21600, 43200, 86400})

# OnCalendar expressions for clock-aligned firing (multiples of interval from midnight)
_SYNC_CALENDAR = {
    300:   "*:0/5",
    600:   "*:0/10",
    900:   "*:0/15",
    1800:  "*:0/30",
    2700:  (
        "*-*-* "
        "00:00,00:45,01:30,02:15,03:00,03:45,04:30,05:15,"
        "06:00,06:45,07:30,08:15,09:00,09:45,10:30,11:15,"
        "12:00,12:45,13:30,14:15,15:00,15:45,16:30,17:15,"
        "18:00,18:45,19:30,20:15,21:00,21:45,22:30,23:15"
    ),
    3600:  "*:00",
    7200:  "*-*-* 00,02,04,06,08,10,12,14,16,18,20,22:00",
    21600: "*-*-* 00,06,12,18:00",
    43200: "*-*-* 00,12:00",
    86400: "*-*-* 00:00",
}

_SYNC_TIMER_PATH = Path.home() / ".config" / "systemd" / "user" / "wanderwall-sync.timer"

_TIMER_TEMPLATE = """\
[Unit]
Description=WanderWall Photo Sync Timer
After=wanderwall-api.service

[Timer]
# Run 15 minutes after boot
OnBootSec=15min
# Fire at clock-aligned intervals
OnCalendar={calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""


async def update_sync_timer(interval_seconds: int) -> bool:
    """
    Write a new wanderwall-sync.timer unit with the given interval and reload systemd.

    If interval_seconds is 0, stop the timer instead.
    interval_seconds must be a value from VALID_SYNC_INTERVALS.
    Returns True on success.
    """
    if interval_seconds not in VALID_SYNC_INTERVALS:
        logger.error(f"Invalid sync interval: {interval_seconds}")
        return False

    try:
        if interval_seconds == 0:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "stop", "wanderwall-sync.timer",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info("Sync timer stopped (disabled)")
            return True

        calendar = _SYNC_CALENDAR[interval_seconds]
        content = _TIMER_TEMPLATE.format(calendar=calendar)

        # Atomic write: temp file then rename
        tmp_path = _SYNC_TIMER_PATH.with_suffix(".timer.tmp")
        tmp_path.write_text(content)
        tmp_path.rename(_SYNC_TIMER_PATH)

        # Reload systemd unit files
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "daemon-reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"daemon-reload failed: {stderr.decode()}")
            return False

        # Restart the timer so the new OnCalendar takes effect immediately
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", "wanderwall-sync.timer",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"timer restart failed: {stderr.decode()}")
            return False

        logger.info(f"Sync timer updated: OnCalendar={calendar}")
        return True

    except Exception as e:
        logger.error(f"Failed to update sync timer: {e}")
        return False


_SLEEP_TIMER_DIR = Path.home() / ".config" / "systemd" / "user"
_DISPLAY_HELPER_PATH = Path.home() / ".local" / "bin" / "wanderwall-display"
_TIME_RE = re.compile(r'^\d{2}:\d{2}$')

# vcgencmd display_power is retired on Pi OS Bookworm / Debian Trixie with KMS.
# wlr-randr is the correct tool for Wayland (labwc) setups.
# The helper script discovers the output name at runtime to avoid hardcoding.
_DISPLAY_HELPER = """\
#!/bin/bash
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/$(id -u)
OUT=$(wlr-randr 2>/dev/null | awk '/^[A-Za-z]/{print $1; exit}')
case "$1" in
    off) exec wlr-randr --output "$OUT" --off ;;
    on)  exec wlr-randr --output "$OUT" --on  ;;
esac
"""

_SLEEP_SERVICE = """\
[Unit]
Description=WanderWall Display Sleep
After=picframe.service

[Service]
Type=oneshot
ExecStart=%h/.local/bin/wanderwall-display off
"""

_WAKE_SERVICE = """\
[Unit]
Description=WanderWall Display Wake

[Service]
Type=oneshot
ExecStart=%h/.local/bin/wanderwall-display on
"""

_SLEEP_TIMER_UNIT = """\
[Unit]
Description=WanderWall Display Sleep Timer

[Timer]
OnCalendar=*-*-* {time}:00
Persistent=true

[Install]
WantedBy=timers.target
"""

_WAKE_TIMER_UNIT = """\
[Unit]
Description=WanderWall Display Wake Timer

[Timer]
OnCalendar=*-*-* {time}:00
Persistent=true

[Install]
WantedBy=timers.target
"""


_SLEEP_TIMERS = ("wanderwall-sleep.timer", "wanderwall-wake.timer")


def _sleep_files(sleep_time: str, wake_time: str) -> dict[Path, str]:
    """Return every file the sleep schedule needs, mapped to its expected content."""
    return {
        _DISPLAY_HELPER_PATH: _DISPLAY_HELPER,
        _SLEEP_TIMER_DIR / "wanderwall-sleep.service": _SLEEP_SERVICE,
        _SLEEP_TIMER_DIR / "wanderwall-wake.service": _WAKE_SERVICE,
        _SLEEP_TIMER_DIR / "wanderwall-sleep.timer": _SLEEP_TIMER_UNIT.format(time=sleep_time),
        _SLEEP_TIMER_DIR / "wanderwall-wake.timer": _WAKE_TIMER_UNIT.format(time=wake_time),
    }


def _write_unit(path: Path, content: str) -> None:
    """Atomically write a systemd unit file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.rename(path)


async def update_sleep_timers(enabled: bool, sleep_time: str, wake_time: str) -> bool:
    """
    Create or remove wanderwall-sleep/wake timer pairs.

    If enabled=False, stops and disables both timers.
    sleep_time and wake_time must be "HH:MM" 24-hour format.
    Returns True on success.
    """
    if not enabled:
        for unit in _SLEEP_TIMERS:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "disable", "--now", unit,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        logger.info("Sleep timers disabled")
        return True

    if not _TIME_RE.match(sleep_time) or not _TIME_RE.match(wake_time):
        logger.error(f"Invalid time format: sleep={sleep_time!r} wake={wake_time!r}")
        return False

    try:
        _DISPLAY_HELPER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SLEEP_TIMER_DIR.mkdir(parents=True, exist_ok=True)
        for path, content in _sleep_files(sleep_time, wake_time).items():
            _write_unit(path, content)
        _DISPLAY_HELPER_PATH.chmod(0o755)

        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "daemon-reload",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"daemon-reload failed: {stderr.decode()}")
            return False

        for unit in _SLEEP_TIMERS:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "enable", "--now", unit,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"Failed to enable {unit}: {stderr.decode()}")
                return False

        logger.info(f"Sleep timers enabled: sleep={sleep_time}, wake={wake_time}")
        return True

    except Exception as e:
        logger.error(f"Failed to update sleep timers: {e}")
        return False


async def _timer_state(unit: str) -> tuple[str, str]:
    """Return (is-enabled, is-active) for a user unit, e.g. ("enabled", "active")."""
    results = []
    for verb in ("is-enabled", "is-active"):
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", verb, unit,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        results.append(stdout.decode().strip())
    return results[0], results[1]


async def reconcile_sleep_timers(enabled: bool, sleep_time: str, wake_time: str) -> str:
    """
    Make the sleep/wake timers match the saved schedule (PL-210).

    The timers are only written when the schedule is saved, so a reinstall (v4 -> v5) or a
    lost file left frames with night mode on in config and nothing to run it. Run at API
    startup: rebuilds the units when a file is missing or differs, or a timer isn't enabled
    and running; turns the timers off when the schedule is off but they are still on.
    Leaves a matching setup alone, so a normal start doesn't touch the timers.

    Returns "ok", "repaired", "disabled" or "failed".
    """
    try:
        if not enabled:
            on = []
            for unit in _SLEEP_TIMERS:
                if not (_SLEEP_TIMER_DIR / unit).exists():
                    continue
                if (await _timer_state(unit))[0] == "enabled":
                    on.append(unit)
            if not on:
                return "ok"
            logger.info(
                f"Sleep schedule is off but {', '.join(on)} still enabled; turning off (PL-210)"
            )
            await update_sleep_timers(False, sleep_time, wake_time)
            return "disabled"

        problems = []
        for path, content in _sleep_files(sleep_time, wake_time).items():
            if not path.is_file():
                problems.append(f"{path.name} missing")
            elif path.read_text() != content:
                problems.append(f"{path.name} differs")
        if not problems:
            for unit in _SLEEP_TIMERS:
                state = await _timer_state(unit)
                if state != ("enabled", "active"):
                    problems.append(f"{unit} {state[0]}/{state[1]}")
        if not problems:
            return "ok"

        logger.info(
            f"Sleep timers out of step with config ({'; '.join(problems)}); rebuilding (PL-210)"
        )
        return "repaired" if await update_sleep_timers(True, sleep_time, wake_time) else "failed"

    except Exception as e:
        logger.error(f"Failed to check sleep timers: {e}")
        return "failed"


class ServiceStatus(BaseModel):
    """Status of a systemd service."""
    name: str
    active: bool
    status: str  # "running", "stopped", "failed", "unknown"
    enabled: bool


class SystemdService:
    """
    Controls systemd user services.

    Only whitelisted services can be controlled for security.
    Uses systemctl --user for user-level services.
    """

    @staticmethod
    def _validate_service(name: str) -> bool:
        """Check if service is in the allowed list."""
        if name not in ALLOWED_SERVICES:
            logger.warning(f"Attempted to control non-whitelisted service: {name}")
            return False
        return True

    async def get_status(self, service_name: str) -> Optional[ServiceStatus]:
        """
        Get the status of a systemd service.

        Args:
            service_name: Name of the service (without .service suffix)

        Returns:
            ServiceStatus if service exists, None otherwise
        """
        if not self._validate_service(service_name):
            return None

        try:
            # Preserve existing unit suffix (.timer, .socket, etc.); default to .service
            unit_name = service_name if "." in service_name else f"{service_name}.service"

            # Check if active
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "is-active", unit_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            status_str = stdout.decode().strip()
            active = status_str == "active"

            # Check if enabled
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "is-enabled", unit_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            enabled = stdout.decode().strip() in ("enabled", "static")

            return ServiceStatus(
                name=service_name,
                active=active,
                status="running" if active else status_str,
                enabled=enabled,
            )

        except Exception as e:
            logger.error(f"Failed to get status for {service_name}: {e}")
            return None

    async def restart(self, service_name: str) -> bool:
        """
        Restart a systemd service.

        Args:
            service_name: Name of the service to restart

        Returns:
            True if restart was successful
        """
        if not self._validate_service(service_name):
            return False

        try:
            logger.info(f"Restarting service: {service_name}")

            if service_name == "wanderwall-api":
                # Fire-and-forget: systemd kills this process before systemctl
                # can report success, so awaiting communicate() always yields a
                # non-zero exit code and a false error log.
                await asyncio.create_subprocess_exec(
                    "systemctl", "--user", "restart", f"{service_name}.service",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                return True

            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "restart", f"{service_name}.service",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.info(f"Service {service_name} restarted successfully")
                return True
            else:
                logger.error(
                    f"Failed to restart {service_name}: {stderr.decode()}"
                )
                return False

        except Exception as e:
            logger.error(f"Failed to restart {service_name}: {e}")
            return False

    async def start(self, service_name: str) -> bool:
        """Start a systemd service."""
        if not self._validate_service(service_name):
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "start", f"{service_name}.service",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Failed to start {service_name}: {e}")
            return False

    async def stop(self, service_name: str) -> bool:
        """Stop a systemd service."""
        if not self._validate_service(service_name):
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "stop", f"{service_name}.service",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Failed to stop {service_name}: {e}")
            return False

    async def list_services(self) -> list[ServiceStatus]:
        """
        List all controllable services and their status.

        Returns:
            List of ServiceStatus for all allowed services
        """
        statuses = []
        for name in ALLOWED_SERVICES:
            status = await self.get_status(name)
            if status:
                statuses.append(status)
        return statuses


# Global service instance
systemd_service = SystemdService()
