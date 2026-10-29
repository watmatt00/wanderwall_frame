# WanderWall Ecosystem - Comprehensive Test Plan

## 1. Overview & How to Use This Plan

### Purpose

This document is the master test plan for the WanderWall ecosystem covering:
- **Raspberry Pi Backend** (`wanderwall_frame`) - FastAPI, web dashboard, services
- **iOS apps** (`wanderwall_app`) - WanderWall – Photo Frame (Manager) and WanderWall Share (Contributor), SwiftUI

It validates every screen, every displayed data element, every configurable setting, and the interactions between the web dashboard and the iOS app.

### Test Run Workflow

This document is a **master template**. For each test run:

1. **Copy the template:**
   ```bash
   cp docs/TEST_PLAN.md docs/test_runs/run_$(date +%Y-%m-%d).md
   ```

2. **If testing a different Pi**, find-and-replace `192.168.102.210:8000` with your frame's IP:port.

3. **Fill in the run header** at the top of the copy:
   ```
   Run Date: 2026-02-15
   Tester: Matt
   Pi Target: tkframe (192.168.102.210:8000)
   App Build: TestFlight 1.0 (458), iPhone 15, iOS 26.x
   Notes: RB-10 release check (3.28)
   ```

4. **Execute tests** - Check boxes as you go:
   - `[x]` = Pass
   - `[-]` = Skip (note reason)
   - Leave unchecked = Not yet tested

5. **Annotate failures** inline:
   ```
   - [ ] Test description <!-- FAIL: what happened vs what was expected -->
   ```

6. **Diff between runs** to track regression:
   ```bash
   diff docs/test_runs/run_2026-02-15.md docs/test_runs/run_2026-02-20.md
   ```

### Failure Annotation Convention

Use HTML comments for machine-parseable failure notes:
```
<!-- FAIL: Expected 200, got 500. Service was not running. -->
```

These are invisible in rendered markdown but searchable with `grep "FAIL:"`.

---

## 2. Environment Setup

### Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| Raspberry Pi 4/5 | Yes | Running wanderwall_frame backend |
| Tailscale | Yes | Funnel enabled on Pi |
| Mac with Xcode | Yes | For iOS simulator builds (or a CodeMagic IPA on a phone) |
| iPhone Simulator | Yes | iPhone 14 Pro recommended |
| Koofr account | Yes | With email + password (not OAuth) |
| Sample photos | Yes | 5-10 JPG files for upload testing |
| curl / httpie | Yes | For API validation section |
| Web browser | Yes | For dashboard testing (Safari/Chrome) |

### Test Environment (tkframe)

All commands in this plan use hardcoded values for tkframe. If testing a different frame, find-and-replace `192.168.102.210:8000` with your frame's IP:port in your test run copy.

| Setting | Value |
|---------|-------|
| Pi LAN IP | `192.168.102.210` |
| API Port | `8000` |
| Dashboard | `http://192.168.102.210:8000` |
| Funnel URL | `https://tkframe.whale-ayu.ts.net` |
| Koofr Email | `koofr.obtain355@passmail.net` |

### How to Reset to Clean State

**Pi backend:**
```bash
# Stop services
systemctl --user stop wanderwall-api picframe

# Clear paired devices
rm ~/.wanderwall/devices.json

# Reset config to defaults
# (backup first, then edit ~/.wanderwall/config.yaml)

# Restart
systemctl --user start wanderwall-api picframe
```

**iOS app (Simulator):**
- Device > Erase All Content and Settings, or
- Delete and reinstall the app from Xcode

### Test Data Requirements

- 5-10 sample JPG photos (various sizes, 1-5 MB each)
- At least 2 different Koofr folders with photos for source switching
- At least one photo source with known photo count for sync verification

---

## 3. Component Tests

Section numbers are stable (test runs refer to them). Screens are named as in the screen maps: dashboard `DASH-*` (`docs/SCREEN_MAP.md`), iOS `MM1`/`SD3`/... (`wanderwall_app/docs/SCREEN_MAP.md`).

---

### 3.1 Health & Connectivity

**Endpoints:** `GET /health`, `GET /version`

- [ ] `GET http://192.168.102.210:8000/health` returns `{"status": "ok"}` with HTTP 200
- [ ] `GET http://192.168.102.210:8000/version` returns `{"version": "5.0.0", "api": "wanderwall"}` with HTTP 200
- [ ] Dashboard loads at `http://192.168.102.210:8000/` without authentication
- [ ] From outside the LAN/tailnet (Funnel URL): `/health` 200, `/api/v1/status` 401 without a token, `/` 403 (blocked page)
- [ ] **Negative:** Request to unreachable IP times out gracefully (no crash)
- [ ] **Negative:** Request to wrong port returns connection refused

> **Automation candidate:** curl health/version checks are trivially scriptable.

---

### 3.2 Pairing

**Endpoints:** `POST /pairing/generate` (dashboard), `POST /api/v1/pairing/generate`, `POST /api/v1/pair`

#### Dashboard: Generate Pairing Code (Settings Tab)

- [ ] Navigate to `http://192.168.102.210:8000/` → Settings tab → Mobile App Pairing card → Show
- [ ] Click "Generate Pairing QR Code" button
- [ ] QR code image is displayed and non-empty
- [ ] Manual code is displayed in `ABC-XYZ` format (6 alphanumeric characters)
- [ ] Expiry countdown is shown (starts at ~5 minutes)
- [ ] Tailscale IP and Frame URL are displayed below the QR code
- [ ] Pairing instructions are visible
- [ ] "Regenerate Code" button generates a new code
- [ ] Pairing result auto-hides when countdown expires

#### iOS: Pair a Frame (PR3)

- [ ] Fresh install → Welcome screen (WL1) with "Pair a Frame", "How pairing works", "About"
- [ ] Tap "Pair a Frame" → PairingView opens
- [ ] **Scan QR Code** opens the camera scanner; scanning the dashboard QR fills Frame URL and code
- [ ] Or enter Frame URL (placeholder `https://your-frame-address`), Pairing Code and This Device's Name
- [ ] Pair button is disabled until the fields are filled
- [ ] On success: Main Menu (MM1) shows the frame; cloud credentials and albums load automatically
- [ ] JWT token is stored in iOS Keychain (verify via frame operations working)

#### Negative Cases

- [ ] Wrong pairing code → error message displayed, frame not added
- [ ] Expired code (wait >5 min) → error message displayed
- [ ] 3 wrong tries use up a code
- [ ] Rate limit: generate 3 codes within an hour, 4th attempt returns 429
- [ ] An invite code entered in the Manager app → 403 "This is an invite code. Use the WanderWall Share app to pair with it."

> **Automation candidate:** Full API-level pairing flow scriptable via curl.

---

### 3.3 Dashboard - Frame Status Tab (DASH-STATUS)

**URL:** `http://192.168.102.210:8000/`
**API:** `GET /dashboard/status`

#### Status Display

- [ ] Traffic light indicator is visible (circle/dot)
- [ ] Traffic light is GREEN when sync status = "match" and counts match
- [ ] Traffic light is AMBER when local and remote counts differ
- [ ] Traffic light is RED when sync error has occurred
- [ ] Traffic light is BLUE (animated) when sync is in progress
- [ ] Cloud photo count is displayed and matches remote count
- [ ] Frame (local) photo count is displayed and matches local count
- [ ] Current album name is shown
- [ ] Current image thumbnail is displayed (from Pi3D)

#### Service Health

- [ ] WanderWall Display service status shown (running/stopped)
- [ ] WanderWall API service status shown (running/stopped)

#### Storage

- [ ] Storage usage shown in GB (e.g., "12.5 GB / 64.0 GB")
- [ ] Storage percentage displayed (e.g., "19.5%")

#### Quick Actions

- [ ] "Sync Now" button triggers sync → traffic light goes BLUE
- [ ] After sync completes, traffic light returns to appropriate color
- [ ] "Restart Display" button restarts picframe service (slideshow only; the Pi stays on)
- [ ] "Restart API" button restarts wanderwall-api service (page may briefly disconnect)
- [ ] "Reboot Frame" → confirm → frame reboots and the dashboard is back in about 1-2 minutes (on an install without the reboot rule: a message to re-run `install_setup.sh`)
- [ ] "Refresh" button updates all displayed data

#### Banners (PL-147)

- [ ] Demo mode on → amber banner on every tab
- [ ] SD card last used on another Pi → banner asks once: keep this frame's albums (moved) or copied (new frame)
- [ ] This frame taken over by another Pi → banner with Undo

#### Advanced Mode

- [ ] Advanced toggle reveals technical details (Source ID, Frame ID)

---

### 3.4 Dashboard - Settings Tab (DASH-SETTINGS)

**URL:** `http://192.168.102.210:8000/` → Settings tab
**API:** `POST /api/settings`, `POST /api/settings/log-level`, `POST /api/settings/sleep-schedule`

- [ ] Frame ID displayed (read-only, grayed out)
- [ ] Frame Name displayed and editable
- [ ] Funnel URL displayed (read-only, grayed out)
- [ ] Rotation Interval field shown with current value (seconds), accepts 5-3600
- [ ] Sync Interval field shown with current value
- [ ] Fade Time field (0.5-30 s)
- [ ] "Save Settings" button → success message displayed
- [ ] Reload page → saved values persist
- [ ] Changing rotation interval triggers frame display restart (message confirms)
- [ ] Network sub-card shows LAN IP and WiFi name
- [ ] Cloud Sync sub-card: Save & Verify checks the Koofr login live; Test Connection reports the result
- [ ] Display Sleep Schedule sub-card: set off/on times → Save Schedule → display goes off and on at those times
- [ ] Logs card: Log Level DEBUG/INFO/WARNING/ERROR + Save Level
- [ ] Updates card: DEV/MAIN badge, Check for Updates, schedule (Frequency, Day, Time) saves
- [ ] Party Mode: needs type-to-confirm; on → sync and WiFi watchdog stop; off → they resume

---

### 3.5 Dashboard - Device Management (Settings Tab)

**URL:** `http://192.168.102.210:8000/` → Settings tab → "Manage Devices" button
**API:** `GET /api/devices`, `POST /devices/{id}/revoke`

- [ ] Click "Manage Devices" button → Paired Devices card appears
- [ ] Device table lists all paired devices
- [ ] Each device shows: name, role (badge), paired date, last seen
- [ ] Device summary shows count and admin count
- [ ] "Revoke" button present for each device
- [ ] Revoke a device → confirm dialog → device removed from table (inline refresh)
- [ ] Success message shown after revoke
- [ ] After revoking, that device's JWT no longer works (app shows unauthorized)
- [ ] **Negative:** Cannot revoke the last admin device → revoke button disabled
- [ ] Click "Manage Devices" again → card hides (toggle behavior)

---

### 3.6 Dashboard - Pairing (Settings Tab)

_(Covered in section 3.2 above - Dashboard: Generate Pairing Code)_

---

### 3.7 Dashboard - Log Viewer (Settings Tab)

**URL:** `http://192.168.102.210:8000/` → Settings tab → Logs card → Show
**API:** `GET /api/logs`

- [ ] Show → log viewer expands
- [ ] Operations log displayed by default
- [ ] Toggle between "Operations Log" and "Security Log" via dropdown
- [ ] Line count selector works (50 / 100 / 500)
- [ ] Log entries display with timestamps in monospaced font
- [ ] Security log shows pairing attempts and auth events
- [ ] Operations log shows sync events and service actions
- [ ] "Refresh" button loads latest entries

---

### 3.8 iOS - Splash, Welcome & Main Menu

**Views:** `SplashView.swift`, `MainContentView.swift` (WL1), `MainMenuView.swift` (MM1)

#### Splash Screen

- [ ] App launches with splash animation
- [ ] Splash transitions to Welcome (no frame) or Main Menu automatically

#### Main Menu (MM1)

- [ ] Header shows "WanderWall" (and "Frame: <name>" with more than one frame)
- [ ] SetupCard ("Let's get you set up") until a cloud login is saved
- [ ] Cloud Storage card shows free / used / total
- [ ] "Your Frames" card shows up to 3 paired frames: name, online dot, album, sync status, counts
- [ ] Menu buttons: Upload Photos, Albums (subtitle = album showing), Share Upload Link (admin), About
- [ ] Toolbar: "+" → Frames list, gear → Settings
- [ ] Tapping Your Frames: one frame → Frame Detail; several → Frames list
- [ ] Revoked on the frame → RepairBanner with Re-pair / Remove

---

### 3.9 iOS - Frame List & Pairing (FL2)

**Views:** `FrameListView.swift`, `PairingView.swift`

#### Frame List

- [ ] Empty state "No Frames Paired" with "Pair a Frame" button
- [ ] Paired frames listed with: name, role badge, online/offline (no address; PL-162)
- [ ] "Needs re-pair" badge on a frame that no longer accepts this phone
- [ ] Online status is accurate (check the frame's `/health`, compare to displayed status)
- [ ] Swipe left on frame → "Unpair" → confirm → frame removed from list
- [ ] Pull-to-refresh updates online status
- [ ] Toolbar "+" → PairingView
- [ ] Tapping a frame opens Frame Detail (full screen)

#### Pairing Flow

_(Covered in section 3.2 above - iOS: Pair a Frame)_

---

### 3.10 iOS - Frame Detail View (FD3)

**View:** `FrameDetailView.swift`

#### Header and Status Card

- [ ] Frame icon, online/offline indicator matches actual state
- [ ] Role badge shows "Admin" or "Contributor"; no address shown (PL-162)
- [ ] Status card: album showing, sync badge, photos on frame / in cloud
- [ ] Frame storage (free of total, used) is human-readable

#### Services Section (Admin only)

- [ ] Lists the frame's services with running/stopped dots
- [ ] Tap Restart → confirmation → service restarts → status updates

#### Paired Devices (Admin only)

- [ ] "N devices paired" → Paired Devices sheet (DV4): name, role, "This device", paired date, last seen
- [ ] Swipe → Revoke Access → confirm (not this device)

#### Connection (Admin only)

- [ ] Home WiFi light: green when the frame is on the LAN, with the WiFi name
- [ ] Remote access light: green when the frame answers on its Funnel URL from the internet; no light when no Funnel URL
- [ ] Local Dashboard link opens `http://<lan>:8000` in Safari (works on the home WiFi)

#### Navigation

- [ ] Frame Settings → Manage Frame (MF3); contributors see "Admin only"
- [ ] Refresh button in toolbar updates all data

---

### 3.11 iOS - Albums (SW2, SD3, AS3, MP3)

**Views:** `DestinationsView.swift` (SwitchPhotosView, AddSourceView, SourceDetailView), `ManagePhotosView.swift`

#### Currently Displaying (SW2)

- [ ] Album showing, sync status badge, on frame / in cloud counts, last sync
- [ ] "Sync Now" (admin) → sync triggers → status updates
- [ ] "Manage Photos" → MP3 (disabled without a cloud folder)

#### Album List

- [ ] All albums listed: name, Active badge, photo count
- [ ] Tapping an album opens Album Detail (SD3)
- [ ] Pull-to-refresh reloads the list

#### Album Detail (SD3)

- [ ] Album Info: Name, Status, Photos on Frame; admin: Technical details (frame folder, cloud folder); no "Stored on frame as" row
- [ ] Sync Status: cloud files, local files, status
- [ ] Actions in order: Show on Frame (if not showing), Upload Photos (if it has a cloud folder), Rename Album, Sync Now (if showing), Share Upload Link
- [ ] Show on Frame → album becomes active, sync starts, SW2 updates
- [ ] Rename Album → new name shown in the app and dashboard; folders unchanged
- [ ] Upload Photos → UP2 with this album preselected; after upload the album syncs (PL-144)
- [ ] Delete Album (red, own section) → confirm → album gone, its photos removed from the frame, cloud folder kept (PL-147)
- [ ] Delete Album is disabled for the album showing, with the explanation line

#### New Album (AS3, admin only)

- [ ] "+" in the toolbar (or "Add Album" when there are none) → New Album
- [ ] Enter Album Name → "Create Album" → album appears in the list
- [ ] Backend auto-configures the cloud folder `KFR_{id}`, or `KFR_{id}_2`… if that folder already exists in the cloud (PL-165)
- [ ] **Negative:** Empty name → button disabled

#### Manage Photos (MP3)

- [ ] Lists the album's photos on the frame with thumbnails; list/grid toggle; sort Newest/Oldest; search
- [ ] Select one → Rename → new name on the frame and in the cloud
- [ ] Select one → Preview → photo shows on the frame for N seconds with a countdown; Stop ends it
- [ ] Select several → Delete (N) → confirm → removed from the cloud and the frame
- [ ] "+" → UP2 for this album; list reloads when it closes (PL-145)

---

### 3.12 iOS - Upload Photos (UP2)

**View:** `UploadSheetView.swift`

#### Album Picker

- [ ] "Album" header; segmented control for 2 or fewer albums, menu above (PL-146)
- [ ] Opened from MM1: the album showing is preselected; from SD3/MP3: that album
- [ ] "Uploading to: <frame>" with more than one frame
- [ ] Not connected / no albums states explained

#### Photo Selection

- [ ] "Select Photos" opens the iOS photo library
- [ ] Selected photos show as a thumbnail grid, with count and "Clear"
- [ ] Photo info → Photo Details (PD3)

#### Upload Flow

- [ ] "Upload" sends the photos to the album's cloud folder
- [ ] Progress shows "Uploading N of M"; slow-connection hint on a slow network
- [ ] A photo already in the album is skipped
- [ ] Cloud quota refreshes after upload
- [ ] **Negative:** No cloud credentials → appropriate message
- [ ] **Negative:** Upload failure (network issue) → error message, no crash
- [ ] **Negative:** 0 photos selected → upload button disabled

> **Automation candidate:** Koofr upload via API is scriptable for quota/file verification.

---

### 3.13 iOS - Settings (ST2, MF3, AP3)

**Views:** `SettingsView.swift` (ST2, AppSettingsView AP3), `FrameSettingsView.swift` (MF3), `UpdateScheduleView.swift` (US4), `ChangeCredentialsView.swift` (CR4)

#### Settings hub (ST2)

- [ ] Two cards: Frame → Manage Frame, App → App Settings; Frame disabled with no frame paired

#### Manage Frame (MF3, admin)

- [ ] Frame Identity: change Frame Name → Save → "Rename Frame?" → name updates on the dashboard
- [ ] Display Settings: rotation interval slider (5 sec-10 min) → Save → display restarts
- [ ] Sync Settings: sync interval slider (1-60 min) → Save (sent as seconds); Sync Now
- [ ] Frame Actions: Restart <service>; Reboot Frame → confirm → back in about 1-2 minutes; View Logs → LG3
- [ ] Frame Software: Version, Check Now, Apply Update Now (when available), Update Schedule (US4: toggles, frequency, day, time, Save)
- [ ] Contributors: Invite to App → IN2
- [ ] Danger Zone: Unpair This Frame → confirm
- [ ] Contributor role: "Admin Only" message instead

#### App Settings (AP3)

- [ ] Account: Connected Account (email), Cloud Storage "Connected", Frame Network with the helper line (PL-148)
- [ ] Test Connections → results per row; an unreachable frame shows "Unreachable"
- [ ] Storage: cloud quota (used, %, free)
- [ ] WanderWall: version; App Cache: size, Clear Cache
- [ ] Change Credentials → Credentials screen (CR4): email, app password, Save & Test Connection
- [ ] Unpair All Frames → confirm → all frames removed
- [ ] Clear All Data → confirm → frames and credentials wiped

---

### 3.14 iOS - Frame Logs (LG3)

**View:** `LogViewerView.swift` (title "Frame Logs")
**API:** `GET /api/v1/logs?lines={n}&log_type={type}`

- [ ] Opened from Manage Frame → View Logs
- [ ] Segmented picker: "Operations" / "Security"; defaults to Operations
- [ ] Log entries displayed in a scrollable list, monospaced
- [ ] Color-coded dots: ERROR=red, WARNING=orange, INFO=blue, other=gray
- [ ] Refresh reloads entries; switching log type reloads
- [ ] Empty state "No log entries"

---

### 3.15 iOS - File Browser

_Removed: `FileBrowserView.swift` no longer exists. Photo management is Manage Photos (3.11)._

---

### 3.16 iOS - About View (AB2)

**View:** `AboutView.swift`

- [ ] App name, about text and How It Works shown
- [ ] The frame's current settings (photo change and sync intervals) with a Settings button → ST2
- [ ] Support line present
- [ ] No broken links or placeholder text

---

### 3.17 iOS - Setup View

_Removed: `SetupView.swift` no longer exists. Cloud credentials come from the frame after pairing, or from App Settings → Change Credentials (3.13)._

---

### 3.18 iOS - Add Destination View

_Removed: `AddDestinationView.swift` no longer exists. Albums are created on the frame (New Album, 3.11) and become upload destinations automatically._

---

### 3.19 Role-Based Access

**Model:** `FrameRole` in `PairedFrame.swift`

#### Admin Role (Manager app)

- [ ] All features accessible: restart, reboot, settings, device management, album create/rename/delete, sync, invites, upload links

#### Contributor Role (WanderWall Share app)

- [ ] Pairs only with an invite code (Manager app refuses invite codes, 3.2)
- [ ] `/api/v1/contributor/*` works; every admin route returns 403 "Admin access required"
- [ ] Can upload photos (3.26); can't change anything on the frame

---

### 3.20 Dashboard - Albums Tab (DASH-ALBUMS)

**URL:** Albums tab
**API:** `GET /api/sources`, `POST /api/sources/create`, `POST /api/sources/delete`, `POST /api/frame-live`

- [ ] Albums table lists every album with cloud and frame counts and status
- [ ] "Show technical columns" reveals ID, Local Path, Actions
- [ ] Activate → confirm → album shows on the frame and syncs
- [ ] Add Album: enter a Display Name → Add Album → appears in the table; cloud folder created (`KFR_<id>`)
- [ ] Add an album whose name matches an existing cloud folder (e.g. one deleted earlier, or another frame's `kframe`) → it gets `KFR_<id>_2`, not the existing folder (PL-165)
- [ ] With cloud storage unreachable, a new album is created without a cloud folder (no error); after the cloud is back, Test Connection fills it in
- [ ] Delete → confirm (states the photo count, cloud folder kept) → album gone, `~/Pictures/<id>` removed, cloud folder still there (PL-147)
- [ ] Delete is not offered for the album that's showing; via API it returns 409
- [ ] Deleting an album while it syncs → 409

---

### 3.21 Dashboard - Tools Tab (DASH-TOOLS)

- [ ] Album selector lists the albums; switching tabs and back keeps the choice
- [ ] Delete an album on the Albums tab, open Tools without reloading → it's gone from the selector
- [ ] Filename Cleaner, Duplicate Finder, Video File Manager, Rename File: scan, review, apply; changes reach the cloud folder first, then the frame
- [ ] Corrupt Photo Finder (PL-127): put an empty `.jpg` and a half-copied JPEG in the album's cloud folder, sync → scan lists both with the problem → Delete → gone from the frame and the cloud
- [ ] Rotate Photos (PL-126): ⟳ on a photo → thumbnail turns, the frame shows it turned on its next pass, the cloud copy is turned too; a photo with an EXIF rotation shows a ↻ badge and Fix makes it upright with no badge
- [ ] Rotate a HEIC photo (needs pillow-heif on the frame)

---

### 3.22 Dashboard - Backups Tab: Photo Backups (DASH-BACKUPS, PL-164)

**API:** `/api/tools/backup/*`, `POST /api/albums/restore-backup`

- [ ] Backups tab exists; Tools has no Photo Backups or Recover Albums card
- [ ] Picker defaults to **Whole frame**; lists every backup with its full path (`/home/pi/Pictures/backups/...`), size, created
- [ ] Pick one album → only that album's backups (not a longer id's, e.g. `trip` vs `trip_2`)
- [ ] Create Backup on one album → `<id>_<ts>.tar.gz` appears
- [ ] Create Backup on Whole frame → confirm → one `frame_<name>_<ts>.tar.gz`; status shows the path and size
- [ ] With too little free space → refused with "Not enough free space…" (1 GB kept free), no partial file
- [ ] Download → the file saves to the computer
- [ ] Restore a whole-frame backup onto the frame as it is → every album "already there", nothing doubled
- [ ] Delete an album → Restore the whole-frame backup → the album comes back on its own cloud folder ("deleted album re-added"); the others already there
- [ ] Restore twice → second run adds nothing
- [ ] Restore one album's backup into an album that has its photos → "already there"; a different photo with the same name → saved as `name_1`
- [ ] A deleted album's backup shows "deleted" and restores into a new album (asks for a name)
- [ ] Delete a backup (album's or whole frame's) → confirm → gone
- [ ] Delete an album on the Albums tab, open Backups without reloading → picker and Recover list are current

---

### 3.23 Dashboard - Backups Tab: Recover Albums (PL-147)

**API:** `/api/albums/recoverable`, `recover-cloud`, `upload-archive`, `take-over`, `undo-takeover`, `frame-swap`

- [ ] Delete an album → Recover Albums lists it under "From cloud storage" with its photo count
- [ ] Recover → album re-added on its own cloud folder and synced; registry shows it active again
- [ ] Albums that belong to another frame on the shared account are never listed
- [ ] On a shared account, unclaimed `KFR_*` folders appear only after ticking "Show unclaimed folders" (with the warning)
- [ ] Upload a .zip of photos into an existing album → photos added and uploaded to its cloud folder; non-photos skipped
- [ ] Upload into a new album → album created
- [ ] Upload a downloaded whole-frame backup → every album restored (the album choice is ignored)
- [ ] File over 16 GB, or bigger than the free space → refused
- [ ] Cloud unreachable → the cloud part shows the error, the rest still works

---

### 3.24 Album Registry, Frame Swap and Take Over (PL-147)

- [ ] `~/.wanderwall/frame_albums.yaml` lists every album with status active/deleted
- [ ] Its copy appears in Koofr `.picframe/frames/<pi-serial>.yaml` after a change
- [ ] Reinstall on the same Pi with a fresh card: after Koofr setup the list comes back from the cloud and deleted albums are recoverable
- [ ] SD card moved to another Pi: dashboard asks once (moved/copied); "moved" keeps the albums and marks the old board replaced
- [ ] New Pi + fresh card: Recover Albums → Other frames → Take over (name typed if seen in the last 24 h); the old frame's albums become recoverable
- [ ] A mistaken take over: the running frame shows a banner with Undo; Undo clears it

---

### 3.24a WiFi Resilience (PL-171, PL-161)

- [ ] After `install_setup.sh`: `/etc/NetworkManager/conf.d/wanderwall-wifi-powersave.conf` has `wifi.powersave = 2`; `iw dev wlan0 get power_save` → `off`; `verify_install.sh` check 14 passes
- [ ] Block the frame on the router (or turn the AP off) for > 10 min: `needs_setup` is set, then `/var/log/...watchdog` shows "bouncing the radio and reconnecting" every 15 min
- [ ] Unblock during that window → WiFi comes back on the next attempt without a reboot; `needs_setup` cleared
- [ ] Keep it blocked > 60 min → one reboot, frame comes up in setup mode and returns to normal when WiFi is back

### 3.25 Status Connection Lights (5.0.0)

**API:** `GET /api/v1/status` → `network`

- [ ] `network.local_connected` true on WiFi/Ethernet; `wifi_ssid` names the network ("" when wired)
- [ ] `network.remote_access` true when the Funnel URL answers from the internet; false when Funnel is off; null with no Funnel URL
- [ ] The app's Connection lights (FD3) match

---

### 3.26 iOS - WanderWall Share (Contributor app)

**Views:** `ContributorHomeView.swift` (CO1, CH1, CS2, CA3), `PairingView.swift`

- [ ] Fresh install → Onboarding (CO1): "WanderWall Share", Pair with Frame
- [ ] Pair with an invite QR or code from the Manager app (IN2) → Home (CH1)
- [ ] Album picker ("Album"; segmented ≤2, menu above)
- [ ] Select Photos → Upload → "Uploading N of M"; photos reach the album's cloud folder
- [ ] Upload the same photo again → skipped ("Already in …")
- [ ] Photo over 50 MB → refused
- [ ] Settings (CS2): Unpair a frame, Pair Another Frame, Test Connection, Clear All Data, Version, About (CA3)
- [ ] Invite revoked/frame revoked this phone → RepairBanner

---

### 3.27 iOS - Invites and Upload Links (IN2, UL3)

- [ ] Manage Frame → Invite to App → New Invite → optional name → QR card (48 h)
- [ ] Pending, Claimed ("Claimed by …") and Expired sections; Clear All on Expired
- [ ] Row QR button shows the QR sheet; trash revokes a pending invite
- [ ] Share Upload Link (MM1 for the album showing, or SD3 for that album): Generate → link and password; Share Link opens the share sheet; Revoke Link → confirm → link stops working
- [ ] Album without a cloud folder → "This album has no cloud folder, so it can't accept uploads."

---

### 3.28 iOS - Release Check on a Physical iPhone (RB-10)

**When:** on the exact TestFlight build that will be submitted to App Review (built by CodeMagic from `main`, D-07). Run 3.2, 3.8–3.14, 3.16, 3.27 and 4.1 on the same build, then this section. Write the build number in the run header ("App Build: TestFlight 1.0 (458), iPhone 15, iOS 26.x").

#### Build and install

- [ ] TestFlight shows the build number that was uploaded, and it's tagged `v1.0.<build>` on `main`
- [ ] Installs as an update over the previous TestFlight build; paired frames and cloud credentials are still there
- [ ] Home-screen name is "WanderWall"; the icon has no black or transparent edges

#### Permission prompts (real phone only; the simulator doesn't show them)

- [ ] First frame contact on the home WiFi → Local Network prompt with "WanderWall connects to your picture frame on your home network to pair and manage it." Allow → pairing works (PL-012)
- [ ] Don't Allow on a fresh install → pairing with the LAN address fails with a clear message; the Funnel `https://` address still works
- [ ] Scan QR Code → Camera prompt with "Camera is used to scan the WanderWall pairing QR code". Allow → the dashboard QR scans (PL-136)
- [ ] Camera denied → the scanner explains it and manual entry still works
- [ ] Select Photos opens the photo picker with no permission prompt (the system picker needs none)

#### iOS 26 look (PL-153)

Walk every screen in `docs/SCREEN_MAP.md` in both light and dark mode:
- [ ] Toolbars and the Liquid Glass bars: no titles or buttons cut off or overlapping
- [ ] Sheets (Upload Photos, Share Upload Link, Invite to App, Paired Devices) open, scroll and close
- [ ] Segmented pickers (album picker, log type) readable
- [ ] Alerts and confirmations show their message and both buttons (PL-130)
- [ ] Largest Dynamic Type size (Settings → Accessibility → Display & Text Size → Larger Text): Main Menu and Album Detail still usable

#### What App Review will do (demo frame tkframe, from cellular with WiFi off)

- [ ] Pair with the Manager demo code from the review notes (RB-18), manual entry, using the Funnel URL
- [ ] Pair by scanning the review-notes QR image (RB-25)
- [ ] Upload Photos, Albums (create one, Show on Frame), Manage Photos, Share Upload Link, Manage Frame (rename, rotation, restart) all work on cellular
- [ ] Software Update on the demo frame shows the locked message, not an update (PL-150)
- [ ] Opening the Funnel URL in Safari shows the short WanderWall page, not raw JSON (PL-128)
- [ ] Every album on the demo frame has photos; no "Finish Setup" image on the frame (PL-063)

#### App Store rules

- [ ] About has working Support (`https://picframe.txphipps.com/support/`) and Privacy Policy (`https://picframe.txphipps.com/privacy/`) links (PL-115, guideline 5.1.1(i))
- [ ] No "PicFrame", "Koofr", "beta" or "test" anywhere the user can see (PL-160, PL-100)
- [ ] No placeholder text, no empty screens, no dead buttons
- [ ] Settings → Clear All Data → back to Welcome with nothing paired (account-deletion rule 5.1.1(v), review notes)
- [ ] Rotate the phone: the app stays usable (or stays portrait)
- [ ] Turn on Airplane mode mid-upload → an error message, no crash; turn it off and the frame comes back

#### Multiple frames (PL-176, PL-023)

- [ ] Pair two frames → both listed; switch between them; each shows its own albums and status
- [ ] Install WanderWall Share too → the Manager still has both frames

---

## 4. End-to-End Scenarios

---

### 4.1 First-Time Setup

**Goal:** Validate the complete onboarding flow from scratch.

- [ ] Start with clean iOS app (no stored data)
- [ ] Generate pairing code on dashboard (Settings tab → "Generate Pairing QR Code")
- [ ] In app: Welcome → Pair a Frame → scan the QR (or enter Frame URL, code, device name) → pair successfully
- [ ] Frame appears in app with online status
- [ ] Cloud credentials arrive from the frame automatically (or set them in App Settings → Change Credentials)
- [ ] Test Koofr connection → success
- [ ] Upload 3-5 sample photos via Upload screen
- [ ] Verify photos appear in Koofr (Koofr web)
- [ ] Trigger sync from app or wait for auto-sync
- [ ] Verify photo count on frame matches uploaded count
- [ ] Dashboard shows matching counts and GREEN traffic light

---

### 4.2 Daily Photo Management

**Goal:** Validate the typical photo upload workflow.

- [ ] Open app → main menu shows current frame status
- [ ] Tap "Upload Photos" → choose the album → select 5 photos
- [ ] Upload completes with progress indicator → success message
- [ ] Koofr quota updates (used space increases)
- [ ] Trigger sync (or wait for scheduled sync)
- [ ] Frame local count increases to match cloud count
- [ ] Dashboard traffic light is GREEN after sync completes
- [ ] Photo is visible on the physical frame display (if testing on real Pi)

---

### 4.3 Album Management

**Goal:** Validate creating, filling, showing and deleting albums.

- [ ] In app: Albums → "+" → New Album "Test Album" → Create Album
- [ ] New album appears in list with 0 photos
- [ ] Album Detail → Upload Photos → upload 3 photos (album preselected; it syncs afterwards)
- [ ] Album Detail → Show on Frame → frame switches, sync triggers automatically
- [ ] "Currently Displaying" updates to the new album; counts match
- [ ] Previous album is no longer marked as active
- [ ] Show the previous album again, then Delete "Test Album" → its photos leave the frame, cloud folder kept
- [ ] Dashboard → Backups → Recover Albums → Recover "Test Album" → it comes back with its photos

---

### 4.4 Dashboard <-> App Consistency

**Goal:** Validate that changes made in one interface are reflected in the other.

- [ ] **Dashboard → App:** Activate an album on the dashboard → refresh app → app shows it
- [ ] **Dashboard → App:** Delete an album on the dashboard → it's gone from the app's Albums list
- [ ] **App → Dashboard:** Change sync interval in Manage Frame (e.g., 5 min) → reload dashboard Settings tab → shows new value
- [ ] **App → Dashboard:** Rename an album in the app → dashboard Albums tab shows the new name
- [ ] **App → Dashboard:** Restart a service from app → dashboard shows service restarting/recovering
- [ ] **App → Dashboard:** Upload photos in app → trigger sync → dashboard counts update
- [ ] **Dashboard → App:** Revoke a device on dashboard (Settings tab → Manage Devices) → app for that device gets unauthorized errors

---

### 4.5 Admin Maintenance

**Goal:** Validate administrative operations.

- [ ] Open Manage Frame → "View Logs" → operations log loads
- [ ] Switch to security log → security events displayed
- [ ] Restart WanderWall Display service from app → service recovers
- [ ] Restart WanderWall API service from app → brief disconnect, then reconnects
- [ ] Check sync status after restart → services resume normally
- [ ] Trigger manual sync → verify it completes and counts match
- [ ] Reboot Frame from Manage Frame → frame is back in about 1-2 minutes and the app reconnects
- [ ] Check Now in Frame Software → shows whether an update is available

---

### 4.6 Device Management

**Goal:** Validate multi-device pairing and revocation.

- [ ] Pair a second device (or simulate with different device name)
- [ ] Dashboard Settings tab → Manage Devices shows both devices
- [ ] App Frame Detail shows paired device count = 2
- [ ] Revoke second device from app → device removed
- [ ] Dashboard Manage Devices table updates to show only 1 device
- [ ] **Negative:** Attempt to revoke last admin → error: "Cannot revoke the last admin device. Add another admin first."

---

### 4.7 Error Recovery

**Goal:** Validate graceful handling of error conditions.

- [ ] Stop the Pi API service → app shows frame as offline (red dot)
- [ ] Restart the API service → app detects frame is back online (green dot)
- [ ] Enter wrong Koofr credentials → "Test Connection" fails with auth error
- [ ] Fix credentials → "Test Connection" succeeds
- [ ] Attempt upload with bad credentials → error message, no crash
- [ ] Fix credentials → retry upload → succeeds
- [ ] Trigger source activation during an active sync → verify behavior (should queue or reject gracefully)
- [ ] **Negative:** Open app with Pi completely offline → frame shows offline, no crash, graceful error messages

---

### 4.8 Backup, Replace and Migrate (PL-147, PL-164)

**Goal:** Validate that a frame's albums survive a reinstall or a new frame.

- [ ] Dashboard → Backups → Whole frame → Create Backup → Download the file to a computer
- [ ] Restore it straight away → everything "already there"
- [ ] Delete two albums → Restore the whole-frame file → both come back on their own cloud folders
- [ ] On another frame (or after a fresh install) on the **same** cloud account: Recover Albums → Take over the old frame → recover its albums from the cloud
- [ ] On a frame on a **different** cloud account: Recover Albums → Upload the downloaded file → every album recreated with its photos, on new cloud folders
- [ ] Next sync keeps every restored photo

---

## 5. API Validation (curl commands)

### Before You Start: Get Your JWT Token

Most curl commands below require a JWT token. Set it once in your terminal session:

**Option A** — Pair via the dashboard's pairing endpoint (no token needed on the LAN; uses one of the 3 codes an hour):
```bash
CODE=$(curl -s -X POST http://192.168.102.210:8000/pairing/generate | python3 -c "import json,sys; print(json.load(sys.stdin)['code'])")
TOKEN=$(curl -s -X POST http://192.168.102.210:8000/api/v1/pair -H "Content-Type: application/json" \
  -d "{\"code\":\"$CODE\",\"device_name\":\"curl-test\",\"requested_role\":\"admin\"}" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
```
This adds a "curl-test" device; revoke it on the dashboard when you're done. (The frame doesn't store tokens, so there's no token to copy from the Pi.)

**Option B** — Paste a token you already have:
```bash
TOKEN=eyJhbG...paste_your_token_here...
```

Verify it works:
```bash
curl -s http://192.168.102.210:8000/api/v1/status -H "Authorization: Bearer $TOKEN" | head -c 100
```

`$TOKEN` is the **only variable** in this section. All other values are hardcoded.

### Health & Version

```bash
# 5.1 Health check
curl -s http://192.168.102.210:8000/health
# Expected: {"status":"ok"}

# 5.2 Version
curl -s http://192.168.102.210:8000/version
# Expected: {"version":"5.0.0","api":"wanderwall"}
```

- [ ] 5.1 Health returns `{"status": "ok"}` with HTTP 200
- [ ] 5.2 Version returns `{"version": "5.0.0", "api": "wanderwall"}` with HTTP 200

### Pairing Flow

```bash
# 5.3 Generate pairing code (requires existing admin token)
curl -s -X POST http://192.168.102.210:8000/api/v1/pairing/generate \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"qr_code_base64":"...","code":"ABC-XYZ","expires_at":"..."}

# 5.4 Exchange code for token
curl -s -X POST http://192.168.102.210:8000/api/v1/pair \
  -H "Content-Type: application/json" \
  -d '{"code":"ABC-XYZ","device_name":"curl-test"}'
# Expected: {"token":"...","frame_id":"...","frame_name":"...","role":"admin","api_port":8000}
```

- [ ] 5.3 Pairing code generation returns code in ABC-XYZ format
- [ ] 5.4 Pairing exchange returns valid JWT token

### Status

```bash
# 5.5 Frame status
curl -s http://192.168.102.210:8000/api/v1/status \
  -H "Authorization: Bearer $TOKEN"
```

- [ ] 5.5 Status returns frame_id, frame_name, current_source, photo_count, services array, sync object, capacity object
- [ ] 5.5 Services array contains picframe and wanderwall-api entries
- [ ] 5.5 Capacity includes total_bytes, used_bytes, free_bytes, percent_used

### Folder/Source Management

```bash
# 5.6 List folders
curl -s http://192.168.102.210:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"folders":[...],"current_source":"..."}

# 5.7 Create folder
curl -s -X POST http://192.168.102.210:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"curl_test_source"}'
# Expected: 201 with id, name, local_path, rclone_remote, enabled, photo_count

# 5.8 Switch display folder
curl -s -X POST http://192.168.102.210:8000/api/v1/display/folder \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id":"curl_test_source"}'
# Expected: {"success":true,"source_id":"...","source_name":"...","path":"...","message":"..."}
```

- [ ] 5.6 Folders list returns array with id, name, path, photo_count and current_source
- [ ] 5.7 Create folder returns 201 with auto-configured rclone remote
- [ ] 5.8 Switch folder returns success and triggers background sync

### Sync

```bash
# 5.9 Trigger sync all
curl -s -X POST http://192.168.102.210:8000/api/v1/folders/sync/all \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"message":"...","sources_queued":[...]}

# 5.10 Get sync status for a source
curl -s http://192.168.102.210:8000/api/v1/folders/{source_id}/sync/status \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"is_syncing":...,"local_count":...,"remote_count":...,"sync_status":"..."}
```

- [ ] 5.9 Sync all returns sources_queued array
- [ ] 5.10 Sync status returns is_syncing, local_count, remote_count, sync_status

### Service Management

```bash
# 5.11 Restart picframe service
curl -s -X POST http://192.168.102.210:8000/api/v1/services/picframe/restart \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"service":"picframe","action":"restart","success":true,"message":"Service 'picframe' restarted successfully"}

# 5.12 Invalid service name
curl -s -X POST http://192.168.102.210:8000/api/v1/services/invalid_service/restart \
  -H "Authorization: Bearer $TOKEN"
# Expected: 400 with error
```

- [ ] 5.11 Restart returns success for valid service
- [ ] 5.12 Invalid service name returns 400 error

### Settings

```bash
# 5.13 Get settings
curl -s http://192.168.102.210:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"sync_interval":...,"rotation_interval":...,"frame_name":"..."}

# 5.14 Update sync interval
curl -s -X PUT http://192.168.102.210:8000/api/v1/settings/sync-interval \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval":600}'
# Expected: {"success":true,"message":"Sync interval updated to 600 seconds"}

# 5.15 Invalid sync interval (not one of 0, 300, 600, 900, 1800, 2700, 3600, 7200, 21600, 43200, 86400)
curl -s -X PUT http://192.168.102.210:8000/api/v1/settings/sync-interval \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval":10}'
# Expected: 422 validation error
```

- [ ] 5.13 Settings returns sync_interval, rotation_interval, frame_name
- [ ] 5.14 Update sync interval returns success
- [ ] 5.15 An interval outside the allowed list returns 422

### Device Management

```bash
# 5.16 List devices
curl -s http://192.168.102.210:8000/api/v1/devices \
  -H "Authorization: Bearer $TOKEN"
# Expected: array of devices with id, name, role, paired_at, last_seen

# 5.17 Revoke device (use a non-critical device ID)
curl -s -X DELETE http://192.168.102.210:8000/api/v1/devices/{device_id} \
  -H "Authorization: Bearer $TOKEN"
# Expected: 204, no body (400 if it is the last admin)
```

- [ ] 5.16 Device list returns array with expected fields
- [ ] 5.17 Device revocation succeeds (test with expendable device)

### Logs

```bash
# 5.18 Operations logs
curl -s "http://192.168.102.210:8000/api/v1/logs?lines=50&log_type=ops" \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"entries":[...],"log_type":"ops","count":...}

# 5.19 Security logs
curl -s "http://192.168.102.210:8000/api/v1/logs?lines=50&log_type=security" \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"entries":[...],"log_type":"security","count":...}
```

- [ ] 5.18 Operations logs return entries array with count
- [ ] 5.19 Security logs return entries array with count

### Cloud Credentials

```bash
# 5.20 Get cloud credentials
curl -s http://192.168.102.210:8000/api/v1/cloud/credentials \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"credentials":{"provider":"koofr","email":"...","password":"..."},"message":"..."}
```

- [ ] 5.20 Cloud credentials return provider, email, password

### Authentication Negative Cases

```bash
# 5.21 No token
curl -s http://192.168.102.210:8000/api/v1/status
# Expected: 401

# 5.22 Invalid token
curl -s http://192.168.102.210:8000/api/v1/status \
  -H "Authorization: Bearer invalid_token_here"
# Expected: 401
```

- [ ] 5.21 Missing token returns 401
- [ ] 5.22 Invalid token returns 401

### Services List

```bash
# 5.23 List services
curl -s http://192.168.102.210:8000/api/v1/services \
  -H "Authorization: Bearer $TOKEN"
# Expected: array of services with name, display_name, active, status, can_restart
```

- [ ] 5.23 Services list returns picframe and wanderwall-api with status fields

### Display Folder (GET)

```bash
# 5.24 Get current display folder
curl -s http://192.168.102.210:8000/api/v1/display/folder \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"source_id":"...","source_name":"...","path":"...","photo_count":...}
```

- [ ] 5.24 Display folder returns source_id, source_name, path, photo_count

### Direct Sync Trigger

```bash
# 5.25 Trigger sync (dashboard endpoint, no auth on LAN)
curl -s -X POST http://192.168.102.210:8000/sync
# Expected: {"status":"started","source":"..."}
```

- [ ] 5.25 Sync trigger returns started status with source name

### Dashboard-Specific APIs

```bash
# 5.26 Dashboard status (no auth, LAN only)
curl -s http://192.168.102.210:8000/dashboard/status
# Expected: JSON with sync_status, counts, services, storage

# 5.27 Current image proxy
curl -s -o /dev/null -w "%{http_code}" http://192.168.102.210:8000/current-image
# Expected: 200 with image data (or 404/502 if Pi3D not running)

# 5.28 Switch source (dashboard endpoint)
curl -s -X POST http://192.168.102.210:8000/switch-source \
  -d 'source_id=tkf1'
# Expected: success response

# 5.29 Save settings (dashboard endpoint)
curl -s -X POST http://192.168.102.210:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{"frame_name":"Test Frame","rotation_interval":30,"sync_interval":900,"fade_time":2.0}'
# Expected: success response
```

- [ ] 5.26 Dashboard status returns sync_status, local_count, remote_count, services, storage fields
- [ ] 5.27 Current image endpoint responds (200 with image or appropriate error if Pi3D offline)
- [ ] 5.28 Dashboard switch source changes active source
- [ ] 5.29 Dashboard settings save persists values

### Source Management (Dashboard)

```bash
# 5.30 List sources (dashboard)
curl -s http://192.168.102.210:8000/api/sources
# Expected: source list with id, name, local_path, rclone_remote, enabled

# 5.31 Create source (dashboard)
curl -s -X POST http://192.168.102.210:8000/api/sources/create \
  -H "Content-Type: application/json" \
  -d '{"name":"Dashboard Test","rclone_remote":"koofr:KFR_dashboard_test"}'
# Expected: created source object

# 5.32 Delete source (dashboard)
curl -s -X POST http://192.168.102.210:8000/api/sources/delete \
  -H "Content-Type: application/json" \
  -d '{"source_id":"dashboard_test"}'
# Expected: success response

# 5.33 Frame live - switch and sync (dashboard)
curl -s -X POST http://192.168.102.210:8000/api/frame-live \
  -H "Content-Type: application/json" \
  -d '{"source_id":"koofr_main"}'
# Expected: switches source and triggers sync
```

- [ ] 5.30 Sources list returns array with expected fields
- [ ] 5.31 Source creation returns new source with auto-configured rclone remote
- [ ] 5.32 Deletion removes the album **and its photos on the frame**, keeps the cloud folder; refused for the album showing (test with an expendable album)
- [ ] 5.33 Frame-live switches source and triggers sync

### rclone Integration (Dashboard)

```bash
# 5.34 List rclone remotes
curl -s http://192.168.102.210:8000/api/rclone/remotes
# Expected: list of configured rclone remotes

# 5.35 Browse rclone directories
curl -s -X POST http://192.168.102.210:8000/api/rclone/list-dirs \
  -H "Content-Type: application/json" \
  -d '{"remote":"koofr:","path":"/"}'
# Expected: directory listing

# 5.36 List local directories
curl -s http://192.168.102.210:8000/api/local/list-dirs
# Expected: list of directories in ~/Pictures

# 5.37 Test remote connection
curl -s -X POST http://192.168.102.210:8000/api/config/test-remote \
  -H "Content-Type: application/json" \
  -d '{"remote":"koofr:"}'
# Expected: connection test result
```

- [ ] 5.34 rclone remotes list returns configured remotes (at least koofr)
- [ ] 5.35 rclone directory browse returns folder listing
- [ ] 5.36 Local directories list returns ~/Pictures contents
- [ ] 5.37 Remote connection test returns success for valid remote

### Device Management (Dashboard)

```bash
# 5.38 List devices (dashboard, no auth)
curl -s http://192.168.102.210:8000/api/devices
# Expected: {"devices":[...],"admin_count":...,"device_count":...}

# 5.39a Revoke device via dashboard endpoint (no auth, LAN only)
curl -s -X POST http://192.168.102.210:8000/devices/{device_id}/revoke
# Expected: {"ok": true} or {"ok": false, "error": "..."}
```

- [ ] 5.38 Dashboard device list returns devices array with admin_count
- [ ] 5.39a Dashboard device revocation works (test with expendable device)

### Contributor Invites

```bash
# 5.40 List contributor invites
curl -s http://192.168.102.210:8000/api/v1/contributors \
  -H "Authorization: Bearer $TOKEN"
# Expected: array of {id, code, expires_at, claimed, claimed_at, claimed_by}

# 5.41 Create contributor invite
curl -s -X POST http://192.168.102.210:8000/api/v1/contributors/invite \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: {"id":"...","code":"...","qr_code_base64":"...","expires_at":"...","funnel_url":"...","claimed":false} (429 after 3 pending an hour)
```

- [ ] 5.40 Contributors list returns the invites array
- [ ] 5.41 Contributor invite returns a code and QR; revoke it afterwards with `DELETE /api/v1/contributors/{id}` (204)

### Albums: Delete and Cloud Folder Naming (PL-147, PL-165)

```bash
# 5.42 Delete an expendable album (not the one showing)
curl -s -X DELETE http://192.168.102.210:8000/api/v1/folders/curl_test_source \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"deleted":"curl_test_source","name":"...","photos_removed":N,"local_folder_removed":true,"cloud_folder":"koofr:KFR_curl_test_source","error":null}

# 5.43 Delete the album that is showing
curl -s -o /dev/null -w "%{http_code}" -X DELETE http://192.168.102.210:8000/api/v1/folders/<showing_id> \
  -H "Authorization: Bearer $TOKEN"
# Expected: 409

# 5.44 Create it again: the old cloud folder still exists, so it gets a new one
curl -s -X POST http://192.168.102.210:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"curl_test_source"}'
# Expected: 201, rclone_remote ends in KFR_curl_test_source_2
```

- [ ] 5.42 Delete returns 200 with `photos_removed`; `~/Pictures/curl_test_source` is gone, the cloud folder is not
- [ ] 5.43 Deleting the album showing returns 409
- [ ] 5.44 Re-creating the album uses `KFR_<id>_2`

### Backups and Recover (dashboard, PL-164)

```bash
# 5.45 Whole-frame backup
curl -s -X POST http://192.168.102.210:8000/api/tools/backup/all/create
# Expected: {"ok":true,"filename":"frame_<name>_<ts>.tar.gz","path":"/home/pi/Pictures/backups/...","size_bytes":N,"albums":N,"skipped":[]}

# 5.46 List every backup
curl -s http://192.168.102.210:8000/api/tools/backup/all
# Expected: {"ok":true,"backups":[{"filename":"frame_...","kind":"frame","album_count":N,"path":"..."}, ...]}

# 5.47 Download it
curl -s -o /tmp/frame_backup.tar.gz -w "%{http_code}" http://192.168.102.210:8000/api/tools/backup/download/<filename>
# Expected: 200; tar tzf /tmp/frame_backup.tar.gz | head -1 → manifest.yaml

# 5.48 Restore it onto the running frame
curl -s -X POST http://192.168.102.210:8000/api/albums/restore-backup \
  -H "Content-Type: application/json" -d '{"filename":"<filename>"}'
# Expected: {"ok":true,"kind":"frame","albums":[{"album":"...","action":"merged","restored":0,"already_there":N,...}],...}

# 5.49 Upload the downloaded file back (whole-frame archive restores every album)
curl -s -X POST "http://192.168.102.210:8000/api/albums/upload-archive?target_id=ignored" \
  --data-binary @/tmp/frame_backup.tar.gz
# Expected: same shape as 5.48, all already_there

# 5.50 Recoverable albums
curl -s http://192.168.102.210:8000/api/albums/recoverable
# Expected: {"ok":true,"cloud":[...],"unclaimed":[...],"unclaimed_needs_confirm":true,"frames":[...],"cloud_error":null,"backups":[...]}

# 5.51 Delete the test backup
curl -s -X POST http://192.168.102.210:8000/api/tools/backup/delete \
  -H "Content-Type: application/json" -d '{"filename":"<filename>"}'
# Expected: {"ok":true}
```

- [ ] 5.45 Whole-frame backup creates one file with a path under `~/Pictures/backups`
- [ ] 5.46 It lists as `kind: "frame"` with the album count
- [ ] 5.47 Download returns the file; its first member is `manifest.yaml`
- [ ] 5.48 Restore onto the running frame adds nothing (`already_there` only)
- [ ] 5.49 Uploading the file gives the same result
- [ ] 5.50 Recoverable lists this frame's deleted albums and no other frame's folders
- [ ] 5.51 Backup delete works; `../` names are refused

### Network Access (LAN-only routes)

```bash
# 5.52 From outside the LAN/tailnet (e.g. a phone on cellular, or resolve the Funnel host via 1.1.1.1)
curl -s -o /dev/null -w "%{http_code}" https://tkframe.whale-ayu.ts.net/api/tools/backup/all
# Expected: 403
```

- [ ] 5.52 Dashboard routes (`/api/tools/*`, `/api/albums/*`, `/`) return 403 from the internet; `/api/v1/*` needs a token

> **Automation candidate:** This entire section is scriptable as a pytest or bash test suite.

---

## 6. Automation Candidates Summary

| Section | Automatable | Priority | Tool |
|---------|-------------|----------|------|
| 3.1 Health & Connectivity | Fully | High | curl / pytest |
| 3.2 Pairing (API level) | Fully | High | pytest |
| 3.2 Pairing (iOS UI) | Partially | Medium | XCUITest |
| 3.3 Dashboard Status Tab | Partially | Medium | Selenium / Playwright |
| 3.4-3.7 Dashboard Settings Tab | Partially | Medium | Selenium / Playwright |
| 3.8-3.19, 3.26-3.27 iOS Views (both apps) | Partially | Medium | XCUITest |
| 3.20-3.24 Dashboard Albums, Tools, Backups, Recover | Partially (APIs fully, section 5) | High | pytest + Playwright |
| 3.25 Status network fields | Fully | Medium | pytest |
| 4.x End-to-End Scenarios | Partially | High | pytest + XCUITest |
| 5.x API Validation | Fully | High | pytest / bash script |

### Recommended Priority Order

1. **API Validation (Section 5)** - Highest ROI, fully scriptable, catches backend regressions
2. **Health & Connectivity (3.1)** - Quick smoke test, run on every deploy
3. **Pairing Flow (3.2 API)** - Critical path, automatable without UI
4. **End-to-End Scenarios (4.x)** - Combined API + manual UI verification
5. **Dashboard Tabs (3.3-3.7, 3.20-3.24)** - Browser automation if resources allow
6. **iOS UI Tests (3.8-3.19, 3.26-3.27)** - XCUITest for critical flows

### Suggested Tools

| Tool | Use Case |
|------|----------|
| **pytest** | API endpoint testing, pairing flow, sync verification |
| **requests** (Python) | HTTP client for API tests |
| **XCUITest** | iOS UI automation (pairing, upload, source switching) |
| **Playwright** | Dashboard browser testing |
| **bash/curl** | Quick smoke tests, CI health checks |
