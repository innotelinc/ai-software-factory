"""Snap this checkout to origin/main's tip.

DELIBERATELY NOT `git checkout main`. This runs in a linked worktree, and the main
clone already holds the branch `main` -- git refuses to have the same branch checked
out in two worktrees at once, so the checkout fails with "already used by worktree
at ...". Fetch plus hard reset gives main's exact file content without ever flipping
HEAD onto the branch.

It also does NOT `git clean -fd`. That looks like the right hygiene and it is not:
in a worktree it happily wipes the in-flight workflow's own files. `reset --hard`
already restores tracked files, which is all this needs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

# nodeio FIRST, before anything that might print at import time: importing it
# redirects stdout to stderr for the whole process, so a library marker can never
# be mistaken for this node's value. emit() writes to the real stdout.
from nodeio import emit, note  # noqa: E402

import config  # noqa: E402


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args], cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


rc, out = git("fetch", "origin", "main", "--quiet")
if rc != 0:
    note(f"SYNC_FAILED: could not fetch origin/main: {out}")
    sys.exit(1)

rc, out = git("reset", "--hard", "origin/main")
if rc != 0:
    note(f"SYNC_FAILED: could not reset to origin/main: {out}")
    sys.exit(1)

_, sha = git("rev-parse", "--short", "HEAD")
_, subject = git("log", "-1", "--pretty=%s")
note(f"SYNCED {sha} {subject}")
emit({"sha": sha, "subject": subject[:200]})
