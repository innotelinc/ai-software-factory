"""The structural gate. One of the two decisions made by code a model cannot argue past.

    python factory/gate.py <pr-target> <gate-log> <verdict.json>

It reads the RAW output of the validation run and the verdict the judge wrote, and
it lets a merge happen only when both agree. WHEN THEY DISAGREE, THE RAW OUTPUT
WINS and the PR escalates -- because a model summarising its own run is precisely
what cannot be trusted at this step.

Every check below is a POSITIVE assertion. None of them test for the absence of the
word "error". A check that never ran produces no failures, and "did anything fail?"
reads that as success.

Exit codes:
    0  GATE_PASS (merge performed) or GATE_PASS_HELD (green, merge held for a human)
    1  GATE_FAIL -- escalated to needs-human
    2  GATE_REFUSED -- called from the wrong state; nothing to gate on
    3  CHANGES_REQUESTED / REJECTED -- a verdict was recorded, no merge
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post(target: str, body: str) -> None:
    """Never let saying something be the thing that fails a decision already made."""
    try:
        state.comment(target, body)
    except Exception as e:  # noqa: BLE001
        print(f"COMMENT_FAILED {target}: {e}", file=sys.stderr)


def fail(target: str, reason: str) -> int:
    """Escalate the PR AND its issue, write the ledger, and notify. All four.

    A PR parked at needs-human whose issue still reads `in-progress` is an
    escalation nothing can see: the dispatcher moves on to unrelated work while the
    escalated issue sits in a state that means "being worked on" with nothing
    working on it. Both halves are done here, by the code that made the decision.
    """
    print(f"GATE_FAIL: {reason}", file=sys.stderr)
    try:
        state.set_state(target, "needs-human", force=True)
    except Exception:  # noqa: BLE001
        pass

    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(f"- {now()}  {target}  (gate)  {reason}\n")

    issue = None
    try:
        issue = state.linked_issue(target)
    except Exception:  # noqa: BLE001
        pass
    if issue:
        try:
            state.set_state(issue, "needs-human", force=True)
        except Exception:  # noqa: BLE001
            pass
        with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
            fh.write(f"- {now()}  {issue}  (gate)  its PR {target} was blocked: {reason}\n")

    # A blocked gate is the single most important thing a human can be told.
    print(notify.send(target, f"(gate) {reason}"))

    post(
        target,
        "## Factory Gate: BLOCKED\n\n"
        f"Reason: {reason}\n\n"
        "Decided by `factory/gate.py`, not by a reviewer. Not appealable by re-running; "
        "fix the underlying cause.",
    )
    return 1


def read_floor() -> dict:
    if not config.FLOOR_FILE.exists():
        return {}
    try:
        raw = json.loads(config.FLOOR_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, int) and not k.startswith("_")}


def counted(log: str, marker: str) -> int | None:
    """`E2E_PASSED steps=11` -> 11. The count is the point: a skipped check and a
    passed check are indistinguishable without one."""
    m = None
    for m in re.finditer(rf"{re.escape(marker)}[^\n]*?=(\d+)", log):
        pass
    return int(m.group(1)) if m else None


# Which marker carries the observed count for each floor key. Adding a floor key
# without a source here is a configuration error, reported rather than ignored --
# a ratchet nobody can read is not a ratchet.
FLOOR_SOURCES = {
    "e2e_steps_asserted": "E2E_PASSED steps",
    "holdout_assertions": "HOLDOUT_PASSED scenarios=%d assertions",
    "unit_tests": "UNIT_PASSED tests",
    "mutations_caught": "MUTATIONS_CAUGHT",
}


def observed_counts(log: str) -> dict[str, int | None]:
    return {
        "e2e_steps_asserted": counted(log, "E2E_PASSED steps"),
        "holdout_assertions": counted(log, "assertions"),
        "unit_tests": counted(log, "UNIT_PASSED tests"),
        "mutations_caught": counted(log, "MUTATIONS_CAUGHT"),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    target, log_path, verdict_path = argv[0], Path(argv[1]), Path(argv[2])

    # --- 0. precondition ------------------------------------------------------
    # The PR must already be `validating`, which the validate workflow sets after
    # the tripwire clears and before any check runs. Asserted rather than assumed:
    # if this can be called on an `open` PR then it can be called on a PR nobody
    # independently validated, and the state machine is the only thing that knows
    # the difference.
    current = state.fetch(target)["_state"]
    if current != "validating":
        print(
            f"GATE_REFUSED: {target} is '{current}', expected 'validating'.\n"
            "  The gate runs INSIDE the validate workflow, after the tripwire and "
            "after state=validating. Reaching it from another state means the "
            "independent validation was skipped, so there is nothing here to gate on.",
            file=sys.stderr,
        )
        return 2

    # --- 1. empty is not pass -------------------------------------------------
    if not log_path.exists() or not log_path.stat().st_size:
        return fail(target, "the gate log is empty -- the validation run produced no output at all")
    log = log_path.read_text(encoding="utf-8", errors="replace")

    # WHICH step stopped the run, if one did. The marker assertions below run in a
    # fixed order and not in run order, so a suite that died at an early step gets
    # reported as "APP_STARTED absent": true, and about four steps downstream of the
    # cause. An unattended system that misnames its own failure sends whoever reads
    # the log at 3am to the wrong file, and that is most of the cost of a failure
    # nobody watched.
    #
    # A RED RUNG IS NOT A MACHINERY FAULT. This used to escalate straight to
    # needs-human, which is wrong in the most ordinary case there is: a check failed,
    # and a failing check is exactly what the fix loop exists for. Escalating it woke
    # a person for something the factory could have fixed itself, and -- worse -- the
    # PR stopped in a state no node may leave, so the fix loop could never see it.
    #
    # So: a NAMED red rung goes round the fix loop with the log attached. Only a run
    # that produced no verdict-able evidence at all reaches a human.
    red_rung = ""
    stopped = re.findall(r"GATE_FAILED:\s*([a-z0-9_-]+)", log)
    if stopped:
        red_rung = stopped[-1]
        idx = log.rfind(f"GATE_FAILED: {red_rung}")
        excerpt = ""
        if idx > 0:
            excerpt = " / ".join(log[max(0, idx - 600):idx].strip().splitlines()[-4:])[:400]
        print(f"GATE_RED step={red_rung} {excerpt}")

    missing = [m for m in config.REQUIRED_MARKERS if m not in log]
    if missing and not red_rung:
        # Markers absent AND nothing reported a failure. That is not a red gate, it is
        # a gate that did not run: a check which neither passed nor failed produced no
        # evidence about anything, and there is nothing here a fix node could act on.
        return fail(
            target,
            "required marker(s) absent from the run log with no step reporting a "
            "failure: " + " ".join(missing) + ". A check that did not report that it "
            "ran, and did not report that it failed, did not run. If you deleted a "
            "check, delete its marker from REQUIRED_MARKERS in the same human commit.",
        )
    if not missing:
        print(f"MARKERS_OK checked={len(config.REQUIRED_MARKERS)}")

    # BLOCKERS are red-gate reasons the fix loop can act on. They are collected rather
    # than raised, because the judge should see the whole picture and the fix node
    # should get every finding in one pass rather than one per cycle.
    blockers: list[str] = []
    if red_rung:
        blockers.append(f"the '{red_rung}' rung failed")
    if missing:
        blockers.append("markers absent after that failure: " + " ".join(missing))

    # --- 2. counts, not vibes -------------------------------------------------
    floor = read_floor()
    obs = observed_counts(log)
    slack: dict[str, int] = {}
    for key, minimum in floor.items():
        got = obs.get(key)
        if got is None:
            if red_rung:
                # The run stopped before this rung reported. Already covered by the
                # red rung above; saying it twice sends the fix node chasing a
                # measurement that was never going to exist.
                continue
            return fail(
                target,
                f"the ratchet has a floor for '{key}' ({minimum}) but the run log "
                f"reports no count for it. A floor nothing measures is a floor nobody "
                f"is held to -- either emit the marker or remove the key in a human commit.",
            )
        if got < minimum:
            blockers.append(
                f"'{key}' ran {got} of a required {minimum}. The rest were skipped, "
                f"and skipped is not passed."
            )
        elif got > minimum:
            slack[key] = got - minimum
    if floor:
        print(f"RATCHET_OK keys={len(floor)} " + " ".join(f"{k}={obs[k]}/{v}" for k, v in floor.items()))
    else:
        print(
            "GATE_NOTE: no ratchet floor set (.factory/locks/floor.json). Counts are "
            "reported but not enforced -- a legitimate day-one state, and an "
            "indefensible level-3 one."
        )

    # Deliberate defects. All must be caught or nothing merges: every miss is a
    # class of bug that can currently merge unreviewed.
    total = counted(log, "MUTATIONS_TOTAL")
    caught = counted(log, "MUTATIONS_CAUGHT")
    not_injected = counted(log, "MUTATIONS_NOT_INJECTED") or 0
    if total is not None:
        if total == 0:
            return fail(
                target,
                "zero deliberate defects were injected -- a gate that has never failed "
                "is a gate nobody has tested",
            )
        if not_injected:
            # FIXABLE, and usually by the diff that caused it: an anchor goes ambiguous
            # when a change introduces a second, byte-identical copy of the line a
            # defect targets. Rewording the duplicate is a one-line fix, so this goes
            # round the loop rather than waking somebody.
            blockers.append(
                f"{not_injected} deliberate defect(s) could not be injected -- an anchor "
                f"moved or went ambiguous. A mutation set that silently stops injecting "
                f"reports a perfect score for doing nothing. See the NOT_INJECTED lines "
                f"in the log for which, and why."
            )
        if caught != total:
            blockers.append(
                f"the gate caught {caught} of {total} deliberate defects; every miss is "
                f"a class of bug that can currently merge unreviewed. See the ESCAPED "
                f"line in the log for which one and what it means."
            )

    # --- 3. what holds the MERGE without stopping the WORK --------------------
    automerge = True
    held_why: list[str] = []

    # SLACK BLOCKS THE DIAL. The gap between observed and floor is exactly the
    # number of assertions that can be deleted with the gate still green, and it
    # GROWS as the harness improves, because raising the floor is a protected edit
    # the factory cannot make. Measured on a real factory, that hole went from 7 to
    # 33 in one cycle BECAUSE the harness got better. Printing it as a note and
    # carrying on is how it widens forever, so here it pins autonomy instead.
    if slack and config.SLACK_CAPS_AUTONOMY:
        automerge = False
        held_why.append(
            "ratchet slack (" + ", ".join(f"{k}+{v}" for k, v in slack.items()) + ")"
        )

    # Some claims are ORDINAL and need no number. Others are MARGIN claims and need
    # a threshold somebody chose. A factory that invents that number to turn a gate
    # green is authoring taste in a config file, and it is the most tempting
    # shortcut there is, because the number is right there in the output and one of
    # them would make the red go away. Any check that has a threshold nobody set
    # emits `<NAME>_UNCALIBRATED=<n>`. That does not fail the gate -- it refuses the
    # AUTO-merge and says so.
    uncal = {m.group(1): int(m.group(2)) for m in re.finditer(r"([A-Z][A-Z0-9_]*)_UNCALIBRATED=(\d+)", log)}
    if uncal:
        automerge = False
        held_why.append(
            "uncalibrated thresholds (" + ", ".join(f"{k}:{v}" for k, v in uncal.items()) + ")"
        )

    # An ASSUMPTION holds the merge, it does not stop the work. The plan node is
    # told to choose unspecified PRODUCT values rather than stop -- a price, a rate,
    # a default -- and to record what it chose. The work is then built, validated
    # and readable, so the human answers "is 1.5 right, here is what it does"
    # instead of "what should the multiplier be" with nothing in front of them.
    #
    # JUDGEMENT values are never covered by this: a lock, a floor, a tolerance, a
    # sample size, a mutation. Choosing one of those is tuning the judge, and the
    # plan node escalates instead. That distinction is the whole safety argument.
    assumptions = ""
    assumption_path = ""
    issue_ref = state.linked_issue(target)
    for candidate in (
        config.ASSUMPTIONS_DIR / f"{target.replace(':', '-')}.txt",
        config.ASSUMPTIONS_DIR / f"{(issue_ref or '').replace(':', '-')}.txt",
    ):
        if candidate.name != "-.txt" and candidate.exists() and candidate.stat().st_size:
            assumptions = candidate.read_text(encoding="utf-8", errors="replace").strip()
            try:
                assumption_path = str(candidate.relative_to(config.SHARED))
            except ValueError:
                assumption_path = str(candidate)
            break
    if assumptions:
        automerge = False
        held_why.append(f"{len([ln for ln in assumptions.splitlines() if ln.strip()])} recorded assumption(s)")

    # --- 4. the verdict -------------------------------------------------------
    if not verdict_path.exists() or not verdict_path.stat().st_size:
        return fail(
            target,
            "verdict file is empty or missing -- the judge step produced nothing, "
            "which is not an approval",
        )
    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        decision = verdict["verdict"]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        return fail(target, f"verdict file is not parseable JSON with a .verdict field ({e})")

    summary = verdict.get("summary", "no summary")
    steps = obs.get("e2e_steps_asserted")

    # THE GATE OVERRIDES THE JUDGE. When the raw markers and the verdict disagree, the
    # raw output wins -- a model summarising a run it just watched is precisely what
    # cannot be trusted here, and "it looked fine to me" over a red gate is the exact
    # failure the structural half exists to prevent.
    #
    # The override direction is one-way: it can only ever ADD a reason to block. A
    # judge that says request_changes over a green gate is believed without argument,
    # because it read the diff against the issue and the markers never did.
    if blockers and decision == "approve":
        print(
            "GATE_OVERRIDE: the judge returned approve and the raw output is red. "
            "Overriding to request_changes -- deterministic output beats a model's "
            "summary of that output, every time."
        )
        decision = "request_changes"
        verdict["verdict"] = "request_changes"
        verdict.setdefault("issues_to_fix", [])
        verdict["summary"] = (
            "The gate is red and the judge approved anyway; the raw output wins. "
            + summary
        )
    if blockers:
        # Prepended, so a fix node reads the machine-checkable failures before the
        # judge's prose. These are the ones with an exact remedy.
        verdict["issues_to_fix"] = [
            {
                "severity": "high",
                "category": "correctness",
                "file": "",
                "description": b,
            }
            for b in blockers
        ] + list(verdict.get("issues_to_fix") or [])
    counts_line = (
        f"- e2e steps asserted: {steps}\n"
        f"- deliberate defects caught: {caught}/{total}\n"
        if total is not None
        else f"- e2e steps asserted: {steps}\n"
    )

    if decision == "approve":
        if not automerge:
            # Guarded like the auto-merge branch below, and for the same reason: this
            # write is a label edit against GitHub and it can fail for ordinary
            # reasons -- a missing label on a fresh factory, or a concurrent
            # escalation that makes the move illegal. Unguarded, the gate ends in a
            # traceback and the PR sits in `validating` with nothing holding it.
            # `held`, NOT `passed`. This is the whole hold, and it used to be a
            # sentence: the gate printed "merge HELD", set the PR to `passed`, and the
            # dispatcher merged it forty-five seconds later -- because `passed` is
            # what a mergeable PR is called, and the dispatcher reads states, not
            # prose. The most subtle gate in the system was defeated by the most
            # obvious one, and it looked exactly like a clean unattended lap.
            try:
                state.set_state(target, "held")
            except Exception as e:  # noqa: BLE001
                return fail(
                    target,
                    f"the gate passed with the merge held, but the state could not be "
                    f"written ({e}) -- and a hold nothing can read is not a hold",
                )
            body = [
                "## Factory Gate: PASS, merge HELD",
                "",
                "Every structural marker is green and the judge returned `approve`.",
                "",
                "**Auto-merge is held because:** " + "; ".join(held_why) + ".",
            ]
            if assumptions:
                body += [
                    "",
                    "The change rests on a decision the factory made rather than one you gave it. "
                    "It is built and validated; merging it is you agreeing with the call.",
                    "",
                    "```",
                    assumptions,
                    "```",
                    "",
                    "Merge to accept, or say what the value should be and it will be rebuilt.",
                    "",
                    "To clear this: record the decision in `.factory/decisions.md`, delete",
                    f"`{assumption_path}`, and commit. Both are protected paths, so that is",
                    "a human commit by construction -- which is the point.",
                ]
            body += [
                "",
                counts_line,
                "This is not a failure and re-running will not change it. It clears when a "
                "human commits the raised floor / the answered assumption. Until then the PR "
                "waits for a human to merge it.",
            ]
            post(target, "\n".join(body))
            print(f"GATE_PASS_HELD pr={target} held={'; '.join(held_why)}")
            return 0

        # GUARDED. An unguarded state write here exits on the spot with no
        # GATE_FAIL, no needs-human and no notification -- and it is reachable for
        # an ordinary reason: this write is a label edit, and a missing label makes
        # it fail. The FIRST green gate a new factory ever produces is exactly when
        # that bites, having already decided to merge.
        try:
            state.set_state(target, "passed")
        except Exception as e:  # noqa: BLE001
            return fail(
                target,
                f"the gate passed but the verdict could not be recorded ({e}); refusing "
                f"to merge something whose state was never written",
            )
        mut = f", mutations {caught}/{total}" if total is not None else ""
        print(f"GATE_PASS pr={target} markers green, e2e steps={steps}{mut}")

        merged = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "merge.py"), target],
            cwd=str(config.ROOT),
        )
        if merged.returncode != 0:
            return fail(target, "merge failed -- leaving the PR for a human")
        return 0

    if decision == "request_changes":
        # HAND THE FINDINGS FORWARD, to a path that outlives this run.
        #
        # The fix node's whole job is to address what the validator objected to, and
        # the objection otherwise lives in a run directory the fix workflow -- a
        # separate process, started later by the dispatcher -- has no way to name. A
        # fix node with nothing to read does not crash: it reads nothing and fixes
        # from memory of the diff, so every fix attempt is a guess at what the
        # validator wanted.
        #
        # Keyed by target so two PRs in flight cannot read each other's findings, and
        # copied rather than referenced so a pruned run directory cannot empty it.
        config.FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
        key = re.sub(r"[/.:\\]", "-", target)
        (config.FINDINGS_DIR / f"{key}.json").write_text(
            json.dumps(verdict, indent=2), encoding="utf-8"
        )
        (config.FINDINGS_DIR / f"{key}.gate.log").write_text(log, encoding="utf-8")
        print(f"FINDINGS_SAVED {config.FINDINGS_DIR / (key + '.json')}")

        try:
            state.set_state(target, "failed")
        except Exception as e:  # noqa: BLE001
            return fail(
                target,
                f"changes were requested but the state could not be written ({e}); the "
                f"fix loop would never see this PR",
            )
        findings = verdict.get("issues_to_fix") or []
        rendered = "\n".join(
            f"- **{f.get('severity', '?')}** [{f.get('category', '?')}]"
            + (f" (`{f['file']}`)" if f.get("file") else "")
            + f": {f.get('description', '')}"
            for f in findings
        )
        post(
            target,
            "## Factory Validation: changes requested\n\n"
            f"{summary}\n\n"
            + ("### Findings\n\n" + rendered if rendered else "")
            + f"\n\nCited: {', '.join(verdict.get('rules_cited', [])) or 'none'}",
        )
        print(f"CHANGES_REQUESTED pr={target} findings={len(findings)}")
        return 3

    if decision == "reject":
        try:
            state.set_state(target, "rejected")
        except Exception as e:  # noqa: BLE001
            return fail(target, f"the PR was rejected but the state could not be written ({e})")
        post(target, f"## Factory Validation: REJECTED\n\n{summary}")
        print(f"REJECTED pr={target}")
        return 3

    return fail(target, f"unknown verdict '{decision}'")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
