"""
Tests for scripts/setup/update_engine.sh (KP-011, KP-012, KP-015) and the display launcher
scripts (PL-187): scripts/display/screen_lib.sh, install_launcher.sh, start_picframe.sh.

The scripts run for real against a fake home. Stubs stand in for the system python3 (it
builds fake venvs), each venv's python (version, pip freeze, pip install, import test),
systemctl, and the engine's HTTP check (a file:// URL to a marker file in the venv the
symlink points at, so "healthy" follows the swap).
"""

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UPDATE_ENGINE = REPO / "scripts" / "setup" / "update_engine.sh"
SCREEN_LIB = REPO / "scripts" / "display" / "screen_lib.sh"
INSTALL_LAUNCHER = REPO / "scripts" / "display" / "install_launcher.sh"
START_PICFRAME = REPO / "scripts" / "display" / "start_picframe.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("flock") is None or shutil.which("curl") is None,
    reason="needs flock and curl",
)

OLD = "2024.11.1"
NEW = "2026.4.22"

PIN = textwrap.dedent(f"""\
    # test pin
    picframe=={NEW}
    numpy==2.4.4
    pi_heif==1.3.0
    """)

# The python inside each fake venv. Its venv is the folder above its bin/, found from the path
# it was called by ($0), so calls through the ~/venv_picframe symlink act on the symlink's target.
VENV_PYTHON = textwrap.dedent("""\
    #!/bin/bash
    venv="$(dirname "$(dirname "$0")")"
    case "$*" in
        *"m.version"*) cat "$venv/fake_version" ;;
        *"import picframe, pi3d"*) [[ ! -f "$venv/fake_import_fails" ]] ;;
        "-m pip freeze") cat "$venv/fake_freeze" ;;
        "-m pip install"*)
            [[ -z "${FAKE_PIP_FAIL:-}" ]] || { echo "pip: simulated failure" >&2; exit 1; }
            req="${@: -1}"
            grep -E '^[A-Za-z0-9].*==' "$req" > "$venv/fake_freeze"
            sed -nE 's/^picframe==(.*)/\\1/p' "$req" > "$venv/fake_version"
            [[ -n "${FAKE_NEW_UNHEALTHY:-}" ]] || touch "$venv/healthy"
            ;;
        *) echo "fake venv python: unexpected args: $*" >&2; exit 2 ;;
    esac
    """)

# The "system python3": only "-m venv <dir>" is used.
SYSTEM_PYTHON = textwrap.dedent("""\
    #!/bin/bash
    [[ "$1 $2" == "-m venv" ]] || { echo "fake python3: unexpected args: $*" >&2; exit 2; }
    dir="$3"
    mkdir -p "$dir/bin" "$dir/lib/python3.11/site-packages"
    cp "$FAKE_VENV_PYTHON" "$dir/bin/python"
    chmod +x "$dir/bin/python"
    printf '#!%s/bin/python\\n# engine entry point\\n' "$dir" > "$dir/bin/picframe"
    chmod +x "$dir/bin/picframe"
    printf 'VIRTUAL_ENV="%s"\\nexport VIRTUAL_ENV\\n' "$dir" > "$dir/bin/activate"
    printf 'home = /usr/bin\\ncommand = /usr/bin/python3 -m venv %s\\n' "$dir" > "$dir/pyvenv.cfg"
    """)

SYSTEMCTL = textwrap.dedent("""\
    #!/bin/bash
    echo "$*" >> "$FAKE_SYSTEMCTL_LOG"
    exit 0
    """)


def _write_exec(path: Path, content: str) -> Path:
    """Write an executable script."""
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Frame:
    """A fake frame home plus the environment that points update_engine.sh at it."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        self.venv_python = _write_exec(self.tools / "venv_python", VENV_PYTHON)
        self.system_python = _write_exec(self.tools / "python3", SYSTEM_PYTHON)
        self.systemctl = _write_exec(self.tools / "systemctl", SYSTEMCTL)
        self.systemctl_log = tmp_path / "systemctl.log"
        self.requirements = tmp_path / "picframe-requirements.txt"
        self.requirements.write_text(PIN)
        self.drm = tmp_path / "drm"
        (self.drm / "card1-HDMI-A-1").mkdir(parents=True)
        self.set_screen("connected")
        self.link = self.home / "venv_picframe"
        self.state = self.home / ".wanderwall" / "engine.yaml"
        self.log = self.home / ".wanderwall" / "logs" / "wanderwall.log"

    def set_screen(self, status: str) -> None:
        """Set the fake HDMI port's status (connected / disconnected)."""
        (self.drm / "card1-HDMI-A-1" / "status").write_text(status + "\n")

    def make_venv(self, path: Path, version: str, freeze: str, healthy: bool = True) -> Path:
        """Create a fake engine venv as the real installers left it."""
        subprocess.run(
            [str(self.system_python), "-m", "venv", str(path)],
            check=True,
            env={**os.environ, "FAKE_VENV_PYTHON": str(self.venv_python)},
        )
        (path / "fake_version").write_text(version + "\n")
        (path / "fake_freeze").write_text(freeze)
        if healthy:
            (path / "healthy").touch()
        return path

    def old_engine_folder(self) -> Path:
        """A v4/v5 frame today: ~/venv_picframe is a real folder with the old engine."""
        return self.make_venv(self.link, OLD, f"picframe=={OLD}\nnumpy==2.1.2\npi_heif==0.20.0\n")

    def env(self, **extra: str) -> dict:
        """Environment for running the script against this fake frame."""
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "WW_HOME": str(self.home),
            "WW_REQUIREMENTS": str(self.requirements),
            "WW_PYTHON": str(self.system_python),
            "WW_SYSTEMCTL": str(self.systemctl),
            "WW_HEALTH_URL": f"file://{self.link}/healthy",
            "WW_HEALTH_TIMEOUT": "2",
            "WW_HEALTH_INTERVAL": "1",
            "WW_MIN_FREE_MB": "1",
            "WW_DRM_DIR": str(self.drm),
            "WW_WLR_RANDR": str(self.tools / "no-such-wlr-randr"),
            "FAKE_VENV_PYTHON": str(self.venv_python),
            "FAKE_SYSTEMCTL_LOG": str(self.systemctl_log),
        }
        env.update(extra)
        return env

    def run(self, **extra: str) -> subprocess.CompletedProcess:
        """Run update_engine.sh."""
        return subprocess.run(
            ["bash", str(UPDATE_ENGINE)],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def state_value(self, key: str) -> str:
        """Read one value from engine.yaml (the script writes key: 'value')."""
        for line in self.state.read_text().splitlines():
            if line.startswith(key + ":"):
                return line.split(":", 1)[1].strip().strip("'")
        return ""

    def systemctl_calls(self) -> list[str]:
        """The systemctl calls the script made."""
        if not self.systemctl_log.exists():
            return []
        return self.systemctl_log.read_text().splitlines()


@pytest.fixture
def frame(tmp_path: Path) -> Frame:
    """A fake frame home."""
    return Frame(tmp_path)


# ── update_engine.sh ─────────────────────────────────────────────────────────


def test_nothing_to_do_when_engine_matches_pin(frame: Frame) -> None:
    """tkframe today: a real folder already at the pin is left alone (no conversion)."""
    frame.make_venv(frame.link, NEW, PIN)
    result = frame.run()
    assert result.returncode == 0, result.stderr
    assert frame.link.is_dir() and not frame.link.is_symlink()
    assert frame.state_value("last_result") == "up_to_date"
    assert frame.systemctl_calls() == []
    assert "matches the pin" in frame.log.read_text()


def test_pin_matching_ignores_name_case_and_separators(frame: Frame) -> None:
    """pip freeze prints PyYAML / pi_heif; the pin may spell them pyyaml / pi-heif."""
    frame.requirements.write_text(f"picframe=={NEW}\nPyYAML==6.0.3\npi-heif==1.3.0\n")
    frame.make_venv(
        frame.link, NEW, f"picframe=={NEW}\npyyaml==6.0.3\npi_heif==1.3.0\nextra==1.0\n"
    )
    result = frame.run()
    assert result.returncode == 0, result.stderr
    assert frame.state_value("last_result") == "up_to_date"


def test_hold_flag_skips_upgrade(frame: Frame) -> None:
    """A frame reinstalled from v4 keeps its engine until Upgrade is pressed."""
    frame.old_engine_folder()
    frame.state.parent.mkdir(parents=True, exist_ok=True)
    frame.state.write_text("# Written by install.sh --from-v4\nupgrade: hold\n")
    result = frame.run()
    assert result.returncode == 0, result.stderr
    assert frame.link.is_dir() and not frame.link.is_symlink()
    assert not (frame.home / f"venv_picframe-{NEW}").exists()
    assert frame.state_value("last_result") == "on_hold"
    assert "upgrade: hold" in frame.state.read_text()  # the hold stays
    assert frame.systemctl_calls() == []


def test_no_screen_postpones(frame: Frame) -> None:
    """No screen: the health check can't pass, so don't start (PL-187)."""
    frame.old_engine_folder()
    frame.set_screen("disconnected")
    result = frame.run()
    assert result.returncode == 0, result.stderr
    assert frame.state_value("last_result") == "postponed"
    assert frame.link.is_dir() and not frame.link.is_symlink()
    assert frame.systemctl_calls() == []


def test_display_asleep_postpones(frame: Frame) -> None:
    """Screen connected but every output off (display sleep): postpone too."""
    frame.old_engine_folder()
    randr = _write_exec(
        frame.tools / "wlr-randr", "#!/bin/bash\necho 'HDMI-A-1 \"x\"'\necho '  Enabled: no'\n"
    )
    result = frame.run(WW_WLR_RANDR=str(randr))
    assert result.returncode == 0, result.stderr
    assert frame.state_value("last_result") == "postponed"


def test_first_conversion_and_upgrade(frame: Frame) -> None:
    """Real folder becomes venv_picframe-<old> with fixed paths; the link points at the new one."""
    frame.old_engine_folder()
    result = frame.run()
    assert result.returncode == 0, result.stdout + result.stderr

    old_dir = frame.home / f"venv_picframe-{OLD}"
    new_dir = frame.home / f"venv_picframe-{NEW}"
    assert frame.link.is_symlink()
    assert os.readlink(frame.link) == str(new_dir)
    assert old_dir.is_dir() and new_dir.is_dir()

    # The old engine's own paths now name its new folder, so it runs there (rollback works)
    assert (old_dir / "bin" / "picframe").read_text().splitlines()[0] == f"#!{old_dir}/bin/python"
    assert f'VIRTUAL_ENV="{old_dir}"' in (old_dir / "bin" / "activate").read_text()
    assert str(old_dir) in (old_dir / "pyvenv.cfg").read_text()
    assert (new_dir / "bin" / "picframe").read_text().splitlines()[0] == f"#!{new_dir}/bin/python"

    assert frame.state_value("last_result") == "ok"
    assert frame.state_value("installed_version") == NEW
    assert frame.state_value("previous_version") == OLD
    calls = frame.systemctl_calls()
    assert "stop picframe.service" in calls
    assert "restart picframe.service" in calls
    assert "upgraded successfully" in frame.log.read_text()
    assert (frame.state.stat().st_mode & 0o777) == 0o600


def test_second_run_after_upgrade_does_nothing(frame: Frame) -> None:
    """Once at the pin, later runs (every app update) change nothing."""
    frame.old_engine_folder()
    assert frame.run().returncode == 0
    frame.systemctl_log.unlink()
    result = frame.run()
    assert result.returncode == 0, result.stderr
    assert frame.state_value("last_result") == "up_to_date"
    assert frame.state_value("previous_version") == OLD
    assert frame.systemctl_calls() == []


def test_unhealthy_new_engine_rolls_back(frame: Frame) -> None:
    """New engine doesn't answer: the link goes back to the old engine, the new one is removed."""
    frame.old_engine_folder()
    result = frame.run(FAKE_NEW_UNHEALTHY="1")
    assert result.returncode == 1
    old_dir = frame.home / f"venv_picframe-{OLD}"
    assert frame.link.is_symlink() and os.readlink(frame.link) == str(old_dir)
    assert not (frame.home / f"venv_picframe-{NEW}").exists()
    assert frame.state_value("last_result") == "rolled_back"
    assert "it answers again" in frame.log.read_text()
    assert frame.systemctl_calls().count("restart picframe.service") == 2


def test_build_failure_keeps_old_engine_untouched(frame: Frame) -> None:
    """pip fails: nothing on the frame changes, not even the folder conversion."""
    frame.old_engine_folder()
    result = frame.run(FAKE_PIP_FAIL="1")
    assert result.returncode == 1
    assert frame.link.is_dir() and not frame.link.is_symlink()
    assert not (frame.home / f"venv_picframe-{NEW}").exists()
    assert frame.state_value("last_result") == "failed"
    assert frame.systemctl_calls() == []
    assert (frame.home / ".wanderwall" / "logs" / "engine-build.log").read_text().strip()


def test_keeps_one_previous_engine(frame: Frame) -> None:
    """After a later upgrade only the current and the previous engine remain."""
    older = frame.make_venv(
        frame.home / "venv_picframe-2023.1.1", "2023.1.1", "picframe==2023.1.1\n"
    )
    previous = frame.make_venv(frame.home / f"venv_picframe-{OLD}", OLD, f"picframe=={OLD}\n")
    frame.link.symlink_to(previous)
    result = frame.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert not older.exists()
    assert previous.is_dir()
    assert os.readlink(frame.link) == str(frame.home / f"venv_picframe-{NEW}")
    assert "stop picframe.service" not in frame.systemctl_calls()  # no conversion needed


def test_dependency_only_pin_change_builds_a_new_folder(frame: Frame) -> None:
    """Same picframe, newer numpy: build venv_picframe-<version>-r2 beside the running one."""
    current = frame.make_venv(
        frame.home / f"venv_picframe-{NEW}", NEW, f"picframe=={NEW}\nnumpy==2.4.0\npi_heif==1.3.0\n"
    )
    frame.link.symlink_to(current)
    result = frame.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert os.readlink(frame.link) == str(frame.home / f"venv_picframe-{NEW}-r2")
    assert current.is_dir()   # kept as the previous engine
    assert frame.state_value("last_result") == "ok"


def test_invalid_pin_is_an_error(frame: Frame) -> None:
    """A pin file without a valid picframe== line stops before touching anything."""
    frame.old_engine_folder()
    frame.requirements.write_text("picframe==latest\n")
    result = frame.run()
    assert result.returncode == 1
    assert "no valid picframe==<version>" in result.stderr
    assert frame.link.is_dir() and not frame.link.is_symlink()


def test_missing_engine_is_an_error(frame: Frame) -> None:
    """No ~/venv_picframe at all."""
    result = frame.run()
    assert result.returncode == 1
    assert frame.state_value("last_result") == "failed"


def test_second_instance_waits_then_exits(frame: Frame) -> None:
    """While one run holds the lock, another waits 10 s, then exits 0 without doing anything."""
    frame.old_engine_folder()
    lock = frame.home / ".wanderwall" / "engine.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    try:
        subprocess.run(["sleep", "0.5"], check=True)
        result = frame.run()
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode == 0
    assert "already running" in result.stdout
    assert frame.link.is_dir() and not frame.link.is_symlink()


# ── screen_lib.sh ────────────────────────────────────────────────────────────


def _screen_state(frame: Frame, randr: str) -> str:
    out = subprocess.run(
        ["bash", "-c", 'source "$1" && screen_state', "x", str(SCREEN_LIB)],
        env={**os.environ, "WW_DRM_DIR": str(frame.drm), "WW_WLR_RANDR": randr},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_screen_state(frame: Frame) -> None:
    """none / asleep / ready from the HDMI status and wlr-randr."""
    on = _write_exec(
        frame.tools / "randr_on", "#!/bin/bash\necho 'HDMI-A-1'\necho '  Enabled: yes'\n"
    )
    off = _write_exec(
        frame.tools / "randr_off", "#!/bin/bash\necho 'HDMI-A-1'\necho '  Enabled: no'\n"
    )
    broken = _write_exec(frame.tools / "randr_broken", "#!/bin/bash\nexit 1\n")
    missing = str(frame.tools / "missing")

    frame.set_screen("disconnected")
    assert _screen_state(frame, str(on)) == "none"
    frame.set_screen("connected")
    assert _screen_state(frame, str(on)) == "ready"
    assert _screen_state(frame, str(off)) == "asleep"
    assert _screen_state(frame, str(broken)) == "ready"  # compositor not up: HDMI status only
    assert _screen_state(frame, missing) == "ready"


# ── install_launcher.sh ──────────────────────────────────────────────────────


def _install_launcher(frame: Frame) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_LAUNCHER)],
        env={**os.environ, "HOME": str(frame.home)},
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "activate", ["source {home}/venv_picframe/bin/activate", "source ~/venv_picframe/bin/activate"]
)
def test_launcher_replaces_installer_stub(frame: Frame, activate: str) -> None:
    """tkframe's (absolute path) and kframe's (~) stubs are both replaced, original kept once."""
    start = frame.home / "start_picframe.sh"
    original = (
        "#!/bin/bash\n"
        + activate.format(home=frame.home)
        + "\nexport SDL_VIDEODRIVER=x11\npicframe &\n"
    )
    start.write_text(original)
    autostart = frame.home / ".config" / "labwc" / "autostart"
    autostart.parent.mkdir(parents=True)
    autostart.write_text(f"{start}\n")

    result = _install_launcher(frame)
    assert result.returncode == 0, result.stderr
    content = start.read_text()
    assert str(START_PICFRAME) in content and "Managed by wanderwall_frame" in content
    assert os.access(start, os.X_OK)
    assert (frame.home / "start_picframe.sh.pre-launcher").read_text() == original
    assert "WARNING" not in result.stderr

    again = _install_launcher(frame)
    assert again.returncode == 0
    assert "no changes" in again.stdout


def test_launcher_leaves_unknown_script_alone(frame: Frame) -> None:
    """A hand-edited start script isn't overwritten."""
    start = frame.home / "start_picframe.sh"
    custom = "#!/bin/bash\nsource ~/venv_picframe/bin/activate\nsleep 30\npicframe &\n"
    start.write_text(custom)
    result = _install_launcher(frame)
    assert result.returncode == 0
    assert start.read_text() == custom
    assert "isn't the stub the installer wrote" in result.stderr


# ── start_picframe.sh ────────────────────────────────────────────────────────


def test_launcher_waits_for_screen_then_runs_engine(frame: Frame) -> None:
    """With no screen the engine isn't started; once the screen connects it is."""
    venv = frame.home / "venv_picframe"
    (venv / "bin").mkdir(parents=True)
    ran = frame.root / "engine_ran"
    _write_exec(venv / "bin" / "picframe", f"#!/bin/bash\ntouch '{ran}'\n")
    _write_exec(frame.tools / "labwc", f"#!/bin/bash\necho \"$*\" > '{frame.root}/labwc_args'\n")
    frame.set_screen("disconnected")

    proc = subprocess.Popen(
        ["bash", str(START_PICFRAME)],
        env={
            **os.environ,
            "HOME": str(frame.home),
            "WW_DRM_DIR": str(frame.drm),
            "WW_WLR_RANDR": str(frame.tools / "missing"),
            "WW_SCREEN_POLL_SECONDS": "1",
            "WW_QUICK_EXIT_SLEEP": "0",
            "PATH": f"{frame.tools}:{os.environ['PATH']}",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        subprocess.run(["sleep", "2.5"], check=True)
        assert not ran.exists()  # still waiting
        frame.set_screen("connected")
        out, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert ran.exists()
    assert "waiting for a screen (state: none" in out
    assert "screen ready after" in out
    assert "display engine exited (code 0" in out
    assert (
        frame.root / "labwc_args"
    ).read_text().strip() == "--exit"  # ends labwc so systemd restarts
