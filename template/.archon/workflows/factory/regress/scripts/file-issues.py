"""File the regression's findings as issues, with dedup. Or file nothing, loudly.

THE GUARD THAT MATTERS IS THE ONE THAT REFUSES. Three separate conditions have to
hold before a single issue is created:

 1. the harness actually ran (positive markers, not just a non-zero exit),
 2. the diagnosis node did not itself conclude this was infrastructure,
 3. there is at least one finding with a title and a body.

Any of them missing means the run reports and files NOTHING. A factory that spams its
own backlog with fabricated product bugs whenever it cannot prove its own test
harness ran is worse than a factory that stayed quiet -- every fabricated issue costs
a triage cycle, and the humans learn to ignore the label.

DEDUP IS BY TITLE, and that is why the diagnosis prompt insists the title is stable
across runs of the same defect. A weekly job that files the same bug five times has
taught everyone to filter it out.
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

green = (os.environ.get("INPUTS_GREEN") or "").strip().lower() == "true"
harness_ran = (os.environ.get("INPUTS_HARNESS_RAN") or "").strip().lower() == "true"
sha = (os.environ.get("INPUTS_SHA") or "?").strip()
raw = (os.environ.get("INPUTS_DIAGNOSIS") or "").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")

LABEL = "factory:from-regression"


def escalate(reason: str) -> None:
    """The one output that must reach a person: the factory cannot check itself."""
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  regression  "
            f"({sha})  {reason}\n"
        )
    print(notify.send("regression", reason))


# --- 1. all green --------------------------------------------------------------
if green:
    print(f"REGRESSION_GREEN {sha} - nothing to file")
    sys.exit(0)

# --- 2. the harness did not run ------------------------------------------------
if not harness_ran:
    reason = (
        f"the scheduled regression could not run its own harness against {sha}. NOTHING "
        f"was filed, because a harness that did not run produces no evidence about the "
        f"product. See {artifacts / 'regress.log'}."
    )
    print(f"INFRA_FAILURE: {reason}", file=sys.stderr)
    escalate(reason)
    sys.exit(1)

# --- 3. the diagnosis ----------------------------------------------------------
if not raw:
    reason = (
        f"the regression against {sha} went red and the diagnosis node produced nothing. "
        f"Nothing was filed: a red run with no reading of it is not a bug report."
    )
    print(f"NO_DIAGNOSIS: {reason}", file=sys.stderr)
    escalate(reason)
    sys.exit(1)

try:
    diagnosis = json.loads(raw)
except json.JSONDecodeError as e:
    reason = f"the diagnosis is not readable JSON ({e}). Nothing filed."
    print(reason, file=sys.stderr)
    escalate(reason)
    sys.exit(1)

if diagnosis.get("infrastructure_failure"):
    reason = (
        f"the regression against {sha} failed for infrastructure reasons, not a product "
        f"defect: {diagnosis.get('summary', '(no summary)')}. NOTHING was filed."
    )
    print(f"INFRA_FAILURE: {reason}")
    escalate(reason)
    sys.exit(0)

findings = [
    f for f in (diagnosis.get("findings") or [])
    if (f.get("title") or "").strip() and (f.get("body") or "").strip()
]
if not findings:
    reason = (
        f"the regression against {sha} went red but the diagnosis produced no usable "
        f"finding. Nothing filed. Summary: {diagnosis.get('summary', '')[:300]}"
    )
    print(reason, file=sys.stderr)
    escalate(reason)
    sys.exit(1)

# --- 4. file, with dedup -------------------------------------------------------
try:
    existing = json.loads(
        state.gh(
            "issue", "list", "--state", "open", "--label", LABEL,
            "--limit", "100", "--json", "number,title",
        ) or "[]"
    )
except Exception as e:  # noqa: BLE001
    print(f"FILE_FAILED: could not list existing issues ({e}). Nothing filed.", file=sys.stderr)
    escalate(f"the regression found {len(findings)} problem(s) but could not file them: {e}")
    sys.exit(1)

by_title = {(i["title"] or "").strip().lower(): i["number"] for i in existing}
filed, deduped = [], []

for f in findings:
    title = f["title"].strip()[:200]
    severity = f.get("severity", "medium")
    priority = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}.get(
        severity, "medium"
    )

    if title.lower() in by_title:
        n = by_title[title.lower()]
        deduped.append((n, title))
        print(f"DEDUPED #{n} {title}")
        continue

    body = "\n".join(
        [
            f["body"].strip(),
            "",
            "---",
            "",
            f"_Filed by the scheduled regression run against `{sha}` on "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}. Area: "
            f"{f.get('area', 'unspecified')}. Suspect: "
            f"{f.get('suspect_commits', 'unclear')}._",
            "",
            "_This issue goes through normal triage like any other. If it is not "
            "actionable as written, reject it and the regression will re-file a "
            "sharper version when it next reproduces._",
        ]
    )

    try:
        out = state.gh(
            "issue", "create", "--title", title, "--body-file", "-",
            "--label", LABEL, "--label", f"priority:{priority}",
            stdin=body,
        )
        url = (out or "").strip().splitlines()[-1] if out else ""
        filed.append((url, title))
        print(f"FILED {url} {title}")
    except Exception as e:  # noqa: BLE001
        print(f"FILE_FAILED for {title!r}: {e}", file=sys.stderr)

print(f"REGRESSION_RED {sha} filed={len(filed)} deduped={len(deduped)}")

# The escalation here is deliberately QUIET about the ordinary case. A regression that
# files one issue is the loop working, and it does not need to wake anybody -- triage
# will pick it up. Only a critical finding interrupts a person.
if any(f.get("severity") == "critical" for f in findings):
    escalate(
        f"the scheduled regression found a CRITICAL break in merged code at {sha}: "
        + "; ".join(t for _, t in filed)[:300]
    )

sys.exit(0)
