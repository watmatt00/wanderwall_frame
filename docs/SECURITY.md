# WanderWall - Security Model

## Overview

WanderWall's security, and its limits:
- **JWT authentication** for the app API (`/api/v1/*`, except `/api/v1/pair`). The web dashboard has **no login**; it is protected only by being reachable from the LAN and tailnet (`LANOnlyMiddleware`, deny by default)
- **Tailscale Funnel** for remote access: HTTPS, and only `/api/v1/*`, `/health` and `/version` are reachable from the internet. On the LAN and tailnet the frame serves plain HTTP on port 8000 (dashboard and API)
- **Time-limited pairing codes** with rate limiting (codes and invites only; no other endpoint is rate-limited)
- **Dual logging** with security event tracking

## Access Model

```
┌─────────────────────────────────────────────────────────────┐
│                      ACCESS MODEL                            │
├─────────────────────────────────────────────────────────────┤
│  LOCAL (LAN)           │  REMOTE (Internet)                 │
├────────────────────────┼────────────────────────────────────┤
│  Web Dashboard         │  Mobile apps                       │
│  http://pi:8000        │  https://frame.ts.net              │
│  No auth required      │  JWT auth required                 │
│  (LAN + tailnet only)  │  Via Tailscale Funnel, /api/v1 only│
└────────────────────────┴────────────────────────────────────┘
```

## Authentication Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Pi Frame   │     │   QR Code   │     │  Mobile App │
│             │     │             │     │             │
│ Generates:  │────>│ Contains:   │────>│ Scans QR    │
│ - 6-char    │     │ - URL       │     │ Extracts:   │
│   code      │     │ - Code      │     │ - URL       │
│ - Displays  │     │ - Name      │     │ - Code      │
│   on screen │     │             │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    POST /pair                 │
                    {code, device_name}        │
┌─────────────┐                         ┌──────▼──────┐
│  Pi Frame   │<────────────────────────│  Mobile App │
│             │                         │             │
│ Validates   │     Returns JWT         │ Stores:     │
│ code        │────────────────────────>│ - URL       │
│ Issues JWT  │     + frame info        │ - Token     │
│             │                         │ - Name      │
└─────────────┘                         └─────────────┘
```

## JWT Security

| Property | Value |
|----------|-------|
| **Algorithm** | HS256 |
| **Secret** | 256-bit random, unique per Pi |
| **Secret Location** | `~/.wanderwall/jwt_secret` (600 permissions) |
| **Expiry** | 90 days; the app refreshes via `POST /api/v1/auth/refresh` when under 30 days remain |
| **Rotation** | A refresh records the new token's issue time on the device (`token_not_before`); older tokens stop working 2 minutes later |
| **Revocation** | Removing a device (dashboard Devices list or `DELETE /api/v1/devices/{id}`) rejects its tokens immediately |
| **Claims** | `device_id`, `device_name`, `role`, `frame_id`, `iat`, `exp` |

### Roles

| Role | Permissions |
|------|-------------|
| **admin** | Full access - service restarts, folder switching, device management |
| **contributor** | WanderWall Share app: list albums and upload photos (`/api/v1/contributor/*`, 50 MB per photo). Every other `/api/v1` route returns 403 |

## Pairing Code Security

| Property | Value |
|----------|-------|
| **Format** | 6 alphanumeric, case-insensitive (e.g., `A3B-X7K`) |
| **Keyspace** | 36^6 = 2.17 billion combinations |
| **Attempt limit** | 3 failures = code invalidated |
| **Expiry** | 5 minutes |
| **Rate limit** | 3 codes per hour |

### Demo Mode (App Store review, PL-015)

Two reusable codes (Manager → admin, Contributor → contributor) so an App Store reviewer can pair at any time over the Funnel. While it's on, **anyone with a demo code becomes admin from the internet**, so:

| Safeguard | Detail |
|-----------|--------|
| **Per-frame gate** | Works only where `demo.allowed: true` was added by hand to `~/.wanderwall/config.yaml` (review frame only). Otherwise the dashboard card is hidden, the routes return 403 and demo codes are ignored. Never set it on a frame with personal photos. |
| **Not in git** | Codes are generated on the frame and stored only in its `config.yaml` (written `600`). The repo is public. |
| **14-day limit** | Demo mode ends 14 days after it's turned on (or after "Generate New Codes"). Checked on every pair, API call and dashboard refresh. |
| **Revoke on end** | Turning it off, or the 14 days ending, revokes every device paired with a demo code. |
| **Visible** | Amber banner on every dashboard tab with days left and demo device count; `DEMO_*` and `PAIR … demo=True` lines in `security.log`. |

**Accepted risk:** there's no global limit on failed `/pair` attempts (Funnel hides client IPs, so per-IP limits don't work). A 6-character code (36^6) for at most 14 days makes guessing impractical.

**Admin phones receive the Koofr app password** (`GET /api/v1/cloud/credentials`), so the review frame must use a dedicated Koofr account with sample photos only.

**Reset between reviews (PL-151):** Reset to Baseline removes demo and Share phones, invites and Koofr upload links, and deletes every `KFR_*` cloud folder not in the baseline. Because it deletes cloud folders, it runs only when the album registry marks the Koofr account `dedicated` and the login is the one the baseline was saved with. LAN-only (dashboard), like the rest of Demo Mode.

**After the review:** turn off demo mode (revokes the reviewer's phones), then rotate the Koofr app password.

## Logging

### Dual Log Strategy

| Log | Purpose | Location | Retention |
|-----|---------|----------|-----------|
| `wanderwall.log` | Operations (sync, display, errors) | `~/.wanderwall/logs/` | 7 days |
| `security.log` | Auth events, API access, failures | `~/.wanderwall/logs/` | 90 days |

### Security Log Events

```
PAIR_CODE_GENERATE_SUCCESS ip=100.64.1.5 admin=Matt's iPhone expires=2026-02-02T18:00:00
PAIR_ATTEMPT_SUCCESS ip=100.64.1.5 code=A3B*** device_name=New Device
PAIR_SUCCESS ip=100.64.1.5 device_id=abc123 device_name=New Device
PAIR_FAILURE ip=100.64.1.5 reason=invalid_or_expired_code
PAIR_SUCCESS ip=127.0.0.1 device_id=def456 device_name=Reviewer iPhone role=admin demo=True
PAIR_FAILURE ip=127.0.0.1 reason=demo_code_expired
DEMO_ENABLE_SUCCESS expires=2026-11-02T12:00:00+00:00
DEMO_DISABLE_SUCCESS reason=expired revoked=2
TOKEN_REFRESH_SUCCESS ip=64.98.52.132 device_id=abc123 device_name=Matt's iPhone
CLOUD_CREDENTIALS_FETCH_SUCCESS ip=64.98.52.132 device_id=abc123 device_name=Matt's iPhone
```

## Cloud Storage Credential

Admin phones upload, list and delete photos directly with Koofr, so `GET /api/v1/cloud/credentials` gives them the frame's Koofr **app password** (never the Koofr account password). Each hand-out is written to `security.log` as `CLOUD_CREDENTIALS_FETCH`, and the response is sent with `Cache-Control: no-store`. The phone keeps it in the iOS Keychain. If Koofr rejects the stored app password, the app fetches the current one from the frame and retries.

### Lost or stolen phone

1. **Revoke the phone** in the dashboard's Devices list. Its frame token stops working immediately.
2. **Revoke the Koofr app password** at app.koofr.net → Preferences → App passwords, and create a new one. The old one stops working for Koofr at once.
3. **Give the frame the new app password** via the dashboard's Koofr setup.
4. Your other phones pick up the new app password automatically the next time Koofr rejects the old one.

## Security Checklist

- [x] JWT secret: 256-bit random, unique per Pi, 600 permissions
- [x] Config files: 600 permissions, YAML (no code execution)
- [x] Pairing codes: cryptographically random, 3 attempts, 5-min expiry
- [x] Last admin protection: cannot remove or unpair the last admin (`devices.py`, 400)
- [ ] SSH recovery: `wanderwall-cli emergency-reset` command
- [x] Input validation: Pydantic models for all inputs
- [x] Path validation: filenames and relative paths validated (`rclone._validate_filename`, `_validate_relative_path`), backup names checked with a traversal guard (`backup_service.backup_path`), archive entries flattened to file names (zip-slip, symlink and zip-bomb guards in `recovery_service`)
- [ ] Rate limiting: per-endpoint limits (pairing codes and invites are limited to 3 an hour; nothing else is)
- [x] Service allowlist: only `picframe`, `wanderwall-api`, `wanderwall-lights`, `wanderwall-sync.timer` can be restarted/started/stopped (`systemd_service.ALLOWED_SERVICES`)
- [x] Tailscale Funnel: HTTPS only, no direct port exposure
- [x] Security log: 90-day retention, 700 permissions on directory

## Network Security

### Tailscale Funnel

- All remote (internet) access goes through Tailscale Funnel
- HTTPS for that path (TLS terminated by Tailscale); the API behind it listens on plain HTTP, locally
- No direct port exposure to the internet
- Funnel URL format: `https://<hostname>.<tailnet>.ts.net`

### LAN Access

- Web dashboard accessible only from the LAN and the tailnet (`LANOnlyMiddleware`, deny by default; see API.md → Network Access)
- No authentication required for LAN access
- Assumes physical network security
- The dashboard's LAN-only endpoints can change a lot without a login: delete albums and their photos on the frame, delete backups, restore archives, and accept uploads up to 16 GB (`/api/albums/upload-archive`, capped by free space). Anyone on the home WiFi or the tailnet can use them. That is the trade-off for a login-free dashboard; keep the tailnet to trusted devices (ACL tags) and the WiFi password private
