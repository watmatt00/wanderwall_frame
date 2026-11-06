#!/bin/bash
# Display engine updater simulator (KP-020). Run on the PC from anywhere:
#   tests/sim/engine/run_sim.sh [kframe-2024.11.1] [mnbframe-2024.9.24]
#   SIM_PIN=<pin file> tests/sim/engine/run_sim.sh …   test that pin instead of the repo's
# Builds an arm64 bookworm image (Python 3.11.2, like kframe and mnbframe) and runs
# scenario.sh once per frame profile in a fresh container, with the repo mounted read-only.
# Needs podman and qemu-user binfmt for aarch64. Slow (emulated): several minutes per profile.
set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SIM_DIR/../../.." && pwd)"
IMAGE="localhost/wanderwall-engine-sim:bookworm"
PROFILES=("$@")
(( ${#PROFILES[@]} )) || PROFILES=(kframe-2024.11.1 mnbframe-2024.9.24)

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }

[[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]] || { log "ERROR: no qemu-aarch64 binfmt; can't run arm64 containers" >&2; exit 1; }
for p in "${PROFILES[@]}"; do
    [[ "$p" =~ ^[a-z]+-[0-9.]+$ && -f "$SIM_DIR/$p.txt" ]] || { log "ERROR: unknown profile $p" >&2; exit 1; }
done

log "Building $IMAGE (linux/arm64)"
podman build -q --platform linux/arm64 -t "$IMAGE" -f "$SIM_DIR/Containerfile" "$SIM_DIR" > /dev/null

PIN_ARGS=()
if [[ -n "${SIM_PIN:-}" ]]; then
    [[ -f "$SIM_PIN" ]] || { log "ERROR: SIM_PIN file not found: $SIM_PIN" >&2; exit 1; }
    PIN_ARGS=(-v "$(realpath "$SIM_PIN"):/pin/picframe-requirements.txt:ro,Z" -e SIM_PIN_FILE=/pin/picframe-requirements.txt)
    log "Testing pin $SIM_PIN"
fi

status=0
for p in "${PROFILES[@]}"; do
    log "Profile $p: starting container"
    if podman run --rm --platform linux/arm64 \
        -v "$REPO:/repo:ro,Z" -v "$SIM_DIR:/sim:ro,Z" "${PIN_ARGS[@]}" \
        "$IMAGE" bash /sim/scenario.sh "$p"; then
        log "Profile $p: passed"
    else
        log "ERROR: Profile $p: failed"
        status=1
    fi
done
exit $status
