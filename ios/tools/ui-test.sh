#!/bin/bash
# The on-screen words, read by a UI test (M1 6.3): the macos-26 job's own step, after the
# tour. ios/UITests/MySchoolTextTests.swift starts the app once for each of My School's six
# iPhone pictures and reads the label and value of every element on the screen; this
# script makes a simulator for it, builds it, runs it and checks how many tests ran.
#
# - Its own simulator, made and booted as tools/tour.sh makes the tour's (the tour deletes
#   its own on exit), and deleted on exit.
# - Built for testing, unsigned, exactly as tools/build.sh builds the app: no certificate,
#   no account, no secret. The project's scheme builds the UI test target for testing only.
# - Every label the test reads is printed (lines that start "ui-read"), from the raw log.
# - The number of tests run, read from the result bundle, must equal ui-test-count.txt.
#
# Bash 3.2 on macOS: no associative arrays, no mapfile.
set -euo pipefail
OUT=ios/out/ui
mkdir -p "$OUT"
LOGS="$(cd "$OUT" && pwd)"
BUILD_LOG="$RUNNER_TEMP/xcodebuild-ui-build.log"
TEST_LOG="$RUNNER_TEMP/xcodebuild-ui-test.log"
RESULT="$RUNNER_TEMP/ui.xcresult"
PRETTY=cat
if command -v xcbeautify >/dev/null 2>&1; then PRETTY=xcbeautify; fi

# The committed count: one whole number; lines that start with # are notes.
WANTED=$(grep -v '^#' ios/tools/ui-test-count.txt | grep -v '^[[:space:]]*$' || true)
case "$WANTED" in
  ''|*[!0-9]*) echo "::error::ios/tools/ui-test-count.txt must hold one whole number."; exit 1 ;;
esac

# Our own device, from what this image has, addressed by id (as tools/tour.sh does).
DEVTYPE=$(xcrun simctl list devicetypes -j | jq -r --arg d "$SIM_DEVICE" \
  '[.devicetypes[] | select(.name == $d) | .identifier] | first // empty')
if [ -z "$DEVTYPE" ]; then
  echo "::error::No '$SIM_DEVICE' on this image."
  xcrun simctl list devicetypes; exit 1
fi
echo "device type: $DEVTYPE"
RUNTIMES=$(xcrun simctl list runtimes -j | jq -r --arg p "$SIM_OS_PREFIX" \
  '[.runtimes[] | select(.isAvailable and ((.name // "") | startswith($p)))]
   | sort_by(.version | split(".") | map(tonumber)) | reverse | .[].identifier')
RUNTIME=""
UDID=""
for CANDIDATE in $RUNTIMES; do
  if UDID=$(xcrun simctl create snowlight-ui "$DEVTYPE" "$CANDIDATE" 2>"$LOGS/simctl-create.txt"); then
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

if ! xcodebuild build-for-testing -project ios/Snowlight.xcodeproj -scheme Snowlight -configuration Debug \
  -destination "id=$UDID" -derivedDataPath "$RUNNER_TEMP/dd-ui" \
  CODE_SIGNING_ALLOWED=NO ONLY_ACTIVE_ARCH=YES ARCHS=arm64 COMPILER_INDEX_STORE_ENABLE=NO \
  2>&1 | tee "$BUILD_LOG" | "$PRETTY"; then
  echo "::error::The build for testing failed. The last 80 lines of the raw log follow."
  tail -80 "$BUILD_LOG"
  exit 1
fi
echo "[$SECONDS s] built for testing (unsigned: CODE_SIGNING_ALLOWED=NO)"

rm -rf "$RESULT"
FAILED=0
if ! xcodebuild test-without-building -project ios/Snowlight.xcodeproj -scheme Snowlight \
  -destination "id=$UDID" -derivedDataPath "$RUNNER_TEMP/dd-ui" -only-testing:SnowlightUITests \
  -resultBundlePath "$RESULT" \
  2>&1 | tee "$TEST_LOG" | "$PRETTY"; then
  echo "::error::The UI test failed (its failures are above and in the summary below)."
  FAILED=1
fi
echo "[$SECONDS s] the UI test ran"

# Every label read, from the raw log (the pretty printer may leave the test's own lines out).
echo "--- what the UI test read"
grep -a 'ui-read' "$TEST_LOG" || echo "::warning::The raw log holds no line that starts ui-read."

# How many tests ran, from the result bundle. Its field names are printed with it.
if [ ! -d "$RESULT" ]; then
  echo "::error::The UI test left no result bundle at $RESULT."
  tail -80 "$TEST_LOG"
  exit 1
fi
SUMMARY="$LOGS/summary.json"
if ! xcrun xcresulttool get test-results summary --path "$RESULT" > "$SUMMARY"; then
  echo "::error::xcresulttool could not read the result bundle's summary."
  exit 1
fi
echo "--- the result bundle's summary"
cat "$SUMMARY"
echo
RAN=$(jq -r '.totalTestCount // empty' "$SUMMARY")
case "$RAN" in
  ''|*[!0-9]*) echo "::error::The summary has no whole totalTestCount (its fields are above)."; exit 1 ;;
esac
echo "UI tests run: $RAN; ios/tools/ui-test-count.txt: $WANTED"
if [ "$RAN" -ne "$WANTED" ]; then
  echo "::error::$RAN UI tests ran and ios/tools/ui-test-count.txt says $WANTED."
  FAILED=1
fi
exit $FAILED
