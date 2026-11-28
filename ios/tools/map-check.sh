#!/bin/bash
# The map's checks (M3): the app's map files, made from the site's own, against what the
# site would make now. Run on Linux by iOS core (a failure) and by the iOS words watch (a
# warning until testers hold the app). Its checks come in from M3 part 1's step 2 on; until
# then it has none.
#
# Bash 3.2 too: no associative arrays, no mapfile.
set -euo pipefail
echo "The map's checks: nothing to check before step 2."
exit 0
