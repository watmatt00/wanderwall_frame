"""
WanderWall - Update Service.

Checks for available updates from GitHub by comparing local git commit vs remote.
Provides a background scheduler for automatic periodic checks.
"""

import asyncio
import calendar
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.config.settings import get_settings, reload_settings
from src.config.manager import config_manager

logger = logging.getLogger(__name__)

# Path to the git repo on the Pi
REPO_PATH = Path.home() / "wanderwall_frame"

# Base version prefix
BASE_VERSION = "5.0"


async def _get_commit_count(repo_path: Path, ref: str = "HEAD") -> Optional[int]:
    """Get the number of commits reachable from ref."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "rev-list", "--count", ref,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return int(stdout.decode().strip())
    except Exception:
        pass
    return None


def _format_version(count: Optional[int]) -> str:
    """Format a commit count as a user-friendly version string."""
    if count is None:
        return f"{BASE_VERSION}.?"
    return f"{BASE_VERSION}.{count}"

# Background scheduler task reference
_scheduler_task: Optional[asyncio.Task] = None


def get_repo_path() -> Path:
    """Get the path to the git repository."""
    return REPO_PATH


async def get_current_branch(repo_path: Optional[Path] = None) -> str:
    """
    Get the active git branch name.

    Returns:
        Branch name string, 'detached' if in detached HEAD state, or 'unknown' on error.
    """
    if repo_path is None:
        repo_path = get_repo_path()
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "branch", "--show-current",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            branch = stdout.decode().strip()
            return branch if branch else "detached"
    except Exception as e:
        logger.warning(f"Failed to get current branch: {e}")
    return "unknown"


async def check_for_updates(repo_path: Optional[Path] = None) -> dict:
    """
    Check for available updates by comparing local HEAD vs remote.

    Runs git fetch then compares HEAD vs @{u}.

    Args:
        repo_path: Path to the git repo. Defaults to ~/wanderwall_frame.

    Returns:
        dict with keys: up_to_date, local_commit, remote_commit, checked_at, error
    """
    if repo_path is None:
        repo_path = get_repo_path()

    checked_at = datetime.now().isoformat()
    branch = await get_current_branch(repo_path)

    try:
        # Run git fetch
        fetch_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "fetch", "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, fetch_stderr = await asyncio.wait_for(fetch_proc.communicate(), timeout=30)

        if fetch_proc.returncode != 0:
            error = fetch_stderr.decode().strip() or "git fetch failed"
            logger.warning(f"git fetch failed: {error}")
            local_count = await _get_commit_count(repo_path, "HEAD")
            return {
                "up_to_date": None,
                "local_commit": None,
                "remote_commit": None,
                "local_version": _format_version(local_count),
                "remote_version": None,
                "checked_at": checked_at,
                "branch": branch,
                "error": f"git fetch failed: {error}",
            }

        # Get local HEAD short hash
        local_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "rev-parse", "--short", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        local_stdout, _ = await local_proc.communicate()
        local_commit = local_stdout.decode().strip()

        # Get remote tracking branch short hash
        remote_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "rev-parse", "--short", "@{u}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        remote_stdout, remote_stderr = await remote_proc.communicate()

        if remote_proc.returncode != 0:
            error = remote_stderr.decode().strip() or "No upstream configured"
            logger.warning(f"Could not get remote commit: {error}")
            local_count = await _get_commit_count(repo_path, "HEAD")
            return {
                "up_to_date": None,
                "local_commit": local_commit,
                "remote_commit": None,
                "local_version": _format_version(local_count),
                "remote_version": None,
                "checked_at": checked_at,
                "branch": branch,
                "error": f"Could not get remote: {error}",
            }

        remote_commit = remote_stdout.decode().strip()
        up_to_date = local_commit == remote_commit

        # Get friendly version strings
        local_count = await _get_commit_count(repo_path, "HEAD")
        remote_count = await _get_commit_count(repo_path, "@{u}")

        return {
            "up_to_date": up_to_date,
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "local_version": _format_version(local_count),
            "remote_version": _format_version(remote_count),
            "checked_at": checked_at,
            "branch": branch,
            "error": None,
        }

    except asyncio.TimeoutError:
        logger.error("git fetch timed out")
        return {
            "up_to_date": None,
            "local_commit": None,
            "remote_commit": None,
            "checked_at": checked_at,
            "branch": branch,
            "error": "git fetch timed out",
        }
    except Exception as e:
        logger.error(f"Update check failed: {e}")
        return {
            "up_to_date": None,
            "local_commit": None,
            "remote_commit": None,
            "checked_at": checked_at,
            "branch": branch,
            "error": str(e),
        }


def save_check_result(result: dict) -> None:
    """
    Save the update check result to config.

    Args:
        result: Result dict from check_for_updates()
    """
    config_manager.set("updates.last_checked", result["checked_at"])

    if result.get("error"):
        config_manager.set("updates.last_result", "error")
        config_manager.set("updates.available_commit", None)
    elif result.get("up_to_date") is True:
        config_manager.set("updates.last_result", "up_to_date")
        config_manager.set("updates.available_commit", None)
    elif result.get("up_to_date") is False:
        config_manager.set("updates.last_result", "update_available")
        config_manager.set("updates.available_commit", result.get("remote_commit"))

    reload_settings()


async def apply_update(repo_path: Optional[Path] = None) -> dict:
    """
    Apply available updates by running git pull.

    Args:
        repo_path: Path to the git repo. Defaults to ~/wanderwall_frame.

    Returns:
        dict with keys: success, output, error
    """
    if repo_path is None:
        repo_path = get_repo_path()

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode == 0:
            output = stdout.decode().strip()
            logger.info(f"git pull succeeded: {output}")
            # Apply service file changes, new packages, enable new services
            script = repo_path / "scripts" / "update_app.sh"
            if script.exists():
                try:
                    update_proc = await asyncio.create_subprocess_exec(
                        "bash", str(script),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=str(repo_path),
                    )
                    update_out, _ = await asyncio.wait_for(
                        update_proc.communicate(), timeout=120
                    )
                    logger.info(f"update_app.sh:\n{update_out.decode().strip()}")
                except asyncio.TimeoutError:
                    logger.warning("update_app.sh timed out — continuing")
                except Exception as exc:
                    logger.warning(f"update_app.sh failed: {exc}")
            return {"success": True, "output": output, "error": None}
        else:
            error = stderr.decode().strip() or "git pull failed"
            logger.error(f"git pull failed: {error}")
            return {"success": False, "output": None, "error": error}

    except asyncio.TimeoutError:
        logger.error("git pull timed out")
        return {"success": False, "output": None, "error": "git pull timed out"}
    except Exception as e:
        logger.error(f"apply_update failed: {e}")
        return {"success": False, "output": None, "error": str(e)}


def calculate_next_check(frequency: str, day: int, check_time: str) -> datetime:
    """
    Calculate the next scheduled check datetime.

    Args:
        frequency: "daily", "weekly", or "monthly"
        day: 1-28 for monthly; 0-6 (Mon=0) for weekly; ignored for daily
        check_time: "HH:MM" string

    Returns:
        Next datetime to run the check
    """
    now = datetime.now()

    # Parse check_time
    try:
        hour, minute = [int(x) for x in check_time.split(":")]
    except (ValueError, AttributeError):
        hour, minute = 2, 0

    if frequency == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if frequency == "monthly":
        # Find next occurrence of day-of-month at check_time
        try:
            candidate = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            candidate = None

        if candidate is None or candidate <= now:
            # Advance to next month
            if now.month == 12:
                next_month_dt = now.replace(year=now.year + 1, month=1)
            else:
                next_month_dt = now.replace(month=now.month + 1)

            try:
                candidate = next_month_dt.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                # Day doesn't exist in that month — use last day
                last_day = calendar.monthrange(next_month_dt.year, next_month_dt.month)[1]
                candidate = next_month_dt.replace(day=last_day, hour=hour, minute=minute, second=0, microsecond=0)

        return candidate

    else:  # weekly
        # day is 0-6 (Mon=0)
        days_ahead = day - now.weekday()
        if days_ahead < 0:
            days_ahead += 7

        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)

        if candidate <= now:
            candidate += timedelta(weeks=1)

        return candidate


async def start_update_scheduler() -> None:
    """
    Background task that runs scheduled update checks.

    Reads schedule config on each iteration, calculates next run time,
    sleeps until then, then runs the check.
    """
    logger.info("Update scheduler started")

    while True:
        try:
            settings = get_settings()
            updates = settings.updates

            if not updates.auto_check:
                # Re-check schedule in 1 hour
                await asyncio.sleep(3600)
                continue

            next_check = calculate_next_check(
                frequency=updates.frequency,
                day=updates.day,
                check_time=updates.check_time,
            )

            wait_seconds = (next_check - datetime.now()).total_seconds()
            if wait_seconds > 0:
                logger.info(f"Next update check scheduled for {next_check.isoformat()}")
                await asyncio.sleep(wait_seconds)

            # Run the check
            logger.info("Running scheduled update check")
            result = await check_for_updates()
            save_check_result(result)

            if result.get("error"):
                logger.warning(f"Scheduled update check failed: {result['error']}")
            elif result.get("up_to_date") is False:
                logger.info(f"Update available on branch '{result.get('branch', 'unknown')}': remote commit {result.get('remote_commit')}")
                # Auto-apply if configured
                if updates.auto_apply and updates_locked():
                    logger.info("Auto-apply skipped: demo mode is on (PL-150)")
                elif updates.auto_apply:
                    logger.info("Auto-apply enabled — running git pull")
                    apply_result = await apply_update()
                    if apply_result["success"]:
                        logger.info("Auto-apply succeeded")
                    else:
                        logger.error(f"Auto-apply failed: {apply_result['error']}")
            else:
                logger.info("System is up to date")

        except asyncio.CancelledError:
            logger.info("Update scheduler cancelled")
            return
        except Exception as e:
            logger.error(f"Update scheduler error: {e}")
            await asyncio.sleep(3600)  # Wait 1 hour before retry


async def get_local_commit(repo_path: Optional[Path] = None) -> Optional[str]:
    """
    Get the current local HEAD short hash without fetching.

    Returns:
        Short commit hash string or None on error
    """
    if repo_path is None:
        repo_path = get_repo_path()

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "rev-parse", "--short", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except Exception as e:
        logger.warning(f"Failed to get local commit: {e}")

    return None


async def get_local_version(repo_path: Optional[Path] = None) -> str:
    """
    Get the current installed version as a friendly string (e.g. '5.0.47').

    Returns:
        Version string like '5.0.47', or '5.0.?' on error
    """
    if repo_path is None:
        repo_path = get_repo_path()
    count = await _get_commit_count(repo_path, "HEAD")
    return _format_version(count)


# =============================================================================
# Request handlers shared by the LAN dashboard and the /api/v1 updates routes
# =============================================================================


# Shown in the app when a reviewer tries to update the demo frame (PL-150)
DEMO_LOCKED_MESSAGE = (
    "Software updates are turned off on this demo frame. The frame owner applies updates."
)


def updates_locked() -> bool:
    """
    True while demo mode is on (PL-150): the reviewer pairs as admin, so the app
    can't apply updates or change the schedule, and scheduled auto-apply is skipped.
    The LAN dashboard can still update the frame.
    """
    demo = get_settings().demo
    return demo.allowed and demo.enabled


class SaveUpdateScheduleRequest(BaseModel):
    """Request to save update schedule settings."""
    auto_check: bool
    auto_apply: bool
    frequency: str
    day: int
    check_time: str


async def get_update_status() -> dict:
    """
    Get current update configuration, last check result, and installed version.

    Returns:
        Dict with schedule settings, last check info, local version/commit and branch
    """
    settings = get_settings()
    local_commit = await get_local_commit()
    local_version = await get_local_version()
    branch = await get_current_branch()
    return {
        "auto_check": settings.updates.auto_check,
        "auto_apply": settings.updates.auto_apply,
        "frequency": settings.updates.frequency,
        "day": settings.updates.day,
        "check_time": settings.updates.check_time,
        "last_checked": settings.updates.last_checked,
        "last_result": settings.updates.last_result,
        "local_version": local_version,
        "local_commit": local_commit,
        "branch": branch,
    }


async def run_update_check() -> dict:
    """
    Run an immediate update check and persist the result.

    Returns:
        Dict describing whether the frame is up to date
    """
    result = await check_for_updates()
    save_check_result(result)

    return {
        "ok": result.get("error") is None,
        "up_to_date": result.get("up_to_date"),
        "local_commit": result.get("local_commit"),
        "remote_commit": result.get("remote_commit"),
        "local_version": result.get("local_version"),
        "remote_version": result.get("remote_version"),
        "checked_at": result.get("checked_at"),
        "branch": result.get("branch"),
        "error": result.get("error"),
    }


def save_update_schedule(request: SaveUpdateScheduleRequest) -> dict:
    """
    Validate and save update schedule configuration.

    Args:
        request: Schedule settings to save

    Returns:
        {"ok": True} on success, or {"ok": False, "error": ...}
    """
    # Validate frequency
    if request.frequency not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": "frequency must be 'daily', 'weekly', or 'monthly'"}

    # Validate day (only relevant for non-daily)
    if request.frequency == "monthly" and not (1 <= request.day <= 28):
        return {"ok": False, "error": "day must be 1-28 for monthly frequency"}
    if request.frequency == "weekly" and not (0 <= request.day <= 6):
        return {"ok": False, "error": "day must be 0-6 for weekly frequency"}

    # Validate check_time
    if not re.match(r"^\d{2}:\d{2}$", request.check_time):
        return {"ok": False, "error": "check_time must be HH:MM format"}
    hour, minute = int(request.check_time[:2]), int(request.check_time[3:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return {"ok": False, "error": "check_time has invalid hour or minute"}

    try:
        config_manager.set("updates.auto_check", request.auto_check)
        config_manager.set("updates.auto_apply", request.auto_apply)
        config_manager.set("updates.frequency", request.frequency)
        config_manager.set("updates.day", request.day)
        config_manager.set("updates.check_time", request.check_time)
        reload_settings()

        logger.info(
            f"Update schedule saved: auto_check={request.auto_check}, auto_apply={request.auto_apply}, "
            f"frequency={request.frequency}, day={request.day}, time={request.check_time}"
        )
        return {"ok": True}
    except Exception as e:
        logger.error(f"Failed to save update schedule: {e}")
        return {"ok": False, "error": str(e)}


async def apply_update_and_restart(source: str) -> dict:
    """
    Apply available updates (git pull) and restart the API service on success.

    Args:
        source: Who triggered the update, for the log ("dashboard" or "app")

    Returns:
        Dict with ok flag, git output and error
    """
    result = await apply_update()

    if result["success"]:
        logger.info(f"Update applied via {source} — restarting API")
        async def _restart_after_response():
            await asyncio.sleep(1)
            # Fire and forget — systemd kills this process before systemctl
            # can report success, so we never await the result (false errors otherwise).
            await asyncio.create_subprocess_exec(
                "systemctl", "--user", "restart", "wanderwall-api.service",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        asyncio.create_task(_restart_after_response())
    else:
        logger.error(f"Update apply failed via {source}: {result['error']}")

    return {
        "ok": result["success"],
        "output": result.get("output"),
        "error": result.get("error"),
    }
