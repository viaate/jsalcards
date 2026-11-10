#!/bin/bash
# Build the app for the simulator, unsigned: no certificate, no account, no secret.
# The raw log is kept, and its tail is printed when the build fails. There is no -sdk
# next to the destination: with -sdk, package plug-ins added later build for the wrong
# platform.
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
