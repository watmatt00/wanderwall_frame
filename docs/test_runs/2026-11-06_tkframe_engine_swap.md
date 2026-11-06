# Hardware test: display engine updater on tkframe (PL-188)

**Covers:** PL-188 (replaces KP-022): the hold flag and the Upgrade button, the first conversion on a real frame,
automatic rollback after a real failure, the smoke test, a successful swap, a bad pin, and the return to the
released pin.
**Frame:** tkframe (Pi 4, trixie, Python 3.13.5), `dev`. Engine before: picframe 2026.4.22 in a real
`~/venv_picframe` folder.
**Who:** Matt set the hold, pressed Check Now / Apply Now on the Updates card for each round, and pressed Upgrade
Engine. Claude pushed a temporary pin to `dev` before each round (tkframe is the only frame on `dev`) and read logs
and state over SSH (read-only).
**Result: pass.** Two flaws found in round A and fixed in `678d73c` (round A2 re-checked the fix).
Not checked: the Updates card rows in a browser (Matt reported what the card showed in round A).

| Round | Pin on `dev` | Matt | Result |
|---|---|---|---|
| A | `ab9ba5d`: kframe's set (picframe 2024.11.1) | set `upgrade: hold`, Update | 12:47:35 `upgrade on hold (2026.4.22 installed, pin 2024.11.1)`; folder untouched; card: "Upgrade on hold" + Upgrade Engine button |
| A | same | **Upgrade Engine** | 12:50:04 hold cleared, unit started; 12:50:51 built 2024.11.1 (45 s), smoke test passed; 12:50:52 **converted** the real folder to `venv_picframe-2026.4.22` + symlink; 2024.11.1 crashed on every start (`ModuleNotFoundError: No module named 'distutils'`, `picframe/start.py:6`; distutils is gone in Python 3.12+); launcher restarted the display every ~16 s; 12:52:24 health check failed → **rolled back**; 12:52:27 `2026.4.22; it answers again`. 2024.11.1 folder removed. Display watch: `skipped_update` throughout. Screen black ~1½ min |
| A2 | same pin; fixes `678d73c` | Update | 13:03:21 `Failed smoke test of display engine 2024.11.1`; the build log shows the `picframe.start` → distutils traceback; **no display restart**, :9000 200 throughout |
| B | `655fb00`: 2026.4.22 with pillow 12.1.0 | Update | 13:06:13 built `venv_picframe-2026.4.22-r2` (~40 s); 13:06:17 `upgraded successfully` (health check passed 4 s after the restart); previous engine kept; engine running with pillow 12.1.0 |
| C1 | `c8148e0`: `picframe==2099.1.1` | Update | 13:09:47 `Failed to build display engine 2099.1.1 … 2026.4.22 kept` (pip: `No matching distribution`); no folder left, no restart |
| C2 | `00c6cf1`: released pin (identical to `b144dac`) | Update | 13:20:18 rebuilt `venv_picframe-2026.4.22`; 13:20:21 `upgraded successfully`; link → `venv_picframe-2026.4.22`, `-r2` kept as previous; pillow 12.2.0; `/api/updates/engine` `matches_pin: true` |

## Findings

1. **picframe 2024.11.1 can't run on Python 3.12+** (trixie): `start.py` imports `distutils`. kframe and mnbframe
   (bookworm, Python 3.11) still have distutils. So the downgrade half of the plan's "both directions" can't run
   on a trixie frame; it ran in the simulator on bookworm (KP-020).
2. **The smoke test was too shallow** (fixed `678d73c`): `import picframe, pi3d` doesn't load `picframe.start`. It
   now imports `picframe, picframe.start, pi3d`, so round A's engine fails at build (A2) instead of after the swap.
   Simulator run 3 (mnbframe profile, real pin) confirms the new test passes a good engine on bookworm: 31 of 31
   checks (`2026-11-06_engine_sim_bookworm_run3.log`).
3. **Python 3.13's `activate` has `VIRTUAL_ENV=$(cygpath <path>)`** (Windows-only line), which the rename didn't
   rewrite (fixed `678d73c`: the old path is rewritten wherever a path-name character doesn't follow it). Harmless on
   a Pi, but the rename is now complete.
4. Cosmetic, not changed: a dependency-only change logs `Upgraded 2026.4.22 -> 2026.4.22`.

## State after the test

`~/venv_picframe` → `venv_picframe-2026.4.22` (released pin), previous `venv_picframe-2026.4.22-r2` kept;
`engine.yaml` `last_result: 'ok'`; no hold flag; `dev` pin identical to `b144dac`.
