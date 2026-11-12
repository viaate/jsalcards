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
# The second run (iOS app run 43137086885, job 130914907555) found that those switches
# do not open the phone: with the inner screen powered on the outer one went to the Home
# Screen, the inner one stayed black in every picture, and the app, started again with the
# outer screen off, still got the outer screen's 466 x 678 pt window. The inner screen
# also refused a landscape geometry (2853x2007@3: "No mode found"). The fold is not in
# simctl; it may be in Simulator.app. The third run (iOS app run 43142363913) found no fold,
# hinge or posture word in CoreSimulator or simctl, and no Simulator.app where it looked;
# the Mac's own screen can be pictured (1024 x 768). The fourth run (iOS app run
# 43147864852) found that the xcode-27 image has no Simulator.app at all (its Xcode's
# Developer/Applications is empty and no app has its bundle id); SimulatorKit is in the
# Xcode's SharedFrameworks and names no fold either. So the stages below that need
# Simulator.app say so and are skipped when it is missing.
#
# The fifth run (iOS app run 43152482009) tried the runtime built for the Duo (iOS 27.2,
# iPhone19-4) first: it did not boot within 280 s. So 27.1 is first again, and the words
# about a fold in each runtime's own files (the system's side of a fold) are looked for
# before any boot.
#
# So this script, for whoever reads the log:
#   1. prints the words about a fold, a hinge or a posture that Simulator.app, SimulatorKit,
#      CoreSimulator and simctl carry (their menus and their calls), and the Duo's profile;
#   2. boots a Duo on iOS 27.1 (the owner's phone's version) or, failing that, the other
#      runtime that makes one;
#   3. starts the app on My School (light) and pictures both screens: the closed phone;
#   4. opens Simulator.app on the Duo, pictures both screens and the Mac's screen, and lists
#      Simulator.app's menus (through System Events, if the runner lets it);
#   5. clicks the menu item that opens the phone, if there is one, and pictures both
#      screens; the app's own lines (Tour/TourGeometry.swift) say what window it was given;
#   6. turns the open phone on its side with Simulator.app's rotate item, and pictures it;
#   7. starts the app again on Settings (dark) and pictures it, open and on its side;
#   8. prints every picture as a coarse grid of colors (tools/grid.swift), because the
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
# The words about a fold. Simulator.app's menus are compiled nibs and its words .strings
# files; the frameworks' method names show what a fold is called inside. Each list is cut
# short; none of this changes anything.
DEV=$(xcode-select -p)
XCODE=$(dirname "$(dirname "$DEV")")
# Run 3 found no Simulator.app at $DEV/Applications on the xcode-27 image, so it is looked
# for: in the active Xcode, by its bundle id, then anywhere in that Xcode.
SIMAPP=""
for CANDIDATE in "$DEV/Applications/Simulator.app" "$XCODE/Contents/Applications/Simulator.app" /Applications/Simulator.app; do
  if [ -d "$CANDIDATE" ]; then SIMAPP=$CANDIDATE; break; fi
done
[ -n "$SIMAPP" ] || SIMAPP=$(limit 20 mdfind "kMDItemCFBundleIdentifier == 'com.apple.iphonesimulator'" 2>/dev/null | head -1)
[ -n "$SIMAPP" ] || SIMAPP=$(limit 40 find "$XCODE" -maxdepth 6 -name Simulator.app -type d 2>/dev/null | head -1)
echo "Simulator.app: ${SIMAPP:-(none found)}; $DEV/Applications holds: $(ls "$DEV/Applications" 2>/dev/null | tr '\n' ' ')"
SIMKIT=$(limit 40 find "$XCODE/Contents" /Library/Developer/PrivateFrameworks -maxdepth 6 -name SimulatorKit.framework -type d 2>/dev/null | head -1)
echo "SimulatorKit: ${SIMKIT:-(none found)}"
FOLD_WORDS='fold|hinge|posture|tabletop|cover display|inner display|outer display'
words() {
  echo "--- $1"
  if [ -e "$2" ]; then
    limit 40 strings -a "$2" 2>/dev/null | grep -i -E "$FOLD_WORDS" | grep -v -i -E 'folder|manifold|scaffold|unfoldable' \
      | sort -u | head -"${3:-40}" | cut -c1-200
  else
    echo "(not here: $2)"
  fi
}
echo "=== The words about a fold in Apple's simulator"
words "Simulator.app" "$SIMAPP/Contents/MacOS/Simulator"
for f in "$SIMAPP"/Contents/Resources/en.lproj/* "$SIMAPP"/Contents/Resources/Base.lproj/*; do
  [ -f "$f" ] || continue
  case "$f" in
    *.strings) if limit 10 plutil -p "$f" 2>/dev/null | grep -q -i -E "$FOLD_WORDS"; then
        echo "--- $(basename "$f")"; limit 10 plutil -p "$f" | grep -i -E "$FOLD_WORDS" | head -20 | cut -c1-200; fi ;;
    *.nib) ;;
    *) if limit 10 strings -a "$f" 2>/dev/null | grep -q -i -E "$FOLD_WORDS"; then words "$(basename "$f")" "$f" 20; fi ;;
  esac
done
for nib in "$SIMAPP"/Contents/Resources/*.nib "$SIMAPP"/Contents/Resources/*/*.nib; do
  [ -e "$nib" ] || continue
  if [ -d "$nib" ]; then nib="$nib/keyedobjects.nib"; fi
  if [ -f "$nib" ] && limit 10 strings -a "$nib" 2>/dev/null | grep -q -i -E "$FOLD_WORDS"; then words "$(basename "$(dirname "$nib")")/$(basename "$nib")" "$nib" 20; fi
done
words "SimulatorKit" "${SIMKIT:-/none}/Versions/A/SimulatorKit"
words "CoreSimulator" "/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/CoreSimulator"
words "simctl" "$DEV/usr/bin/simctl" 20
DUO_BUNDLE=$(xcrun simctl list devicetypes -j | jq -r --arg d "$DEVTYPE" '[.devicetypes[] | select(.identifier == $d) | .bundlePath] | first // empty')
if [ -n "$DUO_BUNDLE" ]; then
  echo "--- the Duo's profile.plist, lines that name a fold, a hinge, a posture or a screen"
  plutil -p "$DUO_BUNDLE/Contents/Resources/profile.plist" 2>/dev/null | grep -i -E "$FOLD_WORDS|screen|display|hid" | head -40 | cut -c1-200
  ls "$DUO_BUNDLE/Contents/Resources" 2>/dev/null | head -30
fi

# The runtimes that list the Duo: 27.1 first, then the one built for it (its identifier
# names iPhone19-4), then the others, newest first.
RUNTIMES=$(xcrun simctl list runtimes -j | jq -r --arg d "$DEVTYPE" '[.runtimes[]
  | select(.isAvailable and ((.name // "") | startswith("iOS 27."))
      and (((.supportedDeviceTypes // []) | map(.identifier) | index($d)) != null))]
  | sort_by((if .version == "27.1" then 2 elif (.identifier | test("iPhone19-4")) then 1 else 0 end), (.version | split(".") | map(tonumber)))
  | reverse | .[] | "\(.identifier)"')
echo "runtimes that make an '$DUO', in the order tried: $(echo $RUNTIMES)"
# runtime_words <runtime id>: the names and words about a fold, a hinge or a posture in a
# runtime's own files (the system's side of a fold). It needs no booted device.
runtime_words() {
  local ROOT
  ROOT=$(xcrun simctl list runtimes -j | jq -r --arg r "$1" '[.runtimes[] | select(.identifier == $r) | .runtimeRoot] | first // empty')
  echo "=== The words about a fold in the files of $1 ($ROOT)"
  if [ -n "$ROOT" ] && [ -d "$ROOT" ]; then
    echo "--- files whose names say fold, hinge or posture"
    limit 40 find "$ROOT/System/Library" "$ROOT/usr/libexec" -maxdepth 4 \( -iname '*fold*' -o -iname '*hinge*' -o -iname '*posture*' \) 2>/dev/null \
      | grep -v -i -E 'folder|scaffold|manifold' | sed "s|$ROOT||" | head -40
    echo "--- the runtime's frameworks named for the simulator"
    ls "$ROOT/System/Library/PrivateFrameworks" 2>/dev/null | grep -i simulator | head -20
    for f in "$ROOT"/System/Library/PrivateFrameworks/*Simulator*.framework; do
      [ -d "$f" ] || continue
      words "$(basename "$f")" "$f/$(basename "$f" .framework)" 30
    done
    words "backboardd" "$ROOT/usr/libexec/backboardd" 30
    words "SpringBoard" "$ROOT/System/Library/CoreServices/SpringBoard.app/SpringBoard" 30
  else
    echo "(no runtime root)"
  fi
}
for CANDIDATE in $RUNTIMES; do runtime_words "$CANDIDATE"; done
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

# shoot <name> <screen>: a picture of one screen, its size, and its grid.
shoot() {
  local name=$1 screen=$2 file="$OUT/duo/$1.png"
  if limit 30 xcrun simctl io "$UDID" screenshot --type=png --display="$screen" "$file" >"$LOGS/duo-shot.txt" 2>&1; then
    say "$name: $(sips -g pixelWidth -g pixelHeight "$file" | tail -2 | tr -s ' \n' ' ')"
    if [ -n "$GRID" ]; then "$GRID" 64 "$file" || true; fi
  else
    say "$name: no picture of screen $screen: $(tr '\n' ' ' < "$LOGS/duo-shot.txt" | cut -c1-300)"
    rm -f "$file"
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

# The menus of Simulator.app, one line each: "<menu>\t<item>\t<sub item>".
menus() {
  limit 60 osascript -e '
    set out to ""
    tell application "System Events" to tell process "Simulator"
      repeat with mb in menu bar items of menu bar 1
        set m to name of mb
        if m is not missing value and m is not "Apple" then
          try
            repeat with mi in menu items of menu 1 of mb
              set n to name of mi
              if n is not missing value then
                set out to out & m & tab & n & linefeed
                try
                  repeat with si in menu items of menu 1 of mi
                    set k to name of si
                    if k is not missing value then set out to out & m & tab & n & tab & k & linefeed
                  end repeat
                end try
              end if
            end repeat
          end try
        end if
      end repeat
    end tell
    return out' 2>&1
}
# click <menu> <item> [<sub item>]: a click on one of Simulator.app's menu items.
click() {
  local script
  if [ -n "${3:-}" ]; then
    script="tell application \"System Events\" to tell process \"Simulator\" to click menu item \"$3\" of menu 1 of menu item \"$2\" of menu 1 of menu bar item \"$1\" of menu bar 1"
  else
    script="tell application \"System Events\" to tell process \"Simulator\" to click menu item \"$2\" of menu 1 of menu bar item \"$1\" of menu bar 1"
  fi
  if limit 20 osascript -e "tell application \"Simulator\" to activate" -e "$script" >"$LOGS/duo-click.txt" 2>&1; then
    say "clicked $1 > $2${3:+ > $3}"
  else
    say "the click on $1 > $2${3:+ > $3} was refused: $(tr '\n' ' ' < "$LOGS/duo-click.txt" | cut -c1-300)"
    return 1
  fi
}
# mac <name>: a picture of the Mac's whole screen (Simulator.app's window), and its grid.
mac() {
  local file="$OUT/duo/$1.png"
  if limit 20 screencapture -x "$file" >"$LOGS/duo-mac.txt" 2>&1 && [ -s "$file" ]; then
    say "$1: $(sips -g pixelWidth -g pixelHeight "$file" | tail -2 | tr -s ' \n' ' ')"
    if [ -n "$GRID" ]; then "$GRID" 64 "$file" || true; fi
  else
    say "$1: no picture of the Mac's screen: $(tr '\n' ' ' < "$LOGS/duo-mac.txt" | cut -c1-200)"
    rm -f "$file"
  fi
}
# both <name>: both screens of the Duo.
both() {
  shoot "$1-outer" "$OUTER"
  shoot "$1-inner" "$INNER"
}

room 200 "the install" || exit 0
if ! limit 180 xcrun simctl install "$UDID" "$APP"; then
  echo "::warning::The app could not be installed on the '$DUO'."
  exit 0
fi
say "the app is installed"

echo "=== Closed: the app on My School, light"
room 150 "the first launch" || exit 0
launch light duo-closed-light-myschool myschool || exit 0
both duo-closed-light-myschool
lines duo-closed-light-myschool

PHASE=closed
MENUS=""
echo "=== Simulator.app on the Duo"
if [ -z "$SIMAPP" ]; then
  say "this image has no Simulator.app: the stages that need it are skipped"
elif room 120 "Simulator.app"; then
  if limit 60 open -a "$SIMAPP" --args -CurrentDeviceUDID "$UDID" >"$LOGS/duo-open.txt" 2>&1; then
    say "Simulator.app asked to show the Duo"
  else
    say "Simulator.app did not open: $(tr '\n' ' ' < "$LOGS/duo-open.txt" | cut -c1-300)"
  fi
  sleep 15
  mac duo-mac-closed
  both duo-simapp-closed-light-myschool
  lines duo-closed-light-myschool
  echo "--- Simulator.app's menus"
  MENUS=$(menus)
  echo "$MENUS" | head -150 | cut -c1-200
  echo "--- the menu items about a fold, a hinge, a posture or a rotation"
  echo "$MENUS" | grep -i -E "$FOLD_WORDS|open|close|rotate|orientation" | grep -v -i -E 'folder|window|open recent|close all' | head -30

  # The item that opens the phone, by the words Simulator.app gives it: "Unfold" first, then
  # an "Open" or "Flat" item under a fold/hinge/posture menu, then any other fold item.
  OPENER=$(echo "$MENUS" | grep -i -E $'\t[^\t]*unfold[^\t]*$' | head -1)
  [ -n "$OPENER" ] || OPENER=$(echo "$MENUS" | grep -i -E 'fold|hinge|posture' | grep -i -E $'\t(open|flat|fully open|opened)$' | head -1)
  [ -n "$OPENER" ] || OPENER=$(echo "$MENUS" | grep -i -E $'\t[^\t]*fold[^\t]*$' | head -1)
  if [ -z "$OPENER" ]; then
    echo "Simulator.app shows no menu item that opens the phone (or its menus could not be read)."
  else
    echo "=== Open: Simulator.app's '$(echo "$OPENER" | tr '\t' '>')'"
    IFS=$'\t' read -r M1 M2 M3 <<<"$OPENER"
    if room 60 "the opening" && click "$M1" "$M2" "${M3:-}"; then
      PHASE=open
      sleep 8
      mac duo-mac-open
      both duo-open-light-myschool
      echo "--- the app's lines since it started, after the opening"
      lines duo-closed-light-myschool
    fi
  fi
fi

echo "=== The app started again, on Settings, dark, the phone $PHASE"
if room 100 "the launch on Settings"; then
  launch dark "duo-$PHASE-dark-settings" settings && {
    both "duo-$PHASE-dark-settings"
    lines "duo-$PHASE-dark-settings"
  }
fi

echo "=== Open, on its side: Simulator.app's rotate item"
ROTATE=$(echo "$MENUS" | grep -i -E $'\trotate (left|right)$' | head -1)
if [ "$PHASE" = open ] && [ -n "$ROTATE" ] && room 60 "the rotation"; then
  IFS=$'\t' read -r M1 M2 M3 <<<"$ROTATE"
  if click "$M1" "$M2" "${M3:-}"; then
    sleep 6
    mac duo-mac-open-landscape
    both duo-open-landscape-dark-settings
    lines duo-open-dark-settings
  fi
else
  say "no rotation: the phone did not open, or Simulator.app has no rotate item, or no time"
fi
[ -z "$SIMAPP" ] || limit 20 osascript -e 'tell application "Simulator" to quit' >/dev/null 2>&1 || true
ls -l "$OUT/duo" || true
say "the Duo measured"
exit 0
