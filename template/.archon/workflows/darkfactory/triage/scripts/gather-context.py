"""Everything the classifier is allowed to see, assembled once, by code.

The classify node has NO TOOLS. That is deliberate: a triage agent that can go
looking around the repository ends up justifying its disposition from something it
found rather than from the governance files, and the citation stops being checkable.
So the inputs are assembled here and handed over whole.

Writes to $ARTIFACTS_DIR and prints the same text, because a command file reads the
prompt and a human reads the artifact.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

import config  # noqa: E402
import state  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
artifacts.mkdir(parents=True, exist_ok=True)

parts: list[str] = []


def section(title: str, text: str) -> None:
    parts.append(f"\n=== {title} ===\n{text.rstrip()}\n")


# --- the issue, exactly as it was filed --------------------------------------
issue_text = state.body_text(target)
(artifacts / "issue.md").write_text(issue_text, encoding="utf-8")
section("THE ISSUE, AS FILED", issue_text)

# --- governance ---------------------------------------------------------------
for name in ("MISSION.md", "FACTORY_RULES.md"):
    p = config.ROOT / name
    section(name, p.read_text(encoding="utf-8", errors="replace") if p.exists()
            else f"({name} is missing -- triage cannot cite what does not exist)")

# --- decisions already made ---------------------------------------------------
# THE POINT OF THIS FILE IS THAT A DECISION IS ASKED ONCE. Without it, one unmade
# product decision is re-discovered by every issue that touches it and reported as a
# fresh escalation each time. The human sees four interruptions and concludes the
# factory refuses too much work, when it actually refused one thing four times.
if config.DECISIONS_FILE.exists():
    section("DECISIONS ALREADY MADE (.factory/decisions.md)",
            config.DECISIONS_FILE.read_text(encoding="utf-8", errors="replace"))

# --- what is already in flight -------------------------------------------------
# So the classifier can recognise a duplicate, or an issue an open PR already
# addresses, instead of queueing the same mechanism twice.
try:
    open_issues = json.loads(
        state.gh("issue", "list", "--state", "open", "--limit", "50",
                 "--json", "number,title,labels") or "[]"
    )
    open_prs = json.loads(
        state.gh("pr", "list", "--state", "open", "--limit", "30",
                 "--json", "number,title,body") or "[]"
    )
except Exception as e:  # noqa: BLE001
    open_issues, open_prs = [], []
    section("IN FLIGHT", f"(could not be read: {e})")
else:
    me = target.split(":")[-1]
    section(
        "OTHER OPEN ISSUES",
        "\n".join(
            f"- #{i['number']}: {i['title']}  [{', '.join(l['name'] for l in i.get('labels', []))}]"
            for i in open_issues
            if str(i["number"]) != me
        ) or "(none)",
    )
    section(
        "OPEN PULL REQUESTS",
        "\n".join(
            f"- #{p['number']}: {p['title']}\n    {(p.get('body') or '')[:200].strip()}"
            for p in open_prs
        ) or "(none)",
    )

blob = "".join(parts)
(artifacts / "triage-context.md").write_text(blob, encoding="utf-8")
sys.stdout.write(blob)
