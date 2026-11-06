#!/bin/bash
# Runs from_v4_check.sh in the bookworm simulator image (built by tests/sim/engine/run_sim.sh),
# as root, with the repo and the engine simulator files mounted read-only.
#   tests/sim/install/run_from_v4_check.sh
#   SIM_PIN=<pin file> tests/sim/install/run_from_v4_check.sh   (pin other than the repo's)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$DIR/../../.." && pwd)"
IMAGE="localhost/wanderwall-engine-sim:bookworm"
podman build -q --platform linux/arm64 -t "$IMAGE" -f "$REPO/tests/sim/engine/Containerfile" "$REPO/tests/sim/engine" > /dev/null
PIN_ARGS=()
[[ -n "${SIM_PIN:-}" ]] && PIN_ARGS=(-v "$(realpath "$SIM_PIN"):/pin/picframe-requirements.txt:ro,Z" -e SIM_PIN_FILE=/pin/picframe-requirements.txt)
exec podman run --rm --platform linux/arm64 --user root \
    -v "$REPO:/repo:ro,Z" -v "$REPO/tests/sim/engine:/sim:ro,Z" -v "$DIR:/check:ro,Z" "${PIN_ARGS[@]}" \
    "$IMAGE" bash /check/from_v4_check.sh
