#!/bin/bash
# Make the small pictures: each full-size picture as a JPEG at half size, with the words
# files beside them. This folder is the one small artifact a run hands back.
set -euo pipefail
mkdir -p ios/out/small
# ios/out/duo/ holds the iPhone Duo's pictures, on the iOS 27 leg only (tools/duo.sh).
for f in ios/out/full/*/*.png ios/out/duo/*.png; do
  [ -e "$f" ] || continue
  sips -s format jpeg -s formatOptions 80 -Z 1748 "$f" \
    --out "ios/out/small/$(basename "$f" .png).jpg" >/dev/null
  # The sizes in pixels, full and small, for whoever reads the log.
  sips -g pixelWidth -g pixelHeight "$f" "ios/out/small/$(basename "$f" .png).jpg" || true
done
cp ios/out/words/*.txt ios/out/small/ 2>/dev/null || true
du -sh ios/out/small || true
ls -l ios/out/small || true
