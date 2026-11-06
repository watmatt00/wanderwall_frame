#!/bin/bash
# Display engine (upstream picframe) updater, KP-011 / KP-012 / KP-015.
#
# Brings ~/venv_picframe to the pin in scripts/setup/picframe-requirements.txt:
#   1. Nothing to do when the installed packages already match the pin (the normal case).
#   2. Skips frames on hold (~/.wanderwall/engine.yaml "upgrade: hold", set by
#      install.sh --from-v4; the dashboard's Upgrade button clears it).
#   3. Postpones when no screen is on (none, or display sleep): the health check needs the
#      engine running, and it can't start without a screen (PL-187).
#   4. Builds ~/venv_picframe-<version> at its final path (venvs can't be moved) and smoke
#      tests it.
#   5. First run on a frame: ~/venv_picframe is a real folder. It's renamed to
#      ~/venv_picframe-<old version> with its bin/ shebangs and activate scripts rewritten,
#      so the old engine keeps working there and rollback to it works.
#   6. Swaps the ~/venv_picframe symlink in one step, restarts picframe.service and checks
#      for up to 90 s that the service is active and the engine's HTTP API (:9000) answers.
#   7. On failure, points the symlink back, restarts, logs an ERROR and exits 1.
#   8. Keeps one previous engine and deletes older ones.
# The result goes to wanderwall.log and ~/.wanderwall/engine.yaml (shown on the Updates card).
#
# Run as the frame user. update_app.sh and the dashboard start it as a transient user unit:
#   systemd-run --user --unit=wanderwall-engine-update --collect bash update_engine.sh
# Exit codes: 0 done, nothing to do, on hold or postponed; 1 error (old engine kept or restored).
#
# Test overrides (tests/unit/test_update_engine.py): WW_HOME, WW_REQUIREMENTS, WW_PYTHON,
# WW_SYSTEMCTL, WW_HEALTH_URL, WW_HEALTH_TIMEOUT, WW_HEALTH_INTERVAL, WW_MIN_FREE_MB,
# WW_DRM_DIR, WW_WLR_RANDR.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOME_DIR="${WW_HOME:-$HOME}"
REQUIREMENTS="${WW_REQUIREMENTS:-$SCRIPT_DIR/picframe-requirements.txt}"
PYTHON="${WW_PYTHON:-/usr/bin/python3}"
read -r -a SYSTEMCTL <<< "${WW_SYSTEMCTL:-systemctl --user}"
HEALTH_URL="${WW_HEALTH_URL:-http://localhost:9000/}"
HEALTH_TIMEOUT="${WW_HEALTH_TIMEOUT:-90}"
HEALTH_INTERVAL="${WW_HEALTH_INTERVAL:-3}"
MIN_FREE_MB="${WW_MIN_FREE_MB:-600}"

LINK="$HOME_DIR/venv_picframe"
WW_DIR="$HOME_DIR/.wanderwall"
STATE_FILE="$WW_DIR/engine.yaml"
LOCK_FILE="$WW_DIR/engine.lock"
LOG_FILE="$WW_DIR/logs/wanderwall.log"
SERVICE="picframe.service"
VERSION_RE='^[0-9]+(\.[0-9]+)*$'
FOLDER_RE='^[0-9]+(\.[0-9]+)*(-r[0-9]+)?$'   # venv_picframe-<version>[-r<n>]

mkdir -p "$WW_DIR/logs"

# ── Logging: stdout (journal of the transient unit) and wanderwall.log ────────
_log() {
    local level="$1"; shift
    local ts; ts="$(date +'%Y-%m-%d %H:%M:%S')"
    if [[ "$level" == "ERROR" ]]; then
        echo "[$ts] ERROR: $*" >&2
    else
        echo "[$ts] $*"
    fi
    printf '%s %-5s [update_engine] %s\n' "$ts" "$level" "$*" >> "$LOG_FILE" 2>/dev/null || true
}
LOG()  { _log INFO "$@"; }
WARN() { _log WARNING "$@"; }
ERR()  { _log ERROR "$@"; }

# ── Engine state file (~/.wanderwall/engine.yaml) ─────────────────────────────
# Flat "key: 'value'" lines, written whole (temp file + rename). The hold flag is kept as it
# is: only install.sh sets it and only the dashboard clears it.
yaml_quote() { local v="${1//$'\n'/ }"; printf "'%s'" "${v//\'/\'\'}"; }

hold_set() {
    [[ -f "$STATE_FILE" ]] && grep -qE "^upgrade:[[:space:]]*['\"]?hold['\"]?[[:space:]]*$" "$STATE_FILE"
}

write_state() {
    # write_state <result> <message> [installed] [previous]
    local result="$1" message="$2" installed="${3:-}" previous="${4:-}" tmp
    tmp="$(mktemp "$STATE_FILE.XXXXXX")"
    {
        echo "# Written by scripts/setup/update_engine.sh"
        hold_set && echo "upgrade: hold"
        echo "pinned_version: $(yaml_quote "$TARGET_VERSION")"
        echo "installed_version: $(yaml_quote "$installed")"
        echo "previous_version: $(yaml_quote "$previous")"
        echo "last_run: $(yaml_quote "$(date +'%Y-%m-%d %H:%M:%S')")"
        echo "last_result: $(yaml_quote "$result")"
        echo "message: $(yaml_quote "$message")"
    } > "$tmp"
    chmod 600 "$tmp"
    mv -f "$tmp" "$STATE_FILE"
}

# ── Helpers ───────────────────────────────────────────────────────────────────
engine_version() {
    # engine_version <venv dir>: prints the installed picframe version, or nothing
    "$1/bin/python" -c 'import importlib.metadata as m; print(m.version("picframe"))' 2>/dev/null || true
}

# Normalise "Name==1.0" lines (PEP 503 names) for comparing the pin with pip freeze.
normalise_reqs() {
    awk -F'==' '/^[A-Za-z0-9][A-Za-z0-9._-]*==/ {
        name = tolower($1); gsub(/[-_.]+/, "-", name)
        ver = $2; sub(/[[:space:];#].*/, "", ver)
        print name "==" ver
    }' | LC_ALL=C sort -u
}

matches_pin() {
    # matches_pin <venv dir>: true when every pinned package is installed at the pinned version
    local frozen missing
    frozen="$("$1/bin/python" -m pip freeze 2>/dev/null)" || return 1
    missing="$(LC_ALL=C comm -23 <(normalise_reqs < "$REQUIREMENTS") <(normalise_reqs <<< "$frozen"))"
    [[ -z "$missing" ]]
}

healthy() {
    # Polls until the service is active and the engine's HTTP API answers, or the timeout.
    local waited=0
    while (( waited < HEALTH_TIMEOUT )); do
        if "${SYSTEMCTL[@]}" is-active --quiet "$SERVICE" 2>/dev/null \
           && curl -sf -o /dev/null --max-time 3 "$HEALTH_URL" 2>/dev/null; then
            return 0
        fi
        sleep "$HEALTH_INTERVAL"
        waited=$(( waited + HEALTH_INTERVAL ))
    done
    return 1
}

point_link() {
    # point_link <target dir>: replaces the symlink in one step (rename over the old link)
    ln -sfn "$1" "$LINK.tmp"
    mv -T "$LINK.tmp" "$LINK"
}

restart_engine() {
    "${SYSTEMCTL[@]}" restart "$SERVICE"
}

# Rewrites absolute paths of a renamed venv: bin/ shebangs, activate scripts, pyvenv.cfg.
rewrite_venv_paths() {
    local dir="$1" old="$2" f
    for f in "$dir"/bin/*; do
        [[ -f "$f" && ! -L "$f" ]] || continue
        if head -c 2 "$f" | grep -q '^#!' && head -n 1 "$f" | grep -qF "#!$old/bin/"; then
            sed -i "1s|^#!$old/bin/|#!$dir/bin/|" "$f"
        fi
    done
    for f in "$dir"/bin/activate "$dir"/bin/activate.csh "$dir"/bin/activate.fish "$dir"/pyvenv.cfg; do
        if [[ -f "$f" ]]; then
            sed -i "s|$old\\([/\"' ]\\)|$dir\\1|g; s|$old\$|$dir|" "$f"
        fi
    done
}

source "$PROJECT_DIR/scripts/display/screen_lib.sh"

# ── Lock: one run at a time ───────────────────────────────────────────────────
exec 9> "$LOCK_FILE"
if ! flock -w 10 9; then   # -w: the display check takes the lock for a moment
    LOG "Engine update already running (lock $LOCK_FILE); nothing to do"
    exit 0
fi

# ── Pin ───────────────────────────────────────────────────────────────────────
if [[ ! -f "$REQUIREMENTS" ]]; then
    ERR "Failed to read the engine pin: $REQUIREMENTS not found"; exit 1
fi
TARGET_VERSION="$(sed -nE 's/^[Pp]icframe==([^[:space:]#]+).*/\1/p' "$REQUIREMENTS" | head -n 1)"
if [[ ! "$TARGET_VERSION" =~ $VERSION_RE ]]; then
    ERR "Failed to read the engine pin: no valid picframe==<version> line in $REQUIREMENTS"; exit 1
fi

# ── Current engine ────────────────────────────────────────────────────────────
if [[ ! -e "$LINK" ]]; then
    ERR "Failed to find the display engine: $LINK doesn't exist"
    write_state "failed" "No display engine at $LINK"
    exit 1
fi
CURRENT_VERSION="$(engine_version "$LINK")"
if [[ ! "$CURRENT_VERSION" =~ $VERSION_RE ]]; then
    ERR "Failed to read the display engine's version from $LINK"
    write_state "failed" "Couldn't read the installed engine version"
    exit 1
fi
PREVIOUS_RECORDED=""
[[ -f "$STATE_FILE" ]] && PREVIOUS_RECORDED="$(sed -nE "s/^previous_version: '(.*)'$/\1/p" "$STATE_FILE" | head -n 1)"

if matches_pin "$LINK"; then
    LOG "Display engine $CURRENT_VERSION matches the pin; nothing to do"
    write_state "up_to_date" "Engine $CURRENT_VERSION matches the pin" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 0
fi

if hold_set; then
    LOG "Display engine upgrade on hold ($CURRENT_VERSION installed, pin $TARGET_VERSION); press Upgrade on the Updates card"
    write_state "on_hold" "Engine $CURRENT_VERSION kept; upgrade to $TARGET_VERSION is on hold" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 0
fi

screen="$(screen_state)"
if [[ "$screen" != "ready" ]]; then
    LOG "Display engine upgrade postponed: screen $screen (the health check needs the engine on screen)"
    write_state "postponed" "Postponed: no screen on ($screen); runs with the next update or the Upgrade button" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 0
fi

free_mb="$(df -Pm "$HOME_DIR" | awk 'NR==2 {print $4}')"
if [[ -z "$free_mb" ]] || (( free_mb < MIN_FREE_MB )); then
    ERR "Failed to upgrade the display engine: ${free_mb:-?} MB free in $HOME_DIR, need $MIN_FREE_MB MB"
    write_state "failed" "Not enough free space (${free_mb:-?} MB, need $MIN_FREE_MB MB)" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 1
fi

LOG "Display engine upgrade starting: $CURRENT_VERSION -> $TARGET_VERSION"

# ── Build the new engine at its final path ────────────────────────────────────
# venv_picframe-<version>, or -r2, -r3… when that folder is the running engine (a pin change
# of a dependency only) or the name the first conversion needs for the old engine.
CURRENT_TARGET="$(readlink -f "$LINK")"
CONVERT_TO=""
[[ -d "$LINK" && ! -L "$LINK" ]] && CONVERT_TO="$HOME_DIR/venv_picframe-$CURRENT_VERSION"
NEW_VENV="$HOME_DIR/venv_picframe-$TARGET_VERSION"
n=1
while [[ "$NEW_VENV" == "$CURRENT_TARGET" || "$NEW_VENV" == "$CONVERT_TO" ]]; do
    n=$(( n + 1 ))
    NEW_VENV="$HOME_DIR/venv_picframe-$TARGET_VERSION-r$n"
done
rm -rf "$NEW_VENV"
build_log="$WW_DIR/logs/engine-build.log"
if ! { "$PYTHON" -m venv "$NEW_VENV" \
       && "$NEW_VENV/bin/python" -m pip install --no-cache-dir --disable-pip-version-check -r "$REQUIREMENTS"; } \
       > "$build_log" 2>&1; then
    rm -rf "$NEW_VENV"
    ERR "Failed to build display engine $TARGET_VERSION (pip output: $build_log); $CURRENT_VERSION kept"
    write_state "failed" "Build of $TARGET_VERSION failed; $CURRENT_VERSION kept (see engine-build.log)" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 1
fi
built="$(engine_version "$NEW_VENV")"
if [[ "$built" != "$TARGET_VERSION" ]] \
   || ! "$NEW_VENV/bin/python" -c 'import picframe, pi3d' > /dev/null 2>>"$build_log" \
   || ! matches_pin "$NEW_VENV"; then
    rm -rf "$NEW_VENV"
    ERR "Failed smoke test of display engine $TARGET_VERSION (got '${built:-none}'); $CURRENT_VERSION kept"
    write_state "failed" "Smoke test of $TARGET_VERSION failed; $CURRENT_VERSION kept" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 1
fi
LOG "Built display engine $TARGET_VERSION in $NEW_VENV (smoke test passed)"

# ── First conversion: real folder -> versioned folder + symlink ───────────────
if [[ -d "$LINK" && ! -L "$LINK" ]]; then
    OLD_VENV="$HOME_DIR/venv_picframe-$CURRENT_VERSION"
    if [[ -e "$OLD_VENV" ]]; then
        rm -rf "$NEW_VENV"
        ERR "Failed to convert $LINK: $OLD_VENV already exists; $CURRENT_VERSION kept"
        write_state "failed" "Can't convert the engine folder: $OLD_VENV exists" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
        exit 1
    fi
    # Stop the engine while its folder moves, so it can't load a module from a moving path.
    "${SYSTEMCTL[@]}" stop "$SERVICE" || true
    mv -T "$LINK" "$OLD_VENV"
    rewrite_venv_paths "$OLD_VENV" "$LINK"
    point_link "$OLD_VENV"
    if [[ "$(engine_version "$LINK")" != "$CURRENT_VERSION" ]]; then
        # The renamed engine doesn't run: put the folder back as it was.
        rm -f "$LINK"
        mv -T "$OLD_VENV" "$LINK"
        rewrite_venv_paths "$LINK" "$OLD_VENV"
        restart_engine || true
        rm -rf "$NEW_VENV"
        ERR "Failed to convert $LINK: the renamed engine didn't run; folder restored, $CURRENT_VERSION kept"
        write_state "failed" "Conversion of the engine folder failed; restored" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
        exit 1
    fi
    LOG "Converted $LINK to a symlink -> $OLD_VENV (first run)"
fi
PREV_VENV="$(readlink -f "$LINK")"

# ── Swap, restart, health check, rollback ─────────────────────────────────────
point_link "$NEW_VENV"
restart_engine || true
if healthy; then
    LOG "Display engine upgraded successfully: $CURRENT_VERSION -> $TARGET_VERSION"
else
    ERR "Failed health check of display engine $TARGET_VERSION (service active + $HEALTH_URL within ${HEALTH_TIMEOUT}s); rolling back"
    point_link "$PREV_VENV"
    restart_engine || true
    if healthy; then
        LOG "Rolled back to display engine $CURRENT_VERSION; it answers again"
        rolled="restored"
    else
        ERR "Rolled back to display engine $CURRENT_VERSION, but it isn't answering either (journalctl --user -u picframe)"
        rolled="restored, but not answering"
    fi
    rm -rf "$NEW_VENV"
    write_state "rolled_back" "$TARGET_VERSION failed its health check; $CURRENT_VERSION $rolled" "$CURRENT_VERSION" "$PREVIOUS_RECORDED"
    exit 1
fi

# ── Clean up: keep the current engine and one previous ────────────────────────
for dir in "$HOME_DIR"/venv_picframe-*; do
    [[ -d "$dir" && ! -L "$dir" ]] || continue
    name="$(basename "$dir")"
    [[ "${name#venv_picframe-}" =~ $FOLDER_RE ]] || continue
    [[ "$dir" == "$NEW_VENV" || "$dir" == "$PREV_VENV" ]] && continue
    rm -rf "$dir"
    LOG "Removed old display engine $dir"
done

write_state "ok" "Upgraded $CURRENT_VERSION -> $TARGET_VERSION" "$TARGET_VERSION" "$CURRENT_VERSION"
exit 0
