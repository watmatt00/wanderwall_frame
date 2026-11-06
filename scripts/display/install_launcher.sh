#!/bin/bash
# Points ~/start_picframe.sh (run by labwc's autostart) at the repo's launcher,
# scripts/display/start_picframe.sh (PL-187). Run as the frame user by update_app.sh and
# install.sh. Idempotent. Takes effect the next time picframe.service starts; it doesn't
# restart the display itself.
#
# Only replaces a stub it recognises: the one-engine-line file the v4 and v5 installers wrote
#   source <home>/venv_picframe/bin/activate
#   export SDL_VIDEODRIVER=x11
#   picframe &
# or its own earlier stub. Anything else is left alone with a warning. The original is kept
# once as ~/start_picframe.sh.pre-launcher.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${WW_START_SCRIPT:-$HOME/start_picframe.sh}"
AUTOSTART="${WW_LABWC_AUTOSTART:-$HOME/.config/labwc/autostart}"
LAUNCHER="$SCRIPT_DIR/start_picframe.sh"
MARKER="# Managed by wanderwall_frame (scripts/display/install_launcher.sh)"

LOG()  { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
WARN() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2; }

desired="#!/bin/bash
$MARKER
# labwc autostart runs this; the launcher waits for a screen, then starts the display engine.
\"$LAUNCHER\" &"

# True when the file is the installers' original stub (comments and blank lines ignored).
is_original_stub() {
    local line count=0 has_activate=false has_engine=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"   # trim leading space
        line="${line%"${line##*[![:space:]]}"}"   # trim trailing space
        [[ -z "$line" || "$line" == \#* ]] && continue
        count=$(( count + 1 ))
        case "$line" in
            "source ~/venv_picframe/bin/activate"|"source $HOME/venv_picframe/bin/activate") has_activate=true ;;
            "export SDL_VIDEODRIVER=x11") ;;
            "picframe &"|"picframe&") has_engine=true ;;
            *) return 1 ;;
        esac
    done < "$1"
    $has_activate && $has_engine && (( count <= 3 ))
}

if [[ ! -x "$LAUNCHER" ]]; then
    WARN "Display launcher not executable: $LAUNCHER (left $TARGET unchanged)"
    exit 1
fi

if [[ -f "$TARGET" ]] && grep -qxF "$MARKER" "$TARGET"; then
    if [[ "$(cat "$TARGET")" == "$desired" ]]; then
        LOG "Display launcher: no changes."
        exit 0
    fi
elif [[ -f "$TARGET" ]]; then
    if ! is_original_stub "$TARGET"; then
        WARN "Display launcher not installed: $TARGET isn't the stub the installer wrote; left unchanged"
        exit 0
    fi
    [[ -e "$TARGET.pre-launcher" ]] || cp -p "$TARGET" "$TARGET.pre-launcher"
fi

tmp="$(mktemp "$TARGET.XXXXXX")"
printf '%s\n' "$desired" > "$tmp"
chmod 755 "$tmp"
mv -f "$tmp" "$TARGET"
LOG "Display launcher installed: $TARGET -> $LAUNCHER (applies at the next display restart)"

if [[ ! -f "$AUTOSTART" ]] || ! grep -qF "start_picframe.sh" "$AUTOSTART"; then
    WARN "$AUTOSTART doesn't run start_picframe.sh; the display engine may not start from it"
fi
