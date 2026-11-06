# Simulator run: display engine updater on bookworm (KP-020)

**Covers:** KP-020 (upgrade, forced failure with automatic rollback, first-conversion rollback, second run does nothing,
bad pin), hold flag (KP-015), for both production starting points.
**Harness:** `tests/sim/engine/run_sim.sh` (arm64 Debian bookworm, Python 3.11.2, under qemu-user; the frames' engine
libraries `libsdl2-2.0-0`, `libgles2`, `libegl1`). Runs the real `scripts/setup/update_engine.sh` and pin from the repo.
The screen is a fake `/sys/class/drm` folder; `systemctl` is a stub that runs `standin_engine.py` with
`~/venv_picframe/bin/python`: it imports picframe and pi3d from the engine and answers on :9000 (no slideshow without a
screen or GPU). A forced failure makes the stand-in exit for the new version.
**Profiles:** the "before" engines are built from kframe's and mnbframe's exact `pip freeze` (read 2026-11-06):
`kframe-2024.11.1.txt`, `mnbframe-2024.9.24.txt`.
**Result: pass.** 62 checks passed, 0 failed (31 per profile). Code at `b144dac` plus the fd 9 fix below.

## Run 1: found a bug (fixed)

Step 3 exited at once with `Engine update already running (lock /home/pi/.wanderwall/engine.lock)`. The engine started
by `systemctl restart` during step 2 had inherited `update_engine.sh`'s lock (fd 9) and kept it held. On a frame,
systemd starts the engine, so it wouldn't inherit it, but the script shouldn't rely on that: every `systemctl` call
in `update_engine.sh` now closes fd 9 (`9>&-`). The simulator's stub keeps passing fds on purpose, so run 2 checks
the script's fix. Unit tests: 19 of 19 pass after the fix.

## Run 2

| Step | kframe (2024.11.1) | mnbframe (2024.9.24) |
|---|---|---|
| Build today's engine (real folder) | built in 201 s | built in 194 s |
| 1. Hold flag set | exit 0, `on_hold`, 9 s | exit 0, `on_hold`, 9 s |
| 2. Hold cleared, new engine forced to crash | exit 1, `rolled_back`, 319 s | exit 1, `rolled_back`, 319 s |
| 3. Upgrade | exit 0, `ok`, 217 s | exit 0, `ok`, 213 s |
| 4. Second run | exit 0, `up_to_date`, 10 s | exit 0, `up_to_date`, 9 s |
| 5. Bad pin (`picframe==2099.1.1`) | exit 1, `failed`, 94 s | exit 1, `failed`, 91 s |

Checks after each step (all passed for both profiles; full output in `2026-11-06_engine_sim_bookworm.log`):
- **Start:** the old engine answers on :9000.
- **1:** `on_hold`; `~/venv_picframe` still a real folder; no new folder built; old engine answering; hold flag kept.
- **2:** `rolled_back`; `~/venv_picframe` is now a symlink to `venv_picframe-<old>`; the failed 2026.4.22 folder is
  removed; the old engine's `bin/picframe` shebang and `bin/activate` name its new folder; the old engine answers again
  from the renamed folder; its `pip` still runs.
- **3:** `ok`; `installed_version` 2026.4.22, `previous_version` the old one; link points at `venv_picframe-2026.4.22`;
  the stand-in reports picframe 2026.4.22; previous engine kept; the new engine's packages match the pin.
- **4:** `up_to_date`; no `systemctl` call; engine still answering.
- **5:** `failed`; link unchanged; no 2099.1.1 folder left; engine still answering.

`wanderwall.log` had exactly two ERROR lines per profile, both from the forced failures:
`Failed health check of display engine 2026.4.22 … rolling back` (step 2) and
`Failed to build display engine 2099.1.1 … 2026.4.22 kept` (step 5).

## Not covered here

- The real slideshow on a screen with the new engine, and the Upgrade button: tkframe, PL-188.
- Python 3.13 / trixie (tkframe, bfframe): covered by PL-188 on tkframe.
