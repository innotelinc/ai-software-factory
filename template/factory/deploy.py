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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()} {sha} {note}\n")


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
        rc, out = run(f"git checkout {previous} -- . && {config.DEPLOY_CMD}")
        print(out[-2000:])
        if rc != 0:
            print("ROLLBACK_FAILED")
            return 1
        record(previous, "rollback")
        print(f"ROLLED_BACK to={previous}")
        return 0

    git("fetch", "--quiet", "origin", "main")
    rc, sha = git("rev-parse", "--short", "origin/main")
    if rc != 0:
        print("DEPLOY_REFUSED: cannot read origin/main")
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

    import json

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"sha": sha, "at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )
    record(sha, "deploy")
    print(f"DEPLOYED sha={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
