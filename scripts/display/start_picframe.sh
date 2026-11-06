#!/bin/bash
# Display engine launcher (PL-187). labwc's autostart runs ~/start_picframe.sh, which runs
# this in the background (install_launcher.sh writes that stub).
#
# 1. Waits until a screen is connected and on. Started with no screen, the engine crashes
#    (pi3d: screen height 0) and never recovers, leaving a black screen with a mouse pointer.
# 2. Runs the engine from ~/venv_picframe, which update_engine.sh points at the pinned version.
# 3. When the engine exits, ends labwc, so systemd (picframe.service, Restart=always) starts
#    the whole display again instead of leaving labwc running with nothing on screen.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${WW_ENGINE_VENV:-$HOME/venv_picframe}"
POLL_SECONDS="${WW_SCREEN_POLL_SECONDS:-5}"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] start_picframe: $*"; }

# shellcheck source=screen_lib.sh
source "$SCRIPT_DIR/screen_lib.sh"

waited=0
last_state=""
while true; do
    state="$(screen_state)"
    [[ "$state" == "ready" ]] && break
    # Log when the state changes and every 10 minutes, not every poll.
    if [[ "$state" != "$last_state" ]] || (( waited % 600 == 0 )); then
        log "waiting for a screen (state: $state, ${waited}s so far)"
        last_state="$state"
    fi
    sleep "$POLL_SECONDS"
    waited=$(( waited + POLL_SECONDS ))
done
(( waited > 0 )) && log "screen ready after ${waited}s"

if [[ ! -x "$VENV/bin/picframe" ]]; then
    log "ERROR: display engine not found at $VENV/bin/picframe"
    exit 1
fi

log "starting display engine ($(readlink -f "$VENV"))"
export SDL_VIDEODRIVER=x11
started=$(date +%s)
"$VENV/bin/picframe"
rc=$?
ran=$(( $(date +%s) - started ))
log "display engine exited (code $rc after ${ran}s); ending labwc so picframe.service restarts"

# A quick exit would otherwise restart in a tight loop and hit systemd's start limit.
(( ran < 30 )) && sleep "${WW_QUICK_EXIT_SLEEP:-15}"

if ! labwc --exit 2>/dev/null; then
    pkill -TERM -u "$(id -u)" -x labwc || log "ERROR: could not end labwc"
fi
