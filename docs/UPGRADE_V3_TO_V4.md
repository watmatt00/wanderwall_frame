# PicFrame v3.0 → v4.0 Upgrade Guide

> **For upgrading an existing v3.0 frame.** Fresh Pi install? See [PI_SETUP.md](PI_SETUP.md).

---

## ⛔ Remote-Only Frame — Read This First

mnbframe is **Tailscale VPN only**. There is no LAN IP and no physical access. If WiFi or Tailscale connectivity is lost mid-upgrade, the frame is completely unreachable until it reboots — and if the reboot config is wrong, it may never recover remotely.

**The good news:** Phases 0–8 of this upgrade have zero impact on WiFi or Tailscale. The only dangerous step is Phase 9 (WiFi watchdog), which must be deferred until you have physical access or a reliable out-of-band path.

**Before starting, confirm both backup access methods work:**

| Access method | How to use | Fails if |
|--------------|-----------|---------|
| Tailscale SSH | `ssh pi@100.125.51.92` | WiFi or Tailscale drops |
| Raspberry Pi Connect | [connect.raspberrypi.com](https://connect.raspberrypi.com) | WiFi drops (uses same WiFi, different service) |

Both run over WiFi. Neither helps if WiFi itself dies. However, having rpi-connect as a backup means a Tailscale-specific problem is recoverable.

---

## Prerequisites — GitHub SSH Access

v3.0 used HTTPS with a password that GitHub no longer supports. Before Phase 2 (clone), set up SSH access on the Pi.

**On the Pi:**
```bash
ssh-keygen -t ed25519 -C "mnbframe" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

**On your PC browser:** github.com → (avatar) → Settings → SSH and GPG keys → **New SSH key**
- Title: `mnbframe`
- Paste the public key → Save

**Verify on the Pi:**
```bash
ssh -T git@github.com
# Expected: Hi watmatt00! You've successfully authenticated...
```

---

## Phase Risk Summary

| Phase | Step | Risk | WiFi impact |
|-------|------|------|------------|
| 0 | Pre-flight check | 🟢 Safe | None |
| 1 | Pre-upgrade backup + switch to daily reboot | 🟢 Safe | None |
| 2 | Clone repo | 🟢 Safe | None |
| 3 | Run install.sh | 🟡 Low | None — API not started yet |
| 4 | Write config | 🟢 Safe | None |
| 5 | Disable v3.0 cron sync | 🟢 Safe | None |
| 6 | Start v4.0 services | 🟡 Low | None — SSH survives API failures |
| 7 | Tailscale Funnel | 🟡 Low | None — only changes serve config |
| 8 | Verify | 🟢 Safe | None |
| 9 | WiFi watchdog installer | 🔴 **DEFER** | **Installs dnsmasq + wlan0 services — do in person** |
| 10 | Cleanup | 🟢 Safe | None |

---

## Architecture Delta

| Aspect | v3.0 | v4.0 |
|--------|------|------|
| Config format | bash `key=value` (`~/.picframe/config`) | YAML (`~/.picframe/config.yaml`) |
| Web interface | Flask dashboard (v3.0 port) | FastAPI dashboard (port 8000) |
| Sync mechanism | cron → `frame_sync_cron.sh` | systemd timer → `POST /sync` |
| Source switching | `frame_live` symlink swap | Pi3D HTTP API (seamless fade) |
| Mobile access | None | JWT + Tailscale Funnel |
| WiFi recovery | Physical access / SD card | AP hotspot + captive portal (Phase 9, in-person) |
| Pi3D display | unchanged | unchanged |
| rclone | unchanged | unchanged |

---

## What Stays the Same

- **Pi3D display service** — `picframe.service` keeps running throughout. Never touched.
- **Pi3D config** — `~/picframe_data/config/configuration.yaml` is untouched.
- **rclone remote** — existing `kfr-mnbframe:` remote reused as-is.
- **`~/Pictures/` directories** — no migration, no moves.
- **Display schedule cron entries** — the xrandr on/off schedule has no v4.0 equivalent; keep every `xrandr` cron line.
- **Weekly reboot cron** — keep as-is.

## What Changes

- `~/.picframe/config` (bash) → `~/.picframe/config.yaml` (YAML). Manual translation required.
- Cron sync (`frame_sync_cron.sh`) → `picframe-sync.timer` + `picframe-api.service`.
- Mobile app must re-pair — v4.0 uses a new JWT auth system; old tokens are invalid.
- `frame_live` symlink is retired; v4.0 calls Pi3D's HTTP API directly for source switching.
- New FastAPI dashboard at `http://localhost:8000`.

---

## Phase 0 — Pre-flight Check 🟢

Verify both access methods before touching anything:

```bash
# From your PC — confirm Tailscale SSH works
ssh pi@100.125.51.92 "echo ok && tailscale status | head -2"
```

Log in to [connect.raspberrypi.com](https://connect.raspberrypi.com) and confirm mnbframe appears as online.

Also confirm the display is still running:

```bash
ssh pi@100.125.51.92 "systemctl --user is-active picframe.service"
# Expected: active
```

---

## Phase 1 — Pre-upgrade Backup 🟢

```bash
ssh pi@100.125.51.92

cp ~/.picframe/config ~/.picframe/config.v3.bak
cp ~/picframe_data/config/configuration.yaml ~/picframe_data/config/configuration.yaml.bak
```

Note the key values you'll need in Phase 4:

```bash
grep RCLONE_REMOTE ~/.picframe/config
grep LOCAL_DIR ~/.picframe/config
cat ~/picframe_3.0/config/frame_sources.conf
```

**Values from the audit — confirmed on mnbframe:**

| Value | Setting |
|-------|---------|
| rclone remote | `kfr-mnbframe:` |
| Primary source | `kfr-mnbframe:kfr_mnbframe` → `/home/pi/Pictures/kfr_mnbframe` |
| Secondary source | `kfr-mnbframe:LVRK` → `/home/pi/Pictures/LVRK` |
| Rotation interval | 20 seconds (from `configuration.yaml` `time_delay`) |
| Active source | `kfr_mnbframe` |

**Switch reboot to daily for the duration of the upgrade:**

If connectivity is lost at any point, a daily 03:00 reboot guarantees recovery within 24 hours instead of up to 7 days. Revert to weekly once the upgrade is stable (Phase 10).

```bash
crontab -e
```

Change:
```
0 3 * * 0 /sbin/reboot
```
To:
```
0 3 * * * /sbin/reboot
```

Confirm:
```bash
crontab -l | grep reboot
# 0 3 * * * /sbin/reboot
```

---

## Phase 2 — Clone picframe_4.0 🟢

```bash
cd ~
git clone https://github.com/watmatt00/picframe_4.0.git
cd picframe_4.0
git checkout main
git log --oneline -3
```

**Checkpoint:** Repo cloned, on `main` branch, recent commits visible.

---

## Phase 3 — Install 🟡

```bash
cd ~/picframe_4.0
bash scripts/install.sh
```

What this does — and why it's safe:
- Creates `~/picframe_4.0/venv/` (separate from `~/venv_picframe/` — do not remove the old one)
- Installs `libheif1` via apt (a library, no services)
- Installs Python packages via pip
- Creates `~/.picframe/config.yaml` from the example (does not overwrite if exists)
- Copies systemd unit files to `~/.config/systemd/user/`
- Runs `systemctl --user daemon-reload` — reloads unit definitions only, starts nothing
- Runs `sudo loginctl enable-linger pi` — allows user services to persist after logout

**Nothing is started. WiFi and Tailscale are completely unaffected.**

If the script fails mid-way (it uses `set -euo pipefail`), just re-run it. Fix any apt or pip errors before proceeding.

**Checkpoint:** `ls ~/picframe_4.0/venv/bin/python` exists.

**Verify Tailscale still connected:**
```bash
tailscale status | head -1
```

---

## Phase 4 — Configure 🟢

**Step 4a — Write config.yaml**

Replace the auto-generated config with the correct values for mnbframe:

```bash
nano ~/.picframe/config.yaml
```

```yaml
frame:
  id: "mnbframe"
  name: "MNB Frame"    # shown in mobile app — adjust to taste

display:
  current_source: "kfr_mnbframe"
  rotation_interval: 20   # matches time_delay from configuration.yaml

sync:
  interval: 900
  rclone_flags: []

tailscale:
  funnel_port: 443

logging:
  level: "INFO"
  retention_days: 7
  security_retention_days: 90

updates:
  auto_check: true
  auto_apply: false
  frequency: "monthly"
  day: 1
  check_time: "02:00"
  last_checked: null
  last_result: null
  available_commit: null
```

Validate the YAML before starting the API:
```bash
~/picframe_4.0/venv/bin/python3 -c "import yaml; yaml.safe_load(open('/home/pi/.picframe/config.yaml')); print('OK')"
```

**Step 4b — Write sources.yaml**

Photo sources are stored in a **separate file** (`~/.picframe/sources.yaml`) — they are NOT part of `config.yaml`. Write the sources file now. Use full paths (`/home/pi/...`), never `~`: not every part of the API expands `~`, and the preview on the frame failed on mnbframe because of it (PL-211, 2026-11-23; the API now expands `~` paths at startup).

```bash
nano ~/.picframe/sources.yaml
```

```yaml
sources:
  - id: "kfr_mnbframe"
    name: "Migrated Source (kfr_mnbframe)"
    local_path: "/home/pi/Pictures/kfr_mnbframe"
    rclone_remote: "kfr-mnbframe:kfr_mnbframe"
    enabled: true
  - id: "LVRK"
    name: "Lawson"
    local_path: "/home/pi/Pictures/LVRK"
    rclone_remote: "kfr-mnbframe:LVRK"
    enabled: true
```

Validate:
```bash
~/picframe_4.0/venv/bin/python3 -c "import yaml; yaml.safe_load(open('/home/pi/.picframe/sources.yaml')); print('OK')"
```

> **Note:** `install.sh` creates a placeholder `sources.yaml` with a single local source. Replace it with the above — do not skip this step or the dashboard will show `current_source: Unknown` and sync will fail.

---

## Phase 5 — Disable v3.0 Sync 🟢

Edit crontab to stop the v3.0 sync job. Leave everything else intact.

```bash
crontab -e
```

Comment out **only** this line:
```
# */15 * * * * /home/pi/picframe_3.0/app_control/frame_sync_cron.sh
```

**Leave these lines untouched** — v4.0 has no display scheduler; these cron entries handle it:
```
0 3 * * 0 /sbin/reboot
45 22 * * 0-4 DISPLAY=:0 XDG_RUNTIME_DIR=... xrandr --output HDMI-1 --off
45 23 * * 5,6 DISPLAY=:0 XDG_RUNTIME_DIR=... xrandr --output HDMI-1 --off
0 6 * * 1-5 DISPLAY=:0 XDG_RUNTIME_DIR=... xrandr --output HDMI-1 --mode 1920x1080 --rate 60
0 7 * * 6,0 DISPLAY=:0 XDG_RUNTIME_DIR=... xrandr --output HDMI-1 --mode 1920x1080 --rate 60
```

Confirm the crontab looks right:
```bash
crontab -l
```

---

## Phase 6 — Start v4.0 Services 🟡

```bash
systemctl --user enable picframe-api.service picframe-sync.timer
systemctl --user start picframe-api.service
systemctl --user start picframe-sync.timer
```

Check status immediately:
```bash
systemctl --user status picframe-api.service
systemctl --user status picframe-sync.timer
```

Expected: `picframe-api` → **active (running)**, `picframe-sync.timer` → **active (waiting)**.

**If the API fails to start:** SSH still works. Tailscale still works. Diagnose:
```bash
journalctl --user -u picframe-api.service -n 50
```
Common causes: YAML parse error in config, missing `~/.picframe/` directory, port 8000 already in use (`lsof -i :8000`).

**If you can't fix it remotely:** roll back (see below) and try again next session.

Test the API locally on the Pi:
```bash
curl http://localhost:8000/health
# {"status":"ok"}
curl http://localhost:8000/version
```

**Verify Tailscale still connected:**
```bash
tailscale status | head -1
```

---

## Phase 7 — Tailscale Funnel 🟡

This exposes the API via HTTPS for the mobile app. It only modifies Tailscale's serve config — the VPN tunnel is completely unaffected if this step fails.

**Prerequisite:** Approve Funnel in the [Tailscale admin console](https://login.tailscale.com/admin/acls) if not already done.

```bash
sudo tailscale funnel --bg 8000
tailscale funnel status
# Should show: https://mnbframe.whale-ayu.ts.net → http://127.0.0.1:8000
```

Update `~/.picframe/config.yaml` to add the Funnel URL:
```yaml
frame:
  id: "mnbframe"
  name: "McNab Frame"
  funnel_url: "https://mnbframe.whale-ayu.ts.net"
```

Restart the API to pick up the config change:
```bash
systemctl --user restart picframe-api.service
```

Test from outside:
```bash
# Run this from your PC, not the Pi
curl https://mnbframe.whale-ayu.ts.net/health
# {"status":"ok"}
```

---

## Phase 8 — Verify 🟢

```bash
# API health
curl http://localhost:8000/health

# Trigger a manual sync and watch it
curl -s -X POST http://localhost:8000/sync
journalctl --user -u picframe-api.service -f &

# Pi3D display still running
systemctl --user is-active picframe.service
# active

# Check photo counts via API
curl http://localhost:8000/dashboard/status 2>/dev/null | python3 -m json.tool | head -20
```

**Access the dashboard from your PC** via Tailscale MagicDNS (no tunnel needed):
```
http://mnbframe.whale-ayu.ts.net:8000
```
Requires Tailscale connected on your PC. Works for all frames on the tailnet.

**Re-pair the mobile app:** The v4.0 JWT system is incompatible with v3.0. In the mobile app, remove the existing mnbframe entry and re-pair using the QR code or manual code from the dashboard Settings tab.

**Checkpoint list:**
- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [ ] Dashboard loads via Tailscale MagicDNS URL and shows photo count
- [ ] Manual sync completes without error
- [ ] Pi3D display still active: `systemctl --user is-active picframe.service` → `active`
- [ ] Mobile app re-paired and shows frame status
- [ ] Tailscale still connected: `tailscale status | head -1`

---

## Phase 9 — WiFi Watchdog 🔴 DEFER

> **Do NOT run this phase remotely.** The installer (`install_setup.sh`) installs `dnsmasq` and disables system-level network services. On a remote-only frame, any disruption to DNS resolution or NetworkManager kills WiFi — and with it, Tailscale and all remote access.
>
> Run this phase the next time you have **physical access** to mnbframe, or can guarantee a recovery path if WiFi drops.

When you are physically present:

```bash
cd ~/picframe_4.0
sudo bash scripts/setup/install_setup.sh
```

Verify immediately after (before leaving):
```bash
sudo systemctl status picframe-watchdog
sudo picframe-config --show
```

See [PI_SETUP.md — Step 9](PI_SETUP.md#step-9-wifi-recovery-setup-phase-6) for full details. Without this phase, the frame still works fully — you just won't have automatic WiFi recovery if credentials ever change.

---

## Phase 10 — Cleanup 🟢

Wait at least one week of stable operation before cleaning up.

**Revert reboot schedule back to weekly:**
```bash
crontab -e
# Change: 0 3 * * * /sbin/reboot
# Back to: 0 3 * * 0 /sbin/reboot
```

```bash
# Archive v3.0 repo
mv ~/picframe_3.0 ~/picframe_3.0_archive

# ~/venv_picframe/ is still used by Pi3D — do NOT remove it
# v4.0 uses ~/picframe_4.0/venv/ — a separate venv

# Old v3.0 logs (optional)
ls ~/logs/
```

---

## Rollback

If anything goes wrong between Phases 3–8, rollback is straightforward — SSH remains available throughout.

```bash
# 1. Stop and disable any 4.0 services started in Phase 6
systemctl --user stop picframe-api.service picframe-sync.timer
systemctl --user disable picframe-api.service picframe-sync.timer

# 2. Re-enable the v3.0 cron sync
crontab -e
# Uncomment: */15 * * * * /home/pi/picframe_3.0/app_control/frame_sync_cron.sh
```

Pi3D display (`picframe.service`) is never stopped and continues showing photos throughout. The frame never goes dark.

---

## Troubleshooting

### API fails to start

```bash
journalctl --user -u picframe-api.service -n 50

# Run manually to see the full error
cd ~/picframe_4.0
source venv/bin/activate
python -m src.main
```

Common causes: YAML syntax error in config.yaml, port 8000 in use (`lsof -i :8000`), missing config directory.

### Sync not working

```bash
# Trigger manually and watch
curl -s -X POST http://localhost:8000/sync

# Test rclone directly
rclone lsf kfr-mnbframe:kfr_mnbframe | head -5
```

### Tailscale Funnel health check fails from outside

```bash
# On the Pi — verify Funnel is configured
tailscale funnel status

# Verify API is bound to 8000
ss -tlnp | grep 8000
```

Funnel requires admin console approval — verify at [login.tailscale.com/admin/acls](https://login.tailscale.com/admin/acls).

### Lost connectivity during upgrade

If you lose Tailscale SSH:
1. Try [connect.raspberrypi.com](https://connect.raspberrypi.com) — rpi-connect runs independently
2. If both are down, the daily 03:00 reboot (set in Phase 1) will fire within 24 hours. After reboot, Pi3D and Tailscale restart automatically. SSH should recover.
3. If the API was the only thing broken (most likely), the reboot clears it. Roll back via crontab after reconnecting.

---

## Appendix: Remote Pairing (Installing the App at Another Location)

### Prerequisites

- Upgrade complete through Phase 8
- Tailscale Funnel configured and verified (Phase 7)
- `funnel_url` set in `~/.picframe/config.yaml`

### Why Both Are Required

**Tailscale on your Mac:** The dashboard is at `http://100.125.51.92:8000` — a Tailscale VPN address only reachable from devices on your tailnet. Your Mac can reach it from any WiFi network, but only if Tailscale is active. Turn it on before you leave home.

**Funnel configured before pairing:** When a phone pairs, the API response includes the `funnel_url`. The mobile app stores that URL and uses it for all future calls (status checks, sync, source switching). If Funnel isn't set up at pairing time, the app has no valid address for the frame and will be unable to connect after the initial session.

### Steps

1. **Before leaving home:** confirm Tailscale is running on your Mac and that `tailscale status` shows mnbframe as a peer
2. **At the remote location:** open a browser on your Mac and navigate to:
   ```
   http://100.125.51.92:8000
   ```
3. Open the **Settings tab** → Device Pairing section
4. Generate a pairing code (or display the QR code)
5. On your sister's phone: install **picframe_mgr** from TestFlight
6. Pair using the code or QR code
7. The app stores `https://mnbframe.whale-ayu.ts.net` as the frame address — works from any network, no VPN required on the phone
