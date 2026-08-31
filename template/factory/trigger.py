"""Component 2, the trigger. Built LAST on purpose.

    python factory/trigger.py --status
    python factory/trigger.py --install
    python factory/trigger.py --remove

TURNING ON A SCHEDULER IS THE MOMENT THE REPO BECOMES AUTONOMOUS. Everything before
it can be run by hand and inspected. A factory whose dispatcher was built first is an
unsupervised code generator that nobody has ever checked.

IT REFUSES BELOW DIAL 1. A scheduler at level 0 wakes up forever and correctly does
nothing, which is exactly how people convince themselves a factory is running when it
has never completed a lap.

NOTHING PUSHES. There is no webhook and there is not meant to be one: this wakes on a
timer, reads the state, and dispatches at most MAX_PARALLEL things. An issue filed at
09:01 waits for the next tick. A push trigger that breaks fails SILENTLY and looks
exactly like a factory with nothing to do; a poll that breaks is a poll you can see
not running.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

DISPATCH = f'"{sys.executable}" factory/dispatch.py'
REGRESS = f'"{sys.executable}" factory/regress-trigger.py'


def record(kind: str, detail: str) -> None:
    config.TRIGGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.TRIGGER_FILE.write_text(
        json.dumps(
            {
                "kind": kind,
                "detail": detail,
                "interval_minutes": config.INTERVAL_MINUTES,
                "armed_at": datetime.now(timezone.utc).isoformat(),
                "autonomy_at_arming": config.AUTONOMY,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def status() -> int:
    if config.TRIGGER_FILE.exists():
        print(config.TRIGGER_FILE.read_text(encoding="utf-8"))
    else:
        print("NOT_ARMED - the factory only runs when you run it.")
        print()
        print("  A fully built factory with nothing scheduled audits identically to a")
        print("  running one. That is why this is a check and not a comment.")
    return 0


def install_cron() -> int:
    rc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=60)
    existing = rc.stdout if rc.returncode == 0 else ""
    if config.TASK_NAME in existing:
        print(f"ALREADY_ARMED: a crontab entry for {config.TASK_NAME} exists")
        return 0

    log = config.SHARED / ".factory" / "factory.log"
    lines = [
        existing.rstrip(),
        f"# {config.TASK_NAME} -- the dark factory dispatcher",
        f"*/{config.INTERVAL_MINUTES} * * * * cd {config.SHARED} && {DISPATCH} >> {log} 2>&1",
        f"# {config.TASK_NAME} -- the scheduled regression",
        f"{config.REGRESS_CRON} cd {config.SHARED} && {REGRESS} >> {log} 2>&1",
        "",
    ]
    p = subprocess.run(["crontab", "-"], input="\n".join(lines), text=True, timeout=60)
    if p.returncode != 0:
        print("ARM_FAILED: crontab refused the entry", file=sys.stderr)
        return 1
    record("cron", f"*/{config.INTERVAL_MINUTES} * * * *")
    print(f"ARMED cron every {config.INTERVAL_MINUTES} minutes; log -> {log}")
    return 0


def install_task_scheduler() -> int:
    """Windows. Note it only runs while someone is logged in unless configured
    otherwise -- a detail that presents as "the factory stopped overnight"."""
    log = config.SHARED / ".factory" / "factory.log"
    cmd = (
        f'cmd /c "cd /d {config.SHARED} && {DISPATCH} >> {log} 2>&1"'
    )
    p = subprocess.run(
        [
            "schtasks", "/Create", "/F",
            "/SC", "MINUTE", "/MO", str(config.INTERVAL_MINUTES),
            "/TN", config.TASK_NAME,
            "/TR", cmd,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if p.returncode != 0:
        print(f"ARM_FAILED: {p.stdout} {p.stderr}", file=sys.stderr)
        return 1
    record("schtasks", config.TASK_NAME)
    print(f"ARMED Task Scheduler task '{config.TASK_NAME}' every {config.INTERVAL_MINUTES} minutes")
    print()
    print("  NOTE: a Task Scheduler task only runs while someone is logged in unless")
    print("  you configure it otherwise. That detail presents as 'the factory stopped")
    print("  overnight', which looks exactly like a factory with nothing to do.")
    return 0


def remove() -> int:
    removed = False
    if os.name == "nt":
        p = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", config.TASK_NAME],
            capture_output=True, text=True, timeout=120,
        )
        removed = p.returncode == 0
    elif shutil.which("crontab"):
        rc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=60)
        if rc.returncode == 0 and config.TASK_NAME in rc.stdout:
            kept = []
            skip_next = False
            for line in rc.stdout.splitlines():
                if config.TASK_NAME in line and line.strip().startswith("#"):
                    skip_next = True
                    continue
                if skip_next:
                    skip_next = False
                    continue
                kept.append(line)
            subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True, timeout=60)
            removed = True
    config.TRIGGER_FILE.unlink(missing_ok=True)
    print("DISARMED" if removed else "DISARMED (nothing was armed)")
    return 0


def main(argv: list[str]) -> int:
    if "--remove" in argv:
        return remove()
    if "--status" in argv or not argv:
        return status()

    if config.AUTONOMY < 1:
        print(
            "REFUSED: the dial is at 0, so a scheduler would wake up forever and\n"
            "  correctly do nothing. That is exactly how people convince themselves a\n"
            "  factory is running when it has never completed a lap.\n\n"
            "  Prove one lap by hand first:\n"
            "    darkfactory run implement gh:issue:<n>\n"
            "  then raise the dial:\n"
            "    darkfactory level 1",
            file=sys.stderr,
        )
        return 1

    if os.name == "nt":
        return install_task_scheduler()
    if shutil.which("crontab"):
        return install_cron()

    print(
        "ARM_FAILED: no scheduler found. Install one by hand:\n\n"
        f"  */{config.INTERVAL_MINUTES} * * * * cd {config.SHARED} && {DISPATCH} "
        f">> {config.SHARED}/.factory/factory.log 2>&1\n"
        f"  {config.REGRESS_CRON} cd {config.SHARED} && {REGRESS} "
        f">> {config.SHARED}/.factory/factory.log 2>&1\n\n"
        "  A systemd timer with OnUnitInactiveSec is worth it once a lap takes longer\n"
        "  than the interval -- it starts counting after the previous run FINISHES,\n"
        "  which a cron does not.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
