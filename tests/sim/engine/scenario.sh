#!/bin/bash
# Runs inside the simulator container (KP-020) as user pi. One frame profile per run:
#   scenario.sh kframe-2024.11.1 | mnbframe-2024.9.24
# Builds that frame's engine exactly as it is today (a real ~/venv_picframe folder), then runs
# the real scripts/setup/update_engine.sh from the repo (mounted at /repo, read-only) through:
#   1. hold flag set (as install.sh --from-v4 leaves it)  -> on_hold, nothing changes
#   2. hold cleared, new engine forced to crash            -> first conversion, rollback to old
#   3. normal upgrade                                      -> link to the pinned engine
#   4. second run                                          -> nothing to do, no restart
#   5. bad pin (version that doesn't exist)                -> build fails, engine untouched
# Prints PASS/FAIL per check and exits 1 on any failure.
set -uo pipefail

PROFILE="${1:?usage: scenario.sh <profile>}"
[[ "$PROFILE" =~ ^[a-z]+-[0-9.]+$ && -f "/sim/$PROFILE.txt" ]] || { echo "unknown profile: $PROFILE" >&2; exit 2; }
OLD="${PROFILE#*-}"
UPDATE_ENGINE=/repo/scripts/setup/update_engine.sh
PIN_FILE=/repo/scripts/setup/picframe-requirements.txt
NEW="$(sed -nE 's/^picframe==([0-9.]+).*/\1/p' "$PIN_FILE")"
LINK="$HOME/venv_picframe"
STATE="$HOME/.wanderwall/engine.yaml"
FAILS=0

ts()   { date +'%H:%M:%S'; }
say()  { echo "[$(ts)] $*"; }
pass() { echo "[$(ts)] PASS  $*"; }
fail() { echo "[$(ts)] FAIL  $*"; FAILS=$(( FAILS + 1 )); }
check() { local desc="$1"; shift; if "$@"; then pass "$desc"; else fail "$desc"; fi; }

state_of() { sed -nE "s/^$1: '(.*)'$/\1/p" "$STATE" 2>/dev/null | head -n 1; }
answer()   { curl -s --max-time 5 http://127.0.0.1:9000/ || true; }
answers_with() { answer | grep -qF "picframe $1 from $2"; }

mkdir -p "$HOME/.sim/drm/card1-HDMI-A-1" "$HOME/.wanderwall/logs"
echo connected > "$HOME/.sim/drm/card1-HDMI-A-1/status"
export WW_SYSTEMCTL=/sim/systemctl WW_DRM_DIR="$HOME/.sim/drm" WW_WLR_RANDR=/nonexistent

run_update() {
    # run_update <label> [extra env...]; sets RC
    local label="$1"; shift
    say "── update_engine.sh: $label"
    local start=$SECONDS
    env "$@" bash "$UPDATE_ENGINE" > "$HOME/.sim/run.out" 2>&1
    RC=$?
    sed 's/^/        /' "$HOME/.sim/run.out"
    say "   exit $RC after $(( SECONDS - start ))s; result '$(state_of last_result)'"
}

say "Profile $PROFILE: build today's engine ($OLD) as a real folder"
start=$SECONDS
python3 -m venv "$LINK" \
  && "$LINK/bin/python" -m pip install -q --no-cache-dir --disable-pip-version-check -r "/sim/$PROFILE.txt" \
  || { echo "could not build the starting engine" >&2; exit 2; }
say "   built in $(( SECONDS - start ))s; $(head -n 1 "$LINK/bin/picframe")"
/sim/systemctl --user start picframe.service
for _ in $(seq 1 60); do answers_with "$OLD" "$LINK" && break; sleep 1; done
check "starting engine $OLD answers on :9000" answers_with "$OLD" "$LINK"

# 1. Hold flag (install.sh --from-v4)
printf '%s\n' "# Written by install.sh --from-v4" "upgrade: hold" > "$STATE"
run_update "1. hold flag set"
check "1. exit 0" test "$RC" -eq 0
check "1. result on_hold" test "$(state_of last_result)" == on_hold
check "1. ~/venv_picframe still a real folder" test -d "$LINK" -a ! -L "$LINK"
check "1. no build folder for $NEW" test ! -e "$HOME/venv_picframe-$NEW"
check "1. old engine still answering" answers_with "$OLD" "$LINK"
check "1. hold flag kept" grep -qx "upgrade: hold" "$STATE"

# 2. Hold cleared (the Upgrade button), new engine crashes -> rollback after the first conversion
sed -i '/^upgrade: hold$/d' "$STATE"
run_update "2. forced failure of $NEW" SIM_FAIL_VERSION="$NEW"
OLD_DIR="$HOME/venv_picframe-$OLD"
check "2. exit 1" test "$RC" -eq 1
check "2. result rolled_back" test "$(state_of last_result)" == rolled_back
check "2. link now points at $OLD_DIR" test "$(readlink "$LINK")" == "$OLD_DIR"
check "2. failed $NEW folder removed" test ! -e "$HOME/venv_picframe-$NEW"
check "2. old engine's shebangs name its new folder" grep -qx "#!$OLD_DIR/bin/python" <(head -n 1 "$OLD_DIR/bin/picframe")
check "2. old engine's activate names its new folder" grep -q "$OLD_DIR" "$OLD_DIR/bin/activate"
check "2. old engine answers again, from its renamed folder" answers_with "$OLD" "$LINK"
check "2. renamed old engine's pip still runs" "$OLD_DIR/bin/pip" --version

# 3. Normal upgrade
run_update "3. upgrade to $NEW"
NEW_DIR="$HOME/venv_picframe-$NEW"
check "3. exit 0" test "$RC" -eq 0
check "3. result ok" test "$(state_of last_result)" == ok
check "3. installed_version $NEW, previous $OLD" test "$(state_of installed_version)/$(state_of previous_version)" == "$NEW/$OLD"
check "3. link points at $NEW_DIR" test "$(readlink "$LINK")" == "$NEW_DIR"
check "3. new engine answers" answers_with "$NEW" "$LINK"
check "3. previous engine kept for rollback" test -d "$OLD_DIR"
check "3. new engine's packages match the pin" bash -c "comm -23 <(grep -E '^[A-Za-z]' '$PIN_FILE' | tr A-Z a-z | tr _ - | sort) <('$NEW_DIR/bin/python' -m pip freeze | tr A-Z a-z | tr _ - | sort) | grep -q . && exit 1 || exit 0"

# 4. Second run: nothing to do
: > "$HOME/.sim/systemctl.log"
run_update "4. second run"
check "4. exit 0" test "$RC" -eq 0
check "4. result up_to_date" test "$(state_of last_result)" == up_to_date
check "4. no systemctl call" test ! -s "$HOME/.sim/systemctl.log"
check "4. new engine still answering" answers_with "$NEW" "$LINK"

# 5. Bad pin: a version that doesn't exist on PyPI
sed 's/^picframe==.*/picframe==2099.1.1/' "$PIN_FILE" > "$HOME/.sim/bad-pin.txt"
run_update "5. bad pin (picframe==2099.1.1)" WW_REQUIREMENTS="$HOME/.sim/bad-pin.txt"
check "5. exit 1" test "$RC" -eq 1
check "5. result failed" test "$(state_of last_result)" == failed
check "5. link unchanged" test "$(readlink "$LINK")" == "$NEW_DIR"
check "5. no 2099.1.1 folder left" test ! -e "$HOME/venv_picframe-2099.1.1"
check "5. engine still answering" answers_with "$NEW" "$LINK"

say "── wanderwall.log ([update_engine] lines)"
grep -F "[update_engine]" "$HOME/.wanderwall/logs/wanderwall.log" | sed 's/^/        /'
if (( FAILS == 0 )); then say "RESULT $PROFILE: all checks passed"; else say "RESULT $PROFILE: $FAILS check(s) failed"; fi
(( FAILS == 0 ))
