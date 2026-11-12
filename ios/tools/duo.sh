#!/bin/bash
# The iPhone Duo, measured. tour.sh runs this on the iOS 27 leg only, after its own tour,
# with the tour's phone shut down.
#
# It finds out, and prints for whoever reads the job's log:
#   1. the SDK the app was built with (the Duo's screens are filled only by an app built
#      with the iOS 27.1 SDK or newer);
#   2. the "iPhone Duo" device type: what its bundle says about its displays, and which
#      runtimes of this image make one;
#   3. what simctl offers for a phone with two displays: every command whose help names a
#      fold, a posture, a hinge or a display, and the displays a booted Duo has;
#   4. pictures of each display the simulator hands out, first on the Home Screen and then
#      with the app on My School (light) and on Settings (dark), and the app's own lines
#      about the window it was given: size in points, safe area, size classes, and where
#      the system put its bars (Tour/TourGeometry.swift);
#   5. each picture again as a coarse grid of colors (tools/grid.swift), because the
#      pictures of this leg stay in its own artifact.
#
# It judges nothing and never fails the job: whatever it cannot do, it says, and goes on.
# Its pictures go to ios/out/duo/, which shots.sh makes small with the others.
#
# Bash 3.2 on macOS: no associative arrays, no mapfile.
set -uo pipefail
BUNDLE=com.snowlightmap.app
APP="$RUNNER_TEMP/dd/Build/Products/Debug-iphonesimulator/Snowlight.app"
DUO="iPhone Duo"
OUT=ios/out
mkdir -p "$OUT/duo" "$OUT/logs"
LOGS="$(cd "$OUT/logs" && pwd)"

# limit <seconds> <command...>: the command, stopped when the time is up (macOS has no
# timeout command; perl's alarm outlives the exec).
limit() {
  local seconds=$1; shift
  perl -e 'alarm shift; exec @ARGV or die "exec failed: $!\n"' "$seconds" "$@"
}

echo "=== 1. The SDK the app was built with"
xcodebuild -version
xcrun --sdk iphonesimulator --show-sdk-version
xcrun --sdk iphonesimulator --show-sdk-build-version
xcodebuild -showsdks 2>&1 | grep -i -E "ios|simulator" || true
plutil -p "$APP/Info.plist" | grep -E '"(DT[A-Za-z]+|MinimumOSVersion|BuildMachineOSBuild)"' || true

echo "=== 2. The device types of this image"
xcrun simctl list devicetypes
TYPES=$(xcrun simctl list devicetypes -j)
DEVTYPE=$(echo "$TYPES" | jq -r --arg d "$DUO" '[.devicetypes[] | select(.name == $d) | .identifier] | first // empty')
if [ -z "$DEVTYPE" ]; then
  echo "::warning::This image has no '$DUO' device type: the list is above."
  exit 0
fi
echo "--- the '$DUO' device type"
echo "$TYPES" | jq --arg d "$DEVTYPE" '.devicetypes[] | select(.identifier == $d)'
BPATH=$(echo "$TYPES" | jq -r --arg d "$DEVTYPE" '[.devicetypes[] | select(.identifier == $d) | .bundlePath // empty] | first // empty')
if [ -n "$BPATH" ] && [ -d "$BPATH" ]; then
  echo "--- what its bundle holds ($BPATH)"
  find "$BPATH" -maxdepth 4 | sed "s#^$BPATH#.#" | head -80
  if [ -f "$BPATH/Contents/Resources/profile.plist" ]; then
    echo "--- its profile.plist"
    plutil -p "$BPATH/Contents/Resources/profile.plist" | head -400
  fi
  if [ -f "$BPATH/Contents/Resources/capabilities.plist" ]; then
    echo "--- the lines of its capabilities.plist that name a display, a screen or a fold"
    plutil -p "$BPATH/Contents/Resources/capabilities.plist" \
      | grep -i -E "display|screen|fold|hinge|posture|cover|outer|inner|secondary|scale|width|height|ppi|inch" | head -150
  fi
fi
echo "--- the iOS runtimes of this image, and whether each makes an '$DUO'"
RUNTIMES_JSON=$(xcrun simctl list runtimes -j)
echo "$RUNTIMES_JSON" | jq -r --arg d "$DEVTYPE" '.runtimes[] | select((.name // "") | startswith("iOS"))
  | [.identifier, .version, (.buildversion // ""), (.isAvailable | tostring),
     (if ((.supportedDeviceTypes // []) | map(.identifier) | index($d)) != null then "makes the Duo" else "no Duo" end)] | @tsv'
# The runtimes that list the Duo, newest first; when none lists it, every iOS 27 runtime,
# newest first, as tour.sh does.
RUNTIMES=$(echo "$RUNTIMES_JSON" | jq -r --arg d "$DEVTYPE" '[.runtimes[]
  | select(.isAvailable and ((.name // "") | startswith("iOS 27."))
      and (((.supportedDeviceTypes // []) | map(.identifier) | index($d)) != null))]
  | sort_by(.version | split(".") | map(tonumber)) | reverse | .[].identifier')
if [ -z "$RUNTIMES" ]; then
  RUNTIMES=$(echo "$RUNTIMES_JSON" | jq -r '[.runtimes[] | select(.isAvailable and ((.name // "") | startswith("iOS 27.")))]
    | sort_by(.version | split(".") | map(tonumber)) | reverse | .[].identifier')
fi

echo "=== 3. What simctl offers for two displays"
xcrun simctl help 2>&1 | head -80
for SUB in io ui; do
  echo "--- simctl help $SUB"
  xcrun simctl help "$SUB" 2>&1 | head -120
done
echo "--- every simctl command whose help names a fold, a posture, a hinge or a display"
for SUB in $(xcrun simctl help 2>&1 | awk '/^Subcommands:/ { on = 1; next } on && NF { print $1 }'); do
  HELP=$(xcrun simctl help "$SUB" 2>&1)
  if grep -q -i -E "fold|posture|hinge|display" <<< "$HELP"; then
    echo "--- simctl help $SUB (the lines that name one)"
    grep -i -E -B2 -A6 "fold|posture|hinge|display" <<< "$HELP" | head -60
  fi
done

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
  echo "::warning::No iOS 27 runtime on this image makes an '$DUO'."
  exit 0
fi
trap 'xcrun simctl shutdown "$UDID" >/dev/null 2>&1 || true; xcrun simctl delete "$UDID" >/dev/null 2>&1 || true' EXIT
echo "=== 4. An '$DUO' on $RUNTIME: $UDID"
if ! limit 300 xcrun simctl boot "$UDID" || ! limit 300 xcrun simctl bootstatus "$UDID" -b; then
  echo "::warning::The '$DUO' did not boot in time."
  exit 0
fi
echo "[$SECONDS s] the Duo is up"
xcrun simctl list devices -j | jq --arg u "$UDID" '.devices[][] | select(.udid == $u)'
echo "--- simctl io enumerate"
limit 60 xcrun simctl io "$UDID" enumerate 2>&1 | head -150

# shoot_all <name>: a picture of every display the simulator hands out under that name:
# <name>.png as simctl gives it with no display named, and <name>-<display>.png for each
# display name it accepts, kept only when it differs from the first.
shoot_all() {
  local name=$1 display file
  if ! limit 60 xcrun simctl io "$UDID" screenshot --type=png "$OUT/duo/$name.png" >"$LOGS/duo-shot.txt" 2>&1; then
    echo "no picture for '$name': $(tr '\n' ' ' < "$LOGS/duo-shot.txt")"
  fi
  for display in internal external inner outer cover main secondary; do
    file="$OUT/duo/$name-$display.png"
    if limit 60 xcrun simctl io "$UDID" screenshot --type=png --display="$display" "$file" >"$LOGS/duo-shot.txt" 2>&1; then
      if [ -f "$OUT/duo/$name.png" ] && cmp -s "$file" "$OUT/duo/$name.png"; then
        echo "display '$display': the same picture as with no display named"
        rm -f "$file"
      else
        echo "display '$display': a picture of its own"
      fi
    else
      echo "display '$display' refused: $(tr '\n' ' ' < "$LOGS/duo-shot.txt" | cut -c1-200)"
      rm -f "$file"
    fi
  done
  for file in "$OUT"/duo/"$name".png "$OUT"/duo/"$name"-*.png; do
    [ -f "$file" ] || continue
    sips -g pixelWidth -g pixelHeight "$file" | tr '\n' ' '; echo
  done
}

xcrun simctl status_bar "$UDID" override --time "9:41" --batteryState charged --batteryLevel 100 \
  --wifiBars 3 --cellularBars 4 || echo "the status bar override was refused"
xcrun simctl ui "$UDID" appearance light || true
sleep 3
echo "--- the Home Screen"
shoot_all duo-home

if ! limit 300 xcrun simctl install "$UDID" "$APP"; then
  echo "::warning::The app could not be installed on the '$DUO'."
  exit 0
fi
echo "[$SECONDS s] the app is installed on the Duo"
DATA=""
# launch <light|dark> <picture name> <screen>: the app on a tour screen, waited for, pictured.
launch() {
  local mode=$1 name=$2 screen=$3 i=0 ready
  xcrun simctl ui "$UDID" appearance "$mode" || true
  if [ -n "$DATA" ]; then rm -f "$DATA/Documents/tour/$name.txt"; fi
  if ! limit 180 xcrun simctl launch --terminate-running-process \
      --stdout="$LOGS/$name.out" --stderr="$LOGS/$name.err" "$UDID" "$BUNDLE" \
      -tour.screen "$screen" -tour.name "$name"; then
    echo "the app did not start for '$name'"
    return 0
  fi
  if [ -z "$DATA" ]; then DATA=$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data 2>/dev/null || true); fi
  ready="$DATA/Documents/tour/$name.txt"
  while [ ! -f "$ready" ] && [ $i -lt 360 ]; do sleep 0.5; i=$((i + 1)); done
  if [ -f "$ready" ]; then
    echo "[$SECONDS s] '$name' is ready"
  else
    echo "'$name' never said it was ready"
  fi
  sleep 3
  shoot_all "$name"
  echo "--- the app's own lines for '$name'"
  cat "$LOGS/$name.err" 2>/dev/null || echo "(no stderr file)"
}
launch light duo-light-myschool myschool
launch dark duo-dark-settings settings
echo "--- the app's lines once more, a few seconds after the last picture"
sleep 4
cat "$LOGS/duo-dark-settings.err" 2>/dev/null | tail -5 || true

echo "=== 5. The pictures as grids of colors"
if xcrun swiftc -O ios/tools/grid.swift -o "$RUNNER_TEMP/grid" 2>"$LOGS/grid-build.txt"; then
  GRIDS=""
  for file in "$OUT"/duo/*.png; do [ -f "$file" ] && GRIDS="$GRIDS $file"; done
  # The iOS 27 phone of the tour, for comparison.
  if [ -f "$OUT/full/light/light-myschool.png" ]; then GRIDS="$GRIDS $OUT/full/light/light-myschool.png"; fi
  # shellcheck disable=SC2086
  if [ -n "$GRIDS" ]; then "$RUNNER_TEMP/grid" 64 $GRIDS || true; fi
else
  echo "grid.swift did not build:"; tail -20 "$LOGS/grid-build.txt"
fi
ls -l "$OUT/duo" || true
echo "[$SECONDS s] the Duo measured"
exit 0
