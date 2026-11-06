#!/bin/bash
# Screen detection shared by start_picframe.sh, update_engine.sh and their tests (PL-187).
# Sourced, not run. Defines screen_state, which prints one word:
#   none    no connected HDMI screen (/sys/class/drm/card*-HDMI-*/status)
#   asleep  a screen is connected but the compositor has every output off (display sleep)
#   ready   a screen is connected and, when wlr-randr can answer, an output is on
# The display engine crashes for good when started with no screen (screen height 0), so
# callers wait for "ready" before starting it.
#
# Test overrides: WW_DRM_DIR (default /sys/class/drm), WW_WLR_RANDR (default wlr-randr).

screen_state() {
    local drm_dir="${WW_DRM_DIR:-/sys/class/drm}"
    local randr="${WW_WLR_RANDR:-wlr-randr}"
    local status_file connected=false out

    for status_file in "$drm_dir"/card*-HDMI-*/status; do
        [[ -f "$status_file" ]] || continue
        if [[ "$(cat "$status_file" 2>/dev/null)" == "connected" ]]; then
            connected=true
            break
        fi
    done
    if ! $connected; then
        echo "none"
        return 0
    fi

    # wlr-randr needs the compositor. If it's missing or can't answer (labwc not up yet),
    # the HDMI status is all we have.
    if ! command -v "$randr" > /dev/null 2>&1; then
        echo "ready"
        return 0
    fi
    if ! out=$(XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
               WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
               "$randr" 2>/dev/null) || [[ -z "$out" ]]; then
        echo "ready"
        return 0
    fi
    if grep -q '^[[:space:]]*Enabled:[[:space:]]*yes' <<< "$out"; then
        echo "ready"
    else
        echo "asleep"
    fi
}
