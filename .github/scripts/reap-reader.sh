#!/usr/bin/env bash
# Make sure no reader is alive before live-read.yml's end steps pack the state (docs/live.md,
# "Stuck passes"): the loop step starts its watcher in a process group of its own and writes
# the group's id to PGID_FILE; whatever of that group still runs here (a reader a cancel or
# a timeout left, or the watcher itself) is KILLed, and `clear=true` goes to $GITHUB_OUTPUT
# once none of it is left (zombies aside). Without that line the record, end push and export
# steps do not run, so no state is packed while a reader may still write it.
#
#   reap-reader.sh PGID_FILE
set -u
if [ "$#" -ne 1 ]; then
  echo "usage: reap-reader.sh PGID_FILE" >&2
  exit 2
fi
file="$1"
say_clear() {
  echo "$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "clear=true" >> "$GITHUB_OUTPUT"; fi
  exit 0
}
if [ ! -f "$file" ]; then
  say_clear "no reader was started"
fi
pgid=$(tr -d '[:space:]' < "$file")
case "$pgid" in
  '' | *[!0-9]* | 0 | 1)
    echo "::warning::The reader's process group is not readable: the state is not packed in this run."
    exit 0
    ;;
esac
alive() {
  # the group's members that are not zombies
  ps -eo pgid=,stat= | awk -v group="$pgid" '$1 == group && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}
if ! alive; then
  say_clear "no reader left"
fi
echo "a reader process is still running: killing it"
kill -KILL -- "-$pgid" 2>/dev/null
tenths=0
while [ "$tenths" -lt 100 ]; do
  if ! alive; then
    say_clear "no reader left"
  fi
  sleep 0.1
  tenths=$((tenths + 1))
done
echo "::warning::A reader process outlived its KILL: the state is not packed in this run."
exit 0
