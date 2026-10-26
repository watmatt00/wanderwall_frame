# WanderWall - API Reference

Every route the frame serves, from `src/api/app.py` (the `/api/v1` routers in `src/api/routes/`) and `src/dashboard/routes.py` (the dashboard). Checked against the code on 2026-10-21 (5.0.0, `dev`).

## Base URL

- **Local (LAN)**: `http://<pi-ip>:8000`
- **Local (Tailscale VPN / MagicDNS)**: `http://<hostname>.whale-ayu.ts.net:8000` (dashboard + API, no JWT for dashboard)
- **Remote (mobile app)**: `https://<hostname>.whale-ayu.ts.net` (via Tailscale Funnel, JWT required)

## Authentication

`/api/v1` endpoints (except `/api/v1/pair`) need a JWT from pairing (see [Security](SECURITY.md)):

```
Authorization: Bearer <token>
```

| Dependency (`src/api/dependencies.py`) | Who passes | Fails with |
|---|---|---|
| `get_current_device` | any paired device | 401 missing/invalid/expired token, revoked device, or a token replaced by `/auth/refresh` more than 2 minutes ago |
| `require_admin` | role `admin` (the Manager app) | 403 `"Admin access required"` |
| `require_contributor` | role `admin` or `contributor` (the Share app) | 403 |

Tokens last 90 days. The dashboard routes have no JWT; they're protected by network access only.

### Network Access

`LANOnlyMiddleware` (`src/api/middleware.py`) is deny-by-default. Callers outside the LAN and tailnet (RFC 1918, loopback, Tailscale `100.64.0.0/10`) can reach only `/api/v1/*`, `/health` and `/version`. Every other route, including the dashboard, `/docs`, `/api/tools/*`, `/api/albums/*` and `/api/updates/*`, returns `403` to them (a browser gets a small "WanderWall" page instead of JSON, PL-128). The caller address is uvicorn's `request.client.host`, which is rewritten from `X-Forwarded-For` only when the TCP peer is `127.0.0.1` (the Tailscale Funnel/Serve proxy).

### Upload size limits

`UploadSizeLimitMiddleware` (`src/api/app.py`) rejects a too-large body with 413 before it's read:
- `/api/v1/contributor/upload/*`: 50 MB per photo (+1 MB multipart framing)
- `/api/albums/upload-archive`: 16 GB (+1 MB); the route also refuses a file that won't fit on the frame with 1 GB left free

## Error Responses

`/api/v1` errors use FastAPI's format, `{"detail": "..."}` (validation errors: 422 with a list in `detail`). Dashboard routes mostly answer 200 with `{"ok": false, "error": "..."}`.

| Status | Meaning |
|---|---|
| 400 | Bad request (invalid input) |
| 401 | Missing, invalid, expired or replaced token; revoked device; wrong pairing code |
| 403 | Wrong role, or a non-local caller on a LAN-only route |
| 404 | Not found |
| 409 | Conflict (a sync is running; the album is showing or syncing) |
| 413 | Body too large |
| 422 | Request body failed validation |
| 429 | Rate limit exceeded |
| 500 / 502 / 503 | Server error / cloud error / feature not set up on this frame |

---

## Public endpoints (no auth, reachable from anywhere)

### GET /health
`{"status": "ok"}`

### GET /version
`{"version": "5.0.0", "api": "wanderwall"}`

### POST /api/v1/pair

Exchange a pairing code (or a contributor invite code) for a JWT.

**Request:**
```json
{"code": "A3B-X7K", "device_name": "Matt's iPhone", "requested_role": "admin"}
```
`requested_role` is optional: the Manager app sends `"admin"`, the Share app `"contributor"`. An invite code used in the Manager app gets 403 `"This is an invite code. Use the WanderWall Share app to pair with it."`

**Response (200):**
```json
{"token": "eyJhbGciOiJIUzI1NiIs...", "frame_id": "tkframe", "frame_name": "Test Frame", "role": "admin", "api_port": 8000, "funnel_url": "https://tkframe.whale-ayu.ts.net"}
```

**Response (401):** `{"detail": "Invalid or expired pairing code"}`

Pairing codes expire after 5 minutes and allow 3 tries.

**Demo codes (PL-015).** On a frame with `demo.allowed: true` and demo mode turned on (dashboard Settings → Demo Mode), two reusable codes also pair. They don't expire for 14 days, have no attempt or rate limits, and aren't used up:

| Code | `requested_role: "admin"` (Manager) | `requested_role: "contributor"` (Share) |
|------|------|------|
| Demo admin code | 200, `role: "admin"` | 200, `role: "contributor"` |
| Demo contributor code | 403 `"This is an invite code. Use the WanderWall Share app to pair with it."` | 200, `role: "contributor"` |
| Demo code after demo mode ended, or replaced by new codes | 401 `"This demo code has expired. Contact the frame owner for a new code."` | same |

Devices paired with a demo code are revoked when demo mode ends (turned off, or 14 days after it was turned on); their next call gets 401 `"Device has been revoked"`.

---

## `/api/v1` endpoints (JWT)

Admin = `require_admin`, Any = `get_current_device`, Contributor = `require_contributor`.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| **Pairing and tokens** | | | |
| `/api/v1/pairing/generate` | POST | Admin | New pairing code + QR: `{qr_code_base64, code, expires_at}`. 429 after 3 codes an hour; 500 if no Funnel URL is set |
| `/api/v1/auth/refresh` | POST | Any | New 90-day token for the caller: `{token, expires_at}`. The old token stops working 2 minutes later. 401 if the device was revoked |
| **Status** | | | |
| `/api/v1/status` | GET | Admin | Frame status, sync, storage, network ([details](#get-apiv1status)) |
| **Devices** | | | |
| `/api/v1/devices` | GET | Admin | Paired devices: a bare list of `{id, name, role, paired_at, last_seen}` |
| `/api/v1/devices/count` | GET | Admin | `{total, admins}` |
| `/api/v1/devices/{id}` | GET | Admin | One device (same fields); 404 if unknown |
| `/api/v1/devices/{id}` | DELETE | Admin | Revoke a device: 204, no body. 404 unknown; 400 `"Cannot revoke the last admin device. Add another admin first."` |
| `/api/v1/devices/me` | DELETE | Any | Unpair the calling device (the apps call this on unpair): 204. 400 if it's the last admin |
| **Services and system** | | | |
| `/api/v1/services` | GET | Admin | List of `{name, active, status, enabled, can_restart}` |
| `/api/v1/services/{name}/restart` | POST | Admin | `{service, action, success, message}`. Allowed names: `picframe`, `wanderwall-api`, `wanderwall-lights`, `wanderwall-sync.timer`; anything else 400 |
| `/api/v1/services/{name}/start` | POST | Admin | Same as restart, action `start` |
| `/api/v1/services/{name}/stop` | POST | Admin | Same as restart, action `stop` |
| `/api/v1/system/reboot` | POST | Admin | Reboot the frame ([details](#post-apiv1systemreboot)) |
| **Display** | | | |
| `/api/v1/display/folder` | GET | Admin | Album showing now: `{source_id, source_name, path, photo_count}` (`source_id: "unknown"` if the config names no known album) |
| `/api/v1/display/folder` | POST | Admin | Show another album: `{"source_id": "trip"}` → `{success, source_id, source_name, path, message}`. Starts a background sync of that album if it has a cloud folder and no sync is running. 404 unknown, 400 disabled |
| `/api/v1/display/spotlight` | POST | Admin | Show one photo for N seconds, then go back ([details](#post-apiv1displayspotlight)) |
| `/api/v1/display/spotlight` | DELETE | Admin | Cancel a spotlight: `{"cancelled": true}`, or `{"cancelled": false, "message": "No active spotlight"}` |
| **Albums (folders)** | | | |
| `/api/v1/folders` | GET | Admin | `{folders: [{id, name, path, photo_count, remote_path}], current_source}`. `remote_path` is the cloud folder as `/KFR_trip`, or null |
| `/api/v1/folders` | POST | Admin | Create an album: `{"name": "Trip"}` → 201 `{id, name, local_path, rclone_remote, enabled, photo_count}`. The cloud folder is `KFR_<id>`, or `KFR_<id>_2`… if that name is taken; none if the cloud can't be listed (PL-165). An explicit `rclone_remote` is used as given |
| `/api/v1/folders/{id}` | GET | Admin | One album (same fields as create); 404 unknown |
| `/api/v1/folders/{id}` | PATCH | Admin | Rename: `{"name": "New name"}` (1-50 chars, no control characters). Only the display name changes |
| `/api/v1/folders/{id}` | DELETE | Admin | Delete an album and its photos on the frame ([details](#delete-apiv1foldersid)) |
| `/api/v1/folders/{id}/sync` | POST | Admin | Sync one album in the background: `{message, source_id}`. 400 no cloud folder, 409 a sync is running |
| `/api/v1/folders/{id}/sync/status` | GET | Admin | `{is_syncing, current_source, local_count, remote_count, sync_status, message}` |
| `/api/v1/folders/sync/all` | POST | Admin | Sync every enabled album with a cloud folder, one after another: `{message, sources_queued}`. 409 a sync is running, 400 none to sync |
| `/api/v1/folders/remotes` | GET | Admin | rclone remotes: list of `{name}` |
| **Photos** | | | |
| `/api/v1/sources/{id}/photos` | GET | Admin | Photos on the frame for an album: `{source_id, photos: [{filename, size_bytes, modified_epoch}], total}` |
| `/api/v1/sources/{id}/photos/thumbnail?filename=` | GET | Admin | JPEG thumbnail, cached in `~/.wanderwall/thumbs/` |
| `/api/v1/sources/{id}/photos/{filename}` | DELETE | Admin | Delete a photo from the cloud folder first, then the frame: `{deleted, message}` |
| `/api/v1/sources/{id}/photos/{filename}` | PATCH | Admin | Rename: `{"new_filename": "..."}`, cloud first, then the frame: `{old_filename, new_filename, message}` |
| **Photo library tools** (same scans as the dashboard Tools tab; every apply is cloud-first) | | | |
| `/api/v1/sources/{id}/tools/scan/filenames` | GET | Admin | Filename issues and proposed names (read-only) |
| `/api/v1/sources/{id}/tools/apply/filenames` | POST | Admin | `{fixes: [...]}` from the scan → batch result |
| `/api/v1/sources/{id}/tools/scan/duplicates` | GET | Admin | Exact-duplicate groups |
| `/api/v1/sources/{id}/tools/apply/duplicates` | POST | Admin | `{to_delete: [filenames]}` (leave out the keeper) |
| `/api/v1/sources/{id}/tools/scan/videos` | GET | Admin | Video files with sizes |
| `/api/v1/sources/{id}/tools/apply/videos` | POST | Admin | `{to_delete: [filenames]}` |
| `/api/v1/sources/{id}/tools/rename` | POST | Admin | `{original, proposed}`: rename one file |
| `/api/v1/sources/{id}/tools/scan/corrupt` | GET | Admin | Empty or undecodable photos: `{source_id, files: [{filename, size_bytes, error}], total_files_scanned, skipped}` (PL-127) |
| `/api/v1/sources/{id}/tools/apply/corrupt` | POST | Admin | `{to_delete: [filenames]}` (photos only) |
| `/api/v1/sources/{id}/tools/rotate` | POST | Admin | `{items: [{filename, rotate: left\|right\|180\|auto}]}`: rotate as seen on screen, or `auto` = apply the EXIF orientation; re-saved upright with orientation 1, uploaded to the cloud first (PL-126) |
| **Contributors (invites)** | | | |
| `/api/v1/contributors` | GET | Admin | Invites: list of `{id, code, expires_at, claimed, claimed_at, claimed_by}` |
| `/api/v1/contributors/invite` | POST | Admin | New single-use invite, 48 h: `{id, code, qr_code_base64, expires_at, funnel_url, claimed}`. 429 after 3 pending invites an hour |
| `/api/v1/contributors/{invite_id}` | DELETE | Admin | Revoke an unclaimed invite: 204. 400 bad id (UUID), 404 unknown or already claimed |
| **Contributor (Share app)** | | | |
| `/api/v1/contributor/folders` | GET | Contributor | Enabled albums: `{folders: [{id, name, photo_count}]}` (no paths or cloud details) |
| `/api/v1/contributor/upload/{id}` | POST | Contributor | Multipart `file`: one photo (image types only, max 50 MB) straight to the album's cloud folder, as `<name>_<time>_<rand>.<ext>`. An identical photo (same size and MD5) already there isn't uploaded again: `skipped: true`. Response `{success, file_name, source_id, message, skipped}`. 400 no cloud folder or bad type, 404 unknown album, 413 too big |
| **Cloud** | | | |
| `/api/v1/cloud/credentials` | GET | Admin | The Koofr login from the frame's rclone config, for the Manager app's uploads: `{credentials: {provider, email, password} \| null, message}`. `Cache-Control: no-store`; every call goes to the security log |
| **Settings** | | | |
| `/api/v1/settings` | GET | Admin | `{sync_interval, rotation_interval, frame_name}` |
| `/api/v1/settings/sync-interval` | PUT | Admin | `{"interval": 900}`: 0 (off), 300, 600, 900, 1800, 2700, 3600, 7200, 21600, 43200 or 86400 seconds → `{success, message}` |
| `/api/v1/settings/frame-name` | PUT | Admin | `{"name": "..."}`: 1-50 letters, digits, spaces, `-`, `_` |
| `/api/v1/settings/rotation-interval` | PUT | Admin | `{"interval": 30}`: 5-3600 s. Restarts the display |
| `/api/v1/settings/sleep-schedule` | POST | Admin | `{enabled, sleep_time: "HH:MM", wake_time: "HH:MM"}`: display off and on daily (systemd timers) |
| **Logs** | | | |
| `/api/v1/logs?lines=100&log_type=ops` | GET | Admin | `{entries, log_type, count}`. `lines` 1-500, `log_type` `ops` or `security` |
| **Software updates** | | | |
| `/api/v1/updates/settings` | GET | Admin | Update schedule, last check result, installed version and branch |
| `/api/v1/updates/check` | POST | Admin | Check for an update now |
| `/api/v1/updates/schedule` | POST | Admin | `{auto_check, auto_apply, frequency: daily\|weekly\|monthly, day, check_time: "HH:MM"}` |
| `/api/v1/updates/apply` | POST | Admin | Apply the update (git pull + `update_app.sh`), then restart the API |

### GET /api/v1/status

**Response (200):**
```json
{
  "frame_id": "tkframe",
  "frame_name": "Test Frame",
  "current_source": "trip",
  "photo_count": 1234,
  "services": [
    {"name": "picframe.service", "display_name": "WanderWall Display", "active": true, "status": "running", "can_restart": true},
    {"name": "wanderwall-api.service", "display_name": "WanderWall API", "active": true, "status": "running", "can_restart": true}
  ],
  "sync": {"last_sync": "2026-02-02T10:00:00+00:00", "status": "match", "local_count": 1234, "remote_count": 0, "is_syncing": false, "current_source": null},
  "capacity": {"total_gb": 64.0, "used_gb": 12.5, "available_gb": 51.5, "percent_used": 19.5, "total_bytes": 68719476736, "used_bytes": 13421772800, "free_bytes": 55297703936},
  "network": {"lan_ip": "192.168.102.210", "tailscale_ip": "100.100.168.66", "funnel_url": "https://tkframe.whale-ayu.ts.net", "local_connected": true, "wifi_ssid": "7Oaks", "remote_access": true}
}
```

`sync.status`: `match`, `mismatch`, `syncing`, `error` or `idle`. `network` drives the app's Connection lights. `local_connected`: the frame has a LAN connection (same test as the frame's WiFi dot). `wifi_ssid`: "" when wired or unknown. `remote_access`: the frame answers on its Funnel URL from the public internet (checked through Tailscale's relay, cached 5 min when OK, 1 min when failing); `null` when no Funnel URL is set. The last three are missing on frames older than 5.0.0.

### POST /api/v1/system/reboot

Reboot the frame (PL-142). The answer comes first; the reboot starts `delay_seconds` later. Poll `GET /health` until it answers again (about 1-2 minutes).

**Response (202):**
```json
{"rebooting": true, "message": "Rebooting. The frame will be back in about 1-2 minutes.", "delay_seconds": 3}
```

**Response (503):** the frame hasn't had `install_setup.sh` re-run since reboot was added (its polkit rule has no reboot permission):
```json
{"detail": "Reboot isn't set up on this frame yet. Run: sudo bash scripts/setup/install_setup.sh"}
```

### DELETE /api/v1/folders/{id}

Delete an album (PL-147). Removes it from the album list and deletes its photos on the frame (`~/Pictures/<id>`). The cloud folder and backups in `~/Pictures/backups` are kept, and the frame's album registry marks it deleted, so it can come back through Recover Albums. The folder is only deleted if it is a direct child of `~/Pictures`, isn't `spotlight` or `backups`, and no other album uses it.

**Response (200):**
```json
{"deleted": "trip", "name": "Trip", "photos_removed": 42, "local_folder_removed": true, "cloud_folder": "koofr:KFR_trip", "error": null}
```
`error` is set (and `local_folder_removed` false) when the album was removed but its folder couldn't be deleted.

**Response (409):** the album is showing, or syncing:
```json
{"detail": "This album is showing on the frame. Show another album first, then delete it."}
```

**Response (404):** unknown album.

### POST /api/v1/display/spotlight

Display a single photo on the frame for a fixed duration, then automatically restore the previous album. Uses Pi3D's HTTP API for a seamless fade (no service restart).

**Request:**
```json
{"source_id": "trip", "filename": "2025/vacation/photo.jpg", "duration_seconds": 30}
```
- `duration_seconds`: 1-3600. Defaults to 30.
- `filename`: relative path within the album's `local_path`.

**Response (200):**
```json
{"success": true, "filename": "2025/vacation/photo.jpg", "duration_seconds": 30, "message": "Displaying 'photo.jpg' for 30s, then restoring 'Trip'"}
```

400 bad filename or duration, 404 unknown album or photo.

- Copies the photo to `~/Pictures/spotlight/` (a persistent folder Pi3D keeps indexed).
- Waits 2.5 s for Pi3D to index the file, then switches via its HTTP API.
- Waits 4.5 s for the fade, then pauses Pi3D to freeze the photo.
- After `duration_seconds`, resumes Pi3D and restores the previous album.
- Starting a new spotlight while one is active cancels the previous one.

---

## Dashboard endpoints (LAN and tailnet only, no auth)

The web dashboard at `http://<pi-ip>:8000` is one page (`GET /`, `dashboard.html` + `static/js/dashboard.js`) with five tabs: Frame Status, Albums, Tools, Backups, Settings. Everything below is called by its JavaScript. Callers outside the LAN and tailnet get `403` (see [Network Access](#network-access)).

### Page, status and setup

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | The dashboard page (the only HTML page; there are no `/settings`, `/devices`, `/pairing` or `/logs` pages) |
| `/dashboard/status` | GET | Live status for the page ([fields](#get-dashboardstatus)) |
| `/current-image` | GET | Thumbnail (560 px, cached) of the photo showing now, or of `?filename=` as named by `/current-image/info`; Pi3D's own image for videos; 503 if the display doesn't answer (PL-174) |
| `/current-image/info` | GET | `{"filename": ...}` of the photo showing now (from Pi3D's `/current_image_original` header), `null` if the display doesn't answer |
| `/dashboard/koofr-setup` | POST | First-run setup step 2: save Koofr credentials after checking them live with rclone |
| `/api/cloud/test` | POST | Test the Koofr connection; recreates the rclone remote from stored credentials if it's missing |
| `/dashboard/test-lights` | POST | Override the indicator lights for manual testing: `{"sync_status": "error"\|"match"\|null, "wifi_connected": true\|false\|null}` |

### Sync, display and services

| Endpoint | Method | Description |
|---|---|---|
| `/sync` | POST | Sync the album that's showing (if it has no cloud folder, the first enabled album that has one): `{status, source}` |
| `/switch-source` | POST | Form field `source_id`: show another album |
| `/api/frame-live` | POST | `{"target_dir": "..."}`: show the album with that folder and sync it |
| `/services/{name}/restart` | POST | Restart a service (same allowlist as `/api/v1/services`) |
| `/system/reboot` | POST | Reboot the frame: `{"ok": true}` or `{"ok": false, "error": ...}` |

### Albums

| Endpoint | Method | Description |
|---|---|---|
| `/api/sources` | GET | Albums for the dashboard (`id`, `label`, `active`, counts, cloud folder) |
| `/api/sources/create` | POST | `{"name": "Trip"}`: create an album (cloud folder named as in `POST /api/v1/folders`) |
| `/api/sources/delete` | POST | `{"source_id": "trip"}`: delete an album **and its photos on the frame** (PL-147); cloud folder and backups kept. Refused for the album that's showing or syncing |
| `/api/rclone/remotes` | GET | Configured rclone remotes |
| `/api/rclone/list-dirs` | POST | `{remote, path}`: folders in a remote |
| `/api/local/list-dirs` | GET | Folders in `~/Pictures` |
| `/api/config/test-remote` | POST | Test an rclone remote |
| `/api/thumbnail/{source_id}?filename=` | GET | JPEG thumbnail of a photo |

### Tools tab (per album, every apply is cloud-first)

| Endpoint | Method | Description |
|---|---|---|
| `/api/tools/{id}/scan/files` | GET | Every file with its EXIF date (Rename File card) |
| `/api/tools/{id}/scan/filenames` | GET | Filename issues and proposed names |
| `/api/tools/{id}/apply/filenames` | POST | Apply the chosen fixes |
| `/api/tools/{id}/scan/duplicates` | GET | Exact duplicates |
| `/api/tools/{id}/apply/duplicates` | POST | Delete the chosen duplicates |
| `/api/tools/{id}/scan/videos` | GET | Video files |
| `/api/tools/{id}/apply/videos` | POST | Delete the chosen videos |
| `/api/tools/{id}/rename` | POST | Rename one file |
| `/api/tools/{id}/scan/corrupt` | GET | Empty or damaged photos (Corrupt Photo Finder) |
| `/api/tools/{id}/apply/corrupt` | POST | Delete the chosen damaged photos |
| `/api/tools/{id}/rotate` | POST | `{items: [{filename, rotate}]}`: rotate photos (Rotate Photos card) |

### Backups tab: Photo Backups (PL-164)

Backups live in `~/Pictures/backups/`: one album is `<album_id>_<YYYY-MM-DD_HHMMSS>.tar.gz`; the whole frame is one `frame_<name>_<YYYY-MM-DD_HHMMSS>.tar.gz` with `manifest.yaml` first (frame name, serial, and each album's id, name, folder, cloud folder and photo count), then a folder per album. Creating a backup is refused if it won't fit with 1 GB left free (the whole set is checked first for a whole-frame backup).

| Endpoint | Method | Description |
|---|---|---|
| `/api/tools/backup/all` | GET | Every backup, newest first: `{ok, backups: [{filename, path, size_bytes, created_at, kind, ...}]}`. `kind: "frame"` rows add `frame_name`, `album_count`; `kind: "album"` rows add `album_id`, `album_name`, `album_exists` (false = the album was deleted) |
| `/api/tools/backup/all/create` | POST | Back up every album into one file: `{ok, filename, path, size_bytes, albums, skipped}` (`skipped`: albums with no folder on the frame yet) |
| `/api/tools/backup/download/{filename}` | GET | The archive as a file download. 400 bad name, 404 missing |
| `/api/tools/backup/delete` | POST | `{"filename": "..."}`: delete any backup, a deleted album's too |
| `/api/tools/backup/{id}/list` | GET | One album's backups: `{ok, backups: [{filename, path, size_bytes, created_at}]}` (only that album's, not a longer id's like `trip_2`) |
| `/api/tools/backup/{id}/create` | POST | Back up one album: `{ok, filename, size_bytes}` |
| `/api/tools/backup/{id}/delete` | POST | `{"filename": "..."}`: delete one of that album's backups |

### Backups tab: Recover Albums (PL-147, PL-164)

Every restore goes staging → the album's cloud folder → the album, so the next sync keeps the photos. It skips photos the album already has (same name and same bytes, or an earlier `name_N` copy), so restoring onto a frame that still has its albums duplicates nothing and running it twice is safe; a different photo with the same name is saved as `name_1.jpg`. Only photos and videos are restored. Single-album results: `{album, restored, already_there, renamed, skipped, uploaded_to_cloud}`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/albums/recoverable` | GET | `{ok, cloud, unclaimed, unclaimed_needs_confirm, frames, cloud_error, backups}`. `cloud`: this frame's deleted albums whose cloud folder still exists (with photo counts); `unclaimed`: `KFR_*` folders no frame claims (`unclaimed_needs_confirm` true on a shared account); `frames`: other frames on the account that can be taken over; `backups`: as `/api/tools/backup/all`. If the cloud can't be reached, `cloud_error` says why and backups are still listed |
| `/api/albums/recover-cloud` | POST | `{folder, name, allow_unclaimed}`: re-add an album pointed at a cloud folder, then sync it. This frame's own folders always; unclaimed ones on a dedicated account, or with `allow_unclaimed`; another frame's never |
| `/api/albums/frame-swap` | POST | `{moved}`: answer "this SD card was last used on another Pi". `true` = moved (keep every album, mark the old board replaced); `false` = copied (new frame, keeps only the albums on the card) |
| `/api/albums/take-over` | POST | `{serial, confirm_name}`: take over another frame's albums. `confirm_name` must match its name if it checked in within 24 hours |
| `/api/albums/undo-takeover` | POST | Clear another Pi's takeover of this frame |
| `/api/albums/restore-backup` | POST | `{filename, target_id \| new_name}`: restore an album backup into an album, or a new one. A whole-frame backup restores **every** album and ignores `target_id`/`new_name` (below) |
| `/api/albums/upload-archive` | POST | Raw body = .zip or .tar.gz (up to 16 GB, and it must fit with 1 GB left free), query `target_id` or `new_name`: add its photos/videos to an album. A whole-frame backup restores every album and ignores the query |

**Whole-frame restore** (`restore-backup` with a `frame_…` file, or `upload-archive` with one): each album in the manifest is matched to an album on this frame by id, cloud folder or name and **merged**; otherwise this frame's deleted album on the same cloud folder is **recovered** onto that folder; otherwise a **new** album is **created** on a cloud folder no other frame uses (`KFR_<id>_2`…). Response: `{ok, kind: "frame", frame_name, albums: [{album, name, action: "merged"|"recovered"|"created", restored, already_there, renamed}], skipped}`. If an album fails (for example the cloud upload), the error names the albums already restored.

### Settings tab

| Endpoint | Method | Description |
|---|---|---|
| `/api/settings` | POST | `{frame_name, rotation_interval, sync_interval, fade_time}` (fade 0.5-30 s) |
| `/api/settings/log-level` | POST | `{"log_level": "INFO"}` |
| `/api/settings/sleep-schedule` | POST | `{enabled, sleep_time, wake_time}` |
| `/api/settings/party` | POST | `{"enabled": true}`: party mode stops cloud sync and the WiFi watchdog |
| `/api/settings/demo` | POST | Turn demo mode on (`{"enabled": true}`, 14 days) or off (revokes demo devices). 403 unless `demo.allowed` |
| `/api/settings/demo/regenerate` | POST | New demo codes and a fresh 14 days; paired demo phones stay paired. 403 unless `demo.allowed` |
| `/api/settings/demo/baseline` | POST | Save the albums, their photos, the showing album, frame name, rotation and sync interval as the demo baseline (PL-151). 403 unless `demo.allowed`; 409 unless the Koofr account is dedicated, every album has a cloud folder and one is showing |
| `/api/settings/demo/reset` | POST | Reset the demo frame to the baseline (PL-151): removes demo and contributor phones, invites and Koofr upload links; restores the baseline albums on the frame and in the cloud; deletes other albums and `KFR_*` cloud folders; restores settings; demo mode on for 14 more days. 409 without a baseline, on a shared account or after a Koofr login change |
| `/pairing/generate` | POST | New pairing code and QR for the Mobile App Pairing card |
| `/api/devices` | GET | Paired devices for the Paired Devices card |
| `/devices/{id}/revoke` | POST | Revoke a paired device |
| `/api/logs?lines=100&log_type=ops` | GET | Log lines for the Logs card (`ops` or `security`) |
| `/api/updates/settings` | GET | Update schedule and last check result |
| `/api/updates/check` | POST | Check for updates now |
| `/api/updates/schedule` | POST | Save the auto-check schedule |
| `/api/updates/apply` | POST | Apply the update (git pull + `update_app.sh`), then restart the API |

### GET /dashboard/status

Polled by the page. Fields:

| Field | Meaning |
|---|---|
| `sync_status` | `idle`, `syncing`, `match`, `mismatch` or `error` |
| `local_count`, `remote_count` | Photos on the frame / in the cloud for the album showing |
| `current_source` | Name of the album showing |
| `services` | `[{name, active, status}]` |
| `storage_used`, `storage_total`, `storage_percent` | SD card use (GB, %) |
| `last_sync`, `next_sync`, `last_restart` | Times as text (`last_restart` from systemd `ActiveEnterTimestamp`) |
| `koofr_configured`, `has_sources` | First-run setup state |
| `rotation_interval` | Seconds per photo |
| `wifi_connected`, `sync_timer_status`, `lights_status`, `api_health_status`, `tailscale_status` | Health checks for the status page |
| `demo` | `allowed`, `enabled`, `admin_code`, `contributor_code` (empty unless allowed), `expires_at`, `days_left`, `demo_devices` |
| `registry` | Album registry banners: `pending_swap` (SD card last used on another Pi), `replaced_by`, `replaced_at` (another Pi took this frame over) |

### Traffic light status logic

The status page shows a traffic light:
- **GREEN**: sync status is `match` or `idle` and the cloud and frame counts match
- **AMBER**: the cloud and frame counts don't match (sync needed)
- **RED**: a sync error
- **BLUE (animated)**: a sync is running
