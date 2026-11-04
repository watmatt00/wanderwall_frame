# DNS baseline before the Koofr polling changes (2026-11-03)

Baseline for the plan `docs/PLAN_koofr_polling.md` and tracker http://utility.home/trackers/koofr-polling/
(KP-021, KP-026, KP-027). Re-run the same queries after each change and add a column/section below.

## Pi-hole query log, 24 h ending 2026-11-03 14:39 MST

Window: 2026-11-02 14:39 → 2026-11-03 14:39 (pihole1 14:39:05, pihole2 14:39:11).

### Totals per frame

| Frame | pihole1 | pihole2 | Both |
|---|---|---|---|
| kframe (192.168.102.200) | 26,023 | 25,969 | **51,992** |
| tkframe (192.168.102.210) | 25,398 | 25,352 | **50,750** |

Both Pi-holes log nearly the same number. The frames resolve through Tailscale MagicDNS (`nameserver 100.100.100.100`
in `/etc/resolv.conf`), which evidently sends each lookup to both Pi-holes. So **~25k real lookups per frame per day,
each logged twice** (observed from the counts; Tailscale's forwarding behaviour not checked in its docs or source).

### By domain

| Frame | Domain | pihole1 | pihole2 |
|---|---|---|---|
| kframe | `app.koofr.net` | 24,815 | 24,763 |
| kframe | `nominatim.openstreetmap.org` | 1,204 | 1,200 |
| kframe | `ws.connect.raspberrypi.com` | 2 | 4 |
| kframe | `0.debian.pool.ntp.org` | 2 | 2 |
| tkframe | `app.koofr.net` | 25,394 | 25,350 |
| tkframe | `0.debian.pool.ntp.org` | 2 | 2 |

`app.koofr.net` is A + AAAA, so ~12.4k `rclone` process starts per frame per day (one every ~7 s).

### By status (Pi-hole v6 codes: 2 forwarded, 3 cache, 12 retried, 14 already forwarded, 17 stale cache)

| Frame | Pi-hole | 3 | 17 | 2 | 14 | 12 |
|---|---|---|---|---|---|---|
| kframe | pihole1 | 25,244 | 753 | 3 | 23 | — |
| kframe | pihole2 | 24,998 | 662 | 283 | 25 | 1 |
| tkframe | pihole1 | 25,090 | 289 | — | 16 | 1 |
| tkframe | pihole2 | 24,941 | 301 | 88 | 22 | — |

Almost all answered from cache; upstream (Quad9) barely touched.

## Frame side (same day)

| Frame | `rclone size` starts | Nominatim (place names) | Picframe | Notes |
|---|---|---|---|---|
| tkframe | 13 in 60 s (12:58–12:59), all from `wanderwall-api` (PID 859) | none | 2026.4.22 | 32/122 photos with GPS |
| kframe | not counted (Pi-hole rate matches tkframe) | ~1,200/day, all HTTP 403 | 2024.11.1 | 753/7,613 photos with GPS, 0 locations cached |
| mnbframe | 6 in 60 s (~14:30), v4 code | 79 HTTP 403 in 24 h | 2024.9.24 | Remote network, not on our Pi-holes. 9/1,302 photos with GPS |
| bfframe | 0 in 60 s (2026-11-04 09:03) | none | 2026.4.22 | 2/3 photos with GPS; no active album (see below) |

### bfframe (192.168.102.215), added 2026-11-04 09:03 MST

bfframe is the `dev` test frame during the Apple review (tkframe is the review demo frame on `main`), so Part A's
live check runs there. 24 h to 2026-11-04 09:03: **200 rows on pihole1, 184 on pihole2, all `app.koofr.net`**
(first seen 2026-10-27 13:45). That's about one lookup pair per 15-min sync and no status polling, because its
`current_source: default` matches no album (its only album is `frame`, `koofr:KFR_frame`). `/dashboard/status`
returns `current_source: Unknown`, `sync_status: idle`, and never runs `rclone size`, although the lights run.
**Not a valid "before" reading:** make `frame` the active album first (KP-019), then take a 1 h reading for .215
with the same queries (client `192.168.102.215`).

**Valid "before" for bfframe (taken 2026-11-04 10:37).** Matt moved bfframe to `dev` and activated `frame`
(picframe restarted 09:34:12 and 09:35:54; see the frozen-engine note in the parking lot). Fixed window
**09:36:00–10:36:00 MST**:

| Pi-hole | Rows in 1 h | Domain |
|---|---|---|
| pihole1 | 1,180 | all `app.koofr.net` |
| pihole2 | 1,178 | all `app.koofr.net` |

About 28k per Pi-hole a day at that rate, the same as tkframe. On the frame: 12 `rclone size` starts in 60 s
(09:37). Re-run with `timestamp >= <start> and timestamp < <end>` and client `192.168.102.215` for the "after".

Sources: indicator lights poll `/dashboard/status` every 10 s (`scripts/indicator_lights.py:25`), each poll runs
`rclone size`; open dashboard tabs add one every 15 s (`dashboard.js:727`), also in background tabs.

## Expected after the changes

- Part A (count cache), 15-min sync interval: ~96 counts + ~96 syncs a day → roughly 400 `app.koofr.net` rows per
  Pi-hole per frame (from ~25k).
- Part B (engine 2026.4.22) on kframe: `nominatim.openstreetmap.org` → 0.

## How to re-run

Same queries on each Pi-hole (read-only; `timestamp` is indexed). From the PC or Chromebook:

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
for h in pihole1 pihole2; do echo "=== $h"; ssh $h 'sudo -n nice -n 19 pihole-FTL sqlite3 -readonly /etc/pihole/pihole-FTL.db' <<'SQL'
.mode list
select 'window', datetime(strftime('%s','now')-86400,'unixepoch','localtime'), datetime('now','localtime');
select 'total', client, count(*) from queries where timestamp > strftime('%s','now')-86400 and client in ('192.168.102.200','192.168.102.210') group by client;
select 'domain', client, domain, count(*) from queries where timestamp > strftime('%s','now')-86400 and client in ('192.168.102.200','192.168.102.210') group by client, domain order by client, 4 desc;
select 'status', client, status, count(*) from queries where timestamp > strftime('%s','now')-86400 and client in ('192.168.102.200','192.168.102.210') group by client, status order by client, 4 desc;
SQL
done
```

Frame-side rclone rate (read-only, 60 s):

```bash
ssh pi@192.168.102.210 'n=0; last=""; end=$((SECONDS+60)); while [ $SECONDS -lt $end ]; do p=$(pgrep -f "^rclone size" | tr "\n" " "); [ -n "$p" ] && [ "$p" != "$last" ] && n=$((n+1)); last=$p; sleep 0.2; done; echo "rclone size starts in 60 s: $n"'
```

Compare a full 24 h that starts after the change is live on that frame (the query log keeps 30 days).

## Results after the changes

(add here: date, frame, version, the same tables)
