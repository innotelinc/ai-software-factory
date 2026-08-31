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


# --- the dial and the checks it makes load-bearing ----------------------------

def marker_checks() -> None:
    """At level 3 nobody reads the diff, so the two checks that justify that must be
    required to have RUN. A holdout that quietly stops running -- renamed, crashed on
    import, skipped by a bad path -- otherwise leaves a green gate, which is exactly
    the failure the marker list exists to prevent, aimed at the one check the whole
    arrangement rests on.

    Asked in a subprocess because the answer depends on the environment config was
    imported under, and this process already imported it once.
    """
    import os
    import subprocess

    here = str(Path(__file__).resolve().parent)
    probe = ("import sys; sys.path.insert(0, r'" + here + "'); "
             "import config; print(' '.join(config.REQUIRED_MARKERS))")

    def markers_at(level: int) -> set:
        env = {**os.environ, "FACTORY_AUTONOMY": str(level)}
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             env=env, timeout=60)
        return set((out.stdout or "").split())

    low, high = markers_at(2), markers_at(3)
    for m in ("PROTECTED_OK", "APP_STARTED", "E2E_PASSED", "GATE_OK"):
        check("marker " + m + " is required at every level", m in low)
    for m in ("HOLDOUT_PASSED", "MUTATIONS_OK"):
        check("marker " + m + " becomes required at level 3", m in high,
              "an unreviewed merge could pass without it having run")
    check("the level-3 set is a superset of the level-2 set", low <= high,
          "raising the dial must never remove a requirement")


# --- what a tick escalated, it must not then dispatch ------------------------

def escalation_checks() -> None:
    """An escalation writes a label to GitHub and the queue is read back from GitHub
    seconds later. GitHub does not promise you read your own write, and it did not: a
    validation was parked at needs-human and re-dispatched eight seconds later, back
    into the state a human had just been told to look at.

    `escalate()` must therefore report every target it parked -- the linked issue
    included -- so the caller can exclude them for the rest of the tick. Checked
    against the source, because calling it would mutate a real repository.
    """
    src = (Path(__file__).resolve().parent / "dispatch.py").read_text(encoding="utf-8")
    check("escalate() reports what it parked",
          "def escalate(target: str, why: str) -> set[str]:" in src,
          "a caller cannot exclude targets it is never told about")
    check("the reconcile sweep collects them",
          "escalated_here |= escalate(" in src)
    check("and seeds the dispatch exclusions with them",
          "exclude: set[str] = set(escalated_here)" in src,
          "the sweep would park a target and the loop would dispatch it anyway")
    check("in-loop escalations exclude too",
          src.count("exclude |= escalate(") >= 2,
          "the fix cap and the merge refusal park a target mid-tick as well")
    check("escalate parks with force",
          src.count('"needs-human", force=True') >= 2,
          "an escalation that the transition table can refuse is not an escalation -- "
          "and a merged PR or an already-parked item reaches needs-human from nowhere")


# --- the table must be enforced where the writes are ------------------------

def enforcement_checks() -> None:
    """A transition table that only the CLI consults governs the CLI.

    Eleven callers import `set_state` and call it directly -- the gate, the merge,
    the dispatcher. While the check lived in a wrapper around the function, every one
    of them was ungoverned, and the guarantee read as absolute in the docs.

    Exercised for real: a fake `fetch` puts an item in a state, and the move is
    attempted. No network, no GitHub.
    """
    original_fetch = state.fetch
    original_gh = state.gh
    writes: list = []
    state.gh = lambda *a, **k: writes.append(a) or ""
    try:
        def at(current_state: str):
            state.fetch = lambda t: {
                "_state": current_state, "_labels": [], "_kind": "pr",
                "_target": t, "state": "OPEN",
            }

        at("needs-human")
        try:
            state.set_state("gh:pr:1", "validating")
            check("a node cannot claim an item parked at needs-human", False,
                  "the write went through; the escalation guarantee is decorative")
        except state.IllegalTransition:
            check("a node cannot claim an item parked at needs-human", True)

        # Park from `merged`, which reaches NOTHING in the table -- so this only
        # passes if `force` is genuinely exempt. Parking from needs-human proves
        # nothing: old == new short-circuits the check before force is consulted,
        # and a build with force removed entirely sailed through that version.
        at("merged")
        before = len(writes)
        try:
            state.set_state("gh:pr:1", "needs-human", force=True)
            check("parking is always allowed, from a state that reaches nothing",
                  len(writes) > before)
        except state.IllegalTransition:
            check("parking is always allowed, from a state that reaches nothing", False,
                  "an escalation a table lookup can block is not an escalation")

        at("validating")
        before = len(writes)
        state.set_state("gh:pr:1", "passed")
        check("a legal move still goes through", len(writes) > before)

        at("passed")
        try:
            state.set_state("gh:pr:1", "validating")
            check("passed cannot be re-claimed for validation", False,
                  "two validations would hold one PR")
        except state.IllegalTransition:
            check("passed cannot be re-claimed for validation", True)

        at("open")
        before = len(writes)
        state.set_state("gh:pr:1", "open")
        check("re-applying the current state is allowed", len(writes) > before,
              "the labels ARE the state, so a correct state with no label is unreadable")
    finally:
        state.fetch = original_fetch
        state.gh = original_gh

    src = (Path(__file__).resolve().parent / "state.py").read_text(encoding="utf-8")
    check("the check is inside set_state, not in a wrapper",
          "raise IllegalTransition(" in src.split("def set_state")[1].split("def ")[0],
          "a wrapper governs only the callers that use the wrapper")


# --- every state write must be able to fail safely ---------------------------

def write_safety_checks() -> None:
    """`set_state` talks to GitHub and can now also refuse an illegal move, so every
    call site must either be inside a `try` or be a forced park.

    One was not. The approve-but-hold branch of the gate wrote the state bare while
    the branch fifteen lines below it -- the same write, for the same reason -- was
    guarded. Unguarded, a label edit that fails ends the gate in a traceback and
    leaves the PR at `validating` with nothing holding it: the exact shape the
    reconcile sweep has to clean up, arriving as a crash instead of a verdict.
    """
    import ast as _ast

    here = Path(__file__).resolve().parent
    for mod in sorted(here.glob("*.py")):
        if mod.name.startswith("_"):
            continue
        try:
            tree = _ast.parse(mod.read_text(encoding="utf-8"))
        except SyntaxError:
            check("factory/" + mod.name + " parses", False)
            continue

        guarded: set = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Try):
                for inner in _ast.walk(node):
                    guarded.add(id(inner))

        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            if not _ast.unparse(node.func).endswith("set_state"):
                continue
            forced = any(k.arg == "force" for k in node.keywords)
            where = "factory/" + mod.name + ":" + str(node.lineno)
            check("the state write at " + where + " can fail safely",
                  forced or id(node) in guarded,
                  "a failed label edit ends the node in a traceback instead of a verdict")


def main() -> int:
    quiet = "--quiet" in sys.argv
    with tempfile.TemporaryDirectory() as td:
        lock_checks(Path(td))
    gate_checks()
    state_checks()
    marker_checks()
    escalation_checks()
    enforcement_checks()
    write_safety_checks()

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
