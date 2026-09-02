"""Component 3. THE LOOP IS NOT CLOSED UNTIL A STRANGER CAN SEE THE CHANGE.

    python factory/deploy.py
    python factory/deploy.py --rollback

If merging does not put code in front of a user, you have built a PR generator with
extra steps, and the validation harness has been proving things about software
nobody runs.

Three properties, whatever your real deploy is:

  * IT NO-OPS WHEN NOTHING CHANGED. An unattended deploy loop runs far more often
    than it deploys, and a deploy path that does work on every tick will eventually
    do damage on a tick where nothing happened.
  * THE HEALTH CHECK GATES THE SWAP. Never point production at a build that has not
    answered. This is the last gate before real users, and the only one that runs
    after the merge.
  * ROLLBACK IS ONE COMMAND, decided now rather than during the incident.

NOT PUSH-TRIGGERED, and this is the trap that silently kills more factories than
anything else: GITHUB DOES NOT TRIGGER WORKFLOWS ON COMMITS MADE WITH THE DEFAULT
GITHUB_TOKEN. The agent commits and merges, your `on: push` deploy never fires,
nothing errors, nothing logs, and the site serves the old build for a week. Either
authenticate as a GitHub App, or do what this does and POLL -- a poll cannot be
silently skipped, because nothing had to fire for it to run.

Prefer the mechanism that fails loudly. This is a system whose defining property is
that nobody is watching it.
"""

from __future__ import annotations

import re
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 ON EVERY STREAM, because this module ECHOES OTHER PROGRAMS.
#
# Windows defaults stdio to the ANSI codepage, and the first real deploy command tried
# here -- `vite build` -- ends its output with a U+2713 tick. deploy.py crashed with
# UnicodeEncodeError on the line that echoes it, AFTER the build had succeeded, so a
# working deploy was reported as a Python traceback. The modules that only print their
# own ASCII do not need this; the ones that relay somebody else's output all do.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

STATE_FILE = config.ROOT / ".factory/deployed.json"
HISTORY = config.ROOT / ".factory/deploy-history.log"


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args], cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    return p.returncode, p.stdout.strip()


def run(cmd: str, timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(
        cmd, shell=True, cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def record(sha: str, note: str) -> None:
    """Append to the history AND move the pointer. One writer, one fact.

    These used to be separate: this appended to the log, and `deployed.json` was written
    only on the forward-deploy path. So a rollback left the pointer naming the sha it
    had just rolled AWAY from, and the next deploy read that pointer, decided the sha
    was already current, and did nothing. After a rollback you could merge the fix, run
    the deploy, be told DEPLOY_NOOP, and still be serving the rolled-back build.

    A pointer that disagrees with reality is worse than no pointer, because the no-op it
    causes looks exactly like success.
    """
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(f"{now} {sha} {note}" + chr(10))
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"sha": sha, "at": now, "how": note}, indent=2) + chr(10),
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    if not config.DEPLOY_CMD:
        print(
            "DEPLOY_NOT_CONFIGURED: FACTORY_DEPLOY_CMD is empty in factory/config.py.\n"
            "  Until it is set, merging is where this factory stops -- which makes it a\n"
            "  PR generator, not a factory. Set DEPLOY_CMD and HEALTH_CMD when you are\n"
            "  ready to close the loop to real users."
        )
        return 0

    if "--rollback" in argv:
        if not HISTORY.exists():
            print("ROLLBACK_FAILED: no deploy history")
            return 1
        lines = [ln for ln in HISTORY.read_text(encoding="utf-8").splitlines() if " deploy" in ln]
        if len(lines) < 2:
            print("ROLLBACK_FAILED: no previous successful deploy to roll back to")
            return 1
        previous = lines[-2].split()[1]

        # REFUSE ON A DIRTY TREE. The checkout below overwrites tracked files, so
        # running it over uncommitted work destroys that work with no way back. Same
        # rule merge.py applies before it fast-forwards a checkout somebody is using:
        # not rolling back is recoverable, eating an afternoon of edits is not.
        rc_status, dirty = run("git status --porcelain --untracked-files=no")
        if rc_status == 0 and dirty.strip():
            print(
                "ROLLBACK_REFUSED: the working tree has uncommitted changes.\n"
                "  Rolling back overwrites tracked files from the previous deploy, which\n"
                "  would destroy them. Commit or stash first.\n"
                f"  {len(dirty.strip().splitlines())} file(s) changed."
            )
            return 1

        # THE OLD FILES EXIST ONLY FOR THE DURATION OF THE DEPLOY COMMAND.
        #
        # This used to check out the previous commit over the working tree and simply
        # return, leaving the repo holding a STAGED REVERT of everything since -- twelve
        # files on a real rollback, including MISSION.md and factory/config.py. HEAD had
        # not moved, so the next commit by anyone, for any reason, would have committed
        # that revert. It is the `update-ref` incident wearing different clothes, and it
        # was armed at the exact moment people are moving fastest.
        #
        # A rollback restores the running SOFTWARE. It has no business rewriting the
        # rules the factory is governed by, and it must hand the repository back exactly
        # as it found it.
        # FILES ADDED SINCE <previous> MUST GO, or the artefact is a hybrid.
        #
        # `git checkout <sha> -- .` restores what exists in <sha> and cannot remove what
        # does not. Rolling back to a commit that predates a file leaves that file at
        # its CURRENT content, so the build is old code for old files and new code for
        # new ones -- neither version, reported as a successful rollback.
        #
        # Measured: a rollback to the `factory init` commit, which predates `app/`
        # entirely, produced a release still containing the feature being rolled back.
        rc_added, added = run(
            f"git diff --name-only --diff-filter=A {previous} HEAD")
        added_files = [ln.strip() for ln in added.splitlines() if ln.strip()] if rc_added == 0 else []

        # YOU CANNOT ROLL BACK PAST YOUR OWN DEPLOY SCRIPT, and saying so beats
        # letting the shell report it. Removing files added since <previous> can
        # remove the very script FACTORY_DEPLOY_CMD invokes, and the failure then
        # surfaces as "python: can't open file ..." followed by ROLLBACK_FAILED,
        # which reads like the deploy is broken rather than like the target is too old.
        _referenced = [f for f in added_files
                       if f and (f in config.DEPLOY_CMD or Path(f).name in config.DEPLOY_CMD)]
        if _referenced:
            print(
                f"ROLLBACK_REFUSED: {previous} predates the deploy command itself.\n"
                f"  FACTORY_DEPLOY_CMD is {config.DEPLOY_CMD!r}, and these were added\n"
                f"  after that commit: {' '.join(_referenced[:4])}\n"
                f"  There is nothing at {previous} that knows how to deploy this, so\n"
                f"  the rollback would build from a tree that cannot build. Roll back\n"
                f"  to a commit that has the deploy script, or redeploy a known sha."
            )
            return 1

        # Remove them BEFORE the deploy command reads the tree, not after.
        if added_files:
            _quoted = " ".join(f'"{f}"' for f in added_files)
            run(f"git rm --quiet --force --ignore-unmatch -- {_quoted}")
        rc, out = run(f"git checkout {previous} -- . && {config.DEPLOY_CMD}")
        print(out[-2000:])
        if added_files:
            print(f"ROLLBACK_REMOVED_ADDED files={len(added_files)} "
                  f"(they do not exist in {previous})")
        restore_rc, restore_out = run("git checkout HEAD -- . && git reset --quiet")
        if restore_rc != 0:
            # Say so LOUDLY. A rollback that deployed and then could not put the tree
            # back has left the repository in the armed state described above, and that
            # is worse than the outage being rolled back.
            print(
                "ROLLBACK_TREE_NOT_RESTORED: the deploy ran but the working tree could\n"
                "  not be returned to HEAD. The repo is holding a staged revert -- do NOT\n"
                "  commit here until `git checkout HEAD -- . && git reset` succeeds.\n"
                f"  {restore_out.strip()[:300]}"
            )
            return 1
        if rc != 0:
            print("ROLLBACK_FAILED")
            return 1
        record(previous, "rollback")
        print(f"ROLLED_BACK to={previous} (working tree restored to HEAD)")
        return 0

    git("fetch", "--quiet", "origin", config.BASE_BRANCH)
    rc, sha = git("rev-parse", "--short", f"origin/{config.BASE_BRANCH}")
    if rc != 0:
        print(f"DEPLOY_REFUSED: cannot read origin/{config.BASE_BRANCH}")
        return 1

    # --- no-op when nothing changed ------------------------------------------
    if STATE_FILE.exists():
        try:
            import json

            if json.loads(STATE_FILE.read_text(encoding="utf-8")).get("sha") == sha:
                print(f"DEPLOY_NOOP sha={sha} already current")
                return 0
        except (OSError, ValueError):
            pass

    print(f"DEPLOY_START sha={sha}")
    rc, out = run(config.DEPLOY_CMD)
    print(out[-4000:])
    if rc != 0:
        print("DEPLOY_FAILED: the deploy command exited non-zero. Pointer NOT moved.")
        return 1

    # --- health check: it must actually start, and actually do the thing ------
    if not config.HEALTH_CMD:
        # Refuses rather than defaulting to healthy. A deploy with no health check
        # is a deploy that cannot fail, and a step that cannot fail is not a gate --
        # it is a comment. Empty-is-not-pass, applied to the last thing standing
        # between a merge and a user.
        print(
            "HEALTH_CHECK_MISSING: FACTORY_HEALTH_CMD is not set.\n"
            "  Set it to a command that starts this build and proves it worked, and set\n"
            "  FACTORY_HEALTH_MARKERS to what its output must contain. Pointer NOT moved."
        )
        return 1

    if not config.HEALTH_MARKERS:
        # THE SAME REFUSAL, ONE STEP LATER, and it was missing. A health command with
        # nothing to look for in its output collapses to "it exited zero" -- exactly
        # what the comment fifteen lines below calls not-evidence. It printed
        # `HEALTH_CHECK_OK markers=0` and moved the pointer, which is the
        # empty-is-not-pass failure this whole system is built around, sitting in the
        # one gate between a merge and a real user.
        print(
            "HEALTH_CHECK_UNCHECKABLE: FACTORY_HEALTH_CMD is set but "
            "FACTORY_HEALTH_MARKERS is empty.\n"
            "  Then the only thing asserted is an exit code, and a process that starts,\n"
            "  does nothing and returns zero passes that. Name at least one string the\n"
            "  working build prints. Pointer NOT moved."
        )
        return 1

    print("HEALTH_CHECK_START")
    rc, health = run(config.HEALTH_CMD, timeout=300)
    if rc != 0:
        print("HEALTH_CHECK_FAILED: the build did not run. Pointer NOT moved.")
        print(health[-2000:])
        return 1
    # Assert the OUTCOME, not the exit code. The failure this catches is the one an
    # exit code cannot see: a process that starts, hangs or does nothing, and
    # returns zero.
    for marker in config.HEALTH_MARKERS:
        if not re.search(marker, health):
            print(
                f"HEALTH_CHECK_FAILED: the build ran but '{marker}' never appeared in its "
                f"output.\n  'It exited zero' is not evidence that the app works. Pointer NOT moved."
            )
            print(health[-2000:])
            return 1
    print(f"HEALTH_CHECK_OK markers={len(config.HEALTH_MARKERS)}")

    # ONE WRITER. `record()` moves the pointer and appends the history together, so
    # they cannot disagree. This used to write the pointer here as well, which is how a
    # rollback -- which only called record() -- left the pointer naming the sha it had
    # just rolled away from.
    record(sha, "deploy")
    print(f"DEPLOYED sha={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
