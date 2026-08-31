"""Run the full gate, here, for the BUILDER's benefit.

NOTHING DOWNSTREAM TRUSTS THIS. The validator re-runs everything in its own process,
against its own checkout, with its own context -- that independence is the whole
reason a merge without a human reading the diff is defensible at all.

So why run it? Because a lap that opens a PR it already knows is red spends a whole
validation cycle to learn what a subprocess could have said here in two minutes. It
is a courtesy to the queue, not a gate.

DELIBERATELY NON-FATAL. A red self-check still opens the PR: the validator's finding
is what the fix node works from, and a red the builder cannot fix is a red a human
should see stated by the independent judge rather than by the thing that wrote the
code. The one thing this does refuse is silence -- an empty log is reported as a
fault, because a check that produced no output at all did not run.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

import config  # noqa: E402

artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
artifacts.mkdir(parents=True, exist_ok=True)
log = artifacts / "selfcheck.log"

cmd = config.VALIDATE_CMD
print(f"SELFCHECK_START {cmd}")

try:
    p = subprocess.run(
        shlex.split(cmd, posix=(os.name != "nt")),
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1500,
    )
    out = (p.stdout or "") + (p.stderr or "")
    rc = p.returncode
except subprocess.TimeoutExpired:
    out, rc = "TIMEOUT after 1500s", 124
except OSError as e:
    out, rc = f"could not run {cmd!r}: {e}", 127

log.write_text(out, encoding="utf-8")

if not out.strip():
    print(
        "SELFCHECK_EMPTY: the validate command produced no output at all. That is not "
        "a pass and it is not a fail -- it is a command that did not run. Check "
        "FACTORY_VALIDATE_CMD in factory/config.py.",
        file=sys.stderr,
    )
    sys.exit(1)

tail = "\n".join(out.splitlines()[-40:])
print(tail)

if rc == 0:
    print("SELFCHECK_GREEN - the independent validator still re-runs all of it")
else:
    print(
        f"SELFCHECK_RED (exit {rc}) - opening the PR anyway. The independent validator "
        f"produces the finding the fix node works from; a builder's own account of why "
        f"its work is red is not evidence."
    )
sys.exit(0)
