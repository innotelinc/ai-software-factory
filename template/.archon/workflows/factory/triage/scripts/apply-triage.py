"""Apply the triage decision. Code, not the model.

The classifier emits a disposition; this applies it through factory/state.py, which
refuses a transition the table does not allow. Everything a human will read goes out
through the one comment helper, which posts it in a single process and READS IT
BACK -- because `exit 0` from the tool that posted a verdict proves the API call
succeeded, not that it carried anything.

A TRIAGE THAT DECIDES `needs-human` MUST REACH A HUMAN. That is easy to miss,
because a correct escalation is not a failure: it takes the success path, and the
success path is the one with no alarm on it. Measured on a real factory: seven probe
issues, two correct needs-human decisions, ZERO notifications.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

import config  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
rate_limited = (os.environ.get("INPUTS_RATE_LIMITED") or "").strip().lower() == "true"
flood_reason = (os.environ.get("INPUTS_FLOOD_REASON") or "").strip()
raw = (os.environ.get("INPUTS_DECISION") or "").strip()

if not target:
    print("APPLY_FAILED: no target", file=sys.stderr)
    sys.exit(1)

# --- the rate-limited path ----------------------------------------------------
if rate_limited:
    state.gh("issue", "edit", target.split(":")[-1], "--add-label", "factory:rate-limited",
             check=False)
    state.comment(
        target,
        "**Factory triage: rate-limited**\n\n"
        f"{flood_reason}\n\n"
        "No disposition has been made. This is a delay, not a decision.",
    )
    print(f"RATE_LIMITED {target}")
    sys.exit(0)

if not raw:
    print(
        "APPLY_FAILED: the classifier produced no decision. A triage run that reaches "
        "here with nothing to apply is a machinery fault, not a disposition -- the "
        "issue keeps its current state and will be re-dispatched.",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    decision = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"APPLY_FAILED: decision is not readable JSON ({e}): {raw[:300]}", file=sys.stderr)
    sys.exit(1)

disposition = decision.get("disposition", "")
if disposition not in {"accepted", "deferred", "rejected", "needs-human"}:
    print(f"APPLY_FAILED: unknown disposition {disposition!r}", file=sys.stderr)
    sys.exit(1)

note = (decision.get("note") or "").strip()
if not note:
    print(
        "APPLY_FAILED: the disposition carries no note. The note is the whole of what "
        "the filer sees; a verdict nobody can read is not a verdict.",
        file=sys.stderr,
    )
    sys.exit(1)

priority = (decision.get("priority") or "").strip()
area = (decision.get("area") or "").strip()
cited = decision.get("rules_cited") or []

# --- publish BEFORE transitioning ---------------------------------------------
# A rejected issue is CLOSED by the state write. Commenting after the close still
# works, but commenting first means that if the close fails the filer has the
# reasoning anyway -- and the reasoning is the part they were owed.
header = {
    "accepted": "accepted",
    "deferred": "deferred",
    "rejected": "rejected",
    "needs-human": "escalated to a human",
}[disposition]

body = [f"**Factory triage: {header}**", "", note]
if disposition == "accepted":
    body += ["", f"_Priority: {priority or 'unset'} · Area: {area or 'unset'}_"]
if cited:
    body += ["", f"_Cited: {', '.join(cited)}_"]
if disposition == "rejected":
    body += [
        "",
        "_If you disagree, reopen with the missing detail and the next triage cycle "
        "picks it up fresh._",
    ]
state.comment(target, "\n".join(body))

# --- then the state -----------------------------------------------------------
if priority and disposition == "accepted":
    state.set_priority(target, priority)

rc = state.main(["set", target, f"state={disposition}"])
if rc != 0:
    print(
        f"APPLY_FAILED: '{disposition}' is not a legal transition for {target}. The "
        f"reasoning has been posted; the label has not moved. This is a triage bug, "
        f"not a filer problem.",
        file=sys.stderr,
    )
    sys.exit(1)

# --- and the alarm, on the one path that needs it -----------------------------
if disposition == "needs-human":
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
            f"(triage)  {note.splitlines()[0][:200]}\n"
        )
    print(notify.send(target, f"(triage) {note.splitlines()[0][:200]}"))

print(f"TRIAGED {target} -> {disposition}" + (f" priority={priority}" if priority else ""))
