#!/usr/bin/env python3
"""HOLDOUT SCENARIOS. This file lives in `.factory/holdout/`, NOT in `harness/`.

    .factory/holdout/run.py      <- here. The builder cannot READ this directory.
    harness/                     <- NOT here. The builder reads everything in harness/.

WHY THE PATH IS THE POINT

Everything in `harness/` sits inside the agent's optimisation loop: it can read
those checks, run them, and iterate until they are green. Given enough attempts it
will satisfy them -- which is exactly what you asked for, and exactly why passing
them proves less than it feels like it does.

These assertions are different only because the builder never sees them. Every
workflow node is launched with a deny list covering this directory, and `guard.py`
treats it as a protected path so no PR can edit it. That is the whole independence
argument, and it is the only honest reason to merge code nobody read.

Test the deny in BOTH directions before believing it: without it a node returns this
file's first line, with it the node returns blocked.

THE RULES, and they are short:

  1. WRITE THESE BEFORE THE WORK. A scenario written after seeing the implementation
     is a description of the implementation.
  2. DUPLICATE, DO NOT IMPORT. Importing a helper from `harness/` re-couples you to
     code the builder can edit, and the wall is gone with one refactor nobody
     noticed. The one carve-out is the process driver -- starting a process is not
     an assertion.
  3. COMPOSE. The dominant real failure is not cheating, it is FEATURE ISOLATION:
     components individually correct that never work together. Unit tests test
     features in isolation by definition, so the thing they measure is precisely the
     thing that is not broken. Test features TOGETHER, in sequences a user would
     actually perform.
  4. USE INPUTS THAT APPEAR NOWHERE ELSE IN THE REPO. If the value is grep-able from
     the builder's side it is a value it can special-case.

Emits `HOLDOUT_PASSED scenarios=N assertions=M`. The count is the point: a skipped
scenario and a passed scenario are indistinguishable without one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The DRIVER is shared (starting a process is not an assertion); the SCENARIOS are
# not. Rule 2 is about assertion helpers -- duplicate those.
_HARNESS = Path(__file__).resolve().parent.parent.parent / "harness"
sys.path.insert(0, str(_HARNESS))
from appproc import make_driver  # noqa: E402

CONFIG = json.loads((_HARNESS / "harness.config.json").read_text(encoding="utf-8"))

ASSERTIONS = 0
FAILURES: list[str] = []


def expect(name: str, ok: bool, detail: str = "") -> None:
    global ASSERTIONS
    ASSERTIONS += 1
    if not ok:
        FAILURES.append(f"{name}: {detail}")


# SCAFFOLD_EXAMPLE_DELETE_THIS_LINE_WHEN_YOU_WRITE_YOUR_OWN
# ==========================================================================
# TODO: DELETE EVERY SCENARIO BELOW AND WRITE YOURS.
# Delete the marker line above when they are yours. `darkfactory doctor` blocks
# level 3 until you do.
# ==========================================================================


def scenario_the_thing_still_works_after_a_restart(app) -> None:
    """Several features composed, across a process boundary.

    Each one passes its own unit test in isolation; what this asks is whether they
    agree with each other when a user actually strings them together.
    """
    status, payload = app.get_json("/health")
    expect("health answers", status == 200, f"status={status}")


SCENARIOS = [
    scenario_the_thing_still_works_after_a_restart,
]


def main() -> int:
    with make_driver(CONFIG) as app:
        for fn in SCENARIOS:
            try:
                fn(app)
            except Exception as e:  # noqa: BLE001
                FAILURES.append(f"{fn.__name__} raised {type(e).__name__}: {e}")

    if FAILURES:
        for f in FAILURES:
            print(f"  HOLDOUT_FAIL  {f}", flush=True)
        print(
            f"HOLDOUT_FAILED scenarios={len(SCENARIOS)} assertions={ASSERTIONS} "
            f"failures={len(FAILURES)}",
            flush=True,
        )
        return 1

    print(f"HOLDOUT_PASSED scenarios={len(SCENARIOS)} assertions={ASSERTIONS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
