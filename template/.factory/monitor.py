"""Operator-side watch on the dispatcher loop. Prints one line per thing worth acting on.

    python .factory/monitor.py            follow, emitting events
    python .factory/monitor.py --since 0  replay the whole log through the filter first

This is the SECOND layer and it is deliberately outside the factory. `factory/watchdog.py`
is the first: it runs inside every tick and can halt the machine on its own, which is the
only layer that works while nobody is watching. This one exists because a watchdog can
only report pathologies it has a detector for, and because a process cannot notice its
own death.

SILENCE IS NOT HEALTH, and that is the whole design constraint here. A monitor that only
prints when something is wrong makes "the factory is fine" and "the factory died four
hours ago" produce identical output. So this emits on:

  * anything the watchdog found, and any halt
  * escalations, stops, reaped locks, dispatch failures
  * THE LOOP GOING QUIET -- no tick for QUIET_MINUTES, re-stated every RENOTIFY_MINUTES
  * the loop coming back

The quiet detector is the one that earns the file. Everything else is a grep.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "runs" / "loop.log"
STOP = HERE / "STOP"

# THE ESCALATION LEDGER, and watching it is the whole reason this file was revised.
#
# The monitor watched only the DISPATCHER'S stdout, and the dispatcher escalates just
# one class of thing: a lap it noticed had stalled. Every other escalation is written
# by a WORKFLOW NODE -- the guard rejecting a protected path, the gate blocking on a
# floor, prepare refusing an unmergeable branch -- in a detached run whose output never
# passes through the loop.
#
# So on the day it mattered, four items escalated to needs-human, the factory went
# quiet because it correctly had nothing left to do, and the monitor reported NOTHING.
# It was working exactly as written. It was reading the one stream that could not carry
# the news. "Something needs a human" is the single most important event this system
# produces, and it was the one event the monitor could not see.
NEEDS_HUMAN = HERE / "needs-human.md"

POLL_SECONDS = 20
QUIET_MINUTES = 6.0        # the loop ticks every 60s, so 6 minutes is five missed ticks
RENOTIFY_MINUTES = 30.0

# Lines worth waking a person for. Deliberately includes the FAILURE signatures and not
# only the happy path: a filter that matches just progress markers goes silent during a
# crash loop, which reads exactly like a quiet, healthy night.
ACTIONABLE = re.compile(
    r"WATCHDOG(?!_OK)"          # any finding, any halt, and WATCHDOG_BROKE
    r"|STOPPED:"
    r"|ESCALATE\b"
    r"|LOCK_REAPED"
    r"|could not be dispatched"
    r"|PIPELINE_ERROR"
    # THE ALARM WATCHES ITSELF. A notification channel that silently stopped
    # working is indistinguishable from a quiet factory, which is the whole
    # reason this file exists one layer up.
    r"|NOTIFY_NTFY_FAILED|NOTIFY_WEBHOOK_FAILED|NOTIFY_DESKTOP_FAILED|NOTIFY_UNDELIVERED"
    # An escalation whose LABEL did not stick is a runaway waiting to happen:
    # the item keeps its old state and the dispatcher picks it straight back up.
    r"|ESCALATION_LABEL_FAILED|ESCALATION_ISSUE_UNKNOWN"
    r"|Traceback|ModuleNotFoundError|PermissionError"
    r"|MERGED\b|MERGE_BLOCKED"
)

TICK = re.compile(r"^=== (\S+) tick")


# A STANDING CONDITION MUST NOT BE A STANDING ALARM.
#
# The dispatcher ticks every 60s, so a persistent finding (`spend-blind`, say) reprints
# on every tick. That is not extra safety, it is the opposite: the tool that carries
# these events stops a monitor that floods, so a noisy line does not just annoy, it
# takes the whole watch offline -- and it buries the one-off events worth reading.
#
# So an identical message is announced ONCE, then suppressed, then re-stated at most
# every REPEAT_MINUTES with a count of how many times it recurred. Suppression is
# always visible in that restatement: a condition that quietly stopped being reported
# is the same failure as a monitor that never reported it.
REPEAT_MINUTES = 60.0
_seen: dict[str, list] = {}   # message -> [last_emitted_epoch, suppressed_count]

_TS = re.compile(r"^\[?\d{4}-\d{2}-\d{2}T[\d:.]+Z?\]?\s*")


def emit(kind: str, text: str) -> None:
    # Key on the message with its timestamp stripped, so the same finding on two
    # different ticks is recognised as the same finding.
    key = f"{kind}:{_TS.sub('', text).strip()}"
    now = time.time()
    prev = _seen.get(key)
    if prev is not None:
        if (now - prev[0]) / 60.0 < REPEAT_MINUTES:
            prev[1] += 1
            return
        suffix = f"  (recurred {prev[1]}x since last reported)" if prev[1] else ""
        _seen[key] = [now, 0]
        print(f"[{datetime.now().strftime('%H:%M')}] {kind}: {text}{suffix}"[:400], flush=True)
        return
    _seen[key] = [now, 0]
    print(f"[{datetime.now().strftime('%H:%M')}] {kind}: {text}"[:400], flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=None,
                    help="byte offset to start from; 0 replays the whole log")
    args = ap.parse_args()

    offset = args.since if args.since is not None else (LOG.stat().st_size if LOG.exists() else 0)
    nh_offset = NEEDS_HUMAN.stat().st_size if NEEDS_HUMAN.exists() else 0
    last_tick = time.time()
    last_quiet_notice = 0.0
    was_quiet = False
    stop_seen = STOP.exists()

    emit("MONITOR", f"watching {LOG.name} + {NEEDS_HUMAN.name}, quiet threshold {QUIET_MINUTES:.0f}m")

    while True:
        try:
            if LOG.exists():
                size = LOG.stat().st_size
                # A truncated or rotated log must not make the reader seek past the end
                # and go permanently silent.
                if size < offset:
                    offset = 0
                if size > offset:
                    with LOG.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                        offset = fh.tell()
                    for line in chunk.splitlines():
                        if TICK.match(line):
                            last_tick = time.time()
                            if was_quiet:
                                was_quiet = False
                                emit("RESUMED", "the loop is ticking again")
                            continue
                        if ACTIONABLE.search(line):
                            emit("EVENT", line.strip())

            # Escalations, which arrive here rather than in the loop's output.
            if NEEDS_HUMAN.exists():
                nh_size = NEEDS_HUMAN.stat().st_size
                if nh_size < nh_offset:
                    nh_offset = 0
                if nh_size > nh_offset:
                    with NEEDS_HUMAN.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(nh_offset)
                        fresh = fh.read()
                        nh_offset = fh.tell()
                    for line in fresh.splitlines():
                        if line.strip().startswith("-"):
                            emit("NEEDS_HUMAN", line.strip().lstrip("- "))

            if STOP.exists() and not stop_seen:
                stop_seen = True
                reason = ""
                try:
                    reason = STOP.read_text(encoding="utf-8", errors="replace").strip()[:250]
                except OSError:
                    pass
                emit("HALTED", f".factory/STOP appeared. {reason}")
            elif not STOP.exists() and stop_seen:
                stop_seen = False
                emit("CLEARED", ".factory/STOP removed; the loop may dispatch again")

            quiet_for = (time.time() - last_tick) / 60.0
            if quiet_for >= QUIET_MINUTES:
                since_notice = (time.time() - last_quiet_notice) / 60.0
                if not was_quiet or since_notice >= RENOTIFY_MINUTES:
                    was_quiet = True
                    last_quiet_notice = time.time()
                    emit("SILENT", f"no dispatcher tick for {quiet_for:.0f} minutes. The loop "
                                   f"may be dead, blocked, or the machine asleep.")
        except Exception as e:  # noqa: BLE001
            # A monitor that dies on a transient read error is a monitor that is off
            # for the rest of the night without saying so.
            emit("MONITOR_ERROR", f"{type(e).__name__}: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
