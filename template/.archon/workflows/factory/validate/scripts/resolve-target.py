"""Turn the run's trigger message into a target, deterministically.

The dispatcher sends "triage gh:issue:12". A human sends "triage issue 12", or
"triage #12", or a URL. Parsing that is a job for code: a model asked to extract a
number will occasionally extract a plausible one that was never filed, and the
factory then acts on it.

Reads (env, because user-controlled values are never substituted into script source):
    ARGUMENTS        the trigger message
    INPUTS_DECLARED  an explicit target passed via the workflow's `inputs:`
    INPUTS_KIND      "issue" or "pr"

Emits {"target": "gh:issue:12", "number": "12"}.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# nodeio FIRST: importing it redirects stdout to stderr for the whole process, so a
# library marker can never be mistaken for this node's value. emit() writes the value.
sys.path.insert(0, str(Path.cwd() / "factory"))
from nodeio import emit, note  # noqa: E402

kind = (os.environ.get("INPUTS_KIND") or "issue").strip()
declared = (os.environ.get("INPUTS_DECLARED") or "").strip()
message = (os.environ.get("ARGUMENTS") or "").strip()

candidate = declared or message

# Most specific first. A bare number is the last resort, because "fix 3 tests" has a
# number in it and is not a target.
patterns = [
    rf"\bgh:{kind}:(\d+)\b",
    rf"github\.com/[^/\s]+/[^/\s]+/(?:{'issues' if kind == 'issue' else 'pull'})/(\d+)",
    rf"\b{kind}\s*#?(\d+)\b",
    r"#(\d+)\b",
    r"^\s*(\d+)\s*$",
]

number = None
for pat in patterns:
    m = re.search(pat, candidate, re.I)
    if m:
        number = m.group(1)
        break

if not number:
    note(
        f"RESOLVE_FAILED: could not find a {kind} number in {candidate!r}.\n"
        f"  Expected something like 'gh:{kind}:12', '#12', or a GitHub URL. Refusing to "
        f"guess: a run dispatched against an item that was never filed does real work "
        f"against nothing."
    )
    sys.exit(1)

note(f"RESOLVED {kind} #{number}")
emit({"target": f"gh:{kind}:{number}", "number": number})
