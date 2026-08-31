"""The one escalation channel.

`needs-human` is the only state a human must act on, so it is the only one allowed
to interrupt one. Everything else this factory writes waits to be found -- and on an
unattended system, "waits to be found" means you learn about it when you next
remember to look.

Defined ONCE, here, because more than one place escalates: the dispatcher, the gate,
and the fix-attempt cap all reach that state by different routes. Three copies of a
notify block is three that drift, and the one that drifts is the one that goes quiet.

NEVER FATAL. An escalation whose webhook is down is still an escalation; the file
write has already happened by the time this is called.

THE CONTRACT, because getting it wrong produces a useless notification rather than
none:

    STDIN    "<target> needs a human: <reason>"   <- the whole message. Read this.
    argv[1]  "<target>"                           <- for routing or a subject line only

Somebody writing their own command reaches for the argument by reflex -- a one-line
Slack curl is the obvious case -- and gets a 3am alert whose entire body is
`gh:pr:14`: it tells you something is wrong and not what, which is close to no
notification at all.

    NOTIFY_CMD = 'curl -s -d @- https://ntfy.sh/my-factory-topic'
    NOTIFY_CMD = 'tee -a /var/log/factory-escalations.log'
    NOTIFY_CMD = 'xargs -0 -I{} curl -s -X POST -H "Content-type: application/json" -d "{\\"text\\":\\"{}\\"}" "$SLACK_WEBHOOK_URL"'

Test it the same way you test the stop button: on purpose, once.

    python factory/notify.py --test
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


def send(target: str, reason: str) -> str:
    """Returns a one-line status for the caller's log. Never raises."""
    if not config.NOTIFY_CMD:
        return (
            "NOT NOTIFIED - FACTORY_NOTIFY_CMD unset; this waits in "
            f"{config.NEEDS_HUMAN.relative_to(config.ROOT) if config.NEEDS_HUMAN.is_relative_to(config.ROOT) else config.NEEDS_HUMAN}"
        )
    # TERMINATED, and it is not cosmetic. The channel receives this on stdin, and the
    # documented starting point is `tee -a .factory/escalations.log`. Without the
    # newline every escalation runs into the next one and the log is a single
    # unreadable line -- which is worse than no log, because it looks like there is
    # one. A channel a person cannot skim is the "file nobody opens" problem wearing
    # a different hat.
    #
    # A stray blank line in a chat message costs nothing; a run-together log costs the
    # only record of what stopped, on the day somebody needs to read it.
    message = f"{target} needs a human: {reason}".rstrip() + "\n"
    try:
        p = subprocess.run(
            config.NOTIFY_CMD,
            shell=True,
            input=message,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(config.ROOT),
            env={**__import__("os").environ, "FACTORY_TARGET": target},
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"NOTIFY_FAILED ({e}) - the escalation is recorded in .factory/needs-human.md"
    if p.returncode != 0:
        return (
            f"NOTIFY_FAILED (exit {p.returncode}: {p.stderr.strip()[:200]}) - the "
            f"escalation is recorded in .factory/needs-human.md"
        )
    return "NOTIFIED via FACTORY_NOTIFY_CMD"


if __name__ == "__main__":
    if "--test" in sys.argv:
        print(send("gh:pr:0", "this is a deliberate test of the escalation channel"))
        print(
            "\nIf nothing arrived, the channel is not wired. Do not go to level 3 that "
            "way: unattended quietly means unmonitored."
        )
        sys.exit(0)
    if len(sys.argv) >= 3:
        print(send(sys.argv[1], " ".join(sys.argv[2:])))
    else:
        print(__doc__)
