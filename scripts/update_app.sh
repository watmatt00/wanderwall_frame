#!/bin/bash
# Idempotent post-pull updater. Run after every git pull to apply service file
# changes, new apt packages, and enable new services. Safe to run multiple times.
#
# Usage: update_app.sh [--branch=dev|main]
#   --branch  Move the frame to that branch first (e.g. the App Review frame onto
#             main), run that branch's copy of this script, then restart the API.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

LOG()  { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
WARN() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2; }
ERR()  { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

BRANCH=""
for arg in "$@"; do
    case "$arg" in
        --branch=*) BRANCH="${arg#--branch=}" ;;
        *) ERR "Unknown option: $arg (usage: update_app.sh [--branch=dev|main])"; exit 1 ;;
    esac
done
if [[ -n "$BRANCH" && "$BRANCH" != "dev" && "$BRANCH" != "main" ]]; then
    ERR "Invalid branch: $BRANCH (allowed: dev, main)"; exit 1
fi

LOG "update_app.sh starting (project: $PROJECT_DIR)"

# ── Step 0: git remote over HTTPS ──────────────────────────────────────────────
# The repo is public; frames pull anonymously over HTTPS and hold no GitHub key.
# Older installs may still use an SSH remote tied to an account-wide GitHub key.
HTTPS_REMOTE="https://github.com/watmatt00/wanderwall_frame.git"
CURRENT_REMOTE="$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || true)"
if [[ "$CURRENT_REMOTE" == git@github.com:* || "$CURRENT_REMOTE" == ssh://* ]]; then
    git -C "$PROJECT_DIR" remote set-url origin "$HTTPS_REMOTE"
    LOG "Git remote switched to HTTPS: $HTTPS_REMOTE (was $CURRENT_REMOTE)"
else
    LOG "Git remote: ${CURRENT_REMOTE:-none} (no change)"
fi

# ── Step 0b: branch switch (--branch) ─────────────────────────────────────────
# All in one if-block: bash parses it whole before running it, so the checkout
# can't change the lines it is about to run. It ends with exit; the rest of
# this file is the old branch's copy and must not run.
if [[ -n "$BRANCH" ]]; then
    CURRENT_BRANCH="$(git -C "$PROJECT_DIR" branch --show-current)"
    if [[ "$CURRENT_BRANCH" == "$BRANCH" ]]; then
        LOG "Branch: already on $BRANCH (no change)"
    else
        if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)" ]]; then
            ERR "Failed to switch to $BRANCH: local changes in $PROJECT_DIR (git status)"; exit 1
        fi
        if ! git -C "$PROJECT_DIR" fetch origin \
            || ! git -C "$PROJECT_DIR" checkout "$BRANCH" \
            || ! git -C "$PROJECT_DIR" pull --ff-only; then
            ERR "Failed to switch from ${CURRENT_BRANCH:-detached} to $BRANCH (see git output above)"; exit 1
        fi
        LOG "Branch switched: ${CURRENT_BRANCH:-detached} -> $BRANCH ($(git -C "$PROJECT_DIR" rev-parse --short HEAD))"

        if ! bash "$SCRIPT_DIR/update_app.sh"; then
            ERR "Failed to run $BRANCH's update_app.sh"; exit 1
        fi

        systemctl --user restart wanderwall-api.service
        for _ in $(seq 1 30); do
            if curl -sf --connect-timeout 2 http://localhost:8000/health > /dev/null 2>&1; then
                LOG "Service wanderwall-api restarted successfully on $BRANCH"
                exit 0
            fi
            sleep 2
        done
        ERR "Failed to restart wanderwall-api: /health not answering after 60 s (journalctl --user -u wanderwall-api)"
        exit 1
    fi
fi

# ── Step 1: APT packages ───────────────────────────────────────────────────────
# Add packages here as new features require them.
APT_PACKAGES=(
    python3-gi
    python3-gi-cairo
    gir1.2-gtk-3.0
)

MISSING=()
for pkg in "${APT_PACKAGES[@]}"; do
    dpkg -l "$pkg" 2>/dev/null | grep -q '^ii' || MISSING+=("$pkg")
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    LOG "Missing packages: ${MISSING[*]} — attempting install..."
    if sudo -n apt-get install -y "${MISSING[@]}"; then
        LOG "  Packages installed."
    else
        WARN "apt-get install failed (missing packages or no sudo). Run manually:"
        WARN "  sudo apt-get update && sudo apt-get install -y ${MISSING[*]}"
    fi
else
    LOG "APT packages: all present."
fi

# ── Step 2: Systemd user service/timer files ───────────────────────────────────
mkdir -p "$SYSTEMD_USER_DIR"
RELOAD_NEEDED=false
CHANGED_SERVICES=()

for src in "$PROJECT_DIR/systemd/"*.service "$PROJECT_DIR/systemd/"*.timer; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    dest="$SYSTEMD_USER_DIR/$name"
    if ! diff -q "$src" "$dest" > /dev/null 2>&1; then
        cp "$src" "$dest"
        LOG "  Updated: $name"
        RELOAD_NEEDED=true
        # Track base service name (strip .service/.timer) for restart logic
        base="${name%.service}"
        base="${base%.timer}"
        CHANGED_SERVICES+=("$base")
    fi
done

if $RELOAD_NEEDED; then
    systemctl --user daemon-reload
    LOG "systemd user daemon reloaded."
else
    LOG "Systemd service files: no changes."
fi

# ── Step 3: Enable managed services/timers ─────────────────────────────────────
# Add new managed services here as they are introduced.
MANAGED_SERVICES=(wanderwall-api wanderwall-lights)
MANAGED_TIMERS=(wanderwall-sync)

for svc in "${MANAGED_SERVICES[@]}"; do
    unit="$svc.service"
    [[ -f "$SYSTEMD_USER_DIR/$unit" ]] || continue
    if ! systemctl --user is-enabled --quiet "$unit" 2>/dev/null; then
        [[ "$unit" == "wanderwall-api.service" ]] && continue  # caller handles API start
        systemctl --user enable --now "$unit"
        LOG "  Enabled and started: $unit"
    fi
done

for tmr in "${MANAGED_TIMERS[@]}"; do
    unit="$tmr.timer"
    [[ -f "$SYSTEMD_USER_DIR/$unit" ]] || continue
    if ! systemctl --user is-enabled --quiet "$unit" 2>/dev/null; then
        systemctl --user enable "$unit"
        LOG "  Enabled: $unit"
    fi
done

# ── Step 4: Restart changed services ──────────────────────────────────────────
# wanderwall-api is excluded — the caller (API update flow) handles that restart.
for base in "${CHANGED_SERVICES[@]}"; do
    [[ "$base" == "wanderwall-api" ]] && continue
    unit="$base.service"
    if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
        systemctl --user restart "$unit"
        LOG "  Restarted: $unit"
    fi
done

# ── Step 5: picframe config.yaml migrations ───────────────────────────────────
# Idempotent patches to ~/picframe_data/config/configuration.yaml.
PCONF="$HOME/picframe_data/config/configuration.yaml"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
if [[ -f "$PCONF" ]]; then
    MIGRATION_OUT=$("${VENV_PYTHON}" - "$PCONF" <<'PYEOF'
import sys, yaml
p = sys.argv[1]
with open(p) as f:
    cfg = yaml.safe_load(f) or {}
changed = False
# Enable Pi3D HTTP API — required for current-image preview and source switching
if not cfg.get("http", {}).get("use_http", False):
    cfg.setdefault("http", {})["use_http"] = True
    changed = True
if changed:
    with open(p, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False)
    print(f"Config migrations applied to {p}")
else:
    print(f"Config migrations: no changes needed.")
PYEOF
)
    LOG "$MIGRATION_OUT"
    # Restart picframe only when a migration changed the config (PL-174); restarting
    # on every update interrupted the slideshow for nothing
    if [[ "$MIGRATION_OUT" == "Config migrations applied"* ]]; then
        if systemctl --user is-active --quiet picframe.service 2>/dev/null; then
            systemctl --user restart picframe.service
            LOG "  Restarted picframe.service after config migration."
        fi
    fi
else
    LOG "picframe config not found at $PCONF — skipping migrations."
fi

LOG "update_app.sh complete."
