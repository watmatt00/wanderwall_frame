# Simulator check: install.sh --from-v4 blocks added 2026-11-06 (before mnbframe, KP-027)

**Covers:** the four blocks added to `scripts/setup/install.sh` in `b144dac` that run on the `--from-v4` path, which
mnbframe's reinstall (KP-027) will take: A. branch-name check, B. hold flag, C. Phase 9 unit copy loop (now with the
display-watch units), D. Phase 9 launcher install. Plus E: the real `update_engine.sh` reading the hold that B wrote.
**How:** `tests/sim/install/run_from_v4_check.sh` runs `from_v4_check.sh` as root in the arm64 bookworm simulator image
(Python 3.11.2), against a home for user `pi` set up like mnbframe's (checked 2026-11-06: the v4 `start_picframe.sh`
stub, labwc autostart, engine built from mnbframe's exact `pip freeze`, 2024.9.24). The blocks are cut out of
`install.sh` by their first and last lines, so the real text runs. `as_user` uses `runuser` (no sudo in the image).
**Result: pass**, 39 of 39 checks (`2026-11-06_install_from_v4_blocks.log`). Shellcheck: `install.sh` has the same 2
warnings as before the change (`52ce322`), none new.

| Block | Checks |
|---|---|
| A | `main`, `dev`, `v5`, `feature/x`, `release-5.0` accepted; `main;touch /tmp/pwned`, `../x`, `-x`, `a b`, `$(id)`, empty refused with exit 1; nothing ran from a branch name |
| B | `~/.wanderwall/engine.yaml` written with `upgrade: hold`, owned `pi:pi`, mode 600, logs the hold; a second run changes nothing and logs nothing; PyYAML reads `upgrade: hold` as the app does |
| C | all six units copied to `~/.config/systemd/user`, owned by `pi`, including `wanderwall-display-watch.service` and `.timer`; no "not found" warning |
| D | `~/start_picframe.sh` now runs `/repo/scripts/display/start_picframe.sh`; the v4 stub kept as `.pre-launcher`; owned by `pi`, mode 755; no warning |
| E | `update_engine.sh` (as `pi`): exit 0, `upgrade on hold (2024.9.24 installed …)`, engine still a real folder, hold still set, `engine.yaml` still `pi`, 600 |

**Not covered:** `user_systemctl enable --now wanderwall-display-watch.timer` (no systemd in the container; same form
as the `enable --now` lines next to it), and the rest of the `--from-v4` path, unchanged since kframe's reinstall on
2026-10-23.
