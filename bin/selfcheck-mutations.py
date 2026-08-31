#!/usr/bin/env python3
"""Would the self-test know?

`factory/_selftest.py` pins the factory's own machinery. This asks the question that
matters about any set of checks: **can they fail?** It injects each defect below into a
throwaway copy of the template and requires the self-test to go red.

Everything in the template answers "is this build good?". The self-test answers "would
the thing deciding that know if it were not?". This answers the same question one level
up, about the self-test.

    python bin/selfcheck-mutations.py
    python bin/selfcheck-mutations.py --repo /path/to/an/installed/repo

A NOT_APPLICABLE entry is a defect that provably changes no behaviour, named here
rather than deleted, because a set that quietly drops the ones it cannot catch is a set
whose score means nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
NEWLINE = chr(10)

# (name, file, anchor, replacement, applicable)
DEFECTS = [
    ("the transition check moves back out of set_state", "factory/state.py",
     "    if not force and old != new and new not in TRANSITIONS.get(old, set()):",
     "    if False:", True),
    ("parking loses its exemption", "factory/state.py",
     "    if not force and old != new", "    if old != new", True),
    ("re-applying the current state is refused", "factory/state.py",
     "    if not force and old != new and", "    if not force and", True),
    ("needs-human stops being terminal", "factory/state.py",
     '    "needs-human": set(),', '    "needs-human": {"accepted"},', True),
    ("escalate stops forcing the park", "factory/dispatch.py",
     'state.set_state(target, "needs-human", force=True)',
     'state.set_state(target, "needs-human")', True),
    ("the sweep stops excluding what it just escalated", "factory/dispatch.py",
     "    exclude: set[str] = set(escalated_here)", "    exclude: set[str] = set()", True),
    ("an unrecognised run status frees a lock", "factory/dispatch.py",
     '                    "error", "errored", "timeout", "timed_out", "stopped"}',
     '                    "error", "errored", "timeout", "timed_out", "stopped", "running"}',
     True),
    ("the level-3 markers stop following the dial", "factory/config.py",
     "if AUTONOMY >= 3:", "if False:", True),
    ("a state write loses its try/except", "factory/gate.py",
     "            try:" + NEWLINE + '                state.set_state(target, "held")',
     '            state.set_state(target, "held")', True),
    ("the deploy gate stops requiring markers", "factory/deploy.py",
     "    if not config.HEALTH_MARKERS:", "    if False:", True),
    ("the reaper consults the pid on a lock that names a run", "factory/dispatch.py",
     "        if lock_run_id(lock):", "        if False:", True),
    ("the hold becomes a sentence again", "factory/gate.py",
     '                state.set_state(target, "held")',
     '                state.set_state(target, "passed")', True),
    ("held becomes mergeable", "factory/state.py",
     '    "held": {"open", "needs-human", "rejected"},',
     '    "held": {"open", "needs-human", "rejected", "merged"},', True),
    ("done stops closing the issue", "factory/state.py",
     '        elif new == "done" and current.get("state") == "OPEN":',
     '        elif False:', True),
    # NOT APPLICABLE, and stated rather than dropped. Removing the empty-list guard
    # changes nothing observable: an empty `status_by_id` means every lookup returns
    # None, and the per-lock "not in the reported window, so keep it" rule already
    # holds the lock. The guard is defence in depth and a statement of intent, not a
    # second mechanism, so no test can distinguish a build without it.
    ("the empty run list guard is removed", "factory/dispatch.py",
     "    if not status_by_id:", "    if False:", False),
]


def main(argv: list[str]) -> int:
    root = HOME / "template"
    if "--repo" in argv:
        root = Path(argv[argv.index("--repo") + 1]).resolve()

    print("injecting into a copy of " + str(root) + "\n")
    caught = applicable = 0
    problems: list[str] = []

    for name, rel, anchor, replacement, live in DEFECTS:
        tmp = Path(tempfile.mkdtemp()) / "probe"
        shutil.copytree(root, tmp, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        target = tmp / rel
        try:
            source = target.read_text(encoding="utf-8")
            hits = source.count(anchor)
            if hits != 1:
                # AN AMBIGUOUS ANCHOR IS NOT A PASS. Injecting into the wrong one of
                # two identical lines measures a defect nobody wrote.
                print("  NOT_INJECTED   " + name + "  (anchor appears "
                      + str(hits) + "x in " + rel + ")")
                problems.append(name)
                continue
            target.write_text(source.replace(anchor, replacement, 1), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(tmp / "factory" / "_selftest.py"), "--quiet"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300,
            )
            went_red = proc.returncode != 0
            if not live:
                print("  NOT_APPLICABLE " + name + "  (changes no behaviour; see the note)")
                continue
            applicable += 1
            if went_red:
                caught += 1
                print("  CAUGHT         " + name)
            else:
                print("  ESCAPED        " + name)
                problems.append(name)
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    print()
    print("SELFCHECK_MUTATIONS_CAUGHT=" + str(caught) + " applicable=" + str(applicable))
    if problems:
        print("\nThe self-test cannot see: " + "; ".join(problems))
        return 1
    print("Every applicable defect turns the self-test red.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
