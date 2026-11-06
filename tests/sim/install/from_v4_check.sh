#!/bin/bash
# Checks the blocks added to scripts/setup/install.sh on 2026-11-06 for the --from-v4 path
# (mnbframe, KP-027), in the bookworm simulator image, as root, against a v4-style home for
# user pi. The blocks are cut out of install.sh by their first and last lines, so the real
# text runs, not a copy:
#   A. branch-name check            B. hold flag in the --from-v4 block
#   C. Phase 9 unit copy loop       D. Phase 9 launcher install (--from-v4 skips Phase 8)
# then runs the real update_engine.sh as pi on mnbframe's engine (2024.9.24) to confirm the
# hold written by install.sh stops the upgrade. Not covered: systemctl enable --now (no
# systemd in the container; same form as the lines next to it).
# Run: tests/sim/install/run_from_v4_check.sh
set -uo pipefail

INSTALL=/repo/scripts/setup/install.sh
FAILS=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAILS=$(( FAILS + 1 )); }
check() { local d="$1"; shift; if "$@"; then pass "$d"; else fail "$d"; fi; }

# cut <first line> <last line>: the block of install.sh from the first exact line to the next exact last line
cut_block() {
    python3 - "$INSTALL" "$1" "$2" <<'PY'
import sys
lines = open(sys.argv[1]).read().split("\n")
first, last = sys.argv[2], sys.argv[3]
starts = [i for i, l in enumerate(lines) if l == first]
if len(starts) != 1:
    sys.exit(f"first line found {len(starts)} times: {first!r}")
s = starts[0]
for e in range(s, len(lines)):
    if lines[e] == last:
        print("\n".join(lines[s:e + 1]))
        break
else:
    sys.exit(f"last line not found after {first!r}")
PY
}

# The installer's helpers and variables, as install.sh defines them (as_user via runuser: no sudo here)
ACTUAL_USER=pi
ACTUAL_HOME=/home/pi
PROJECT_DIR=/repo
log() { echo "        [install.sh] $*"; }
as_user() { runuser -u "$ACTUAL_USER" -- "$@"; }

mkdir -p /tmp/blocks
cut_block '# Branch name goes into git commands and the engine pin URL: allow only a plain ref name.' 'fi' > /tmp/blocks/A.sh || exit 2
cut_block '    ENGINE_STATE="$ACTUAL_HOME/.wanderwall/engine.yaml"' '    fi' > /tmp/blocks/B.sh || exit 2
cut_block '    as_user mkdir -p "$ACTUAL_HOME/.config/systemd/user"' '    done' > /tmp/blocks/C.sh || exit 2
cut_block '    # --from-v4 skips Phase 8: point its start_picframe.sh at the launcher here (idempotent)' '        || log "  WARNING: display launcher not installed (see above)"' > /tmp/blocks/D.sh || exit 2
for b in A B C D; do echo "── block $b ($(wc -l < /tmp/blocks/$b.sh) lines)"; sed 's/^/        | /' /tmp/blocks/$b.sh; done

# ── A. branch-name check ─────────────────────────────────────────────────────
for good in main dev v5 feature/x release-5.0; do
    check "A. branch '$good' accepted" bash -c "BRANCH='$good'; log(){ :; }; set -e; source /tmp/blocks/A.sh"
done
# Refused names make the block exit 1
for bad in 'main;touch /tmp/pwned' '../x' '-x' 'a b' '$(id)' ''; do
    if bash -c "BRANCH=\"\$1\"; log(){ :; }; source /tmp/blocks/A.sh; exit 0" -- "$bad" > /dev/null 2>&1; then
        fail "A. branch '$bad' must be refused"
    else
        pass "A. branch '$bad' refused (exit 1)"
    fi
done
check "A. nothing ran from a branch name" test ! -e /tmp/pwned

# ── v4-style home, as on mnbframe (checked 2026-11-06) ───────────────────────
printf '#!/bin/bash\nsource ~/venv_picframe/bin/activate\nexport SDL_VIDEODRIVER=x11\npicframe &\n' > /home/pi/start_picframe.sh
chmod 755 /home/pi/start_picframe.sh
mkdir -p /home/pi/.config/labwc && echo /home/pi/start_picframe.sh > /home/pi/.config/labwc/autostart
chown -R pi:pi /home/pi
echo "── building mnbframe's engine (2024.9.24) as pi"
runuser -u pi -- python3 -m venv /home/pi/venv_picframe
runuser -u pi -- /home/pi/venv_picframe/bin/python -m pip install -q --no-cache-dir --disable-pip-version-check \
    -r /sim/mnbframe-2024.9.24.txt || exit 2

# ── B. hold flag (the --from-v4 block creates ~/.wanderwall first) ───────────
install -d -m 700 -o "$ACTUAL_USER" -g "$ACTUAL_USER" "$ACTUAL_HOME/.wanderwall"
out=$(set -e; source /tmp/blocks/B.sh 2>&1); rc=$?
echo "$out"
check "B. block exits 0" test "$rc" -eq 0
check "B. engine.yaml written" test -f /home/pi/.wanderwall/engine.yaml
check "B. contains 'upgrade: hold'" grep -qx 'upgrade: hold' /home/pi/.wanderwall/engine.yaml
check "B. owned by pi" test "$(stat -c %U:%G /home/pi/.wanderwall/engine.yaml)" == pi:pi
check "B. mode 600" test "$(stat -c %a /home/pi/.wanderwall/engine.yaml)" == 600
check "B. logs the hold" grep -q "upgrade is on hold" <<< "$out"
before=$(cat /home/pi/.wanderwall/engine.yaml)
out2=$(set -e; source /tmp/blocks/B.sh 2>&1)
check "B. second run changes nothing" test "$(cat /home/pi/.wanderwall/engine.yaml)" == "$before"
check "B. second run logs nothing" test -z "$out2"
check "B. the app's YAML reader sees on_hold" /home/pi/venv_picframe/bin/python -c "
import yaml, sys
d = yaml.safe_load(open('/home/pi/.wanderwall/engine.yaml'))
sys.exit(0 if str(d.get('upgrade', '')).strip().lower() == 'hold' else 1)"

# ── C. Phase 9 unit copy loop ────────────────────────────────────────────────
out=$(set -e; source /tmp/blocks/C.sh 2>&1); rc=$?
echo "$out"
check "C. block exits 0" test "$rc" -eq 0
for u in wanderwall-api.service wanderwall-sync.service wanderwall-sync.timer wanderwall-lights.service \
         wanderwall-display-watch.service wanderwall-display-watch.timer; do
    check "C. $u copied, owned by pi" test "$(stat -c %U /home/pi/.config/systemd/user/$u 2>/dev/null)" == pi
done
check "C. no 'not found' warning" bash -c "! grep -q 'not found' <<< \"\$1\"" -- "$out"

# ── D. Phase 9 launcher install ──────────────────────────────────────────────
out=$( source /tmp/blocks/D.sh 2>&1 ); rc=$?
echo "$out"
check "D. block exits 0" test "$rc" -eq 0
check "D. start_picframe.sh now runs the repo launcher" grep -qF '"/repo/scripts/display/start_picframe.sh" &' /home/pi/start_picframe.sh
check "D. original kept as .pre-launcher" grep -qx 'picframe &' /home/pi/start_picframe.sh.pre-launcher
check "D. start_picframe.sh owned by pi, executable" test "$(stat -c %U:%a /home/pi/start_picframe.sh)" == pi:755
check "D. no warning" bash -c "! grep -q WARNING <<< \"\$1\"" -- "$out"

# ── update_engine.sh honours the hold install.sh wrote ───────────────────────
mkdir -p /home/pi/.sim/drm/card1-HDMI-A-1 && echo connected > /home/pi/.sim/drm/card1-HDMI-A-1/status
chown -R pi:pi /home/pi/.sim
out=$(runuser -u pi -- env HOME=/home/pi WW_SYSTEMCTL=/sim/systemctl WW_DRM_DIR=/home/pi/.sim/drm WW_WLR_RANDR=/nonexistent \
      WW_REQUIREMENTS="${SIM_PIN_FILE:-/repo/scripts/setup/picframe-requirements.txt}" bash /repo/scripts/setup/update_engine.sh 2>&1); rc=$?
echo "$out" | sed 's/^/        /'
check "E. update_engine.sh exits 0" test "$rc" -eq 0
check "E. upgrade on hold" grep -q "upgrade on hold (2024.9.24 installed" <<< "$out"
check "E. engine folder untouched (still a real folder)" test -d /home/pi/venv_picframe -a ! -L /home/pi/venv_picframe
check "E. hold still set" grep -qx 'upgrade: hold' /home/pi/.wanderwall/engine.yaml
check "E. engine.yaml still owned by pi, mode 600" test "$(stat -c %U:%a /home/pi/.wanderwall/engine.yaml)" == pi:600

if (( FAILS == 0 )); then echo "RESULT from-v4 blocks: all checks passed"; else echo "RESULT from-v4 blocks: $FAILS check(s) failed"; fi
(( FAILS == 0 ))
