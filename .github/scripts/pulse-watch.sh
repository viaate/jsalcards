#!/usr/bin/env bash
# The live reader's watcher, outside Python (docs/live.md, "Stuck passes"): runs the command
# given after `--` and ends it when its pulse file is too old, so a hang that holds the
# interpreter (a runaway regex, say) is caught too: TERM first, then KILL a grace later.
#
#   pulse-watch.sh PULSE MAX_AGE_SECONDS GRACE_SECONDS -- COMMAND...
#
# The pulse is the mtime of PULSE (`snowlight live run` touches it at every tick of a pass's
# reads, per source it folds in and resolves, at each request to the live host and the state
# database, and after each pass and 60-second check); before it exists, the watcher's own
# start counts. The exit is the command's own, or 124 when the watcher ended it (and
# `killed=true` goes to $GITHUB_OUTPUT when that is set). PULSE_POLL sets the seconds between
# looks (default 10).
#
# A TERM to the watcher (the loop step forwards a cancel: the runner signals only the step's
# own shell) is passed on to the command, which is KILLed when it still runs STOP_GRACE
# seconds later (default 5, inside the runner's 7.5 s between its SIGINT and its SIGTERM);
# the watcher exits 143 once the command is gone, so no reader outlives a cancelled step.
set -u
if [ "$#" -lt 5 ] || [ "$4" != "--" ]; then
  echo "usage: pulse-watch.sh PULSE MAX_AGE GRACE -- COMMAND..." >&2
  exit 2
fi
pulse="$1"
max_age="$2"
grace="$3"
shift 4
poll="${PULSE_POLL:-10}"
stop_grace="${STOP_GRACE:-5}"
"$@" &
child=$!
stop() {
  trap '' TERM INT
  kill -TERM "$child" 2>/dev/null
  tenths=0
  while kill -0 "$child" 2>/dev/null && [ "$tenths" -lt $((stop_grace * 10)) ]; do
    sleep 0.1
    tenths=$((tenths + 1))
  done
  if kill -0 "$child" 2>/dev/null; then kill -KILL "$child" 2>/dev/null; fi
  wait "$child" 2>/dev/null
  echo "pulse-watch: stopped: the reader is ended"
  exit 143
}
trap stop TERM INT
start=$(date +%s)
while kill -0 "$child" 2>/dev/null; do
  sleep "$poll" &
  wait $! 2>/dev/null
  kill -0 "$child" 2>/dev/null || break
  now=$(date +%s)
  last="$start"
  if [ -f "$pulse" ]; then
    last=$(stat -c %Y "$pulse" 2>/dev/null || echo "$start")
  fi
  age=$((now - last))
  if [ "$age" -ge "$max_age" ]; then
    echo "pulse-watch: the reader's pulse is ${age} s old: stopping it"
    kill -TERM "$child" 2>/dev/null
    waited=0
    while kill -0 "$child" 2>/dev/null && [ "$waited" -lt "$grace" ]; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$child" 2>/dev/null; then
      echo "pulse-watch: still running after ${grace} s: killing it"
      kill -KILL "$child" 2>/dev/null
    fi
    wait "$child" 2>/dev/null
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "killed=true" >> "$GITHUB_OUTPUT"; fi
    exit 124
  fi
done
wait "$child"
exit $?
