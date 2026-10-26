# WanderWall - Pi Setup Guide

Complete setup guide for a fresh Raspberry Pi.

**Upgrading an existing v3.0 frame?** See [UPGRADE_V3_TO_V4.md](UPGRADE_V3_TO_V4.md) instead.

**IMPORTANT FOR CLAUDE**: When guiding a user through Pi setup, prompt them explicitly
at each step checkpoint before moving to the next step. Do not assume any step is complete
unless the user confirms it.

## Prerequisites

- Raspberry Pi 4 or 5 (64-bit recommended)
- MicroSD card (32GB+ recommended)
- Display connected via HDMI
- Network connection (Ethernet or WiFi)
- Tailscale account

---

## Step 1: Raspberry Pi OS

**PROMPT USER**: "Have you flashed Raspberry Pi OS to the SD card and completed initial boot?"

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS (64-bit)** to SD card
3. In imager settings:
   - Enable SSH
   - Set hostname (e.g., `tkframe`)
   - Configure WiFi if needed
   - Set username/password
4. Boot Pi and complete initial setup

```bash
# Optional: Configure additional settings
sudo raspi-config
```

**CHECKPOINT**: User should be able to SSH into the Pi.

---

## Step 2: Verify Python Version

**PROMPT USER**: "Confirm Python 3.11+ is available — the installer will fail immediately if not."

```bash
python3 --version
# Should be 3.11+
```

The installer handles OS updates and all package installs automatically. No manual `apt` steps needed.

**CHECKPOINT**: Ask user to confirm Python version is 3.11+.

---

## Steps 3–9: Full Install (single command)

**PROMPT USER**: "Now we'll run the combined installer. It asks a few questions upfront, then handles everything automatically — including multiple reboots."

Before running, generate a **Tailscale pre-auth key** to skip browser auth:
1. Go to [Tailscale admin → Settings → Keys](https://login.tailscale.com/admin/settings/keys)
2. Create a one-time, ephemeral auth key
3. Paste it when the installer prompts (or leave blank to auth via browser)

Run the installer for Main:

```bash
curl -fsSL https://raw.githubusercontent.com/watmatt00/wanderwall_frame/main/scripts/setup/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

Run the installer for Dev:

```bash
curl -fsSL https://raw.githubusercontent.com/watmatt00/wanderwall_frame/dev/scripts/setup/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

> **Note:** Keep this as a single line — the `\` line-continuation form breaks when pasted into a terminal. Process substitution (`sudo bash <(curl ...)`) also fails on Pi OS.

The installer prompts for:
- **Frame name** (hostname, e.g. `tkframe`)
- **Branch** (`main` for production, `dev` for testing)
- **Tailscale pre-auth key** (leave blank for browser auth)
- **Koofr email + app password** — generate an app password at [app.koofr.net](https://app.koofr.net) → Preferences → App passwords (use an app password, NOT your main account password)

Then it runs fully automatically through 4 reboots (~15–20 minutes total). It installs:
1. **OS update** — packages up to date
2. **Console mode** — no desktop environment needed
3. **Core packages** — labwc (Wayland compositor), SDL2, VLC, FFmpeg
4. **picframe** — display engine via pip, initialized with display defaults
5. **wanderwall_frame** — repo cloned, venv created, API installed
6. **Config** — `~/.wanderwall/config.yaml` written with frame name + Funnel URL
7. **labwc** — Wayland compositor + systemd user service wired up
8. **API/sync/lights** — `wanderwall-api`, `wanderwall-sync`, `wanderwall-lights` services started
9. **Koofr** — credentials validated and configured (no dashboard step needed)
10. **Phase 6** — WiFi watchdog, AP portal, `wanderwall-config` tool installed

Optional services (pass as flags):
```bash
sudo bash /tmp/install.sh --with-samba --with-mqtt
```

To monitor progress during install (open a second SSH session):
```bash
tail -f ~/install_log.txt
```

**CHECKPOINT**: Ask user to confirm the script completes successfully and shows the summary banner.

---

## Reinstall a PicFrame v4 frame as WanderWall v5

v5 renamed the app's services, folders and repo, so a v4 frame gets a one-time reinstall instead of `git pull`. It runs on the existing OS over SSH: Tailscale, Funnel, WiFi, the Koofr remote, the display engine and its settings all stay. No reboots.

```bash
curl -fsSL https://raw.githubusercontent.com/watmatt00/wanderwall_frame/main/scripts/setup/install.sh -o /tmp/install.sh
sudo bash /tmp/install.sh --from-v4 --branch=main
```

- Copies `config.yaml`, `sources.yaml`, `frame_albums.yaml` and `deleted_albums.yaml` (if present; folded into the registry on first start) from `~/.picframe` to `~/.wanderwall`, and `state.yaml` from `/var/lib/picframe` to `/var/lib/wanderwall`.
- Does **not** copy pairings (`devices.json`, `jwt_secret`, `invites.json`): pair each phone again afterwards.
- Stops the v4 services and moves their unit files to `~/picframe_v4_backup`. `~/picframe_4.0` and `~/.picframe` are left as they were.
- Undo: `sudo bash ~/wanderwall_frame/scripts/setup/rollback_v4.sh` (restores and restarts v4).

---

## Step 10: Verify Installation

**PROMPT USER**: "Let's verify everything is working."

Check services:
```bash
# Pi3D display
systemctl --user status picframe.service

# API (if running via systemd)
systemctl --user status wanderwall-api.service
```

Test API locally:
```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/version
# {"version":"5.0.0","api":"wanderwall"}
```

Test via Tailscale Funnel:
```bash
curl https://<hostname>.<tailnet>.ts.net/health
# {"status":"ok"}
```

**CHECKPOINT**: Ask user to confirm both local and Funnel health checks pass.

---

## Verification Checklist

- [ ] `python3 --version` shows 3.11+
- [ ] `systemctl --user status picframe.service` shows loaded
- [ ] `rclone version` shows installed
- [ ] `tailscale status` shows connected
- [ ] `~/wanderwall_frame/venv/` exists
- [ ] `~/.wanderwall/config.yaml` exists
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`
- [ ] `curl https://<hostname>.<tailnet>.ts.net/health` returns `{"status":"ok"}`
- [ ] `sudo systemctl status wanderwall-watchdog` shows active (running)
- [ ] `sudo wanderwall-config --show` prints state without errors

---

---

## Recover a deleted album

Delete Album removes an album's photos from the frame but keeps its cloud folder and backups. Dashboard → Backups tab brings it back (♻️ Recover Albums, and 💾 Photo Backups for backups):

- **From cloud storage:** lists this frame's deleted albums whose cloud folder (`KFR_*`) still exists and no album uses. Recover re-adds the album pointed at that folder and syncs it. A folder another frame on the same Koofr account owns is never offered. Folders no frame owns (e.g. deleted before frames kept a list) appear automatically on an account only this frame uses, otherwise behind **Show unclaimed folders** with a warning.
- **From a backup:** Photo Backups → **Whole frame** lists every backup in `~/Pictures/backups`, including a deleted album's (marked *deleted*). Restore puts it into the album, or into a new album if the album is gone.
- **Whole-frame backup:** Photo Backups → **Whole frame** → Create Backup saves every album into one file, `frame_<name>_<time>.tar.gz` (a `manifest.yaml` with the album names and cloud folders, then a folder per album). It checks there's room first and keeps 1 GB free. **Download** it to keep a copy off the SD card. **Restore** brings back every album in one click: albums still on the frame get only the photos they're missing, this frame's deleted albums come back on their own cloud folder, and anything else becomes a new album on a cloud folder no other frame uses. Running it twice changes nothing.
- **Moving to a new frame:** on the same Koofr account, use **Take over** (below); the photos are already in the cloud. Otherwise (new account, or the cloud copy is gone), upload the downloaded whole-frame file in Recover Albums → Upload.
- **Upload a .zip:** a .zip or .tar.gz of photos from your computer (up to 16 GB, and it has to fit on the frame with 1 GB left free) into an existing or a new album. A whole-frame backup restores all its albums instead.

Restored photos are copied to the album's cloud folder first and then added on the frame, so the next sync doesn't remove them. Nothing is overwritten or duplicated: a photo the album already has (same name and same bytes) is skipped, and a different photo with the same name is saved as `name_1.jpg`. Only photos and videos are restored; other files are skipped.

### Which albums are this frame's

Each frame keeps a list of every album it has had (active or deleted) in `~/.wanderwall/frame_albums.yaml`, with a copy in Koofr at `.picframe/frames/<pi-serial>.yaml`. The Pi's board serial (`/proc/cpuinfo`) identifies the frame, so the list survives reflashing. Each frame writes only its own file; entries are marked deleted, never removed. `last_seen` is refreshed after a sync about once a day.

- **Reinstall (same Pi, fresh SD card):** once Koofr is set up again, the frame reads its list back and every old album appears in Recover Albums.
- **SD card moved to a new Pi:** the dashboard asks once whether the card was **moved** (keep every album; the old board's file is marked `replaced_by` the new one) or **copied** to start a second frame (it keeps only the albums on the card).
- **New Pi and fresh SD card:** Recover Albums → *Other frames on this cloud account* → **Take over**. A frame that checked in within the last 24 hours may still be running, so you type its name to confirm.
- **Taken over by mistake:** the running frame shows a banner with **Undo**. Nothing is deleted either way.
- **Dedicated or shared account:** decided once, when the frame first writes its list. Dedicated only if every `KFR_*` folder in the account is this frame's; it counts as shared as soon as another frame's file appears.

---

## Reboot Frame (dashboard and Manager app)

Reboot Frame (dashboard Frame Status quick actions, or the Manager app's Frame Settings) needs a polkit rule that `install_setup.sh` installs. On a frame set up before 2026-10-19, pull, then re-run it once:

```bash
cd ~/wanderwall_frame && git pull
sudo bash scripts/setup/install_setup.sh
```

Until then, Reboot Frame answers "Reboot isn't set up on this frame yet". Re-running keeps state.yaml; it reinstalls the setup packages, rewrites the hotspot config, setup service units and polkit rule, and restarts the WiFi watchdog (the slideshow keeps running).

---

## Demo Mode (App Store review frame)

Reusable pairing codes for an App Store reviewer (PL-015). See `docs/SECURITY.md` → Demo Mode for the risks.

0. **Put the review frame on `main`** so a `dev` push can't change it mid-review (RB-07): `bash ~/wanderwall_frame/scripts/update_app.sh --branch=main`. It checks out `main`, runs `main`'s copy of the script and restarts the API. `--branch=dev` moves it back after the review.
1. **Allow it on the review frame only.** Add this to `~/.wanderwall/config.yaml` on that frame, then `systemctl --user restart wanderwall-api`:
   ```yaml
   demo:
     allowed: true
   ```
   Never on a frame with personal photos or a personal Koofr account.
2. **Turn it on:** dashboard → Settings → 🍎 Demo Mode → Turn On Demo Mode. The card shows the Manager code and the Contributor code, each with a QR code (Download QR saves a PNG to attach to the App Review notes), plus the Frame URL. The QR codes use the Funnel URL; without one they fall back to the Tailscale IP, which won't work for a reviewer, and the card says so. An amber banner shows on every tab with the days left.
3. **It lasts 14 days**, then turns itself off and revokes the demo phones. **Generate New Codes** replaces both codes and restarts the 14 days (paired phones stay paired); the old codes then report "expired".
4. **Baseline and reset (PL-151).** Needs a Koofr account only this frame uses (the album registry marks it `dedicated`). Set the frame up (albums with sample photos, the album to show, name, rotation, sync interval), then Demo Mode card → **Save as Baseline**. It copies the albums' photos to `~/.wanderwall/demo_baseline` with the settings. **Reset to Baseline** before each submission and after a reviewer session:
   - removes phones paired with a demo code and every Share (contributor) phone (normally paired admins stay), every invite, and every Koofr upload link on the account
   - makes each baseline album, on the frame and in its cloud folder, hold exactly the saved photos (recreated if deleted, renamed back), shows the saved album, deletes every other album and every other `KFR_*` cloud folder on the account
   - puts back the frame name, rotation and sync interval, and turns demo mode on for 14 more days with the same codes
   It refuses if the account isn't dedicated or the Koofr login changed since the baseline was saved. Running it twice is safe.
5. **After the review:** Turn Off Demo Mode (revokes demo phones), then rotate the Koofr app password.

To stop allowing it, remove `allowed: true` (or set it false) and restart the API; demo mode ends and demo phones are revoked on the next check.

---

## WiFi Recovery — Usage Guide

### How setup mode is triggered

| Condition | When |
|-----------|------|
| First boot (`provisioned=false`) | Immediately on boot |
| WiFi lost > 10 minutes | `needs_setup` flag set; setup mode on next reboot if WiFi is still unavailable 90 s after boot |
| Manual trigger | `sudo wanderwall-config --force-setup` then reboot |

### What the frame does in setup mode

1. Photo display stops
2. Console (`/etc/issue`) shows a box with the hotspot name, AP password, and portal URL — visible above the login prompt. After an outage the box reads **"WanderWall - No WiFi"**: photos resume automatically when WiFi is back, and the hotspot steps are only for a changed WiFi name or password
3. Frame broadcasts a WiFi hotspot: `WanderWall-<framename>` with a unique 8-character password derived from the Pi's serial number
4. Any URL resolves to `http://192.168.4.1` (DNS hijack via dnsmasq)
5. **Outage-triggered setup mode leaves by itself:** every 15 minutes the hotspot stops for up to 90 s while the frame tries to rejoin home WiFi (the watchdog re-enables NetworkManager autoconnect first). If it connects, the slideshow resumes without a reboot, the clock is re-synced and a photo sync runs right away (clearing the sync error from the outage); otherwise the hotspot comes back. First-run and manual setup mode wait for the setup page.

### Reconfiguring WiFi via hotspot

1. On your phone or laptop, connect to `WanderWall-<framename>` (password shown on console)
2. A captive portal should open automatically — or open a browser to `http://192.168.4.1`
3. Enter your home WiFi SSID and password
4. Frame reboots and reconnects; gallery resumes

### First-run setup (new frame, two steps)

**Step 1 — Portal:** Enter frame name + home WiFi credentials. Success page shows Step 2 instructions.

**Step 2 — Dashboard:** Rejoin your home WiFi, open `http://<framename>.local:8000` in a browser. A Koofr setup banner appears — enter your Koofr email and password. The frame validates credentials and starts syncing photos.

### Reconfiguring WiFi via SSH / `wanderwall-config`

If you can reach the frame over Tailscale or Ethernet:

```bash
# Update WiFi credentials (creates a NetworkManager connection profile)
sudo wanderwall-config --wifi-ssid "MyNetwork" --wifi-password "mysecret"
sudo reboot

# Show current frame state
sudo wanderwall-config --show

# Other commands
sudo wanderwall-config --frame-name "kframe"
sudo wanderwall-config --koofr-user "user@example.com" --koofr-pass "secret"
sudo wanderwall-config --force-setup     # trigger setup mode on next reboot
sudo wanderwall-config --clear-setup     # cancel a pending setup mode
```

### Checking watchdog and AP service logs

```bash
# Watchdog (WiFi monitor)
sudo journalctl -u wanderwall-watchdog -f

# AP setup service (hostapd + portal)
sudo journalctl -u wanderwall-ap-setup -f

# Current state
sudo cat /var/lib/wanderwall/state.yaml
```

---

## Claude Setup Prompt Sequence

When setting up a new Pi, Claude should follow this sequence:

1. **Ask**: "Is this a fresh Pi or updating an existing one?"
2. **Step 1**: "Have you flashed Raspberry Pi OS and can SSH in?"
3. **Step 2**: "Run system updates. Confirm Python 3.11+?"
4. **Steps 3–9**: "Before running the installer, have you generated a Tailscale pre-auth key and a Koofr app password? Run the installer and confirm it completes with the summary banner."
5. **Step 10**: "Run verification checks. All passing?"

## Troubleshooting

### SSH Connection Issues

```bash
# Check SSH service
sudo systemctl status ssh

# Check firewall
sudo ufw status
```

### Tailscale Funnel Not Working

1. Verify Funnel is enabled in [Tailscale admin console](https://login.tailscale.com/admin/acls)
2. Check Funnel status: `tailscale funnel status`
3. Verify API is running on port 8000

### Pi3D Not Displaying

1. Check service: `systemctl --user status picframe.service`
2. Check logs: `journalctl --user -u picframe.service -f`
3. Verify display: `echo $DISPLAY`

### WiFi Hotspot Not Appearing

1. Check watchdog entered setup mode: `sudo journalctl -u wanderwall-watchdog -n 20`
2. Check AP service started: `sudo systemctl status wanderwall-ap-setup`
3. Check hostapd is running: `sudo iw dev wlan0 info` — should show `type AP`
4. If `type managed` instead, NetworkManager reclaimed the interface — check AP service logs: `sudo journalctl -u wanderwall-ap-setup -n 30`

### Frame Won't Reconnect After Portal Submit

1. Check `needs_setup` was cleared: `sudo cat /var/lib/wanderwall/state.yaml`
2. Verify NM connection was created: `nmcli con show wanderwall-wifi`
3. If connection missing, reconfigure manually: `sudo wanderwall-config --wifi-ssid "..." --wifi-password "..."`

### API Won't Start

1. Check if port 8000 is in use: `lsof -i :8000`
2. Check Python path: `which python3`
3. Verify venv is activated: `source ~/wanderwall_frame/venv/bin/activate`

## Test Pi Environment

For reference, the test Pi used during development:

| Property | Value |
|----------|-------|
| IP | 192.168.102.210 |
| Hostname | tkframe.local |
| Username | pi |
| Funnel URL | https://tkframe.whale-ayu.ts.net |
