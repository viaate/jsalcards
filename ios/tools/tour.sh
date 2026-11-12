#!/bin/bash
# The picture tour: one picture per screen, taken from the real simulator screen, in light
# and in dark.
#
# For each picture the app is started with launch arguments that name the screen and the
# picture. The app (debug builds only) shows that screen and then writes the words of the
# screen's model to a file in its own Documents folder. This script waits for that file,
# takes the picture, prints the words and compares them with ios/tools/tour-words/.
#
# What the words file is: every string the screen's model offers the view. It is not a
# reading of the screen.
#
# The last picture is the machine probe. It has no words: its file holds two facts about
# the machine it ran on, so it is printed and never compared.
#
# Bash 3.2 on macOS: no associative arrays, no mapfile.
set -euo pipefail
BUNDLE=com.snowlightmap.app
APP="$RUNNER_TEMP/dd/Build/Products/Debug-iphonesimulator/Snowlight.app"
OUT=ios/out
mkdir -p "$OUT/full/light" "$OUT/full/dark" "$OUT/words" "$OUT/logs"
LOGS="$(cd "$OUT/logs" && pwd)"

if [ ! -d "$APP" ]; then
  echo "::error::There is no built app at $APP."
  exit 1
fi

# Our own device, from what this image has, addressed by id (a name can be missing or doubled).
DEVTYPE=$(xcrun simctl list devicetypes -j | jq -r --arg d "$SIM_DEVICE" \
  '[.devicetypes[] | select(.name == $d) | .identifier] | first // empty')
if [ -z "$DEVTYPE" ]; then
  echo "::error::No '$SIM_DEVICE' on this image."
  xcrun simctl list devicetypes; exit 1
fi
echo "device type: $DEVTYPE"
# The runtimes whose name starts with the prefix, newest first. Two can share a version
# (the xcode-27 image has an iOS 27.2 made for one new phone only, beside the ordinary
# iOS 27.2), and a runtime refuses a device it was not made for ("Incompatible device").
# So the device is made on each in turn, and the first runtime that accepts it is used.
RUNTIMES=$(xcrun simctl list runtimes -j | jq -r --arg p "$SIM_OS_PREFIX" \
  '[.runtimes[] | select(.isAvailable and ((.name // "") | startswith($p)))]
   | sort_by(.version | split(".") | map(tonumber)) | reverse | .[].identifier')
RUNTIME=""
UDID=""
for CANDIDATE in $RUNTIMES; do
  if UDID=$(xcrun simctl create snowlight-ci "$DEVTYPE" "$CANDIDATE" 2>"$LOGS/simctl-create.txt"); then
    RUNTIME=$CANDIDATE
    break
  fi
  UDID=""
  echo "runtime $CANDIDATE did not make a '$SIM_DEVICE': $(tr '\n' ' ' < "$LOGS/simctl-create.txt")"
done
if [ -z "$RUNTIME" ] || [ -z "$UDID" ]; then
  echo "::error::No '$SIM_OS_PREFIX' runtime on this image makes a '$SIM_DEVICE'."
  xcrun simctl list runtimes; exit 1
fi
echo "runtime: $RUNTIME"
trap 'xcrun simctl shutdown "$UDID" >/dev/null 2>&1 || true; xcrun simctl delete "$UDID" >/dev/null 2>&1 || true' EXIT
echo "device: $UDID"
xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" -b
echo "[$SECONDS s] the simulator is up"
xcrun simctl install "$UDID" "$APP"
echo "[$SECONDS s] the app is installed"
xcrun simctl status_bar "$UDID" override --time "9:41" --batteryState charged --batteryLevel 100 \
  --wifiBars 3 --cellularBars 4 || echo "::warning::The status bar override was refused."

FAILED=0
FIRST=1
MISSES=0
DATA=""
app_data() {  # the app's data container, read once: it stays the same for every launch of this install
  if [ -z "$DATA" ]; then
    DATA=$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data 2>/dev/null || true)
    if [ -n "$DATA" ]; then echo "[$SECONDS s] the app's data container: $DATA"; fi
  fi
}
say_why() {  # everything the machine knows about a screen that never came up
  local name=$1 ips
  echo "--- the app's own output for '$name'"
  tail -40 "$LOGS/$name.err" 2>/dev/null || echo "(no stderr file)"
  tail -20 "$LOGS/$name.out" 2>/dev/null || echo "(no stdout file)"
  for ips in "$HOME"/Library/Logs/DiagnosticReports/Snowlight*.ips; do
    [ -e "$ips" ] || continue
    echo "--- crash report $ips"; head -80 "$ips"
  done
  xcrun simctl spawn "$UDID" log show --last 2m --style compact \
    --predicate 'process == "Snowlight"' | tail -40 || true
}
start_app() {  # start_app <picture name> <screen> [more launch arguments]; 0 when the app was started
  local name=$1 screen=$2; shift 2
  # The app's output goes to two files. If this simctl refuses the two flags, the app is
  # started without them, and the system log and the crash reports are what is left.
  if xcrun simctl launch --terminate-running-process \
      --stdout="$LOGS/$name.out" --stderr="$LOGS/$name.err" "$UDID" "$BUNDLE" \
      -tour.screen "$screen" -tour.name "$name" ${1+"$@"}; then
    return 0
  fi
  echo "::warning::simctl launch with --stdout and --stderr failed for '$name'. Trying without them."
  sleep 3
  xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE" \
    -tour.screen "$screen" -tour.name "$name" ${1+"$@"}
}
shoot() {  # shoot <light|dark> <picture name> <screen> <diff|nodiff> [more launch arguments]
  local mode=$1 name=$2 screen=$3 check=$4; shift 4
  local limit=120 tries=0 i ready=""
  # The first launch on a cold hosted simulator is slow: up to 120 seconds. Later ones: 60.
  if [ "$FIRST" = 1 ]; then limit=240; FIRST=0; fi
  # If the look cannot be set, the picture is still taken: its pixel line is the judge.
  xcrun simctl ui "$UDID" appearance "$mode" \
    || echo "::warning::The simulator's look could not be set to $mode for '$name'."
  while [ $tries -lt 2 ]; do
    tries=$((tries + 1))
    # A words file left by an earlier try must not be taken for this try's.
    app_data
    if [ -n "$DATA" ]; then rm -f "$DATA/Documents/tour/$name.txt"; fi
    if ! start_app "$name" "$screen" ${1+"$@"}; then
      echo "::warning::simctl launch failed for '$name' (try $tries)."
      sleep 5
      continue
    fi
    app_data
    ready="$DATA/Documents/tour/$name.txt"
    i=0
    while [ ! -f "$ready" ] && [ $i -lt $limit ]; do sleep 0.5; i=$((i + 1)); done
    if [ -f "$ready" ]; then break; fi
    echo "::warning::'$name' was not ready after try $tries."
  done
  if [ -z "$ready" ] || [ ! -f "$ready" ]; then
    echo "::error::The screen '$name' never said it was ready."
    say_why "$name"
    FAILED=1; MISSES=$((MISSES + 1))
    # Two in a row: the app is not coming up at all. Stop before the job's time runs out.
    if [ $MISSES -ge 2 ]; then echo "::error::Two screens in a row never came up. Stopping the tour."; exit 1; fi
    return 0
  fi
  MISSES=0
  # The words file is written about 0.6 seconds after the screen appears. Two seconds
  # more let a slow hosted simulator finish drawing before the picture is taken.
  sleep 2
  if ! xcrun simctl io "$UDID" screenshot --type=png "$OUT/full/$mode/$name.png"; then
    sleep 2
    xcrun simctl io "$UDID" screenshot --type=png "$OUT/full/$mode/$name.png" \
      || { echo "::error::No picture of '$name' could be taken."; FAILED=1; }
  fi
  cp "$ready" "$OUT/words/$name.txt"
  echo "[$SECONDS s] --- $name"; cat "$OUT/words/$name.txt"
  if [ "$check" = diff ]; then
    diff -u "ios/tools/tour-words/$name.txt" "$OUT/words/$name.txt" \
      || { echo "::error::The model's words for '$name' changed."; FAILED=1; }
  fi
  # Where the app's own output landed, and what it said.
  ls -l "$LOGS/$name.out" "$LOGS/$name.err" 2>&1 || true
  if [ ! -e "$LOGS/$name.err" ]; then
    find "$HOME/Library/Developer/CoreSimulator/Devices/$UDID/data" -name "$name.err" 2>/dev/null | head -3 || true
  fi
  head -20 "$LOGS/$name.err" 2>/dev/null || true
}

# Ten pictures: each of the five screens with the simulator in its light look and in its
# dark look, and the app on System.
for mode in light dark; do
  for screen in myschool map callit settings search; do
    shoot "$mode" "$mode-$screen" "$screen" diff
  done
done
# The stored choice beats the phone: forced Dark on a light simulator, forced Light on a
# dark one. Only keys that begin with tour. are passed, never the app's own key: a launch
# argument would shadow the stored value for the whole run.
shoot light light-settings-forced-dark settings diff -tour.appearance dark
shoot dark dark-settings-forced-light settings diff -tour.appearance light
# Started on a stored Dark with the simulator light, then switched back to System in code
# after the first frame. The picture must be light.
shoot light light-settings-dark-then-system settings diff -tour.appearance dark -tour.then system
# The simulator's language set to Spanish and a 24-hour region: do the words iOS itself
# draws change when the app ships English only? Judged by eye.
shoot light light-search-es search diff -AppleLanguages "(es)" -AppleLocale es_ES
# The machine probe: the top half of the screen is a Metal view cleared to one teal and
# presented once, with two glass controls over it. Its file holds facts about this machine
# (the Metal device's name, whether a drawable was presented), not words: it is printed
# and uploaded, never compared with a committed file. Whether the teal shows in the
# picture is read by ios/tools/pixels.swift and printed as yes or no.
shoot dark dark-probe probe nodiff
# On the iOS 27 leg only: the iPhone Duo, measured (tools/duo.sh). What it finds is printed;
# it never changes this tour's result. This tour's phone is shut down first, so that two
# simulators never run side by side on the runner's 7 GB.
if [ "$SIM_OS_PREFIX" = "iOS 27." ]; then
  xcrun simctl shutdown "$UDID" >/dev/null 2>&1 || true
  echo "[$SECONDS s] the iPhone Duo, measured by tools/duo.sh"
  bash ios/tools/duo.sh || echo "::warning::The Duo measurement ended with status $?."
fi
exit $FAILED
