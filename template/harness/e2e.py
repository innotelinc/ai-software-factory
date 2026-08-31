"""The end-to-end path: ONE journey, the most valuable one, as the real user does it.

Not a suite. The answer to "the single most valuable thing someone does with this,
from the first click to the thing they end up looking at."

THIS IS WHERE THE ASSERTIONS LIVE, and they are the part of the harness nobody can
write for you. Everything else in `harness/` is plumbing that is the same in every
factory; these lines are the only place your product appears.

Three rules that decide whether any of it is worth anything:

  1. ASSERT WHAT A USER WOULD NOTICE, not a status code. `200 OK` is not evidence
     that the page said the right thing. A test that only checks the status passes
     on an app that returns an empty body forever.
  2. COUNT THE STEPS. `run_e2e` returns how many ASSERTIONS ran, and the gate
     compares that to a protected floor. A skipped assertion and a passed assertion
     are indistinguishable without a count.
  3. RETURN None ON FAILURE, having printed why. The caller turns that into a named
     GATE_FAILED so the log says which rung broke.
"""

from __future__ import annotations

STEPS = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global STEPS
    STEPS += 1
    if ok:
        print(f"  ok    {name}", flush=True)
        return True
    print(f"  FAIL  {name}  {detail}", flush=True)
    return False


def run_e2e(app) -> int | None:
    """Drive the app as a person does. Returns the assertion count, or None on failure."""
    global STEPS
    STEPS = 0

    # SCAFFOLD_EXAMPLE_DELETE_THIS_LINE_WHEN_YOU_WRITE_YOUR_OWN
    # ==================================================================
    # TODO: REPLACE EVERYTHING BELOW WITH YOUR OWN JOURNEY.
    #
    # Delete the marker line above once these are YOUR assertions.
    # `darkfactory doctor` BLOCKS level 2 and above until you do, because a gate
    # that is green about the template's sample product is worse than no gate at
    # all: it is green.
    #
    # What is here is a worked example against the shape of a small HTTP service,
    # kept because the SHAPE is worth stealing: act, then assert something
    # observable about what came back.
    # ==================================================================

    status, body, _ = app.get("/")
    if not check("the landing page renders", status == 200 and "<" in body, f"status={status}"):
        return None

    status, payload = app.get_json("/health")
    if not check(
        "the health readout answers with a real state",
        status == 200 and isinstance(payload, dict) and payload.get("status") == "ok",
        f"status={status} payload={payload}",
    ):
        return None

    return STEPS
