#!/usr/bin/env python3
"""MUTATION TESTING. Break the software on purpose and require the gate to notice.

    python harness/mutations/run.py

THE ONLY THING IN THE GATE THAT MEASURES YOUR HARNESS RATHER THAN YOUR CODE.

Everything else answers "is this build good?". This answers "would this gate know if
it were not?" -- and they are completely different questions. A gate that has never
failed is a gate nobody has tested, and until you run this you have no evidence that
any of your checks can fail at all.

HOW IT WORKS. For each defect: copy the repo to a temp dir, apply one textual
mutation to real source, run the gate there, and require it to go RED. A mutation
the gate misses is a class of bug that can currently merge unreviewed.

WHAT MAKES A GOOD DEFECT. Not typos -- the compiler finds those. Aim at the seams
where your checks are weakest:

  * an invariant quietly inverted (a comparison flipped, a guard removed)
  * a value that stops changing (a counter that no longer increments)
  * an output made constant (always the same answer)
  * an error path that silently succeeds
  * a persistence write dropped (works until a restart)
  * an off-by-one at a boundary (right on average, wrong at the edge)

AIM AT LEAST ONE DEFECT AT EACH RUNG, and read WHICH rung caught each one. `ci.py`
stops at the first red rung, so a set built only from logic defects gets caught
entirely by 'unit' -- and the e2e, holdout and gate rungs are never once shown to be
able to fail. A real build scored 9/9 that way: the number read as "the gate can
fail" when all it meant was "the unit suite can fail". If every line below says
`by unit`, it is not a finished set.

Emits MUTATIONS_TOTAL, MUTATIONS_CAUGHT and MUTATIONS_NOT_INJECTED. The gate
requires caught == total and not_injected == 0.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEFECTS = HERE / "defects.json"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# What to copy into each throwaway build. Keep it small; this runs once per defect.
# Read from defects.json so it travels with the project rather than being edited here.
DEFAULT_COPY = ["app", "src", "tests", "harness", ".factory", "pyproject.toml", "package.json"]
SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", "runs", "locks-runtime", "builds", ".worktrees", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def build_copy(dest: Path, items: list[str]) -> int:
    copied = 0
    for item in items:
        src = ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        else:
            (dest / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest / item)
        copied += 1
    return copied


def apply(dest: Path, d: dict) -> tuple[bool, str]:
    """Textual mutation. Returns (injected, why-not).

    THE ANCHOR MUST BE UNIQUE, and that is not fussiness -- it is a bug this runner
    had and a factory found.

    A `replace(find, replace, 1)` hits the FIRST occurrence. When a change adds a
    second, byte-identical occurrence somewhere earlier in the file, the mutation
    silently starts rewriting the new line instead of the intended one. The intended
    target is left correct, so the check aimed at it never fires, and the defect is
    reported as ESCAPED -- pointing at a hole in the harness that does not exist,
    while the real problem is that the defect was injected into the wrong place.

    Observed exactly that way: a new route's `return self._error(409, str(e))` was
    identical to the one in an older handler, and the e2e assertion aimed at the older
    one stopped being exercised. Everything about the report was misleading.

    So an ambiguous anchor is NOT INJECTED, and it says which file and how many
    matches -- a defect that cannot be placed precisely is a defect that proves
    nothing.
    """
    target = dest / d["file"]
    if not target.exists():
        return False, f"{d['file']} does not exist in the build copy"
    body = target.read_text(encoding="utf-8")
    count = body.count(d["find"])
    if count == 0:
        return False, f"anchor not found in {d['file']}"
    if count > 1:
        return False, (
            f"anchor appears {count} times in {d['file']} -- ambiguous. The mutation "
            f"would hit the first one, which may not be the line this defect is about. "
            f"Lengthen the anchor until it is unique, or reword the duplicate."
        )
    target.write_text(body.replace(d["find"], d["replace"], 1), encoding="utf-8")
    return True, ""


def main() -> int:
    if not DEFECTS.exists():
        print("MUTATIONS_ABSENT no defects.json next to this script", flush=True)
        return 0

    spec = json.loads(DEFECTS.read_text(encoding="utf-8"))
    defects = spec["defects"]
    copy_items = spec.get("copy") or DEFAULT_COPY
    total = caught = not_injected = 0

    print("MUTATION_START", flush=True)
    for d in defects:
        total += 1
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "build"
            dest.mkdir()
            if build_copy(dest, copy_items) == 0:
                # Pointed at the wrong paths, the runner would otherwise score a
                # perfect run against a build containing no code at all.
                print(
                    f"  NOT_INJECTED  {d['id']:<40} the build copy matched nothing from "
                    f"{copy_items}",
                    flush=True,
                )
                not_injected += 1
                continue

            injected, why = apply(dest, d)
            if not injected:
                # NOT a pass. The anchor moved or went ambiguous, so this defect tested
                # nothing -- and a mutation set that silently stops injecting reports a
                # perfect score for doing nothing at all.
                not_injected += 1
                print(f"  NOT_INJECTED  {d['id']:<40} {why}", flush=True)
                continue

            env = dict(os.environ, FACTORY_IN_MUTATION="1")
            try:
                r = subprocess.run(
                    [sys.executable, "harness/ci.py"], cwd=dest, env=env,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=1200,
                )
                rc, out = r.returncode, (r.stdout or "")
            except subprocess.TimeoutExpired:
                rc, out = 124, "TIMEOUT"

            if rc != 0:
                caught += 1
                step = "gate"
                for line in out.splitlines():
                    if line.startswith("GATE_FAILED:"):
                        step = line.split(":", 1)[1].strip()
                print(f"  CAUGHT        {d['id']:<40} by {step}", flush=True)
            else:
                print(f"  ESCAPED       {d['id']:<40} <-- {d['why']}", flush=True)

    print(f"MUTATIONS_TOTAL={total}", flush=True)
    print(f"MUTATIONS_CAUGHT={caught}", flush=True)
    print(f"MUTATIONS_NOT_INJECTED={not_injected}", flush=True)
    if caught == total and not_injected == 0:
        print("MUTATIONS_OK", flush=True)
        return 0
    print(
        "MUTATIONS_FAILED - every escaped defect is a class of bug that can currently "
        "merge unreviewed",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
