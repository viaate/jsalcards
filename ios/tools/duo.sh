#!/bin/bash
# The iPhone Duo, measured. tour.sh runs this on the iOS 27 leg only, after its own tour,
# with the tour's phone shut down, and gives it DUO_BUDGET: the seconds it may take before
# the job's 30 minutes are in danger. Each stage starts only if the budget still holds it.
#
# What the first run found (iOS app run 43129256570, job 130889026453): the
# "iPhone Duo" device type (iPhone19,4) is made by the iOS 27.1 runtime and by the 27.2
# runtime built for it, not by the ordinary 27.2. A booted Duo has two screens, and simctl
# needs one named for every picture: --display=1 is "LCD", the outer display, 1398 x 2034
# pixels at 3x; --display=3 is "LCD-1", the inner display, 2007 x 2853 at 3x. The app
# starts on the outer one. simctl's only control of a screen is
# `io <device> screenConfig --display=<n> power on|off` (and `geometry`); there is no fold
# command.
#
# So this script, for whoever reads the log:
#   1. boots a Duo on iOS 27.1 (the owner's phone's version) or, failing that, the other
#      runtime that makes one;
#   2. starts the app on My School (light) and pictures both screens: the closed phone;
#   3. powers the inner screen on, pictures both screens, then powers the outer one off
#      and pictures both again: the open phone, if that is what the two switches mean;
#      the app's own lines (Tour/TourGeometry.swift) say what size its window was given
#      after each switch, without a relaunch;
#   4. starts the app again on Settings (dark) with the phone open, and pictures it;
#   5. asks the inner screen for a landscape geometry (2853 x 2007) and pictures it;
#   6. prints every picture as a coarse grid of colors (tools/grid.swift), because the
#      pictures of this leg stay in its own artifact.
# It judges nothing and never fails the job: whatever it cannot do, it says, and goes on.
# Its pictures go to ios/out/duo/, which shots.sh makes small with the others.
#
# Bash 3.2 on macOS: no associative arrays, no mapfile.
set -uo pipefail
BUNDLE=com.snowlightmap.app
APP="$RUNNER_TEMP/dd/Build/Products/Debug-iphonesimulator/Snowlight.app"
DUO="iPhone Duo"
OUTER=1
INNER=3
BUDGET=${DUO_BUDGET:-600}
OUT=ios/out
mkdir -p "$OUT/duo" "$OUT/logs"
LOGS="$(cd "$OUT/logs" && pwd)"
GRID="$RUNNER_TEMP/grid"

# limit <seconds> <command...>: the command, stopped when the time is up (macOS has no
# timeout command; perl's alarm outlives the exec).
limit() {
  local seconds=$1; shift
  perl -e 'alarm shift; exec @ARGV or die "exec failed: $!\n"' "$seconds" "$@"
}
# room <seconds> <what>: true when the budget still holds that many seconds.
room() {
  if [ $((BUDGET - SECONDS)) -ge "$1" ]; then return 0; fi
  echo "::warning::The Duo measurement stopped before $2: $((BUDGET - SECONDS)) of its $BUDGET seconds were left."
  return 1
}
say() { echo "[duo $SECONDS s] $*"; }

say "budget $BUDGET s"
# The grid tool is built while the simulator boots.
xcrun swiftc -O ios/tools/grid.swift -o "$GRID" >"$LOGS/grid-build.txt" 2>&1 &
GRID_BUILD=$!

DEVTYPE=$(xcrun simctl list devicetypes -j | jq -r --arg d "$DUO" '[.devicetypes[] | select(.name == $d) | .identifier] | first // empty')
if [ -z "$DEVTYPE" ]; then
  echo "::warning::This image has no '$DUO' device type."
  xcrun simctl list devicetypes | grep -i iphone || true
  exit 0
fi
# The runtimes that list the Duo: 27.1 first, then the others, newest first.
RUNTIMES=$(xcrun simctl list runtimes -j | jq -r --arg d "$DEVTYPE" '[.runtimes[]
  | select(.isAvailable and ((.name // "") | startswith("iOS 27."))
      and (((.supportedDeviceTypes // []) | map(.identifier) | index($d)) != null))]
  | sort_by((if .version == "27.1" then 1 else 0 end), (.version | split(".") | map(tonumber)))
  | reverse | .[] | "\(.identifier)"')
echo "runtimes that make an '$DUO', in the order tried: $(echo $RUNTIMES)"
RUNTIME=""
UDID=""
for CANDIDATE in $RUNTIMES; do
  if UDID=$(xcrun simctl create snowlight-duo "$DEVTYPE" "$CANDIDATE" 2>"$LOGS/duo-create.txt"); then
    RUNTIME=$CANDIDATE
    break
  fi
  UDID=""
  echo "runtime $CANDIDATE did not make an '$DUO': $(tr '\n' ' ' < "$LOGS/duo-create.txt")"
done
if [ -z "$UDID" ]; then
  echo "::warning::No runtime on this image makes an '$DUO'."
  exit 0
fi
trap 'xcrun simctl shutdown "$UDID" >/dev/null 2>&1 || true; xcrun simctl delete "$UDID" >/dev/null 2>&1 || true' EXIT
say "an '$DUO' on $RUNTIME: $UDID"
room 300 "the boot" || exit 0
if ! limit 280 xcrun simctl boot "$UDID" || ! limit 280 xcrun simctl bootstatus "$UDID" -b >/dev/null; then
  echo "::warning::The '$DUO' did not boot in time."
  exit 0
fi
say "the Duo is up"
xcrun simctl status_bar "$UDID" override --time "9:41" --batteryState charged --batteryLevel 100 \
  --wifiBars 3 --cellularBars 4 || echo "the status bar override was refused"
if wait "$GRID_BUILD"; then
  say "grid.swift built"
else
  echo "grid.swift did not build:"; tail -20 "$LOGS/grid-build.txt"
  GRID=""
fi

# screens <label>: the screens' states as simctl's IO ports list them. enumerate keeps
# running after its list, so it is given a terminal (its output is not held back) and
# stopped after 12 seconds.
screens() {
  echo "--- the IO ports ($1)"
  limit 12 script -q /dev/null xcrun simctl io "$UDID" enumerate 2>&1 | tr -d '\r' | head -80
}
# shoot <name> <screen>: a picture of one screen, its size, and its grid.
shoot() {
  local name=$1 screen=$2 file="$OUT/duo/$1.png"
  if limit 60 xcrun simctl io "$UDID" screenshot --type=png --display="$screen" "$file" >"$LOGS/duo-shot.txt" 2>&1; then
    say "$name: $(sips -g pixelWidth -g pixelHeight "$file" | tail -2 | tr -s ' \n' ' ')"
    if [ -n "$GRID" ]; then "$GRID" 64 "$file" || true; fi
  else
    say "$name: no picture of screen $screen: $(tr '\n' ' ' < "$LOGS/duo-shot.txt" | cut -c1-300)"
    rm -f "$file"
  fi
}
# power <screen> <on|off>: simctl's switch of a screen.
power() {
  if limit 30 xcrun simctl io "$UDID" screenConfig --display="$1" power "$2" >"$LOGS/duo-power.txt" 2>&1; then
    say "screen $1 power $2: done $(tr '\n' ' ' < "$LOGS/duo-power.txt" | cut -c1-200)"
  else
    say "screen $1 power $2: refused: $(tr '\n' ' ' < "$LOGS/duo-power.txt" | cut -c1-300)"
  fi
}
# lines <name>: the app's geometry lines of a launch so far.
lines() {
  grep -E "geometry|error|could not" "$LOGS/$1.err" 2>/dev/null | cut -c1-900 || echo "(no lines from the app)"
}
DATA=""
# launch <light|dark> <name> <screen>: the app on a tour screen, waited for.
launch() {
  local mode=$1 name=$2 screen=$3 i=0 ready
  xcrun simctl ui "$UDID" appearance "$mode" || true
  if [ -n "$DATA" ]; then rm -f "$DATA/Documents/tour/$name.txt"; fi
  if ! limit 150 xcrun simctl launch --terminate-running-process \
      --stdout="$LOGS/$name.out" --stderr="$LOGS/$name.err" "$UDID" "$BUNDLE" \
      -tour.screen "$screen" -tour.name "$name" >/dev/null; then
    say "the app did not start for '$name'"
    return 1
  fi
  if [ -z "$DATA" ]; then DATA=$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data 2>/dev/null || true); fi
  ready="$DATA/Documents/tour/$name.txt"
  while [ ! -f "$ready" ] && [ $i -lt 300 ] && [ $((BUDGET - SECONDS)) -gt 60 ]; do sleep 0.5; i=$((i + 1)); done
  if [ -f "$ready" ]; then say "'$name' is ready"; else say "'$name' never said it was ready"; fi
  sleep 2
}

screens "booted"
room 200 "the install" || exit 0
if ! limit 180 xcrun simctl install "$UDID" "$APP"; then
  echo "::warning::The app could not be installed on the '$DUO'."
  exit 0
fi
say "the app is installed"

echo "=== Closed: the app on My School, light"
room 150 "the first launch" || exit 0
launch light duo-closed-light-myschool myschool || exit 0
shoot duo-closed-light-myschool "$OUTER"
shoot duo-closed-light-myschool-inner "$INNER"
lines duo-closed-light-myschool

echo "=== Opening: the inner screen on, then the outer one off, the app left running"
room 60 "the opening" || exit 0
power "$INNER" on
sleep 4
screens "inner on"
shoot duo-inner-on-light-myschool-outer "$OUTER"
shoot duo-inner-on-light-myschool "$INNER"
power "$OUTER" off
sleep 4
screens "outer off"
shoot duo-open-light-myschool "$INNER"
shoot duo-open-light-myschool-outer "$OUTER"
echo "--- the app's lines since it started, after both switches"
lines duo-closed-light-myschool

echo "=== Open: the app started again, on Settings, dark"
if room 100 "the launch on the open phone"; then
  launch dark duo-open-dark-settings settings && {
    shoot duo-open-dark-settings "$INNER"
    lines duo-open-dark-settings
  }
fi

echo "=== Open, landscape: the inner screen asked for 2853 x 2007"
if room 40 "the landscape try"; then
  if limit 30 xcrun simctl io "$UDID" screenConfig --display="$INNER" geometry 2853x2007@3 >"$LOGS/duo-geometry.txt" 2>&1; then
    say "geometry 2853x2007@3: done $(tr '\n' ' ' < "$LOGS/duo-geometry.txt" | cut -c1-200)"
    sleep 4
    shoot duo-open-landscape-dark-settings "$INNER"
    lines duo-open-dark-settings
  else
    say "geometry 2853x2007@3: refused: $(tr '\n' ' ' < "$LOGS/duo-geometry.txt" | cut -c1-300)"
  fi
fi
ls -l "$OUT/duo" || true
say "the Duo measured"
exit 0
