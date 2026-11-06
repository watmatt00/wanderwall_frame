# Hardware test: display launcher (PL-187) and self-repair (KP-034, KP-035), tkframe

**Covers:** PL-187 (slideshow no longer crashes when no screen is detected at boot), KP-034 / KP-035 (restart
picframe when :9000 stops answering), and the no-op path of the engine updater (KP-011, KP-013).
**Frame:** tkframe (Pi 4, trixie, Python 3.13.5, picframe 2026.4.22), on `dev` at `b144dac`.
**Who:** Matt updated the frame, unplugged and replugged HDMI, pressed Restart Frame and ran the freeze command.
Claude read logs and state over SSH (read-only).
**Result: pass** (3 of 3 rounds). The Updates card rows weren't checked in a browser.

## 1. Update applied (11:21, Matt: dashboard Update)

`wanderwall.log`, `update_app.sh` output:
- `Updated: wanderwall-display-watch.service`, `Updated: wanderwall-display-watch.timer`, `Enabled and started: wanderwall-display-watch.timer`
- `Display launcher installed: /home/pi/start_picframe.sh -> /home/pi/wanderwall_frame/scripts/display/start_picframe.sh (applies at the next display restart)`; original kept as `~/start_picframe.sh.pre-launcher`
- `Display engine check started in the background (wanderwall-engine-update …)`, then `[update_engine] Display engine 2026.4.22 matches the pin; nothing to do`
- `~/.wanderwall/engine.yaml`: `last_result: 'up_to_date'`; `~/venv_picframe` still a real folder (no conversion at the pin)
- `GET /api/updates/engine`: `matches_pin: true`, `running: false`
- First watch run 11:21:47: `display check: ok`. No warnings or errors.

## 2. Boot with no screen (PL-187)

Matt unplugged HDMI, pressed Restart Frame, waited, plugged HDMI back in. Photos appeared.

| Time | Source | Line |
|---|---|---|
| 11:23:45 | kernel | `vc4-drm gpu: [drm] Cannot find any crtc or sizes` (no screen at boot, as in the 10:04 crash) |
| 11:24:04 | picframe.service | `start_picframe: waiting for a screen (state: none, 0s so far)` |
| 11:26:56 – 11:29:56 | display watch | `display check: no_screen` every minute; no failures counted |
| 11:30:15 | kernel | `fb0: vc4drmfb frame buffer device` (HDMI plugged in) |
| 11:30:18 | picframe.service | `start_picframe: screen ready after 355s`, `starting display engine (/home/pi/venv_picframe)` |

No `Traceback` or `ZeroDivisionError` in the boot. :9000 answered 200 at 11:30:46.

Seen, not caused by this change: labwc's first start at 11:23:51 failed (`Failed to start a DRM session`, libseat
"Could not open target tty"); systemd's restart worked. The 10:04 boot (before `b144dac`) shows the same. Cause not checked.

## 3. Frozen slideshow (KP-034, KP-035)

Matt froze the engine with `kill -STOP` (PID 3720) at about 11:32:30.

| Time | Line |
|---|---|
| 11:33:01 | `display check: failing` (1) |
| 11:34:06 | `display check: failing` (2); PID 3720 state `Tl`, :9000 not answering |
| 11:35:01 | `WARNING [display_watch] Display engine not answering on http://localhost:9000/ for 3 checks in a row; restarting picframe.service` |
| 11:35:01 | `INFO [display_watch] Service picframe.service restarted successfully by the display check` |
| 11:35:02 | `start_picframe: starting display engine (/home/pi/venv_picframe)` (new launcher PID 5444) |
| 11:35:13 | new engine PID 5456 running, :9000 200; `display_watch.json` 0 failures, 1 restart recorded |

About 2½ minutes from freeze to recovery. The fail-safe (`kill -CONT`) wasn't needed.

## Not covered here

- Updates card rows in a browser.
- Engine conversion, upgrade, rollback and the hold button: `pf_pi_sim` (KP-020), then tkframe (PL-188).
