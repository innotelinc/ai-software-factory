#!/usr/bin/env python3
"""Push template changes into a repo that already ran `darkfactory init`.

    python bin/sync-to.py ../tally
    python bin/sync-to.py ../tally --dry-run

WHY THIS IS A SCRIPT AND NOT `cp -r`. The runner is COPIED into a repo and never
linked, so a fix here reaches nothing already built. That is a known cost. What is
not obvious is that the obvious command for paying it silently does not work: on Git
Bash for Windows, `cp -r src/. dst/` reports success and leaves the destination
untouched. Two rounds of a real fix were lost to that -- the same failure reproduced
after a fix that had, as far as anything visible said, been applied.

So this compares CONTENT, copies only what differs, and prints exactly what it
changed. A sync that did nothing says so.

IT NEVER TOUCHES THE THREE THINGS THAT ARE YOURS: MISSION.md, harness/e2e.py and
.factory/holdout/. Those are the product, not the machinery, and overwriting them
with a scaffold is the one thing this must never do.
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
TEMPLATE = HOME / "template"

# The machinery, which is the same in every factory and therefore safe to overwrite.
SYNC = [
    "factory",
    ".archon/workflows/darkfactory",
    "harness/ci.py",
    "harness/appproc.py",
    "harness/mutations/run.py",
]

# NEVER. These are the product.
NEVER = {
    "MISSION.md", "FACTORY_RULES.md", "CLAUDE.md", "AGENTS.md", "FACTORY.md",
    "harness/e2e.py", "harness/harness.config.json", "harness/mutations/defects.json",
    ".factory/holdout/run.py", ".factory/locks/floor.json", ".factory/decisions.md",
    "factory/config.py",  # every project-specific setting lives here
}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    dry = "--dry-run" in argv
    dest = Path([a for a in argv if not a.startswith("-")][0]).resolve()
    if not (dest / "factory").is_dir():
        print(f"{dest} has no factory/ -- run `darkfactory init` there first.", file=sys.stderr)
        return 1

    changed, skipped = [], []
    for entry in SYNC:
        src = TEMPLATE / entry
        if not src.exists():
            continue
        files = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else [src]
        for f in files:
            rel = f.relative_to(TEMPLATE).as_posix()
            if rel in NEVER:
                skipped.append(rel)
                continue
            target = dest / rel
            if target.exists() and filecmp.cmp(f, target, shallow=False):
                continue
            changed.append(rel)
            if not dry:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)

    for rel in changed:
        print(("would update " if dry else "updated ") + rel)
    for rel in sorted(set(skipped)):
        print(f"kept (yours)  {rel}")
    print(f"\n{len(changed)} file(s) {'would change' if dry else 'changed'}, "
          f"{len(set(skipped))} left alone")
    if not changed:
        print("Nothing to do -- the machinery here already matches the template.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
