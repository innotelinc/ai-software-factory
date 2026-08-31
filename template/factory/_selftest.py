"""_selftest.py -- the harness for the factory's own machinery.

`harness/` asks "is the product working?". THIS asks "is the thing that decides
that working?", and the two are not the same question. Every check below exists
because the behaviour it pins was once wrong in a way that read as normal
operation: a lock released a tick after it was taken, a gate that passed on an
empty log, a state machine that let a node walk an item back out of needs-human.

Fast, offline, no network, no GitHub. The doctor runs it on every audit, so a
regression here is reported before the dial is trusted rather than after.

    python factory/_selftest.py            # run them
    python factory/_selftest.py --quiet    # markers only
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Import the way every other module here imports -- flat, from this directory.
# `import config` and `from factory import config` produce TWO module objects with
# separate state, so a test that reaches for the second one is configuring a copy
# of the thing it believes it is testing. That mistake is silent: the calls all
# succeed and every assertion about the effect comes back false.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import dispatch  # noqa: E402
import gate  # noqa: E402
import state  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(what + ((" -- " + detail) if detail else ""))


# --- the lock, and the difference between "finished" and "unanswered" ---------
# THE INCIDENT: the release path built a set of active branch names, the engine
# populated none of them, the blanks were filtered away, and every lock was then
# compared against an empty set. `any()` over nothing is False, so it released
# every lock one tick after it was taken and the reconcile sweep escalated a
# running lap as dead. An empty answer was read as a negative answer.

def lock_checks(tmp: Path) -> None:
    original = config.LOCKS_RUNTIME
    original_log = dispatch.log
    # A test must not write to the operator's log. A LOCK_RELEASED line about a run id
    # that never existed is worse than noise: it is evidence, in the place someone goes
    # to reconstruct what the factory did, about something that never happened.
    dispatch.log = lambda *a, **k: None
    config.LOCKS_RUNTIME = tmp / "locks"
    config.LOCKS_RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        run_id = "11111111-2222-3333-4444-555555555555"

        def fresh() -> Path:
            lk = config.LOCKS_RUNTIME / "implement-gh-issue-9.lock"
            lk.unlink(missing_ok=True)
            assert dispatch.acquire(lk)
            with lk.open("a", encoding="utf-8") as fh:
                fh.write("run " + run_id + "\n")
            return lk

        lk = fresh()
        check("acquire is exclusive", not dispatch.acquire(lk),
              "a second dispatcher took a lock that was already held")
        check("the run id is read back off the lock",
              dispatch.lock_run_id(lk) == run_id)

        dispatch.release_settled_locks(payload_override={"runs": []})
        check("an EMPTY run list keeps the lock", lk.exists(),
              "empty was treated as an answer; this is the original incident")

        dispatch.release_settled_locks(payload_override={"runs": [{"id": "", "status": ""}]})
        check("a run list with no usable ids keeps the lock", lk.exists())

        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": "99999999-0000-0000-0000-000000000000", "status": "completed"}]})
        check("a list that does not mention this run keeps the lock", lk.exists(),
              "absence from a windowed list is not evidence the run ended")

        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": run_id, "status": "running"}]})
        check("a RUNNING run keeps the lock", lk.exists())

        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": run_id, "status": "some-state-this-engine-invented"}]})
        check("an unrecognised status keeps the lock", lk.exists(),
              "unknown must mean still running, never settled")

        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": run_id, "status": "completed"}]})
        check("a COMPLETED run releases the lock", not lk.exists(),
              "nothing would ever be released, so every target stalls until reaped")

        lk = fresh()
        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": run_id, "status": "failed"}]})
        check("a FAILED run releases the lock", not lk.exists())

        lk = config.LOCKS_RUNTIME / "implement-gh-issue-8.lock"
        lk.unlink(missing_ok=True)
        assert dispatch.acquire(lk)          # no run id recorded
        dispatch.release_settled_locks(payload_override={"runs": [
            {"id": run_id, "status": "completed"}]})
        check("a lock carrying no run id is left to the age reaper", lk.exists())
        lk.unlink(missing_ok=True)
    finally:
        config.LOCKS_RUNTIME = original
        dispatch.log = original_log


# --- the gate, and "empty is not pass" ---------------------------------------

def gate_checks() -> None:
    check("an empty log yields no counts",
          all(v is None for v in gate.observed_counts("").values()),
          "a missing marker must read as unknown, never as zero-and-fine")
    check("a marker with no count reads as unknown",
          gate.counted("E2E_PASSED", "E2E_PASSED steps") is None)
    check("the last occurrence of a marker wins",
          gate.counted("E2E_PASSED steps=3\nE2E_PASSED steps=17", "E2E_PASSED steps") == 17,
          "a re-run inside one log must not be scored on its first attempt")
    for key in gate.FLOOR_SOURCES:
        check("floor key " + key + " has a source marker",
              key in gate.observed_counts("E2E_PASSED steps=1"))


# --- the state machine, and the escalation guarantee --------------------------

def state_checks() -> None:
    check("needs-human is terminal for every node",
          state.TRANSITIONS["needs-human"] == set(),
          "a node could walk an item back out of the one state that means STOP")
    check("merged is terminal", state.TRANSITIONS["merged"] == set())
    check("passed does not lead back to validating",
          "validating" not in state.TRANSITIONS["passed"],
          "two validations would claim one PR")
    check("every state can reach needs-human",
          all("needs-human" in v for k, v in state.TRANSITIONS.items()
              if v and k not in ("merged",)),
          "a state with no escape hatch is a state that strands work")
    for src, dsts in state.TRANSITIONS.items():
        for d in dsts:
            check("transition target " + d + " is a declared state",
                  d in state.TRANSITIONS, "reachable from " + src)
    # `open` is a PR with no disposition label and `closed-unlabelled` is an issue
    # GitHub closed on merge, so both are the ABSENCE of a label by construction.
    # Naming them here is what stops that exemption growing quietly: any other
    # label-less state is a state that cannot be written, so it cannot be read back.
    labelless = {"open", "closed-unlabelled"}
    check("every state that is not defined by absence has a label",
          all(s in state.LABEL_FOR_STATE for s in state.TRANSITIONS if s not in labelless),
          "missing: " + " ".join(sorted(
              s for s in state.TRANSITIONS
              if s not in labelless and s not in state.LABEL_FOR_STATE)))


def main() -> int:
    quiet = "--quiet" in sys.argv
    with tempfile.TemporaryDirectory() as td:
        lock_checks(Path(td))
    gate_checks()
    state_checks()

    if FAILURES:
        if not quiet:
            print("The factory's own machinery is broken:", file=sys.stderr)
            for f in FAILURES:
                print("  FAIL  " + f, file=sys.stderr)
        print("SELFTEST_FAILED checks=" + str(CHECKS) + " failed=" + str(len(FAILURES)))
        return 1
    if not quiet:
        print("Every machinery invariant holds.")
    print("SELFTEST_PASSED checks=" + str(CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
