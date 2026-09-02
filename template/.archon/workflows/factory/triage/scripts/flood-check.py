"""Flood protection. FACTORY_RULES 1.

Non-owner accounts are capped at N issues per UTC calendar day. Excess issues get
`factory:rate-limited` and wait; the next day's triage removes the label and
re-evaluates them, so the cap is a DELAY and not a wastebasket.

Runs BEFORE the classifier so a rate-limited issue never costs a model call. The
repository owner is exempt -- you should not be able to lock yourself out of your
own factory by filing four issues in a morning.

Emits {"rate_limited": bool, "reason": str}.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

# nodeio FIRST -- see factory/nodeio.py for the incident that made this a rule.
from nodeio import emit, note  # noqa: E402

import config  # noqa: E402
import state  # noqa: E402

# THROUGH CONFIG, not os.environ. A workflow node runs under the engine with a
# declared set of bindings; an undeclared env read here can never be set by anyone,
# so the cap was permanently 3 whatever the operator configured, and the only symptom
# was a warning in `archon workflow list`.
DAILY_CAP = config.ISSUE_CAP_PER_DAY
target = (os.environ.get("INPUTS_TARGET") or "").strip()

if not target:
    emit({"rate_limited": False, "reason": "no target"})
    sys.exit(0)


def owner() -> str:
    """The repo owner is exempt. Read it, do not configure it -- a hardcoded name
    is a footgun the moment this template is copied to a second repo."""
    try:
        url = state.gh("repo", "view", "--json", "owner")
        return json.loads(url)["owner"]["login"]
    except Exception:  # noqa: BLE001
        return ""


try:
    item = state.fetch(target)
except Exception as e:  # noqa: BLE001
    # A flood check that cannot run must not silently pass every issue. It also must
    # not block the whole factory on a transient API hiccup, so it reports the fact
    # and lets the classifier decide -- the disposition still goes through the
    # transition table either way.
    emit({"rate_limited": False, "reason": f"flood check unavailable: {e}"})
    sys.exit(0)

author = (item.get("author") or {}).get("login", "")
repo_owner = owner()

# --- unstick yesterday's rate-limited issues ---------------------------------
# Any open issue labelled factory:rate-limited whose createdAt is on a prior UTC
# date gets the label removed so a later cycle re-evaluates it. Without this the
# cap is permanent for anyone who ever tripped it.
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
try:
    stale = json.loads(
        state.gh(
            "issue", "list", "--state", "open", "--label", "factory:rate-limited",
            "--limit", "100", "--json", "number,createdAt",
        ) or "[]"
    )
    for it in stale:
        if it["createdAt"][:10] < today:
            state.gh("issue", "edit", str(it["number"]), "--remove-label",
                     "factory:rate-limited", check=False)
            note(f"UNSTUCK #{it['number']} (created before {today})")
except Exception:  # noqa: BLE001
    pass

if author == repo_owner or not author:
    emit({"rate_limited": False, "reason": f"{author or 'unknown'} is exempt"})
    sys.exit(0)

# --- count today's issues from this author -----------------------------------
# Open AND closed, so the author's full daily footprint counts rather than only what
# survived triage.
try:
    todays = json.loads(
        state.gh("issue", "list", "--state", "all", "--limit", "200",
                 "--json", "number,author,createdAt") or "[]"
    )
except Exception as e:  # noqa: BLE001
    emit({"rate_limited": False, "reason": f"could not count: {e}"})
    sys.exit(0)

mine = sorted(
    [
        it for it in todays
        if it["createdAt"][:10] == today and (it.get("author") or {}).get("login") == author
    ],
    key=lambda it: it["createdAt"],
)
position = next((i for i, it in enumerate(mine) if str(it["number"]) == target.split(":")[-1]), None)

if position is not None and position >= DAILY_CAP:
    reason = (
        f"@{author} has filed {len(mine)} issues today; the cap for non-owner accounts "
        f"is {DAILY_CAP} per UTC day (FACTORY_RULES 1). This one is held and will be "
        f"re-evaluated after midnight UTC."
    )
    emit({"rate_limited": True, "reason": reason})
    sys.exit(0)

emit({
    "rate_limited": False,
    "reason": f"@{author} is at {len(mine)}/{DAILY_CAP} today",
})
