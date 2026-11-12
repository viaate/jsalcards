#!/bin/bash
# Build the app for the simulator, unsigned: no certificate, no account, no secret.
# The raw log is kept, and its tail is printed when the build fails. There is no -sdk
# next to the destination: with -sdk, package plug-ins added later build for the wrong
# platform.
#
# Two builds of the same scheme: Debug, which the picture tour runs, then Release, which
# nothing runs. The Release build is there so that what a release holds is compiled on
# every push: the tour (Tour/) is wholly inside #if DEBUG, so a view that named a tour
# symbol outside it would build in Debug and first fail on the day of a signed build. And
# the release app must hold no trace of the tour: its launch keys are looked for in it.
set -euo pipefail
LOG="$RUNNER_TEMP/xcodebuild.log"
PRETTY=cat
if command -v xcbeautify >/dev/null 2>&1; then PRETTY=xcbeautify; fi
if ! xcodebuild build \
  -project ios/Snowlight.xcodeproj -scheme Snowlight -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$RUNNER_TEMP/dd" \
  CODE_SIGNING_ALLOWED=NO ONLY_ACTIVE_ARCH=YES ARCHS=arm64 COMPILER_INDEX_STORE_ENABLE=NO \
  2>&1 | tee "$LOG" | "$PRETTY"; then
  echo "::error::The build failed. The last 80 lines of the raw log follow."
  tail -80 "$LOG"
  exit 1
fi
APP="$RUNNER_TEMP/dd/Build/Products/Debug-iphonesimulator/Snowlight.app"
if [ ! -d "$APP" ]; then
  echo "::error::The build passed but left no app at $APP."
  ls -R "$RUNNER_TEMP/dd/Build/Products" | head -60 || true
  exit 1
fi
# What was built, for whoever reads the log: its size and the settings file Xcode made.
du -sh "$APP" || true
plutil -p "$APP/Info.plist" || true
# On the iOS 27 leg the app must be built with the iOS 27.1 SDK or newer: only an app built
# with it is given the whole of the iPhone Duo's screens.
if [ "${SIM_OS_PREFIX:-}" = "iOS 27." ]; then
  SDK=$(plutil -extract DTPlatformVersion raw "$APP/Info.plist" 2>/dev/null || true)
  MAJOR=${SDK%%.*}
  MINOR=0
  case "$SDK" in *.*) MINOR=${SDK#*.}; MINOR=${MINOR%%.*} ;; esac
  case "$MAJOR:$MINOR" in
    :*|*:|*[!0-9:]*) echo "::error::The app's SDK could not be read (DTPlatformVersion '$SDK')."; exit 1 ;;
  esac
  if [ "$MAJOR" -lt 27 ] || { [ "$MAJOR" -eq 27 ] && [ "$MINOR" -lt 1 ]; }; then
    echo "::error::The app was built with the iOS $SDK SDK; the iPhone Duo needs 27.1 or newer."
    exit 1
  fi
  echo "The app was built with the iOS $SDK SDK ($(plutil -extract DTSDKName raw "$APP/Info.plist" 2>/dev/null || true))."
fi

RLOG="$RUNNER_TEMP/xcodebuild-release.log"
if ! xcodebuild build \
  -project ios/Snowlight.xcodeproj -scheme Snowlight -configuration Release \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$RUNNER_TEMP/dd" \
  CODE_SIGNING_ALLOWED=NO ONLY_ACTIVE_ARCH=YES ARCHS=arm64 COMPILER_INDEX_STORE_ENABLE=NO \
  2>&1 | tee "$RLOG" | "$PRETTY"; then
  echo "::error::The Release build failed. The last 80 lines of its raw log follow."
  tail -80 "$RLOG"
  exit 1
fi
RAPP="$RUNNER_TEMP/dd/Build/Products/Release-iphonesimulator/Snowlight.app"
if [ ! -d "$RAPP" ]; then
  echo "::error::The Release build passed but left no app at $RAPP."
  ls -R "$RUNNER_TEMP/dd/Build/Products" | head -60 || true
  exit 1
fi
du -sh "$RAPP" || true
if grep -r -a -l -F -e tour.screen -e tour.name "$RAPP"; then
  echo "::error::The Release app holds the picture tour's launch keys (the files above): debug code reached a release build."
  exit 1
fi
echo "The Release app holds no trace of the picture tour."
