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
# Where the operator watch reads from. `.factory/monitor.py` tails exactly this.
LOOP_LOG="${FACTORY_LOOP_LOG:-.factory/runs/loop.log}"
INTERVAL="${FACTORY_LOOP_INTERVAL:-60}"

# Escalations and watchdog halts must REACH somebody. The default is a log file.
export FACTORY_NOTIFY_CMD="${FACTORY_NOTIFY_CMD:-bash .factory/notify.sh}"

mkdir -p .factory/runs

# PORTABILITY, resolved once at start rather than per tick.
#
# `timeout` is GNU coreutils and macOS does not ship it; Homebrew installs it as
# `gtimeout`. With neither, the loop runs WITHOUT a per-tick cap, which is the right
# trade: the cap stops one wedged tick stalling the loop, and refusing to start has
# already stalled it permanently.
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT="timeout 900"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT="gtimeout 900"
else
  TIMEOUT=""
  echo "NOTE: no timeout/gtimeout on PATH, so a wedged tick will not be capped."
  echo "      brew install coreutils   gets you gtimeout."
fi

# macOS has shipped python3 without a bare `python` since Monterey. Without this the
# tick reports "command not found" once a minute and the loop looks alive while doing
# nothing whatsoever.
if command -v python >/dev/null 2>&1; then
  PY="python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "REFUSING TO START: neither python nor python3 is on PATH."
  exit 4
fi

# `date -Is` is GNU. BSD date rejects -I, so on macOS every log line below -- including
# the one announcing the loop started -- would be an error message. This spelling is
# understood by both and matches what the rest of the factory writes.
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if [ -f "$LOCK" ]; then
  OTHER="$(cat "$LOCK" 2>/dev/null)"
  # A STALE PID FILE MUST NOT WEDGE THE LOOP FOREVER. The common way this file is left
  # behind is the machine dying, which is exactly when you need the loop to come back
  # on its own. So a pid that is gone is cleared rather than obeyed.
  if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
    echo "=== $(stamp) REFUSING TO START: loop already running as pid $OTHER"
    echo "    Stop it first, or remove $LOCK if you are certain it is dead."
    exit 3
  fi
  echo "=== $(stamp) clearing stale $LOCK (pid ${OTHER:-unknown} is gone)"
  rm -f "$LOCK"
fi

echo $$ > "$LOCK"
# Clear it on any exit, including a kill, so the next start is not blocked by our own
# corpse. This is the half that makes the check above safe to be strict.
trap 'rm -f "$LOCK"' EXIT INT TERM

# THE LOOP WRITES ITS OWN LOG, because the monitor reads a FILE and this used to
# write only to a terminal.
#
# The README gives two commands, `bash .factory/loop.sh` and `python
# .factory/monitor.py`, and they did not connect: monitor.py tails
# .factory/runs/loop.log, which nothing created unless the operator happened to
# redirect. Follow the documentation exactly and you get a monitor watching a file
# that never appears, reporting "no dispatcher tick for 6 minutes" forever while the
# loop is running perfectly. Two shipped components, each correct, that did not
# compose -- and the failure mode is the one this project cares most about, because
# "the loop is dead" and "nobody wired the log" produce identical output.
#
# Still goes to stdout too, so running it in a terminal behaves as before.
mkdir -p "$(dirname "$LOOP_LOG")"
exec > >(tee -a "$LOOP_LOG") 2>&1

echo "=== $(stamp) loop starting as pid $$ (interval ${INTERVAL}s)"

while true; do
  if [ -f .factory/STOP ]; then
    echo "=== $(stamp) STOP file present, loop exiting"
    break
  fi
  echo "=== $(stamp) tick"
  $TIMEOUT "$PY" factory/dispatch.py 2>&1
  sleep "$INTERVAL"
done
