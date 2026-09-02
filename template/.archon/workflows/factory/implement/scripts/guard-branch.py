"""Run the protected-path guard against this branch, and escalate if it fires.

A protected-file violation is an AUTO-REJECT with no fix attempt (FACTORY_RULES 6):
needing one of those files touched means the scope was misunderstood, which is a
triage bug rather than a code bug. So it parks the issue for a human instead of
sending it round the fix loop, where it would fail twice more and then park anyway.

Size and scope violations are the same shape for a different reason: a PR nobody
could review even in principle is not shippable here, and no number of fix attempts
makes it smaller.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

import config  # noqa: E402
import guard  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402

base = (os.environ.get("INPUTS_BASE") or "origin/main").strip()
target = (os.environ.get("INPUTS_TARGET") or "").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")

# HEAD, not the branch name. The workflow is standing in the worktree that holds the
# work, and naming the branch would make this depend on a ref that a rebase or a
# rename can move under it.
rc = guard.main(["--base", base, "--head", "HEAD"])

if rc == 0:
    print("GUARD_OK")
    sys.exit(0)

reason = {
    1: "the change touches a protected path, or exceeds the size or scope cap",
    2: "the guard could not compute the diff, so nothing was checked",
}.get(rc, f"the guard exited {rc}")

print(f"GUARD_BLOCKED: {reason}", file=sys.stderr)

if target:
    try:
        state.main(["set", target, "state=needs-human"])
    except Exception:  # noqa: BLE001
        pass
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
            f"(guard)  {reason}\n"
        )
    try:
        state.comment(
            target,
            "**Factory guard: blocked**\n\n"
            f"{reason}\n\n"
            "Auto-reject, no fix attempt (FACTORY_RULES §6). No pull request was "
            "opened. Needing a protected file touched means the scope was "
            "misunderstood, which is a triage decision rather than a code fix.",
        )
    except Exception:  # noqa: BLE001
        pass
    print(notify.send(target, f"(guard) {reason}"))

sys.exit(1)
