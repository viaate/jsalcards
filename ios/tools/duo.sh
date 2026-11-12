#!/bin/bash
# The picture tour on the iPhone Duo. tour.sh runs this on the iOS 27 leg only, after its
# own tour, with the tour's phone shut down, and gives it DUO_BUDGET: the seconds it may
# take before the job's 30 minutes are in danger. Each stage starts only if the budget
# still holds it.
#
# What the measuring runs found (iOS app runs 43129256570 to 43166875190):
#   - The "iPhone Duo" device type (iPhone19,4) is made by the iOS 27.1 runtime and by the
#     27.2 runtime built for it (iOS-27-2-iPhone19-4), not by the ordinary 27.2. It boots
#     on 27.1 in 60 to 210 s; on the other it once did not boot within 280 s, so 27.1 goes
#     first.
#   - It is ONE device with TWO screens, and simctl needs one named for every picture:
#     --display=1 is "LCD", the outer screen, 1398 x 2034 px at 3x; --display=3 is
#     "LCD-1", the inner screen, 2007 x 2853 px at 3x.
#   - The app starts on the outer screen, the phone closed. The app itself reports a
#     window of 466 x 678 pt with the safe area's right inset 84, compact width and
#     regular height, and the system's tab bar moved to a column on the right (x 397,
#     69 wide), its four tabs in a bottom-aligned platter, icons only, and the search
#     button apart below it.
#   - The phone cannot be opened on this image: simctl has no fold, hinge or posture
#     command, neither have CoreSimulator, SimulatorKit or the Duo's profile, the image
#     has no Simulator.app (whose Device menu might), the screens' power switches do not
#     move the app, and the inner screen stays black in every picture.
#
# So this script:
#   1. prints what the Duo's runtimes hold about a hinge (SpringBoardFoundation's
#      hinge-samples.csv), before any boot;
#   2. boots a Duo, the iOS 27.1 runtime first, and installs the app;
#   3. takes the tour CLOSED: My School, Map, Call it, Settings and the search tab, with
#      the simulator light and then dark, the app on System, each picture from the outer
#      screen into ios/out/full/duo/duo-closed-<look>-<screen>.png. The words of each
#      picture are compared with tools/tour-words/<look>-<screen>.txt (the same screen
#      models as on any iPhone), and the app's own last geometry line is read: on the four
#      tab screens the system's tab bar must stand upright on the right;
#   4. pictures the inner screen once with the app running, to say what it holds;
#   5. if time is left, looks for the names of a hinge, a posture or a fold state in the
#      system's own code (the runtime's shared cache), for whoever tries to open the phone
#      next;
#   6. prints every picture as a grid of colors (tools/grid.swift), because the pictures
#      of this leg stay in its own artifact.
# The pixel step (tools/pixels.swift) reads the closed pictures with the others.
#
# It ends with status 1 when a check fails: a screen that never says it is ready or cannot
# be pictured, a picture's words changed, or a tab screen's tab bar not on the right. What
# the runner cannot give it (no Duo, no boot, no time), it says, and ends with 0.
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
SHOTS="$OUT/full/duo"
mkdir -p "$SHOTS" "$OUT/duo" "$OUT/logs" "$OUT/words"
LOGS="$(cd "$OUT/logs" && pwd)"
GRID="$RUNNER_TEMP/grid"
# The seconds kept back for the grids at the end, after the budget's last stage.
GRID_TIME=60

# limit <seconds> <command...>: the command, stopped when the time is up (macOS has no
# timeout command; perl's alarm outlives the exec).
limit() {
  local seconds=$1; shift
  perl -e 'alarm shift; exec @ARGV or die "exec failed: $!\n"' "$seconds" "$@"
}
# room <seconds> <what>: true when the budget still holds that many seconds besides the grids'.
room() {
  if [ $((BUDGET - GRID_TIME - SECONDS)) -ge "$1" ]; then return 0; fi
  echo "::warning::The Duo's tour stopped before $2: $((BUDGET - SECONDS)) of its $BUDGET seconds were left."
  return 1
}
say() { echo "[duo $SECONDS s] $*"; }
FAILED=0
fail() { echo "::error::$*"; FAILED=1; }

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
# The runtimes that list the Duo: 27.1 first, then the one built for it (its identifier
# names iPhone19-4), then the others, newest first.
RUNTIMES=$(xcrun simctl list runtimes -j | jq -r --arg d "$DEVTYPE" '[.runtimes[]
  | select(.isAvailable and ((.name // "") | startswith("iOS 27."))
      and (((.supportedDeviceTypes // []) | map(.identifier) | index($d)) != null))]
  | sort_by((if .version == "27.1" then 2 elif (.identifier | test("iPhone19-4")) then 1 else 0 end), (.version | split(".") | map(tonumber)))
  | reverse | .[] | "\(.identifier)"')
echo "runtimes that make an '$DUO', in the order tried: $(echo $RUNTIMES)"
# runtime_root <runtime id>: the runtime's root folder, where its system files are.
runtime_root() {
  xcrun simctl list runtimes -j | jq -r --arg r "$1" '[.runtimes[] | select(.identifier == $r) | .runtimeRoot] | first // empty'
}
echo "=== The hinge samples each Duo runtime holds"
for CANDIDATE in $RUNTIMES; do
  HINGE="$(runtime_root "$CANDIDATE")/System/Library/PrivateFrameworks/SpringBoardFoundation.framework/hinge-samples.csv"
  if [ -f "$HINGE" ]; then
    echo "--- $CANDIDATE: hinge-samples.csv, $(wc -l < "$HINGE" | tr -d ' ') lines, $(wc -c < "$HINGE" | tr -d ' ') bytes; the first 6 lines and the last 2:"
    head -6 "$HINGE" | cut -c1-200
    tail -2 "$HINGE" | cut -c1-200
  else
    echo "--- $CANDIDATE: no hinge-samples.csv"
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
room 200 "the install" || exit 0
if ! limit 180 xcrun simctl install "$UDID" "$APP"; then
  echo "::warning::The app could not be installed on the '$DUO'."
  exit 0
fi
say "the app is installed"

DATA=""
READY=""
# launch <light|dark> <name> <screen>: the app on a tour screen, waited for. 0 when the
# screen said it was ready; 2 when the budget ran out while waiting; 1 otherwise.
launch() {
  local mode=$1 name=$2 screen=$3 i=0
  xcrun simctl ui "$UDID" appearance "$mode" || echo "the simulator's look could not be set to $mode"
  if [ -n "$DATA" ]; then rm -f "$DATA/Documents/tour/$name.txt"; fi
  if ! limit 150 xcrun simctl launch --terminate-running-process \
      --stdout="$LOGS/$name.out" --stderr="$LOGS/$name.err" "$UDID" "$BUNDLE" \
      -tour.screen "$screen" -tour.name "$name" >/dev/null; then
    say "the app did not start for '$name'"
    return 1
  fi
  if [ -z "$DATA" ]; then DATA=$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data 2>/dev/null || true); fi
  READY="$DATA/Documents/tour/$name.txt"
  while [ ! -f "$READY" ] && [ $i -lt 300 ] && [ $((BUDGET - GRID_TIME - SECONDS)) -gt 20 ]; do sleep 0.5; i=$((i + 1)); done
  if [ ! -f "$READY" ]; then
    if [ $i -lt 300 ]; then say "'$name' was not ready when the time ran out"; return 2; fi
    say "'$name' never said it was ready"
    tail -20 "$LOGS/$name.err" 2>/dev/null || true
    return 1
  fi
  say "'$name' is ready"
  # The words file is written about 0.6 s after the screen appears; two seconds more let
  # a slow simulator finish drawing.
  sleep 2
}
# geometry <name>: the last line the app wrote about its window on this launch.
geometry() {
  grep -o 'geometry: .*' "$LOGS/$1.err" 2>/dev/null | tail -1 | cut -c1-1200
}
# bar_on_right <name> <judged: yes|no>: reads the system's tab bar from the app's last
# geometry line. On the closed Duo it stands upright on the right: its left edge past the
# middle of the window, and taller than it is wide.
bar_on_right() {
  local name=$1 judged=$2 line window bar verdict
  line=$(geometry "$name")
  echo "$name: $line"
  window=$(echo "$line" | grep -o 'window [0-9.]* x [0-9.]* pt' | head -1)
  bar=$(echo "$line" | grep -o '[ ,]UITabBar at x [0-9.]* y [0-9.]* w [0-9.]* h [0-9.]*' | head -1 | sed 's/^[ ,]*//')
  verdict=$(echo "$window|$bar" | awk -F'|' '{
      split($1, a, " "); split($2, b, " ");
      if (a[2] == "" || b[4] == "") { print "unknown"; exit }
      if (b[4] + 0 > a[2] / 2 && b[10] + 0 > b[8] + 0) print "right"; else print "elsewhere" }')
  if [ "$verdict" = right ]; then
    say "$name: the system's tab bar stands upright on the right ($bar; $window): ok"
  elif [ "$judged" = yes ]; then
    fail "$name: the system's tab bar does not stand upright on the right (${bar:-no UITabBar in the last geometry line of the app}; ${window:-no window size in it})."
  else
    say "$name: the system's tab bar does not stand upright on the right (${bar:-no UITabBar in the last geometry line of the app}); not judged on this screen"
  fi
}

TAKEN=0
MISSES=0
CHANGED=0
# closed <light|dark> <screen>: one picture of the tour, the phone closed. 1 when the tour
# must stop: no time left (said, not a failure), or two screens in a row that never came
# up or could not be pictured (a failure, as on the iPhone's tour).
closed() {
  local mode=$1 screen=$2 name="duo-closed-$1-$2" need=40 judged=yes started=0
  if [ $TAKEN -eq 0 ]; then need=150; fi
  room $need "'$name'" || return 1
  launch "$mode" "$name" "$screen" || started=$?
  if [ $started -eq 2 ]; then
    echo "::warning::The Duo's tour ran out of time on '$name'."
    return 1
  fi
  if [ $started -ne 0 ]; then
    fail "The Duo's screen '$name' never said it was ready."
    MISSES=$((MISSES + 1))
    if [ $MISSES -ge 2 ]; then echo "::error::Two of the Duo's screens in a row never came up. Its tour stops here."; return 1; fi
    return 0
  fi
  if ! limit 30 xcrun simctl io "$UDID" screenshot --type=png --display="$OUTER" "$SHOTS/$name.png" >"$LOGS/duo-shot.txt" 2>&1; then
    fail "No picture of the Duo's outer screen could be taken for '$name': $(tr '\n' ' ' < "$LOGS/duo-shot.txt" | cut -c1-300)"
    rm -f "$SHOTS/$name.png"
    MISSES=$((MISSES + 1))
    if [ $MISSES -ge 2 ]; then echo "::error::Two of the Duo's pictures in a row could not be taken. Its tour stops here."; return 1; fi
    return 0
  fi
  MISSES=0
  TAKEN=$((TAKEN + 1))
  say "$name: $(sips -g pixelWidth -g pixelHeight "$SHOTS/$name.png" | tail -2 | tr -s ' \n' ' ')"
  cp "$READY" "$OUT/words/$name.txt"
  if ! diff -u "ios/tools/tour-words/$mode-$screen.txt" "$OUT/words/$name.txt"; then
    CHANGED=$((CHANGED + 1))
    fail "The model's words for '$name' are not those of tools/tour-words/$mode-$screen.txt."
  fi
  if [ "$screen" = search ]; then judged=no; fi
  bar_on_right "$name" "$judged"
}

echo "=== The tour on the Duo, closed (the outer screen)"
STOPPED=no
for mode in light dark; do
  for screen in myschool map callit settings search; do
    if ! closed "$mode" "$screen"; then STOPPED=yes; break; fi
  done
  [ "$STOPPED" = no ] || break
done
say "closed: $TAKEN of 10 pictures"

echo "=== Open (the inner screen)"
if [ $TAKEN -gt 0 ] && room 30 "the picture of the inner screen"; then
  if limit 30 xcrun simctl io "$UDID" screenshot --type=png --display="$INNER" "$OUT/duo/duo-inner.png" >"$LOGS/duo-shot.txt" 2>&1; then
    say "duo-inner, with the app running on the outer screen: $(sips -g pixelWidth -g pixelHeight "$OUT/duo/duo-inner.png" | tail -2 | tr -s ' \n' ' ')"
  else
    say "no picture of the inner screen: $(tr '\n' ' ' < "$LOGS/duo-shot.txt" | cut -c1-300)"
  fi
fi
echo "The phone cannot be opened on this image (no fold command, no Simulator.app): no open picture."

echo "=== The names of a hinge, a posture or a fold state in the system's own code"
if room 150 "the look into the shared cache"; then
  ROOT=$(runtime_root "$RUNTIME")
  CACHES=()
  while IFS= read -r FOUND; do
    [ -n "$FOUND" ] && CACHES+=("$FOUND")
  done <<EOF
$(limit 40 find "$ROOT" /Library/Developer/CoreSimulator/Caches "$HOME/Library/Developer/CoreSimulator/Caches" \
  -maxdepth 7 -name 'dyld_sim_shared_cache*' -type f -size +1M 2>/dev/null | grep -v -E '\.(map|atlas)$' | head -40)
EOF
  if [ ${#CACHES[@]} -eq 0 ]; then
    say "no shared cache found under the runtime or the simulator's caches"
  else
    say "shared cache files: ${#CACHES[@]}, the first: ${CACHES[0]}"
    # Each name with a hinge, a posture, a fold state or a cover display in it, and how
    # often it comes. Line-buffered, so what was found before the time ran out is kept.
    ( export LC_ALL=C
      limit 110 grep -a -o -h --line-buffered -E \
        '[A-Za-z_]*([Hh]inge|[Pp]osture|[Ff]oldState|[Uu]nfold|[Cc]overDisplay)[A-Za-z_]*' "${CACHES[@]}" 2>/dev/null \
        | grep -v -i -E 'folder|unfoldable' | cut -c1-120 | sort | uniq -c | sort -rn | head -80 )
  fi
fi

if wait "$GRID_BUILD"; then
  say "grid.swift built"
  for f in "$SHOTS"/*.png; do
    [ -e "$f" ] || continue
    "$GRID" 96 "$f" || true
  done
  if [ -f "$OUT/duo/duo-inner.png" ]; then "$GRID" 12 "$OUT/duo/duo-inner.png" || true; fi
else
  echo "grid.swift did not build:"; tail -20 "$LOGS/grid-build.txt"
fi
ls -l "$SHOTS" "$OUT/duo" || true
say "the Duo's tour: $TAKEN of 10 closed pictures, $CHANGED with changed words; status $FAILED"
exit $FAILED
