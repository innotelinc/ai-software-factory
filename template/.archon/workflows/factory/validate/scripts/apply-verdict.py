"""Hand the raw log and the verdict to factory/gate.py, which decides.

Nothing is decided here. This is the seam between "a model produced a judgement" and
"code acted on it", and keeping it thin is the point: the gate re-reads the markers
itself, overrides the verdict when they disagree, holds the merge on an assumption or
on ratchet slack, saves the findings where a later fix run can read them, and calls
the merge.

THE ONE THING THIS FILE OWNS is the case where the judge produced nothing at all. A
missing verdict is not an approval and it is not a rejection of the work -- it is a
validator that failed, and treating it as a verdict about the PR sends whoever reads
it looking for a defect that is not there.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

import config  # noqa: E402
import gate  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
raw = (os.environ.get("INPUTS_VERDICT") or "").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
gate_log = artifacts / "gate.log"
verdict_file = artifacts / "verdict.json"

if not target:
    print("APPLY_FAILED: no target", file=sys.stderr)
    sys.exit(1)


def infra_failure(reason: str) -> None:
    """The validator itself failed. Park it and say so -- do NOT dress it up as a
    verdict about the code.

    The PR stays open. A human needs to see the diff to investigate, and closing it
    would throw away work that may be perfectly good."""
    print(f"VALIDATOR_FAILED: {reason}", file=sys.stderr)

    # ALREADY PARKED? Then an earlier node in this same run has already labelled it,
    # written the ledger line and sent the notification -- and doing all three again
    # produces two alerts for one failure. "If everything notifies, you mute it, and
    # then nothing notifies" is a rule about volume, and the cheapest place to lose is
    # the duplicate you send yourself.
    try:
        if state.fetch(target)["_state"] == "needs-human":
            print(f"ALREADY_PARKED {target} - an earlier node reported this; not repeating it")
            sys.exit(1)
    except Exception:  # noqa: BLE001
        pass

    try:
        state.main(["set", target, "state=needs-human"])
    except Exception as e:  # noqa: BLE001
        # LOUD. This label IS the state machine: if it does not stick the item keeps its
        # old state, the dispatcher re-selects it next tick, and an escalation that
        # looked successful becomes a loop. needs-human.md is written either way, so
        # silence here left the only evidence pointing at a successful park.
        print(f"ESCALATION_LABEL_FAILED {target}: {e}. Recorded in needs-human.md, but "
              f"the label did not change -- the dispatcher may re-select this.",
              file=sys.stderr)
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
            f"(validator)  {reason}\n"
        )
    try:
        state.comment(
            target,
            "**Factory validation: could not render a verdict**\n\n"
            f"{reason}\n\n"
            "This is a validator-side failure, not a defect in this pull request. The "
            "PR is left open and labelled for a human. Do not re-queue the issue for "
            "another implementation attempt until the cause is understood.",
        )
    except Exception:  # noqa: BLE001
        pass
    print(notify.send(target, f"(validator) {reason}"))
    sys.exit(1)


if not gate_log.exists() or not gate_log.stat().st_size:
    infra_failure(
        "the gate produced no log at all, so no check can be shown to have run. "
        "Nothing here is evidence about the diff."
    )

if not raw:
    infra_failure(
        "the judge node produced no verdict. A missing verdict is not an approval: "
        "it means the independent judgement never happened."
    )

try:
    verdict = json.loads(raw)
except json.JSONDecodeError as e:
    infra_failure(f"the judge's verdict is not readable JSON ({e}): {raw[:300]}")

verdict_file.write_text(json.dumps(verdict, indent=2), encoding="utf-8")

rc = gate.main([target, str(gate_log), str(verdict_file)])

# 0 merged or held green · 1 blocked and escalated · 2 called from the wrong state ·
# 3 a verdict was recorded and no merge happened. Only 2 is a machinery fault worth
# failing the run over -- the others are the gate working.
if rc == 2:
    infra_failure(
        "the gate refused to run: the PR was not in 'validating' when it was reached, "
        "so the independent validation was skipped and there is nothing to gate on."
    )

print(f"GATE_EXIT={rc}")
sys.exit(0 if rc in (0, 1, 3) else rc)
