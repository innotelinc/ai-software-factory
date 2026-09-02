"""Push the branch and open the pull request. Code, not the model.

Same rule as the merge: a model's only output is a RECORD, and code decides what
happens to it. A node holding `gh pr create` is a node that can open a PR against any
branch it likes, including one that nothing validated.

TWO THINGS ARE ASSERTED RATHER THAN ASSUMED, and both have bitten real factories:

 1. THE SHAPE OF THE RECORD, not just its presence. The review prompt is one of the
    files you are meant to rewrite, and a rewrite can silently drop a field the
    machinery depends on. Observed once, and it cost the whole second half of the
    loop: a rewritten review prompt produced a perfectly good human-readable PR body
    with no front matter, so nothing could find the branch, and the PR could never
    be validated by anything. The implement lap looked like a complete success.

 2. THE BODY SURVIVED THE ROUND TRIP. `exit 0` from the tool that posted it proves
    the API call succeeded, not that it carried anything. The PR body is where the
    `Closes #N` link lives, and a PR without that link cannot be validated at all.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

# nodeio FIRST, before anything that might print at import time: importing it
# redirects stdout to stderr for the whole process, so a library marker can never
# be mistaken for this node's value. emit() writes to the real stdout.
from nodeio import emit, note  # noqa: E402

import config  # noqa: E402
import state  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
number = (os.environ.get("INPUTS_NUMBER") or "").strip()
branch = (os.environ.get("INPUTS_BRANCH") or "").strip()
base = (os.environ.get("INPUTS_BASE") or "origin/main").strip()
base_branch = base.split("/")[-1] or "main"
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")


def die(msg: str) -> None:
    note(f"OPEN_PR_FAILED: {msg}")
    sys.exit(1)


record = artifacts / "pr.md"
if not record.exists() or not record.stat().st_size:
    die(
        f"the review node wrote no PR record at {record}. Without it there is nothing "
        f"to open: the record carries the title, the summary and the issue link."
    )

text = record.read_text(encoding="utf-8", errors="replace")

# --- assert the shape ---------------------------------------------------------
front: dict[str, str] = {}
body = text
if text.lstrip().startswith("---"):
    parts = text.lstrip().split("---", 2)
    if len(parts) >= 3:
        for line in parts[1].strip().splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, v = line.split(":", 1)
                front[k.strip()] = v.strip().strip("\"'")
        body = parts[2].lstrip()

missing = [k for k in ("issue", "title") if not front.get(k)]
if missing:
    die(
        f"the PR record has no {', '.join(missing)} in its front matter. The review "
        f"prompt must emit the full block (issue / title). Failing here, naming the "
        f"missing field, beats failing three steps later as 'no branch'."
    )

title = front["title"][:120]

# --- the issue link, which is not optional ------------------------------------
# The validator extracts it to find what the diff was supposed to solve. A PR without
# it cannot be validated, so it is appended here rather than trusted to the prose.
if not re.search(r"(?:fixes|closes|resolves)\s+#\d+", body, re.I):
    body = body.rstrip() + f"\n\nCloses #{number}\n"

body = (
    body.rstrip()
    + "\n\n---\n"
    + f"Opened by `factory-implement`. No human read this diff.\n"
)
body_file = artifacts / "pr-body.md"
body_file.write_text(body, encoding="utf-8")


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args], cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


rc, out = git("rev-parse", "--abbrev-ref", "HEAD")
head = out if rc == 0 and out and out != "HEAD" else branch
if not head:
    die("could not determine the branch to push")

rc, out = git("push", "-q", "-u", "origin", head)
if rc != 0:
    die(f"could not push {head} to origin: {out}")
note(f"PUSHED {head}")

# --- open it, as a draft ------------------------------------------------------
# A DRAFT on purpose. It says "not ready for a human yet" while the independent
# validator has it, and the merge flips it. On a repo where someone is watching the
# PR list, that distinction is the difference between a queue and a pile.
p = subprocess.run(
    ["gh", "pr", "create", "--base", base_branch, "--head", head,
     "--title", title, "--body-file", str(body_file), "--draft"],
    cwd=str(config.ROOT), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=300,
)
if p.returncode != 0:
    # An existing PR for this head is not a failure -- a re-dispatch after a partial
    # run reaches here legitimately. Find it rather than opening a second one.
    existing = subprocess.run(
        ["gh", "pr", "list", "--head", head, "--json", "number,url", "--limit", "1"],
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    found = json.loads(existing.stdout or "[]") if existing.returncode == 0 else []
    if not found:
        die(f"gh pr create failed: {p.stderr.strip()}")
    pr_number, url = str(found[0]["number"]), found[0]["url"]
    note(f"PR_EXISTS #{pr_number} for {head} -- reusing it")
else:
    url = (p.stdout or "").strip().splitlines()[-1]
    m = re.search(r"/pull/(\d+)", url)
    if not m:
        die(f"could not read the PR number back from {url!r}")
    pr_number = m.group(1)
    note(f"PR_OPENED #{pr_number} {url}")

# --- read the body back -------------------------------------------------------
check = subprocess.run(
    ["gh", "pr", "view", pr_number, "--json", "body"],
    cwd=str(config.ROOT), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=120,
)
stored = json.loads(check.stdout or "{}").get("body", "") if check.returncode == 0 else ""
if f"#{number}" not in stored:
    die(
        f"PR #{pr_number} was opened but its body does not contain the issue link. The "
        f"validator extracts that link to find what the diff was supposed to solve, so "
        f"this PR could never be validated. Fix the body by hand."
    )
note("PR_BODY_VERIFIED issue link present")

# --- hand it to the independent validator -------------------------------------
if state.main(["set", f"gh:pr:{pr_number}", "state=open"]) != 0:
    die(
        f"could not label PR #{pr_number} for review. It exists and nothing will pick "
        f"it up -- label it factory:needs-review by hand."
    )

emit({"pr": pr_number, "url": url})
