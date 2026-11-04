# Plan: Koofr count polling and display engine updates

Written 2026-11-03. Status: **planned, not started.** Two parts:

- **Part A:** cache the cloud photo count so status requests stop starting `rclone size`.
- **Part B:** a safe way to upgrade the picframe display engine on production frames. The old engine retries refused Nominatim lookups forever.

**Tracker:** the items (KP-001…036) are in `wanderwall_app/docs/PARKING_LOT.md`, Frame Backend & Setup, on the
WanderWall page http://utility.home:8765/ (folded in 2026-11-04; the koofr-polling tracker is retired).

## Why: what the Pi-hole audit found

pihole1 query log, 24 h to 2026-11-03 13:00:

| Frame | Rows/day | `app.koofr.net` (A + AAAA) | `nominatim.openstreetmap.org` |
|---|---|---|---|
| tkframe (.210) | 24,746 | ~24,700 | 0 |
| kframe (.200) | 25,475 | ~24,200 | ~1,200 (all refused, HTTP 403) |
| mnbframe | not on our Pi-holes (remote network) | 6 `rclone size` runs/min observed, so ~8–9k/day | 79 refused lookups/day |

Almost all of it was answered from the Pi-hole cache, so Quad9 wasn't hit. The cost is log noise, about 12k Koofr API calls per frame per day, and a Go process started every few seconds on the Pi.

### Cause 1: the cloud count is never cached

- `get_photo_counts()` runs `rclone size <album> --json` on every request (`src/services/status_service.py:40`, call at `:59`; `src/utils/rclone.py:441`). It has no cache.
- It's called by `GET /dashboard/status` (`src/dashboard/routes.py:606`) and the app's `GET /api/status` (`src/api/routes/status.py:128`).
- Who calls those endpoints, and how often:
  - **The indicator lights:** every 10 s, around the clock (`scripts/indicator_lights.py:24-25`). That's 8,640 a day by itself.
  - **Each open dashboard tab:** every 15 s (`src/dashboard/static/js/dashboard.js:727`). It keeps polling in background tabs; only the preview poll pauses when hidden (`dashboard.js:706`).
  - **The app:** on its own refreshes.

### Cause 2: the old picframe ignores `load_geoloc`

All four frames have the same config: `load_geoloc: false`, `geo_key: this_needs_to@be_changed`, `show_text` includes `location`, `show_text_tm: 0`.

| Frame | Hardware | OS / Python | Picframe | GPS photos | Lookups |
|---|---|---|---|---|---|
| kframe | Pi 4, 8 GB | bookworm, 3.11.2 | 2024.11.1 | 753 / 7,613 | ~1,200/day, all 403 |
| mnbframe | Pi 4, 4 GB, still v4 | bookworm, 3.11.2 | 2024.9.24 | 9 / 1,302 | 79/day, all 403 |
| tkframe | Pi 4, 4 GB | trixie, 3.13.5 | 2026.4.22 | 32 / 122 | none |
| bfframe | Pi 5, 2 GB | trixie, 3.13.5 | 2026.4.22 | 2 / 3 | none |

**Old versions (2024.x):**
- They read `load_geoloc` but never use it.
- Any photo with GPS and no cached place name triggers a Nominatim call every time it's shown (`image_cache.py:161-162`).
- The call uses Python's default user agent, so Nominatim refuses it. Nothing is cached, so it tries again next time.

**2026.4.22:**
- `GeoReverse.get_address()` returns before any network call when `load_geoloc` is false or `geo_key` is the placeholder.
- It also sends its own user agent and waits 2 s between requests.

**So no config change is needed. The engine just needs upgrading.** Today no path does that:
- `install.sh:650-653` installs picframe unpinned, and only when it builds a new venv.
- `--from-v4` keeps the old venv (`install.sh:347`).
- `update_app.sh` never touches the venv.

## Part A: cloud count cache

### Decisions (Matt, 2026-11-03)

- **The count is refreshed by syncs**, so it follows the sync interval.
- **Sync interval 0:** never count automatically.
- **Party mode:** the cache follows the timer that's actually running.
- **Manual actions** refresh the count straight away.
- **Status may show the cached count;** no live count is needed.

### Design

1. **New `src/services/cloud_count_cache.py`.**
   - It maps an album remote to: count, `checked_at`, `stale` flag.
   - It's saved to `~/.wanderwall/cloud_counts.yaml` with an atomic write (temp file, then rename) so restarts and updates keep it.
2. **Status reads only the cache.**
   - `get_photo_counts()` never starts rclone, except when the active album's entry is marked stale (step 4).
3. **Syncs refresh it.**
   - Every sync goes through `sync_service.sync_source()` (`src/services/sync_service.py:53`): the timer, Sync Now, the app, folders, recovery, demo reset.
   - After a successful `rclone sync`, it counts once and stores the result.
   - **The timer is the only automatic trigger, so the cache follows it with no extra logic:**
     - Interval 0 means no syncs and no counts.
     - Party mode stops the timer (`src/services/party_service.py:77`) and restores it at the end (`:124`).
4. **Manual cloud changes mark the album stale.**
   - Done inside the write helpers in `src/utils/rclone.py`: `rclone_deletefile`, `rclone_movefile`, the `*_raw` variants, `rclone_copyto`, `rclone_copy_dir`, `rclone_sync_up`, `rclone_purge`.
   - The next status read recounts once and clears the flag. That's within about 10 s, given the lights' poll.
   - A batch (for example the Filename Cleaner renaming 200 files) costs one count.
   - This applies at interval 0 too, because these are manual actions.
5. **Other manual reads feed the cache.**
   - Switching albums counts the new album straight away.
   - Opening the Albums tab (`/api/sources`, `src/dashboard/routes.py:951`) counts every album live, as today, and stores the results.
   - The app's per-folder `get_sync_status()` (`src/utils/rclone.py:662`) does the same.
6. **No count yet** (brand-new frame before its first sync, or interval 0 before any manual action):
   - `determine_sync_status()` (`status_service.py:68`) returns `"unknown"`.
   - The app decodes `sync_status` as a plain `String` (`wanderwall_app/iosApp/iosApp/Models/FrameStatus.swift:112`), so a new value is safe.
   - **Open:** what the lights show for `"unknown"`. Today anything other than `"match"` shows amber (`indicator_lights.py:121`).
7. **Optional:** add `remote_count_checked_at` to both status responses so the dashboard can show "cloud count as of 12:45". Update `docs/API.md`.
8. **Optional:** stop the 15 s status poll in background tabs, the same way the preview poll does.

**Expected:** at a 15-min interval, ~96 counts plus 96 syncs a day, about 400 Pi-hole rows per frame (down from ~24k).

### Tests

- **Unit (`tests/unit`):**
  - Status reads never start rclone.
  - A sync refreshes the count.
  - The stale flag: a batch costs one recount.
  - Interval 0 and party mode: no automatic counts.
  - Save, reload, and recovery from a corrupt cache file.
  - The `"unknown"` status.
- **bfframe** (the `dev` test frame during the Apple review; tkframe is the review demo frame on `main` and is off
  limits until approval):
  - First make `frame` its active album: today `current_source: default` matches no album, so status never counts
    and the before reading would be meaningless (`docs/test_runs/2026-11-03_dns_baseline.md`, bfframe section).
  - Watch `rclone size` processes for 10 min: only after syncs and manual actions.
  - Pi-hole rows for .215 over 1 h, before (with the album active) and after.
  - The lights and the dashboard's Frame Status traffic light behave as before.
  - Delete a photo from the Tools tab; the count updates within ~10 s.
- **Update `docs/TEST_PLAN.md`.**

## Part B: display engine (picframe) updates

### Design

1. **Pin the version** in a new file, `scripts/setup/picframe-requirements.txt`:
   - `picframe==2026.4.22`, plus its key dependencies (pi3d, Pillow, numpy, pi_heif, paho-mqtt) at tkframe's versions.
   - Raising the pin becomes an ordinary release: dev → the `dev` test frame → tag → main.
2. **New `scripts/setup/update_engine.sh`** (`set -euo pipefail`, `flock`, standard log lines):
   - **Already at the pin:** do nothing (the normal case).
   - **Otherwise, build:**
     - Build `~/venv_picframe-<version>` at its final path. Venvs can't be moved: their scripts hard-code the path (kframe: `#!/home/pi/venv_picframe/bin/python`).
     - Run a smoke test: import `picframe` and `pi3d`, and check the version.
   - **Swap:** point the `~/venv_picframe` symlink at the new venv in one atomic step (`ln -sfn` to a temp link, then `mv -T`), and restart `picframe.service`.
   - **Health check, up to 90 s:** the service is active, and picframe's HTTP API on :9000 answers (source switching depends on it).
   - **On failure:** point the symlink back, restart, log an ERROR, exit 1.
   - **Clean-up:** keep one previous version and delete older ones.
3. **First conversion.**
   - `~/venv_picframe` is a real folder on every frame today. It has to be renamed to `~/venv_picframe-<old version>` before the symlink can take its place.
   - Renaming breaks its scripts, so the shebangs in `bin/` must be rewritten during the rename. Otherwise rolling back to the old engine fails.
   - This is the riskiest step; prove it in `pf_pi_sim` first.
4. **Run in the background.**
   - `update_app.sh` starts it with `systemd-run --user --unit=wanderwall-engine-update` and carries on.
   - This keeps it outside the 120 s limit that `apply_update` gives `update_app.sh` (`src/services/update_service.py:256`). pip on a Pi can take longer.
   - The result goes to `wanderwall.log`.
   - The Updates card shows the engine version and the last engine update result.
5. **`install.sh` uses the same pin and script** for fresh installs.
6. **Hold flag** for frames reinstalled from v4 (see mnbframe below):
   - `install.sh --from-v4` keeps the existing engine and writes `engine_upgrade: hold` to `/var/lib/wanderwall/state.yaml`.
   - While it's set, `update_engine.sh` skips the frame, and an automatic update (e.g. 03:30) never upgrades the engine.
   - The Updates card shows "Display engine 2024.9.24, upgrade on hold" with a button.
   - The button clears the flag and runs the upgrade, so Matt chooses when and can watch it.
7. **Config check before promotion:**
   - Compare kframe's picframe config keys (file written by 2024.11.1) with tkframe's.
   - Picframe fills missing keys from defaults (`model.py`), but confirm nothing it relies on was renamed.

### Tests

- **`pf_pi_sim` as bookworm / Python 3.11**, twice: starting from 2024.11.1 (kframe) and from 2024.9.24 (mnbframe).
  - Check the upgrade, a forced failure with automatic rollback, the first-conversion rollback, and that a second run does nothing.
- **bfframe (`dev`):**
  - Pin 2024.11.1, then 2026.4.22, so both directions run on real hardware (Pi 5, trixie; kframe's bookworm case is
    covered by `pf_pi_sim`).
  - Then a deliberately bad pin, to watch the rollback.
  - Then the hold flag and its button.

## Rollout

| Step | Frame | What | Gate |
|---|---|---|---|
| 1 | `pf_pi_sim` | Part B tests (bookworm, 3.11) | — |
| 2 | bfframe | Parts A and B on `dev`, tests above (moved to `dev` 2026-11-04 for the Apple review) | Matt moves it (`update_app.sh --branch=dev`) |
| 3 | bfframe | Back to `main` before it ships (`update_app.sh --branch=main`); engine already at the pin | Matt |
| — | tkframe | Untouched until approval (review demo frame on `main`); afterwards back to `dev` | approval |
| 4 | — | Tag `v5.0.X`, merge `dev` → `main`; not before the Apple review is done (`main` frozen) | **Matt's explicit OK** |
| 5 | kframe | First real bookworm engine upgrade; at home, so a screen and keyboard are at hand if needed. Monthly auto-update (Dec 2, 03:30) or Update button | **Matt's OK** for any manual update |
| 6 | mnbframe | **Two steps** (Matt, 2026-11-03), see below | **Matt's OK** for each step |

**mnbframe (remote, v4):**
1. **Reinstall to v5** with `install.sh --from-v4`. It keeps the 2024.9.24 engine and sets the hold flag. Part A arrives with v5.
   - Check it's healthy: slideshow, dashboard, syncs, and `rclone size` only after syncs.
2. **Upgrade the engine** with the Updates card button, once step 1 has been healthy. The automatic rollback has to have been proven on kframe (step 5) first.

No changes go to v4 (`~/picframe_4.0`); mnbframe gets both fixes through the reinstall.

## Open

- The lights' behaviour when `sync_status` is `"unknown"` (Part A, step 6).
- Whether to add `remote_count_checked_at` and pause background-tab polling (Part A, steps 7–8).
- Parking lot items, once `main` is back to normal (KP-032).
