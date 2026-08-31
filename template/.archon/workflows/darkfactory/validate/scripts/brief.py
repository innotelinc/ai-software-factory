"""Compose everything the judge may see into ONE document, and hand it over.

THE BUG THIS EXISTS TO FIX, and it is the most instructive one in this build.

The judge runs with `allowed_tools: []`. That is the mechanism: the inability to go
looking is what makes its verdict about the diff rather than about whatever it found
on the way past. The prompt then told it to "read these from $ARTIFACTS_DIR" -- files
it had no tool to open.

It did exactly the right thing. It refused to fabricate a judgment, said its inputs
were missing, and returned reject. Which is correct behaviour and a rejected pull
request, because the prompt asked a node to do something the node could not do.

That is the failure the skill warns about in the other direction -- a plan that
specifies a step the next node cannot perform -- and it is silent in both: nothing
crashes, a node just quietly cannot do its job and says something plausible instead.

So the inputs are SUBSTITUTED into the prompt rather than read from disk. The judge
keeps no tools, and everything it may consider is in front of it.

WHAT GOES IN, and the omissions are the point:

    the issue, as filed                the contract
    the diff, against the merge base   what the code does now
    the commit SUBJECTS                titles only -- a commit body is the coder's story
    the gate log                       what the checks printed, verbatim
    governance from the BASE branch    the rulebook this PR cannot have weakened

    NOT the plan. NOT the implementation report. NOT the priming. NOT any comment on
    the PR, including the judge's own from a previous round.

TRUNCATION IS DECLARED, NEVER SILENT. A diff clipped without saying so is a judge
reasoning about a file it thinks it read to the end.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# nodeio FIRST. Its value here is not the stdout redirect (this node's value IS a
# document) but the UNCONDITIONAL UTF-8 on every stream: Windows defaults stdio to the
# ANSI codepage, and this file died at the final write on a single non-ASCII character
# after doing all of its work.
sys.path.insert(0, str(Path.cwd() / "factory"))
from nodeio import emit_text, note  # noqa: E402

artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")

# Generous, and bounded. A 400 KB diff would not fit in a prompt and would not be read
# carefully if it did -- and the size cap means a legitimate factory PR is nowhere
# near these numbers. A PR that is, has already been rejected by the guard.
DIFF_LINES = 2500
LOG_LINES = 500
GOV_CHARS = 20000


def read(name: str) -> str:
    p = artifacts / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def clip_lines(text: str, limit: int, what: str) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    kept = "\n".join(lines[:limit])
    return (
        kept
        + f"\n\n[TRUNCATED: {len(lines) - limit} further lines of {what} are not shown. "
        f"Judge only what is above; do not assume anything about what is missing, and "
        f"say so in your reasoning if it matters.]"
    )


def clip_chars(text: str, limit: int, what: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[TRUNCATED: {what} continues beyond {limit} characters.]"


def tail_lines(text: str, limit: int, what: str) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return (
        f"[EARLIER OUTPUT OMITTED: {len(lines) - limit} lines. The end of a check log is "
        f"where the verdict lives.]\n\n" + "\n".join(lines[-limit:])
    )


sections: list[str] = []


def section(title: str, body: str, if_absent: str = "") -> None:
    body = body.strip()
    if not body:
        body = f"(empty -- {if_absent or 'this input was not produced'})"
    sections.append(f"\n\n=== {title} ===\n\n{body}")


section(
    "THE ISSUE, EXACTLY AS IT WAS FILED",
    read("issue.md"),
    "without it there is nothing to judge the diff against",
)
section("PULL REQUEST", read("pr-meta.json"))
section(
    "THE DIFF, computed against the merge base",
    clip_lines(read("diff.patch"), DIFF_LINES, "diff"),
    "an empty diff does not solve an issue",
)
section(
    "COMMIT SUBJECTS (titles only, deliberately)",
    read("commits.txt"),
)
section(
    "THE GATE LOG -- the raw output of the checks that just ran",
    tail_lines(read("gate.log"), LOG_LINES, "gate log"),
    "no check can be shown to have run",
)
for name in ("MISSION.md", "FACTORY_RULES.md", "CLAUDE.md", "AGENTS.md"):
    body = read(f"base-{name}")
    if body:
        section(f"{name} -- READ FROM THE BASE BRANCH, not from this PR",
                clip_chars(body, GOV_CHARS, name))

blob = "".join(sections).strip()
(artifacts / "judge-brief.md").write_text(blob, encoding="utf-8")

# The brief IS this node's value: it is substituted straight into the judge's prompt,
# which is why the node has no output_format. Its value is a document, not a field.
note(f"BRIEF_COMPOSED {len(blob)} chars, {len(sections)} sections")
emit_text(blob)
