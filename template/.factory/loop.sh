#!/usr/bin/env bash
# The dispatcher loop. One tick per interval; a tick is idempotent and exits fast when
# there is nothing to do. Stop it with `touch .factory/STOP` (the tick checks that
# first, before it reads anything else) or by killing this process.
#
# SINGLETON, AND THAT IS NOT A NICETY.
#
# Three copies of this script ended up running at once, because stopping the wrapper
# that launched it did not always take the bash child with it. They raced on one pull
# request: three MERGE dispatches inside three seconds, two of them refused because
# GitHub had already merged it, and both refusals escalated a PR that had in fact
# merged perfectly. The code was fine; the records said needs-human on a merged PR and
# its closed issue.
#
# The per-target lock does not save you here. It makes a single dispatcher safe against
# itself; it was never a mutex between separate dispatchers, and the merge path does not
# take one at all. So the loop refuses to start twice.
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1   # the repo root, wherever it is

LOCK=".factory/loop.pid"
INTERVAL="${FACTORY_LOOP_INTERVAL:-60}"

# Escalations and watchdog halts must REACH somebody. The default is a log file.
export FACTORY_NOTIFY_CMD="${FACTORY_NOTIFY_CMD:-bash .factory/notify.sh}"

mkdir -p .factory/runs

if [ -f "$LOCK" ]; then
  OTHER="$(cat "$LOCK" 2>/dev/null)"
  # A STALE PID FILE MUST NOT WEDGE THE LOOP FOREVER. The common way this file is left
  # behind is the machine dying, which is exactly when you need the loop to come back
  # on its own. So a pid that is gone is cleared rather than obeyed.
  if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
    echo "=== $(date -Is) REFUSING TO START: loop already running as pid $OTHER"
    echo "    Stop it first, or remove $LOCK if you are certain it is dead."
    exit 3
  fi
  echo "=== $(date -Is) clearing stale $LOCK (pid ${OTHER:-unknown} is gone)"
  rm -f "$LOCK"
fi

echo $$ > "$LOCK"
# Clear it on any exit, including a kill, so the next start is not blocked by our own
# corpse. This is the half that makes the check above safe to be strict.
trap 'rm -f "$LOCK"' EXIT INT TERM

echo "=== $(date -Is) loop starting as pid $$ (interval ${INTERVAL}s)"

while true; do
  if [ -f .factory/STOP ]; then
    echo "=== $(date -Is) STOP file present, loop exiting"
    break
  fi
  echo "=== $(date -Is) tick"
  timeout 900 python factory/dispatch.py 2>&1
  sleep "$INTERVAL"
done
