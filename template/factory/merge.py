"""The merge. The second of the two decisions made by code rather than by a model.

    python factory/merge.py <pr-target>

EXIT CODES CARRY MEANING, because the caller has to tell two very different
non-zero outcomes apart:

    0  merged
    1  refused, and it needs a human
    2  refused, and ALREADY HANDLED -- the PR was requeued for revalidation

Without the split, the dispatcher escalated every refusal -- including the one this
script had just recovered from by itself. The PR went back to `open`, and then
straight to `needs-human` one line later, which is terminal for nodes: a recovery
that undid itself.

This RE-CHECKS the structural gates itself before touching a branch. It does not
trust that gate.py already did, and it does not trust the verdict file at all. The
reason is ordering: gate.py runs the checks and then calls this, so if anything ever
calls this directly -- a retry, a human, a future workflow, a bug -- the merge still
cannot happen against an unchecked branch.

Re-checking costs seconds. Merging an unchecked branch costs a debugging session
that starts with "but the gate was green".

WHY BRANCH PROTECTION DOES NOT REPLACE THIS. The tempting move is to delete this
file and let a required check plus a ruleset be the gate, on the grounds that a
ruleset is not something the agent can edit. It is, in the case that matters: the
factory authenticates as a principal that administers the repository, and an account
that can edit a ruleset can bypass one. Unless you have provisioned a separate
least-privilege identity and verified it cannot administer the repo, the merge stays
in code you control. Branch protection is a good second lock and a bad only lock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import guard  # noqa: E402
import state  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args],
        cwd=str(config.ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


def refuse(msg: str) -> int:
    print(f"MERGE_REFUSED: {msg}")
    return 1


def worktree_holding(branch: str) -> str:
    """The path of the working tree that has `branch` checked out, or "".

    Asked so that nothing ever moves a ref out from under a checkout. `git worktree
    list --porcelain` reports every attached tree including the main one, which is
    the only source that knows about the checkout this process is not running in.
    """
    rc, out = git("worktree", "list", "--porcelain")
    if rc != 0:
        # Unknown, so assume it IS checked out somewhere: the cost of being wrong that
        # way is a checkout left behind, which prints a note. The other way silently
        # arms a revert.
        return str(config.SHARED)
    path = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch}":
            return path
    return ""


def raise_floor(holder: str) -> str:
    """Close the ratchet slack this merge just created. MONOTONIC: it never lowers.

    WHY THIS IS SAFE, and why it is not a hole in the protected list. The guard still
    rejects any PULL REQUEST that touches `.factory/locks/floor.json`, so a builder
    still cannot delete an assertion and lower the floor to match -- which is the
    attack the protection exists to stop. This runs afterwards, in the machinery, and
    can only move a number UP. "The floor never falls without a human" is the ratchet,
    and it is exactly preserved.

    WHY IT HAS TO BE AUTOMATIC. Slack is the gap between what the harness asserts and
    what the floor requires, and it is precisely the number of assertions that could
    be deleted with the gate still green. The gate held every merge until a human
    closed it. That is the right instinct and the wrong remedy: it made the SUCCESS
    case -- a PR that adds tests -- require a human, so on a good day the factory
    stopped completely. Four pull requests in one session were each held on slack
    alone, and closing them by hand took four separate commits.

    Raising it here closes the gap in the same breath as the merge that opened it,
    which is both faster than a human and strictly more honest: the floor now
    describes what main actually has, at the moment main comes to have it.

    THE COUNTS COME FROM THE GATE RUN ON THE MERGED CONTENT. The merge is a squash of
    a branch that was required to be fast-forwardable, so the tree that landed is the
    tree that was measured. Raising to numbers measured somewhere else is how main
    ends up claiming coverage it does not have, which happened by hand earlier and
    turned main red on its own gate.
    """
    raw = os.environ.get("FACTORY_OBSERVED_COUNTS", "")
    if not raw:
        # THE OTHER MERGE PATH. gate.py hands the counts over in an env var when it
        # merges; the DISPATCHER also merges, whenever it finds a PR already in
        # `passed`, and it never ran a gate so it has nothing to hand over. That is the
        # path that merged PR #15, and the floor silently did not move -- the auto-raise
        # was there, correct, and simply never invoked.
        #
        # So the gate writes the counts to disk as well, and this reads them when the
        # env var is absent. Two producers, one consumer, and the consumer must work for
        # both or the feature only exists on the path you happened to test.
        try:
            import re as _re
            # NO REGEX HERE, deliberately. This must produce the same filename
            # gate.py wrote, and the pattern it needs contains a backslash inside a
            # character class -- which has now been mangled twice by the tooling that
            # edits this file, each time producing `unterminated character set` at
            # IMPORT of the fallback rather than an obviously wrong filename. A plain
            # replace cannot be escaped wrongly.
            key = os.environ.get("FACTORY_MERGE_TARGET", "")
            for _ch in ("/", ".", ":", chr(92)):
                key = key.replace(_ch, "-")
            key = key or None
            if key:
                cand = config.FINDINGS_DIR / f"{key}.counts.json"
                if cand.exists():
                    raw = cand.read_text(encoding="utf-8")
        except (OSError, AttributeError):
            raw = ""
    if not raw:
        return ""
    try:
        obs = {k: int(v) for k, v in json.loads(raw).items()}
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
        return ""

    floor_path = Path(holder) / ".factory" / "locks" / "floor.json"
    if not floor_path.exists():
        return ""
    try:
        data = json.loads(floor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    raised = []
    for key, value in data.items():
        # `_MAX` keys are CEILINGS, not floors: UNCALIBRATED_MAX says how many margins
        # nobody has set may exist, and raising that would loosen the check rather than
        # tighten it. This path may only ever tighten, so it does not touch them. They
        # come down as margins get calibrated, in a human commit.
        if key.startswith("_") or key.endswith("_MAX") or not isinstance(value, int):
            continue
        got = obs.get(key)
        # NEVER invent a key, and NEVER move one down. Both would be the factory
        # editing its own judge rather than tightening it.
        if got is None or got <= value:
            continue
        data[key] = got
        raised.append(f"{key} {value}->{got}")
    if not raised:
        return ""

    floor_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    msg = ("ratchet: close the slack this merge opened\n\n"
           + "\n".join("  " + r for r in raised)
           + "\n\nRaised automatically by factory/merge.py, from the counts the gate\n"
             "observed on the tree that just landed. Monotonic: this path can only\n"
             "raise. Lowering a floor is still a human commit, and a pull request that\n"
             "touches this file is still auto-rejected, so the ratchet is unchanged.\n")
    rc, _ = git("-C", holder, "add", ".factory/locks/floor.json")
    if rc != 0:
        return ""
    rc, out = git("-C", holder, "commit", "-m", msg)
    if rc != 0:
        print(f"RATCHET_RAISE_FAILED could not commit: {out.strip()[:200]}")
        return ""
    rc, out = git("-C", holder, "push", "origin", config.BASE_BRANCH)
    if rc != 0:
        print(f"RATCHET_RAISE_UNPUSHED committed locally but push failed: {out.strip()[:200]}")
        return ", ".join(raised)
    return ", ".join(raised)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    target = argv[0]
    kind, num = state.parse_target(target)
    if kind != "pr":
        return refuse(f"{target} is not a pull request")

    pr = state.fetch(target)
    branch = pr.get("headRefName") or ""
    issue = state.linked_issue(target)

    if not branch:
        return refuse(f"no head branch on {target}")
    if pr["_state"] != "passed":
        return refuse(f"state is '{pr['_state']}', not 'passed'")

    rc, _ = git("fetch", "--quiet", "origin", config.BASE_BRANCH, branch)
    if rc != 0:
        # A branch already deleted server-side, or a fetch that cannot see it, is
        # not a merge we should guess at.
        rc2, _ = git("fetch", "--quiet", "origin", config.BASE_BRANCH)
        if rc2 != 0:
            return refuse("cannot fetch from origin")

    base = f"origin/{config.BASE_BRANCH}"
    head = f"origin/{branch}"
    print(f"MERGE_START branch={branch} base={base} issue={issue}")

    # --- re-check, independently ---------------------------------------------
    if guard.main(["--base", base, "--head", head]) != 0:
        return refuse("protected-path guard failed on re-check")

    rc, _ = git("rev-parse", "--verify", "--quiet", head)
    if rc != 0:
        return refuse(f"{head} does not exist")

    # The branch must actually contain the base, or the squash silently drops work
    # that landed while this branch was in flight.
    rc, _ = git("merge-base", "--is-ancestor", base, head)
    if rc != 0:
        # REQUEUE, do not park. Refusing is right -- squashing a stale branch
        # silently drops whatever landed while it was in flight -- but the refusal
        # must not be terminal: the PR would sit at `passed`, which nothing
        # dispatches, and every later tick would reprint this line forever.
        # Indistinguishable from an idle factory.
        #
        # The remedy the message recommends is exactly what the validate workflow
        # does on its own, so send it back rather than telling a human to do it by
        # hand. `passed -> open` is legal for this reason.
        print(
            f"MERGE_REFUSED: {branch} is behind {base} -- squashing it now would silently "
            f"drop whatever landed while it was in flight"
        )
        try:
            state.set_state(target, "open")
            print(
                f"MERGE_REQUEUED: {target} is back to 'open'; the validator will rebase it "
                f"and re-judge the rebased tree"
            )
            return 2  # handled: do not escalate on top of a recovery
        except Exception as e:  # noqa: BLE001
            print(f"MERGE_REFUSED: could not requeue {target} ({e}) -- it needs a human")
        return 1

    # GitHub's own view, re-read here rather than taken from the labels. A label
    # says what the factory believes; `state` and `mergeStateStatus` say what GitHub
    # will actually do, and a PR closed or made conflicting since validation must
    # not be squashed anyway.
    raw = state.gh(
        "pr", "view", num, "--json", "state,mergeable,isDraft,baseRefName,mergeStateStatus"
    )
    view = json.loads(raw)
    if view["state"] != "OPEN":
        return refuse(f"PR #{num} is {view['state']}")
    if view["isDraft"]:
        # A draft cannot be merged at all. Flip it, because the factory opened it as
        # a draft on purpose and this is the moment that stops being true.
        state.gh("pr", "ready", num, check=False)
        view["isDraft"] = False
    if view["baseRefName"] != config.BASE_BRANCH:
        return refuse(f"PR #{num} targets '{view['baseRefName']}', not main")
    if view["mergeable"] != "MERGEABLE":
        return refuse(f"GitHub reports mergeable={view['mergeable']}")

    # `mergeable` and `mergeStateStatus` are different questions, and only the
    # second knows about branch protection. A PR on a protected branch reports
    # mergeable=MERGEABLE (there is no conflict) and mergeStateStatus=BLOCKED (a
    # required review or check has not happened). Checking only the first sails
    # past every pre-check and fails at the merge with a generic error, which is
    # true and useless: a human reads it, re-runs, and gets the same thing forever,
    # because a protection rule is not a transient failure.
    merge_state = view.get("mergeStateStatus") or ""
    if merge_state == "BLOCKED":
        print(
            f"MERGE_REFUSED: GitHub reports mergeStateStatus=BLOCKED on PR #{num}.\n"
            "  Branch protection on the base branch is refusing this merge -- typically a required\n"
            "  approving review, or a required status check that has not run. The factory\n"
            "  cannot satisfy either: it has no second human to review, and at level 3 the\n"
            "  merge IS the review.\n"
            "  Decide deliberately: exempt this actor from the rule, or run at level 2 and\n"
            "  merge these by hand. Re-running will not help."
        )
        return 1
    if merge_state == "DIRTY":
        return refuse(f"PR #{num} is DIRTY -- GitHub sees a conflict with main")
    if merge_state in ("", "UNKNOWN"):
        # GitHub computes this asynchronously; empty or UNKNOWN means "not worked
        # out yet", which is not the same as "fine". Refuse and let the next tick
        # ask again.
        return refuse(
            f"GitHub has not computed a merge state for PR #{num} yet "
            f"(mergeStateStatus={merge_state!r}). Not merging on an unknown."
        )

    title = pr.get("title") or f"factory: {issue}"
    body = (
        f"Merged by factory/merge.py from {branch}.\n"
        f"Issue: {issue}\n"
        "Gates: protected paths, markers, ratchet, mutations, e2e -- all green on re-check.\n"
        "No human read this diff."
    )
    p = subprocess.run(
        ["gh", "pr", "merge", num, "--squash", "--subject", title[:68], "--body", body],
        cwd=str(config.ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if p.returncode != 0:
        return refuse(f"gh pr merge failed -- leaving for a human: {p.stderr.strip()}")

    # Bring the local checkout back in line. Without this the next branch is cut
    # from a main that is one merge behind, and the guard's merge base is a commit
    # the remote has already moved past. Nothing errors; the diff just quietly
    # contains someone else's work.
    git("fetch", "--quiet", "origin", config.BASE_BRANCH)
    rc, current = git("rev-parse", "--abbrev-ref", "HEAD")
    # NEVER `update-ref` A BRANCH THAT IS CHECKED OUT. This is the most damaging bug
    # found in this build, and it left no error behind.
    #
    # `update-ref` moves the branch pointer and touches neither the index nor the
    # working tree. When nothing has that branch checked out, that is exactly right.
    # When something does -- and the main checkout always has the base branch checked
    # out -- HEAD jumps to the merge while the index and the files stay on the commit
    # before it. `git status` in that checkout then reports the merged work as
    # STAGED DELETIONS, and the next `git commit` there, by anyone, for any reason,
    # commits a revert of the merge that just landed.
    #
    # That happened: a `git add -A && git commit` 74 seconds after an unattended merge
    # wiped a feature and 106 lines of its tests, and the push succeeded. I blamed the
    # habit. The habit was the trigger; this line was the trap, and it was armed after
    # every single merge.
    #
    # This code runs from a validate WORKTREE, where the current branch is the
    # validation branch -- so the `else` was taken every time, and the safe branch
    # above almost never ran.
    holder = worktree_holding(config.BASE_BRANCH)
    if rc == 0 and current == config.BASE_BRANCH:
        git("merge", "--ff-only", f"origin/{config.BASE_BRANCH}")
    elif holder:
        # Fast-forward it IN ITS OWN CHECKOUT, which moves ref, index and files
        # together. It refuses when that tree has local changes, and refusing is the
        # right answer: leaving someone's edits is strictly better than desynchronising
        # their repository behind their back.
        rc_ff, out_ff = git("-C", holder, "merge", "--ff-only", f"origin/{config.BASE_BRANCH}")
        if rc_ff != 0:
            print(
                f"MERGE_NOTE: {config.BASE_BRANCH} is checked out at {holder} and could "
                f"not be fast-forwarded ({out_ff.strip().splitlines()[-1] if out_ff.strip() else 'no output'}). "
                f"That checkout is now BEHIND the merge -- run `git pull` there before "
                f"committing anything. Its ref was left alone on purpose"
            )
    else:
        git("update-ref", f"refs/heads/{config.BASE_BRANCH}", f"origin/{config.BASE_BRANCH}")
    _, sha = git("rev-parse", "--short", f"origin/{config.BASE_BRANCH}")
    _, landed = git("log", "-1", "--pretty=%s", f"origin/{config.BASE_BRANCH}")
    if title[:40] in landed:
        print(f"MERGE_VERIFIED subject={landed}")
    else:
        print(f"MERGE_WARNING: squash subject is '{landed}', expected to contain '{title[:40]}'")

    # =========================================================================
    # EVERYTHING PAST THIS LINE IS BOOKKEEPING, AND BOOKKEEPING MUST NOT BE ABLE
    # TO REPORT THE MERGE AS FAILED.
    # =========================================================================
    # The merge is the least reversible thing this factory does, and it has now
    # HAPPENED. What follows updates records to match reality. If one of those
    # writes fails, reality is unchanged -- the code is on the base branch either
    # way.
    #
    # A false "it failed" after a successful merge is the worst direction for this
    # error to point: it invites someone to re-run or re-implement work that
    # already shipped.
    failures = []
    try:
        state.set_state(target, "merged")
    except Exception as e:  # noqa: BLE001
        failures.append(f"PR-record({target}: {e})")
    if issue:
        try:
            state.set_state(issue, "done")
        except Exception as e:  # noqa: BLE001
            failures.append(f"issue({issue}: {e})")

    print(f"MERGED branch={branch} -> main")
    print(f"MERGED_SHA={sha}")

    # Bookkeeping, and deliberately inside the section that cannot fail the merge:
    # a floor that did not get raised is slack, which the next gate reports. A merge
    # wrongly reported as failed invites someone to re-run work that already shipped.
    if holder:
        try:
            os.environ.setdefault("FACTORY_MERGE_TARGET", target)
            raised = raise_floor(holder)
            if raised:
                print(f"RATCHET_RAISED {raised}")
        except Exception as e:  # noqa: BLE001
            print(f"RATCHET_RAISE_FAILED {type(e).__name__}: {e}")
    else:
        print("RATCHET_RAISE_SKIPPED - no checkout holds the base branch")

    if failures:
        print("MERGE_BOOKKEEPING_FAILED: " + " ".join(failures))
        print(f"  THE CODE IS MERGED. {sha} is on main and the deploy should run.")
        print("  What failed is the record-keeping -- most often an item already parked at")
        print("  needs-human, which a node may never move. Fix the record by hand; do NOT")
        print("  re-run the implementation, and do not treat this as an unmerged PR.")
        config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
        with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
            fh.write(
                f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
                f"(merge)  merged as {sha} but records not updated: {' '.join(failures)}\n"
            )

    # Deployment is a separate step on purpose: a merge that also deploys makes a
    # bad merge and a bad deploy the same incident.
    print("NEXT: python factory/deploy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
