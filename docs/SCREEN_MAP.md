# Screen Map — Web Dashboard

Screens of the frame's web dashboard (`http://<pi-ip>:8000`, LAN and tailnet only). The **iOS screens** (both apps) are mapped in `wanderwall_app/docs/SCREEN_MAP.md`, which owns the `MM1`/`SD3`/... IDs used below.

## How to Use Screen IDs

Use these stable IDs in test plans, bug reports, and development references:
- `DASH-xxx` - Web dashboard tabs
- iOS screens: see `wanderwall_app/docs/SCREEN_MAP.md`

**Last updated:** 2026-10-21

---

## Dashboard Screens

### DASH-STATUS - Frame Status (Tab 1)

- **Files:** `dashboard.html` + `dashboard.js`
- **Presentation:** Default active tab in unified dashboard
- **UI Elements:**

  **Banners (above the tabs, when they apply):**
  - Demo mode on (PL-015)
  - "This SD card was last used on another Pi": **Yes, keep this frame's albums** (moved) or copied (new frame) (PL-147)
  - This frame was taken over by another Pi: **Undo** (PL-147)

  **Status Banner (top of page, always visible):**
  - Sync status text (e.g., "Photo sync status", "Syncing photos...")
  - Status pill: OK / SYNCING / ERROR / UNKNOWN
  - Last checked timestamp
  - Frame name pill
  - Dynamic background color: green (ok), orange (syncing), red (error), gray (unknown)

  **Overall Status Card:**
  - Status title with sync details (e.g., "Out of sync (15 cloud / 12 local)")
  - Status severity chip
  - Traffic light indicator (green/amber/red, one lit at a time)
  - Count tiles: Cloud photo count, Frame photo count
  - Service grid:
    - Currently Showing: source name
    - Frame Display: status dot + text
    - Dashboard: always "RUNNING"
    - Storage: percent used with progress bar (e.g., "85% (42.5 / 50 GB)")
  - Current image thumbnail (auto-refreshes every 30s)
  - Collapsible advanced details: Source ID, Frame ID

  **Quick Actions Card:**
  - Refresh Dashboard button
  - Sync Now button (shows spinner, confirmation on success)
  - Restart Display button (confirmation dialog; restarts the slideshow only)
  - Restart API button (confirmation dialog, page reloads after 3s)
  - Reboot Frame button (confirmation dialog; back in about 1-2 minutes; needs `install_setup.sh` re-run on older installs, PL-142)
  - Last sync / last restart timestamps

- **Auto-Refresh:** Status every 15 seconds, thumbnail every 30 seconds
- **Footer:** "Auto-updates every 15 seconds"

---

### DASH-ALBUMS - Albums (Tab 2)

(Was DASH-SWITCH, "Switch Photos". The tab button's `data-tab` is still `sources`.)

- **Files:** `dashboard.html` + `dashboard.js`
- **Presentation:** Tab 2; reloads the album list each time it opens
- **UI Elements:**

  **☁️ Albums card:**
  - Columns: ID (tech), Name, Remote, Local Path (tech), Cloud (count), Local (count), Status, Actions (tech)
  - Tech columns toggleable via "▸ Show technical columns"
  - Status badges: Active (green), Ready (blue), Disabled (gray)
  - Action buttons (tech columns):
    - Activate (confirm dialog; shows the album and syncs it)
    - Delete (confirm dialog; deletes the album **and its photos on the frame**, keeps the cloud folder and backups; not offered for the album showing, PL-147)

  **➕ Add Album card:**
  - Display Name only ("Album ID, local folder, and cloud folder are auto-generated from this name"); the cloud folder is `KFR_<id>`, or `KFR_<id>_2`… if that name is taken (PL-165)
  - Add Album button; status message

---

### DASH-TOOLS - Tools (Tab 3)

- **Files:** `dashboard.html` + `dashboard.js`
- **Presentation:** Tab 3; the album picker reloads each time the tab opens
- **UI Elements:**

  **Album Selector** (shared by all tool cards):
  - Dropdown of the frame's albums; keeps the picked album if it still exists, otherwise the one showing

  **Card Header UX (all Tools cards):**
  - Clicking anywhere on the card header expands/collapses the card
  - Scan cards (Filename Cleaner, Duplicate Finder, Video Manager, Rename File): clicking the header triggers a scan directly when collapsed
  - Collapse button is always **✕ Close** (visible once results are shown)

  **Filename Cleaner Card:**
  - Click header to scan → results table: Preview | ☐ | Original Filename | Proposed Name | EXIF Date | Issues
  - Issues detected: Google ID tokens, numbered dup suffixes, spaces→underscores, long name (>20 chars → renamed to YYYYMMDD_HHMMSS), wrong/uppercase extension
  - Filter bar: All / per-issue type with tooltips
  - Apply Selected Renames button (top + bottom), Cancel button, ✕ Close

  **Duplicate Finder Card:**
  - Click header to scan → grouped duplicate sets with suggested keeper
  - Delete Duplicates button (top + bottom, destructive red), Cancel, ✕ Close

  **Video File Manager Card:**
  - Click header to scan → table of video files with sizes
  - Delete Selected Videos button (top + bottom, destructive red), Cancel, ✕ Close

  **Corrupt Photo Finder Card** (PL-127):
  - Click header to scan (checks every photo, decoding at reduced scale) → table: ☐ | Filename | Size | Problem
  - Empty files and photos Pillow can't open or decode; HEIC is skipped when pillow-heif is missing (count shown)
  - Delete Selected Photos (confirm; cloud first, then the frame), ↻ Rescan, ✕ Close

  **Rename File Card:**
  - Click header to scan → table: Preview | Original Filename | EXIF Date | New Filename
  - New Filename inputs are blank by default (original shown as placeholder)
  - Apply Renames button enabled only when at least one name is filled in and all are conflict-free
  - Guardrails: red highlight if proposed name already exists or is used twice in the same batch
  - Apply sends only changed rows via cloud-first rename; table refreshes after success
  - ✕ Close hides results

  **Rotate Photos Card** (PL-126):
  - Click header to load the album's JPEG/PNG/HEIC photos → table: Preview | Filename | EXIF orientation badge | ⟲ ⟳ 180° (and Fix when EXIF says it's turned)
  - "Only photos with an EXIF rotation" filter; **Fix EXIF Orientation (N)** fixes them all at once
  - Rotation is relative to how the photo looks now; the photo is re-saved upright (EXIF orientation 1), uploaded to the cloud folder, then replaces the frame's copy; thumbnails refresh

### DASH-BACKUPS - Backups (Tab 4, PL-164)

- **Files:** `dashboard.html` + `dashboard.js`
- **Presentation:** Tab 4; reloads its album picker (and the Recover list, if open) each time the tab opens
- **UI Elements:**

  **Photo Backups Card** (collapsible via ▸ Show):
  - Album picker of its own (not the Tools one): **Whole frame** (default) or one album
  - Create Backup → tar.gz of the album's local_path → `~/Pictures/backups/{source_id}_{YYYY-MM-DD_HHMMSS}.tar.gz`; Whole frame makes one file `frame_{name}_{YYYY-MM-DD_HHMMSS}.tar.gz` (manifest.yaml first, a folder per album; confirm first). Refused if it won't fit with 1 GB left free
  - Lists backups with their full path on the frame (Whole frame adds an Album column: "Whole frame (N albums)" rows, and deleted albums' backups marked *deleted*)
  - Per backup: Restore (album → into it, or a new album if it's gone; whole frame → every album in one click, merging), Download, Delete (with confirm)

  **Recover Albums Card** (collapsible): from cloud storage (this frame's deleted albums; unclaimed folders behind a warning), take over another frame, upload a .zip/.tar.gz (up to 16 GB; a whole-frame backup restores all its albums)

---

### DASH-SETTINGS - Settings (Tab 5)

- **Files:** `dashboard.html` + `dashboard.js`
- **Presentation:** Tab 5
- **UI Elements:**

  **⚙️ Frame Settings Card** (▸ Show):
  - Frame Name, Rotation Interval (seconds), Frame ID (read-only), Sync Interval, Funnel URL (read-only), Fade Time (seconds)
  - Save Settings button (shows "Saving...", updates header frame name on success; a rotation change restarts the display)
  - **Network sub-card** (▸ Show): LAN IP Address, WiFi Network (SSID), read-only
  - **Cloud Sync sub-card** (▸ Show): Koofr email and password, **Save & Verify** (checked live with rclone before saving), **⚡ Test Connection**
  - **Display Sleep Schedule sub-card** (▸ Show): Sleep Time (display off), Wake Time (display on), Save Schedule (systemd user timers via `POST /api/settings/sleep-schedule`)

  **📱 Mobile App Pairing Card** (▸ Show):
  - Generate Pairing QR Code button; Manage Devices toggle (shows the Paired Devices card)
  - Pairing result: QR code, manual code, countdown, connection info (Tailscale IP, Frame URL), Regenerate Code, how-to-pair steps
  - Auto-hides when the countdown ends

  **Paired Devices Card** (toggled via Manage Devices):
  - Table: Name, Role (badge), Paired, Last Seen, Revoke (disabled for the only admin)
  - Device summary (e.g. "3 device(s), 1 admin(s)"); loads `GET /api/devices`, revokes via `POST /devices/{id}/revoke`

  **📋 Logs Card** (▸ Show):
  - Log type: Operations Log / Security Log; line count: 50 / 100 (default) / 500; Refresh
  - Log Level: DEBUG / INFO / WARNING / ERROR + Save Level (`POST /api/settings/log-level`)
  - Loads `GET /api/logs?log_type={ops|security}&lines={50|100|500}`

  **🔄 Updates Card** (▸ Show):
  - Branch badge **DEV** (blue) or **MAIN** (green); version comparison
  - Check for Updates; Apply Updates (when available: git pull + `update_app.sh`, then the API restarts)
  - Automatic check schedule: Frequency (Daily/Weekly/Monthly), Day, Time, Save Schedule

  **🍎 Demo Mode Card** (only when `demo.allowed: true` is set by hand, PL-015):
  - Turn On / Turn Off Demo Mode, Generate New Codes; reviewer codes and their expiry
  - Reset the demo frame (PL-151): Save as Baseline, Reset to Baseline (disabled until a baseline is saved), baseline date and albums with photo counts

  **🎉 Party Mode Card** (▸ Show, bottom):
  - Shows what's displaying; enabling needs a type-to-confirm; stops cloud sync and the WiFi watchdog so the frame runs as a standalone slideshow (`POST /api/settings/party`)

---

## Dashboard Navigation

```
Dashboard (single page, dashboard.html)
  ├── Banners (demo mode; SD card swap / takeover, when they apply)
  ├── Status Banner (always visible, all tabs)
  ├── Tab 1: Frame Status (DASH-STATUS) [default]
  ├── Tab 2: Albums (DASH-ALBUMS) [reloads on open]
  │     ├── ☁️ Albums card (table, Activate, Delete)
  │     └── ➕ Add Album card
  ├── Tab 3: Tools (DASH-TOOLS) [picker reloads on open]
  │     ├── Album Selector
  │     ├── Filename Cleaner card
  │     ├── Duplicate Finder card
  │     ├── Video File Manager card
  │     ├── Corrupt Photo Finder card
  │     ├── Rename File card
  │     └── Rotate Photos card
  ├── Tab 4: Backups (DASH-BACKUPS) [picker and Recover reload on open]
  │     ├── Photo Backups card [collapsible, own album picker incl. Whole frame]
  │     └── Recover Albums card [collapsible]
  └── Tab 5: Settings (DASH-SETTINGS)
        ├── Frame Settings card [collapsible]
        │     ├── Network sub-card
        │     ├── Cloud Sync sub-card
        │     └── Display Sleep Schedule sub-card
        ├── Mobile App Pairing card [collapsible]
        ├── Paired Devices card [toggled via Manage Devices]
        ├── Logs card [collapsible, includes Log Level]
        ├── Updates card [collapsible, branch badge DEV/MAIN]
        ├── Demo Mode card [only when demo.allowed]
        └── Party Mode card [collapsible, bottom]
```

---

## Feature Cross-Reference

iOS IDs are from `wanderwall_app/docs/SCREEN_MAP.md` (Manager app unless marked Share).

| Feature | iOS Screen | Dashboard Screen |
|---|---|---|
| Sync status overview | MM1 (Your Frames card), FD3, SW2 | DASH-STATUS |
| Photo counts (frame/cloud) | FD3, SW2, SD3 | DASH-STATUS, DASH-ALBUMS |
| Sync Now | SW2, SD3, MF3 | DASH-STATUS |
| Restart services | FD3, MF3 | DASH-STATUS |
| Reboot Frame | MF3 | DASH-STATUS |
| View logs | LG3 | DASH-SETTINGS (Logs card) |
| Album list | SW2 | DASH-ALBUMS |
| Show an album on the frame | SD3 | DASH-ALBUMS (Activate) |
| Add album | AS3 | DASH-ALBUMS (Add Album) |
| Rename album | SD3 | -- |
| Delete album | SD3 | DASH-ALBUMS (Delete) |
| Upload photos | UP2 (from MM1, SD3, MP3); Share: CH1 | -- |
| Manage photos (rename, delete, preview) | MP3 | DASH-TOOLS (Rename File) |
| Filename cleaning, duplicates, videos, corrupt photos, rotation | -- | DASH-TOOLS |
| Backups (album or whole frame) | -- | DASH-BACKUPS (Photo Backups) |
| Recover deleted albums | -- | DASH-BACKUPS (Recover Albums) |
| Frame name, rotation, sync interval | MF3 | DASH-SETTINGS (Frame Settings) |
| Fade time, log level | -- | DASH-SETTINGS |
| Sleep schedule | -- | DASH-SETTINGS (Display Sleep Schedule) |
| Generate pairing code | -- | DASH-SETTINGS (Mobile App Pairing) |
| Pair (enter or scan code) | PR3; Share: CO1 → PR3 | -- |
| Paired devices, revoke | DV4 | DASH-SETTINGS (Paired Devices) |
| Contributor invites | IN2 | -- |
| Share Upload Link (browser uploads) | UL3 | -- |
| Software updates, schedule | MF3, US4 | DASH-SETTINGS (Updates) |
| Connection status (home WiFi, remote access) | FD3 (Connection) | DASH-SETTINGS (Network) |
| Cloud login | AP3, CR4 | DASH-SETTINGS (Cloud Sync) |
| Cloud storage quota | MM1, AP3 | -- |
| Frame storage capacity | MM1, FD3 | DASH-STATUS |
| Current image preview | -- | DASH-STATUS |
| Party mode, demo mode | -- | DASH-SETTINGS |
| Indicator lights (frame display overlay) | -- | On the frame's screen (GTK3 overlay) |
| Unpair frames | FL2, MF3, AP3; Share: CS2 | -- |
| Clear app data | AP3; Share: CS2 | -- |
