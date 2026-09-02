"""Run the full gate against main and report honestly what happened.

THE DISTINCTION THIS FILE EXISTS TO MAKE, and it is the whole value of the node:

    the harness ran and the software is broken     -> file an issue
    the harness did not run                        -> file NOTHING, tell a human

They look identical from a non-zero exit code, and getting them confused in the
generous direction is how a backlog fills with fictional product bugs: the harness
could not start, every check "failed", and the diagnosis node dutifully writes up six
defects that do not exist. Every one then goes through triage, and a human eventually
works out that the real problem was a missing dependency.

So the test is POSITIVE and structural: did the harness emit the markers that prove
it got as far as running? `HARNESS_START` proves it launched. The required markers
prove each family reported. Absence of either is an infrastructure failure, whatever
the exit code says.
"""

from __future__ import annotations

import json
import os
import re
import shlex
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

artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
artifacts.mkdir(parents=True, exist_ok=True)
log_file = artifacts / "regress.log"

cmd = config.VALIDATE_CMD
note(f"REGRESS_START {datetime.now(timezone.utc).isoformat()} {cmd}")

try:
    p = subprocess.run(
        shlex.split(cmd, posix=(os.name != "nt")),
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=2700,
    )
    out = (p.stdout or "") + (p.stderr or "")
    rc = p.returncode
except subprocess.TimeoutExpired as e:
    out = (e.stdout or "") if isinstance(e.stdout, str) else ""
    out += "\nTIMEOUT after 2700s\n"
    rc = 124
except OSError as e:
    out, rc = f"could not run {cmd!r}: {e}\n", 127

log_file.write_text(out, encoding="utf-8")
note(out[-6000:])

# --- did the harness actually run? --------------------------------------------
launched = "HARNESS_START" in out
reported = [m for m in config.REQUIRED_MARKERS if m in out]
# PROTECTED_OK comes from the guard, which this node does not run -- the regression
# is checking merged code, not a diff, so there is no protected-path question to ask.
expected = [m for m in config.REQUIRED_MARKERS if m != "PROTECTED_OK"]
missing = [m for m in expected if m not in out]

failed_step = ""
steps = re.findall(r"GATE_FAILED:\s*([a-z0-9_-]+)", out)
if steps:
    failed_step = steps[-1]

harness_ran = launched and (not missing or bool(failed_step))
green = rc == 0 and launched and not missing

if not harness_ran:
    summary = (
        "the harness did not run to completion: "
        + ("it never started" if not launched else "no step reported a failure and "
           + str(len(missing)) + " required marker(s) never appeared: " + " ".join(missing))
        + ". This is an infrastructure failure, not a product defect -- NOTHING will be filed."
    )
elif green:
    summary = f"all green ({len(reported)} marker families reported)"
else:
    summary = (
        f"the suite stopped at the '{failed_step or 'unknown'}' step"
        if failed_step
        else f"the harness ran and exited {rc}"
    )

note(f"REGRESS_DONE green={green} harness_ran={harness_ran} {summary}")
emit(
        {
            "green": green,
            "harness_ran": harness_ran,
            "failed_step": failed_step,
            "summary": summary,
        }
)
