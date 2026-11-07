"""
WanderWall - Display engine (upstream picframe) status and upgrade (KP-014, KP-015).

The engine lives in ~/venv_picframe, a symlink that scripts/setup/update_engine.sh points at
~/venv_picframe-<version>, built from the pin in scripts/setup/picframe-requirements.txt.
update_engine.sh writes its result to ~/.wanderwall/engine.yaml; this module reads it for the
Updates card, and the card's Upgrade button clears the hold flag and starts the script.
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from src.services.update_service import get_repo_path

logger = logging.getLogger(__name__)

ENGINE_UNIT = "wanderwall-engine-update"
VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
_DIST_INFO_RE = re.compile(r"^picframe-(\d+(?:\.\d+)*)\.dist-info$", re.IGNORECASE)
_PIN_RE = re.compile(r"^picframe==(\d+(?:\.\d+)*)\s*$", re.IGNORECASE)
_HOLD_RE = re.compile(r"""^upgrade:\s*['"]?hold['"]?\s*$""")
# Any "<name>-<version>.dist-info" folder; the name part never holds a "-" (wheel naming).
_ANY_DIST_INFO_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._]*)-([^-]+)\.dist-info$")
# A "Name==1.0" requirements line, as update_engine.sh's normalise_reqs reads it.
_REQ_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")


def engine_link() -> Path:
    """The engine path the display launcher runs (a symlink once update_engine.sh has run)."""
    return Path.home() / "venv_picframe"


def engine_state_path() -> Path:
    """update_engine.sh's result file (also holds the hold flag)."""
    return Path.home() / ".wanderwall" / "engine.yaml"


def requirements_path(repo_path: Path | None = None) -> Path:
    """The engine pin in the repo."""
    return (repo_path or get_repo_path()) / "scripts" / "setup" / "picframe-requirements.txt"


def pinned_version(path: Path | None = None) -> str | None:
    """
    Read the picframe version from the pin file.

    Returns:
        The version string, or None when the file or a valid picframe== line is missing
    """
    path = path or requirements_path()
    try:
        for line in path.read_text().splitlines():
            match = _PIN_RE.match(line.strip())
            if match:
                return match.group(1)
    except OSError:
        return None
    return None


def installed_version(link: Path | None = None) -> str | None:
    """
    Read the installed engine version from its dist-info folder (no subprocess).

    Returns:
        The version string, or None when the engine or its metadata isn't found
    """
    link = link or engine_link()
    for site in sorted(link.glob("lib/python*/site-packages")):
        try:
            for entry in site.iterdir():
                match = _DIST_INFO_RE.match(entry.name)
                if match and entry.is_dir():
                    return match.group(1)
        except OSError:
            continue
    return None


def _normalise_name(name: str) -> str:
    """PEP 503 name: lower case, runs of '-', '_' and '.' become one '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_packages(path: Path | None = None) -> dict[str, str]:
    """
    Read every "Name==version" line of the pin file.

    Returns:
        {normalised name: version}; empty when the file can't be read
    """
    path = path or requirements_path()
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    packages: dict[str, str] = {}
    for line in lines:
        match = _REQ_RE.match(line.strip())
        if match:
            packages[_normalise_name(match.group(1))] = match.group(2)
    return packages


def installed_packages(link: Path | None = None) -> dict[str, str]:
    """
    Read the engine's installed packages from its dist-info folders (no subprocess).

    Returns:
        {normalised name: version}; empty when the engine isn't found
    """
    link = link or engine_link()
    packages: dict[str, str] = {}
    for site in sorted(link.glob("lib/python*/site-packages")):
        try:
            entries = list(site.iterdir())
        except OSError:
            continue
        for entry in entries:
            match = _ANY_DIST_INFO_RE.match(entry.name)
            if match:
                packages[_normalise_name(match.group(1))] = match.group(2)
    return packages


def engine_matches_pin(link: Path | None = None, path: Path | None = None) -> bool:
    """
    True when every pinned package is installed at exactly the pinned version.

    The same test as update_engine.sh's matches_pin (which compares pip freeze with the pin),
    so the Updates card and the updater agree on whether an upgrade is due.
    """
    pinned = pinned_packages(path)
    if not pinned:
        return False
    installed = installed_packages(link)
    return all(installed.get(name) == version for name, version in pinned.items())


def read_engine_state(path: Path | None = None) -> dict[str, Any]:
    """
    Read ~/.wanderwall/engine.yaml.

    Returns:
        Its keys as a dict; empty when the file is missing or unreadable
    """
    path = path or engine_state_path()
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def clear_hold(path: Path | None = None) -> bool:
    """
    Remove the "upgrade: hold" line, keeping the rest of the file (atomic write, mode 600).

    Returns:
        True when a hold was cleared, False when there was none
    """
    path = path or engine_state_path()
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return False
    kept = [line for line in lines if not _HOLD_RE.match(line)]
    if len(kept) == len(lines):
        return False
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
    logger.info("Display engine upgrade hold cleared (%s)", path)
    return True


async def _run(*args: str, timeout: float = 15) -> tuple[int, str]:
    """Run a command with explicit arguments; returns (exit code, combined output)."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timed out"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def upgrade_running() -> bool:
    """True while the transient wanderwall-engine-update unit is active."""
    try:
        code, _ = await _run("systemctl", "--user", "is-active", "--quiet", ENGINE_UNIT)
    except OSError:
        return False
    return code == 0


async def get_engine_status() -> dict[str, Any]:
    """
    Engine facts for the Updates card and GET /api/updates/settings.

    Returns:
        installed_version, pinned_version, matches_pin, on_hold, running, last_result,
        last_run, message, previous_version
    """
    state = read_engine_state()
    installed = installed_version()
    pinned = pinned_version()
    return {
        "installed_version": installed,
        "pinned_version": pinned,
        "matches_pin": bool(installed and pinned and installed == pinned and engine_matches_pin()),
        "on_hold": str(state.get("upgrade", "")).strip().lower() == "hold",
        "running": await upgrade_running(),
        "last_result": state.get("last_result") or None,
        "last_run": state.get("last_run") or None,
        "message": state.get("message") or None,
        "previous_version": state.get("previous_version") or None,
    }


async def start_engine_upgrade(source: str) -> dict[str, Any]:
    """
    Clear the hold flag and start update_engine.sh in the background (the Upgrade button).

    Args:
        source: Who asked, for the log ("dashboard")

    Returns:
        {"ok": True, "message": ...} or {"ok": False, "error": ...}
    """
    if await upgrade_running():
        return {"ok": False, "error": "An engine update is already running."}
    script = get_repo_path() / "scripts" / "setup" / "update_engine.sh"
    if not script.is_file():
        return {"ok": False, "error": f"Engine updater not found: {script}"}
    try:
        cleared = clear_hold()
    except OSError as exc:
        logger.error("Failed to clear the engine upgrade hold: %s", exc)
        return {"ok": False, "error": f"Couldn't clear the hold: {exc}"}
    try:
        code, out = await _run(
            "systemd-run",
            "--user",
            f"--unit={ENGINE_UNIT}",
            "--collect",
            "--quiet",
            "--description=WanderWall display engine update",
            "/bin/bash",
            str(script),
        )
    except OSError as exc:
        code, out = 1, str(exc)
    if code != 0:
        logger.error("Failed to start the display engine update via %s: %s", source, out)
        return {"ok": False, "error": f"Couldn't start the engine update: {out or code}"}
    logger.info("Display engine update started via %s (hold cleared: %s)", source, cleared)
    return {
        "ok": True,
        "message": "Engine update started. It can take several minutes; the display restarts once.",
    }
