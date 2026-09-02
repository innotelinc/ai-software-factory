"""Assemble exactly what the validator may see, and nothing else.

ORDER IS LOAD-BEARING. Governance is read from the BASE branch BEFORE the PR is
checked out, so a PR cannot weaken the rulebook it is about to be judged against.
Reversed, a diff that edits FACTORY_RULES.md is judged against the edited version and
passes.

WHAT THE VALIDATOR GETS
  - the issue body, exactly as it was filed
  - the diff, computed against the MERGE BASE
  - the commit SUBJECTS only
  - MISSION / FACTORY_RULES / conventions, from the base branch
  - whatever the checks it ran itself printed

WHAT IT DOES NOT GET, and this is not an oversight
  - the implementation plan, the priming, the implementation report
  - the builder's reasoning, scratch notes, or commit bodies
  - prior comments on the PR, including its own from a previous round
  - any artifact from the run that produced the code

The last one is why the PR is fetched without `comments` and `reviews`: a third-party
app can comment on a PR seconds after it opens, so a judge that reads PR comments is
reading a stranger's text.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

# nodeio FIRST, before anything that might print at import time: importing it
# redirects stdout to stderr for the whole process, so a library marker can never
# be mistaken for this node's value. emit() writes to the real stdout.
from nodeio import emit, note  # noqa: E402

import config  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402
import tripwire  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
artifacts.mkdir(parents=True, exist_ok=True)


def die(msg: str) -> None:
    """Park the PR before exiting. Otherwise the dispatcher retries it forever.

    THE WEDGE THIS REMOVES, and it was live. Everything here runs BEFORE the PR is
    moved to `validating`, so a failure leaves it at `open` -- which is exactly the
    state the dispatcher looks for. The next tick re-dispatches the same PR into the
    same failure, and the tick after that, and so on: a factory that looks busy,
    progresses at zero, and tells nobody.

    Every failure in this file is a machinery or human fault -- a missing issue link,
    a conflicting rebase, a tripped wire, an empty diff. None of them are things a fix
    node could address, so `needs-human` is the honest destination.
    """
    note(f"PREPARE_FAILED: {msg}")
    if target:
        try:
            state.main(["set", target, "state=needs-human"])
        except Exception:  # noqa: BLE001
            pass
        config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
        try:
            with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  "
                    f"{target}  (validate/prepare)  {msg}\n"
                )
        except OSError:
            pass
        try:
            state.comment(
                target,
                "**Factory validation: could not start**\n\n"
                f"{msg}\n\n"
                "This is a validator-side failure, not a defect in this pull request. "
                "The PR is left open and labelled for a human; without this label the "
                "dispatcher would retry the same failure on every tick.",
            )
        except Exception:  # noqa: BLE001
            pass
        note(notify.send(target, f"(validate/prepare) {msg}"))
    sys.exit(1)


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args], cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


pr = state.fetch(target)
number = target.split(":")[-1]
branch = pr.get("headRefName") or ""
if not branch:
    die(f"{target} has no head branch")

if pr["_state"] == "needs-human":
    die(f"{target} is parked at needs-human; a node may never move it out of that state")

if pr["_state"] in ("passed", "merged"):
    # NOT a failure, and not something to escalate. A `passed` PR has already been
    # validated and is waiting for the merge step; re-validating it is a dispatcher
    # mistake or a hand-run, and parking it at needs-human for that would be the
    # factory punishing a PR for something it did not do.
    #
    # The transition table refuses `passed -> validating` on purpose -- `validating`
    # is owned by a running validation and nothing hands it out twice -- so this
    # stops cleanly and says what to run instead.
    note(
        f"ALREADY_VALIDATED: {target} is '{pr['_state']}'. It has passed and is "
        f"waiting for the merge step, not for another validation. Run the dispatcher "
        f"(`factory tick`) at autonomy 3 or above, or merge it by hand. Nothing "
        f"here is wrong with the pull request."
    )
    sys.exit(1)

# --- the linked issue: what this diff was supposed to solve -------------------
issue = state.linked_issue(target)
if not issue:
    die(
        f"{target} does not link an issue with Fixes/Closes/Resolves. The judge has "
        f"nothing to judge the diff AGAINST, and 'does it look fine' is not a standard."
    )

# --- governance from the BASE branch, before the checkout --------------------
git("fetch", "--quiet", "origin", "main")
base = "origin/main"
if git("rev-parse", "--verify", "--quiet", base)[0] != 0:
    base = "main"

for name in ("MISSION.md", "FACTORY_RULES.md", "CLAUDE.md", "AGENTS.md"):
    rc, content = git("show", f"{base}:{name}")
    if rc == 0:
        (artifacts / f"base-{name}").write_text(content, encoding="utf-8")

# --- the branch --------------------------------------------------------------
git("fetch", "--quiet", "origin", f"{branch}:refs/remotes/origin/{branch}")
checkout = f"origin/{branch}"
if git("rev-parse", "--verify", "--quiet", checkout)[0] != 0:
    checkout = branch
if git("rev-parse", "--verify", "--quiet", checkout)[0] != 0:
    die(f"neither origin/{branch} nor {branch} exists here")

# --- rebase BEFORE validating, not after being refused -----------------------
# THE DEADLOCK THIS REMOVES. The merge refuses a branch that is behind the base, and
# it is right to: squashing a stale branch silently drops whatever landed while it
# was in flight. But the designed remedy -- rebase and re-validate -- is unreachable
# once the gate has already recorded a verdict. On a repo with any commit velocity,
# "someone pushed to main while a lap was running" is not an edge case, it is
# Tuesday.
#
# Rebasing HERE is safe in a way rebasing after a verdict is not: nothing has been
# judged yet, so everything downstream -- the guard, the gate, the judge -- runs
# against the tree that will actually merge.
# NEVER CHECK OUT THE PR BRANCH BY NAME. Git refuses to have one branch checked out
# in two worktrees at once, and the implement run's worktree legitimately still holds
# it -- so `git checkout -B factory/impl-1` fails with "already used by worktree at
# ...". The first version of this ignored that return code, and the consequence was
# the worst shape a bug can take: **it printed REBASED and had not rebased.** Every
# node downstream then judged a stale tree while the log said otherwise, and the
# factory's own fixes to its own harness were invisible to the run validating them.
#
# Assert on the artifact, not the exit code -- and here, not even on the exit code:
# on the actual ancestry afterwards.
#
# DETACHED, which cannot collide with anything. A private branch name would work
# until two validations of different PRs raced for it; a detached HEAD has no name to
# contend over at all, and nothing here needs one -- the diff, the gate and the judge
# all work from HEAD.
rc, out = git("checkout", "-q", "--detach", checkout)
if rc != 0:
    die(f"could not check out {checkout}: {out}")

if git("merge-base", "--is-ancestor", base, "HEAD")[0] == 0:
    note(f"REBASE_NOT_NEEDED {checkout} already contains {base}")
else:
    note(f"REBASE_REQUIRED {checkout} is behind {base} - rebasing before validation")
    rc, out = git("rebase", base)
    if rc != 0:
        git("rebase", "--abort")
        die(
            f"{branch} conflicts with {base} and cannot be rebased automatically. A "
            f"human has to resolve the conflict; the factory will not guess at a merge."
        )
    # THE CLAIM IS VERIFIED, not trusted. A rebase that reports success and leaves the
    # branch where it was is exactly the failure above, one layer down.
    if git("merge-base", "--is-ancestor", base, "HEAD")[0] != 0:
        die(
            f"the rebase onto {base} reported success and HEAD still does not contain "
            f"{base}. Refusing to validate a tree whose contents are not what this run "
            f"believes them to be."
        )
    # Publish it, so the merge sees the same tree this validation judged. Pushed by
    # explicit refspec rather than by branch name, for the same reason as above.
    rc, out = git("push", "-q", "--force-with-lease", "origin", f"HEAD:{branch}")
    if rc != 0:
        note(f"REBASE_PUSH_FAILED ({out.strip()[:200]}) - validating the local rebased tree")
    note(f"REBASED {branch} onto {base}; everything below judges the rebased tree")

rc, head = git("rev-parse", "--short", "HEAD")
note(f"CHECKED_OUT {branch} at {head} (detached)")
checkout = "HEAD"

# --- the tripwire -------------------------------------------------------------
if tripwire.main([str(config.ROOT)]) != 0:
    die(
        "a builder artifact is in the validator's tree; its verdict would not be "
        "independent evidence. This is a workflow bug, not a code bug."
    )

# --- the inputs ---------------------------------------------------------------
(artifacts / "issue.md").write_text(state.body_text(issue), encoding="utf-8")

rc, diff = git("diff", f"{base}...{checkout}")
if rc != 0:
    die("could not compute the diff")
if not diff.strip():
    die(
        f"the diff between {base} and {checkout} is empty. There is nothing to judge, "
        f"and an empty diff does not solve an issue."
    )
# THREE DOTS. A two-dot diff reports the base branch's own commits as this branch's
# work, which is a false positive in the most severe gate there is.
(artifacts / "diff.patch").write_text(diff[:400_000], encoding="utf-8")

rc, commits = git("log", "--format=%h %s", f"{base}..{checkout}")
# SUBJECTS ONLY. The commit body is the coder's story about why, and the judge is
# here to read what the code does now.
(artifacts / "commits.txt").write_text(commits, encoding="utf-8")

(artifacts / "pr-meta.json").write_text(
    json.dumps(
        {
            "number": number,
            "title": pr.get("title", ""),
            "additions": pr.get("additions"),
            "deletions": pr.get("deletions"),
            "changedFiles": pr.get("changedFiles"),
        },
        indent=2,
    ),
    encoding="utf-8",
)

note(f"DIFF_RENDERED {len(diff.splitlines())} lines")

# --- claim it ------------------------------------------------------------------
# Guarded. An unguarded state write here would exit on the spot with no escalation,
# which is the same silent shape that makes a fix loop unreachable. This is also the
# write that CLAIMS the PR: everything below assumes a validation owns it.
if pr["_state"] != "validating":
    if state.main(["set", target, "state=validating"]) != 0:
        die(
            f"could not move {target} to 'validating'. A validation cannot claim a PR "
            f"it is not allowed to hold."
        )

emit(
        {
            "target": target,
            "number": number,
            "issue": issue,
            "branch": branch,
            "base": base,
        }
)
