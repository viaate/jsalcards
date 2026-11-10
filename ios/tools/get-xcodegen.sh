#!/bin/bash
# Fetch the pinned XcodeGen release and refuse it unless its checksum is the one the
# workflow names. This is the only download the iPhone app's CI makes.
set -euo pipefail
url="https://github.com/yonaskolb/XcodeGen/releases/download/${XCODEGEN_VERSION}/xcodegen.zip"
curl -fsSL --retry 3 -o "$RUNNER_TEMP/xcodegen.zip" "$url"
echo "${XCODEGEN_SHA256}  $RUNNER_TEMP/xcodegen.zip" | shasum -a 256 -c -
unzip -q -o "$RUNNER_TEMP/xcodegen.zip" -d "$RUNNER_TEMP"
"$RUNNER_TEMP/xcodegen/bin/xcodegen" --version
