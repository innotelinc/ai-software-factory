"""Dispatch the scheduled regression. What the weekly cron entry calls.

Separate from the dispatcher on purpose. The dispatcher answers "what work is
pending?" from the queue; this answers "is what already merged still working?", which
is a different question with a different cadence and a different failure mode. Folding
it into the dispatcher's priority order would mean a busy queue silently starves the
one check that looks at main.

It respects the same two things the dispatcher does: the stop button, and the dial.
Level 4 is where a factory is allowed to file its own bugs -- below that the
regression still RUNS, it just reports rather than filing, because an issue queue that
fills itself before anyone has watched a full cycle is a queue nobody trusts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import state  # noqa: E402


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}", flush=True)


def main() -> int:
    stopped, why = state.stop_requested()
    if stopped:
        log(f"STOPPED: {why}")
        return 0

    if config.AUTONOMY < 1:
        log("AUTONOMY=0: the regression is not dispatched. Run it by hand to watch it.")
        return 0

    if config.AUTONOMY < 4:
        log(
            f"autonomy={config.AUTONOMY}: the regression will RUN and report, but issues "
            f"it finds are not filed automatically until level 4."
        )

    lock = config.LOCKS_RUNTIME / "regress.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        log("SKIP - a regression run already holds its lock")
        return 0

    try:
        config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        logfile = config.RUNS_DIR / "regress.log"
        cmd = [
            config.ARCHON_BIN, "workflow", "run", config.WORKFLOW_REGRESS,
            "--branch", "factory/regress", "--detach", "regress",
        ]
        log(f"DISPATCH {config.WORKFLOW_REGRESS}")
        with logfile.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.now(timezone.utc).isoformat()} {' '.join(cmd)}\n")
            fh.flush()
            rc = subprocess.run(
                cmd, cwd=str(config.SHARED), stdout=fh, stderr=subprocess.STDOUT,
                timeout=600, env={**os.environ, "IS_SANDBOX": "1"},
            ).returncode
        if rc != 0:
            log(f"DISPATCH_FAILED exit {rc} - see {logfile}")
            return 1
        log("DISPATCHED (detached)")
        return 0
    finally:
        # Released here, not by a completion hook: this dispatch is one shot a week and
        # a lock that outlives it by six days would silently skip the next run.
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
