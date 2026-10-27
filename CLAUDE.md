# WanderWall - Project Context

## Overview

WanderWall is a Raspberry Pi picture frame management system:
- **FastAPI backend** with JWT authentication (port 8000)
- **Web dashboard** for LAN-based management (no auth, Jinja2 + vanilla JS)
- **Mobile app** via Tailscale Funnel (separate repo: `wanderwall_app`)
- **Pi3D PictureFrame** integration for GPU-accelerated display
- **rclone sync** for cloud photo synchronization

## Architecture

```
Mobile App ──(Tailscale Funnel)──> Pi API (JWT) ──> Pi3D Display
Web Dashboard ──(LAN or Tailscale VPN)──> Pi API (no auth) ──> Pi3D Display
Cloud (Koofr) ──────────────────────────> rclone sync ──> local photos
```

## Device Connection Info

| Device | IP (LAN) | IP (VPN) | Dashboard URL | User | Branch | Notes |
|--------|----------|----------|---------------|------|--------|-------|
| **tkframe** | 192.168.102.210 | 100.100.168.66 | `http://tkframe.whale-ayu.ts.net:8000` | pi | `dev` | Test frame — tracks dev branch |
| **kframe** | 192.168.102.200 | 100.69.17.26 | `http://kframe.whale-ayu.ts.net:8000` | pi | `main` | Home frame (production) |
| **mnbframe** | 192.168.1.154 | 100.125.51.92 | `http://mnbframe.whale-ayu.ts.net:8000` | pi | `main` | Remote only (production) |
| **bfframe** | 192.168.102.215 (home, until shipped) | — | `http://bfframe.whale-ayu.ts.net:8000` | pi | `main` | Pi 5, being built for Burke and Fafa, then remote (production). `docs/BUILD_bfframe.md` |
| **fuckms** | 192.168.102.100 | 100.82.140.119 | — | matt | — | Main PC (dev) |

Dashboard URLs require Tailscale connected (MagicDNS on tailnet `whale-ayu.ts.net`). LAN IPs also work directly on port 8000.

Pi frames are **pull-only** from GitHub. All dev/push happens on PC.

## Key File Locations (on Pi)

| File | Purpose |
|------|---------|
| `~/picframe_data/config/configuration.yaml` | Pi3D display config (rotation interval, pic_dir, etc.) |
| `~/.wanderwall/config.yaml` | Dashboard config (frame name, sync interval, current source) |
| `~/.wanderwall/sources.yaml` | Photo source definitions |
| `~/.wanderwall/frame_albums.yaml` | Albums this frame owns (active/deleted), mirrored to Koofr `.picframe/frames/<pi-serial>.yaml` — Recover Albums ownership (PL-147) |
| `~/.wanderwall/logs/wanderwall.log` | Operations log |
| `~/.wanderwall/logs/security.log` | Auth/security log |
| `~/.local/share/systemd/timers/stamp-wanderwall-sync.timer` | Last sync timestamp |
| `~/.config/systemd/user/wanderwall-api.service` | API service unit |
| `~/.config/systemd/user/wanderwall-sync.service` | Sync service unit (calls POST /sync) |
| `~/.config/systemd/user/wanderwall-sync.timer` | Sync timer unit |
| `~/.config/systemd/user/picframe.service` | Pi3D display service unit |
| `/var/lib/wanderwall/state.yaml` | Phase 6 state (provisioned, koofr_configured, needs_setup, frame_name) |
| `/var/lib/wanderwall/install.conf` | Written by install_setup.sh — frame user, home dir, project path |
| `/etc/hostapd/wanderwall-hostapd.conf` | AP hotspot config (SSID, random password from Pi serial) |
| `~/picframe_data/data/no_pictures.jpg` | Shown by Pi3D when no photos exist; replaced with setup instruction image during first-run |
| `~/Pictures/spotlight/` | Persistent spotlight dir — Pi3D keeps it indexed; contents cleared after each spotlight |

## Deployment Workflow

### Branch Policy
- `dev` — all active development. tkframe tracks this.
- `main` — production. kframe and mnbframe track this. **Only receives tagged merges from `dev`.**
- Tag format: `v4.0.X` where X matches the commit count shown in the dashboard (e.g. `v4.0.52`).
- The dashboard Updates card shows each frame's active branch (DEV/MAIN badge).

### Dev Branch (daily work → tkframe)
1. Work on `dev` branch on PC
2. `git add && git commit && git push origin dev`
3. Pull on tkframe: `ssh pi@192.168.102.210 "cd ~/wanderwall_frame && git pull"`
4. Restart API: `ssh pi@192.168.102.210 "systemctl --user restart wanderwall-api"`
5. Test dashboard: `http://192.168.102.210:8000`

### Promoting dev → main (kframe, mnbframe)
1. Tag the commit: `git tag v4.0.X && git push origin v4.0.X`
2. Merge to main: `git checkout main && git merge dev && git push origin main`
3. Prod frames pull on next scheduled check, or manually:
   - kframe: `ssh pi@192.168.102.200 "cd ~/wanderwall_frame && git pull"`
   - mnbframe: `ssh pi@100.125.51.92 "cd ~/wanderwall_frame && git pull"`
4. Restart API on prod frames as needed
5. `git checkout dev` to return to dev work

### One-Time Branch Setup (tkframe)
```bash
ssh pi@192.168.102.210 "cd ~/wanderwall_frame && git fetch origin && git checkout dev"
```
kframe and mnbframe are already on `main` — no action needed.

User services (`systemctl --user`): `wanderwall-api`, `wanderwall-sync`, `wanderwall-sync.timer`, `wanderwall-lights` (indicator lights overlay), `picframe` (the upstream display engine)

**Phase 6 system services** (run as root, `systemctl` without `--user`):
- `wanderwall-watchdog` — WiFi monitor, enabled at boot
- `wanderwall-ble-setup` — BLE WiFi setup, started on demand by watchdog
- `wanderwall-ap-setup` — AP hotspot + captive portal, started on demand by watchdog

## Dashboard Architecture

Single-page five-tab interface (`dashboard.html`). No standalone pages — all features are consolidated into tabs. Full endpoint list: `docs/API.md`.

Tab order: **Frame Status | Albums | Tools | Backups | Settings** (the Albums button's `data-tab` is still `sources`)

- **Frame Status Tab**: Traffic light (green/amber/red), photo counts (cloud + local), current image thumbnail, quick actions (Sync Now, Restart Frame, Restart API, Reboot Frame — needs install_setup.sh re-run for its polkit rule, PL-142)
- **Albums Tab**: album table (name, cloud folder, cloud and frame counts, status; ID, local path and Activate/Delete behind "Show technical columns"), Add Album (Display Name only; id, local folder and cloud folder derived from it, cloud folder `KFR_<id>` or `_2`… if taken, PL-165). Delete removes the album's photos on the frame, keeps the cloud folder and backups, and is hidden for the album showing (PL-147)
- **Tools Tab**: Album selector (shared by all cards, reloaded each time the tab opens), Filename Cleaner (spaces→underscores, long-name >20 chars renamed to YYYYMMDD_HHMMSS, Google ID tokens, numbered suffixes, ext case/wrong-ext), Duplicate Finder, Video File Manager, Rename File (scan all files → editable table → batch cloud-first rename, blank inputs, dup guardrails), Corrupt Photo Finder (empty/undecodable photos, cloud-first delete, PL-127), Rotate Photos (⟲ ⟳ 180° or apply EXIF orientation, re-saved upright, cloud-first, PL-126)
- **Backups Tab** (PL-164): Photo Backups with its own album picker (one album, or **Whole frame**: one `frame_<name>_<ts>.tar.gz` with `manifest.yaml` first, one-click restore that merges, free-space check; list with full path, restore, download, delete, deleted albums' backups too). Every restore skips photos the album already has (same name + bytes). Recover Albums (cloud folders, take over another frame, upload .zip/.tar.gz up to 16 GB). The picker and Recover list reload each time the tab opens
- **Settings Tab**: Frame settings (name, rotation interval, sync interval, log level, read-only Frame ID + Funnel URL), Network sub-card (LAN IP + WiFi SSID, nested in Frame Settings), device pairing (QR code, manual code, countdown, Tailscale IP, instructions), manage devices (inline table with AJAX revoke via `GET /api/devices`), log viewer (expandable, ops/security toggle, line count, auto-refresh), software updates (check/apply, auto-check schedule, DEV/MAIN branch badge), Demo Mode card (only when `demo.allowed: true` is hand-set in config; reusable reviewer codes, 14-day expiry, revoke on end, amber banner on every tab — PL-015)

### Key Behaviors
- Rotation interval changes write to `~/picframe_data/config/configuration.yaml` (model.time_delay) and auto-restart picframe service
- Sync interval is stored in seconds but displayed as minutes in UI
- `POST /sync` syncs the **active display source** (falls back to first enabled source if active has no remote)
- Photo counts (cloud/local) reflect the active source only, not all sources combined
- Traffic light goes AMBER when cloud/local counts don't match
- Dashboard auto-refreshes every 15 seconds via AJAX to `/dashboard/status`
- Cloud photo count uses shared `rclone_count()` via `status_service.py` with 15-second timeout
- "Last restart" queries systemd `ActiveEnterTimestamp` (survives log rotation)
- **Source switching uses Pi3D's HTTP API** (`GET http://localhost:9000/?subdirectory=<rel>`) for seamless fade with no service restart; falls back to config + restart only when the HTTP API is unreachable or the path is outside `~/Pictures`
- **Revoked devices blocked on every request**: `get_current_device()` checks device storage after token validation — revoked tokens return 401 immediately
- Tools tab card headers are **clickable**: clicking the header expands/collapses the card; scan cards (Filename Cleaner, Duplicate Finder, Video Manager, Rename File) trigger a scan directly when clicked from collapsed state

## Mobile App Scope

**Android is permanently on hold. iOS only.** Do NOT suggest, plan, or reference Android work.

Two iOS apps: WanderWall – Photo Frame (Manager, admin) and WanderWall Share (contributor). Built on the Mac (Xcode, simulator against tkframe) and by CodeMagic (IPAs). See `docs/TEST_PLAN.md` for the manual test plan covering both backend and iOS app.

## Cross-Repo Relationship

| Repo | Purpose | API Role | PC clone |
|------|---------|----------|----------|
| `wanderwall_frame` (this) | Pi backend + dashboard | Defines API | `~/Downloads/GitHub/wanderwall_frame` |
| `wanderwall_app` | Mobile apps (iOS only) | Consumes API | `~/Downloads/GitHub/wanderwall_app` |

Known issues and parking lot for BOTH repos: `wanderwall_app/docs/PARKING_LOT.md` (single source of truth; frame items tagged `frame`). Do not add items to `docs/PARKING_LOT.md` here — it is only a pointer.
Phase 4, 5 & 6 plan in `docs/PHASE_4_5_PLAN.md` is historical (all built). Next steps come from the parking lot.
Test plan in `docs/TEST_PLAN.md` - covers backend, dashboard, and iOS app. Test runs stored in `docs/test_runs/`.
Phase 6 setup guide in `docs/PI_SETUP.md` — includes WiFi recovery usage guide and troubleshooting.

## Phase 6: First-Run & WiFi Recovery

Two-step first-run flow:
1. **Portal (Step 1):** Frame broadcasts `WanderWall-[name]` AP hotspot. User connects, enters WiFi SSID/password + frame name. Frame reboots.
2. **Dashboard banner (Step 2):** After WiFi connects, dashboard shows Koofr setup banner. User enters Koofr email + password (validated live). Once saved, normal operation begins.

While waiting for Step 2, Pi3D displays a PIL instruction image (`no_pictures.jpg`) with the dashboard URL. Image is restored to the original once Koofr is configured.

WiFi recovery (existing frame): same AP portal, Step 1 only (no frame name or Koofr — already configured).

Phase 6 install: `sudo bash scripts/setup/install_setup.sh` (run from project root as sudo).

When making API changes, update `docs/API.md` so mobile repo can reference it.

## Coding Standards

- Python: PEP 8, type hints, docstrings, no bare except
- Validate all user input (regex for IDs, paths, remote names)
- Never interpolate user input into shell commands
- Use `asyncio.create_subprocess_exec()` for external commands (rclone, systemctl)
- Use `systemctl --user` (not system-level) for all service operations

### Settings Cache Pattern

`get_settings()` uses `@lru_cache` for performance. After modifying config via `config_manager.set()`, you **must** call `reload_settings()` to clear the cache:

```python
from src.config.settings import get_settings, reload_settings

config_manager.set("display.current_source", source_id)
reload_settings()  # Required! Otherwise get_settings() returns stale data
```
