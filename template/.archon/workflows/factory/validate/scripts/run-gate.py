"""Run the guard and the harness, and write ONE gate log.

THE APPEND CONTRACT, which is the thing that bites. The guard's output goes in
FIRST, then the validate command's output is APPENDED to the same file. `PROTECTED_OK`
is one of the required markers and it comes from the guard, not from your harness --
so a harness that truncates or redirects over this log makes the guard's marker
vanish and every gate fail for a reason that has nothing to do with the code.

Your harness prints to stdout. This does the plumbing. Do not print PROTECTED_OK
yourself.

A PROTECTED-PATH VIOLATION SHORT-CIRCUITS EVERYTHING. It is an auto-reject with no
fix attempt: needing a protected file touched means the scope was misunderstood,
which is a triage decision rather than a code fix, and sending it round the fix loop
just fails twice more before parking it anyway.

This node does NOT decide the verdict. It runs things and records what they printed.
A red gate still reaches the judge, because the judge's finding is what the fix node
works from -- and because a gate that stops the pipeline on red never produces the
explanation a human needs.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "factory"))

# nodeio FIRST, before anything that might print at import time: importing it
# redirects stdout to stderr for the whole process, so a library marker can never
# be mistaken for this node's value. emit() writes to the real stdout.
from nodeio import emit, note  # noqa: E402

import config  # noqa: E402
# NOTE: `guard` is deliberately NOT imported from this checkout any more.
# See the block below; it is materialised from the base ref instead.
import notify  # noqa: E402
import state  # noqa: E402

target = (os.environ.get("INPUTS_TARGET") or "").strip()
base = (os.environ.get("INPUTS_BASE") or "origin/main").strip()
artifacts = Path(os.environ.get("ARTIFACTS_DIR") or ".")
artifacts.mkdir(parents=True, exist_ok=True)
gate_log = artifacts / "gate.log"


class Tee:
    """Capture and echo. The operator watching the run and the judge reading the log
    must see the same thing -- a log nobody streamed is a log nobody reads until the
    postmortem."""

    def __init__(self, path: Path) -> None:
        self.buf: list[str] = []
        self.path = path

    def write(self, text: str) -> None:
        # STDERR, not stdout. This node declares an output_format, so its stdout is
        # the machine's channel and must carry exactly one JSON object. Streaming the
        # gate log there would make every downstream `.field` read fail -- and the
        # failure would land on the CONSUMER, several nodes later, reading as though
        # that node were broken. Archon streams and retains stderr, so nothing is
        # lost by this; it is simply not mistaken for a value.
        self.buf.append(text)
        sys.stderr.write(text)
        sys.stderr.flush()

    def flush(self) -> None:
        self.path.write_text("".join(self.buf), encoding="utf-8")


tee = Tee(gate_log)
tee.write(f"GATE_RUN_START {datetime.now(timezone.utc).isoformat()} target={target}\n")

# --- 1. the guard, FIRST ------------------------------------------------------
import io  # noqa: E402

# THE GUARD MUST COME FROM THE BASE BRANCH, NOT FROM THE BRANCH IT IS JUDGING.
#
# This used to `import guard` off `Path.cwd()/factory`, which in a validate run is the
# PULL REQUEST'S OWN CHECKOUT. So the code deciding whether a PR may touch protected
# files was code the PR could edit, and the whole protected-path mechanism -- the thing
# that makes merging without review defensible -- was self-referential.
#
# It is exploitable in one commit, and was demonstrated: a branch that set UNIT_CHECKS
# to 1 in the protected ratchet AND changed `if violations:` to `if False:` in guard.py
# printed
#
#     BLOCK  .factory/locks/floor.json
#     BLOCK  factory/guard.py
#     PROTECTED_OK
#
# and exited 0. It SAW both violations, reported them, and waved itself through, and
# `PROTECTED_OK` is a required marker so everything downstream was satisfied.
#
# The workflow already reads GOVERNANCE from the base branch for exactly this reason
# ("a PR must not be able to weaken the rulebook it is about to be judged against").
# The rulebook was protected and the code enforcing it was not, which is the more
# important half: a rule nothing enforces is a comment.
#
# So the guard is materialised from the base ref into a temp directory and run from
# there. `config._repo_root()` resolves from the CWD, so it still measures the diff in
# THIS worktree -- trusted code, untrusted subject, which is the right way round.
_guard_dir = Path(tempfile.mkdtemp(prefix="df-base-guard-"))
_names = subprocess.run(
    ["git", "ls-tree", "--name-only", base, "factory/"],
    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
)
_materialised = 0
for _entry in (_names.stdout or "").splitlines():
    _entry = _entry.strip()
    if not _entry.endswith(".py"):
        continue
    _blob = subprocess.run(
        ["git", "show", f"{base}:{_entry}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if _blob.returncode != 0:
        continue
    _dest = _guard_dir / Path(_entry).name
    _dest.write_text(_blob.stdout, encoding="utf-8")
    _materialised += 1

if not (_guard_dir / "guard.py").exists():
    # FAIL CLOSED. Being unable to obtain the trusted guard is not permission to use
    # the untrusted one; that is the whole bug, reintroduced as a fallback.
    tee.write("\nGATE_FAILED: could not materialise the guard from the base branch\n")
    tee.flush()
    note("GUARD_UNAVAILABLE: the base branch's guard could not be read, so nothing was "
         "checked. Refusing to fall back to the branch's own copy.")
    emit({"markers_present": False, "exit_code": 2,
          "summary": "the trusted guard could not be read from the base branch"})
    raise SystemExit(2)

_guard_run = subprocess.run(
    [sys.executable, str(_guard_dir / "guard.py"), "--base", base, "--head", "HEAD"],
    cwd=str(Path.cwd()), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600,
)
guard_rc = _guard_run.returncode
guard_out = (_guard_run.stdout or "") + (_guard_run.stderr or "")
tee.write(f"GUARD_SOURCE base={base} files={_materialised} (trusted, not this branch)\n")
tee.write(guard_out)

if guard_rc != 0:
    tee.write(f"\nGATE_FAILED: guard (exit {guard_rc})\n")
    tee.flush()
    reason = (
        "the change touches a protected path, or exceeds the size or scope cap"
        if guard_rc == 1
        else "the guard could not compute the diff, so nothing was checked"
    )
    note(f"GUARD_BLOCKED: {reason}")
    try:
        state.main(["set", target, "state=rejected"])
        state.comment(
            target,
            "**Factory validation: REJECTED**\n\n"
            f"{reason}\n\n"
            "Auto-reject, no fix attempt (FACTORY_RULES §6). Needing a protected file "
            "touched means the scope was misunderstood, which is a triage decision "
            "rather than a code fix.\n\n"
            "```\n" + guard_out[-2000:] + "\n```",
        )
    except Exception:  # noqa: BLE001
        pass
    issue = None
    try:
        issue = state.linked_issue(target)
    except Exception as e:  # noqa: BLE001
        print(f"ESCALATION_ISSUE_UNKNOWN {target}: {e}. The PR is parked; the issue "
              f"behind it was not, and may sit in-progress with nothing working on it.",
              file=sys.stderr)
    if issue:
        try:
            state.main(["set", issue, "state=needs-human"])
        except Exception as e:  # noqa: BLE001
            print(f"ESCALATION_LABEL_FAILED {issue}: {e}. Recorded in needs-human.md, "
                  f"but the label did not change.", file=sys.stderr)
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
            f"(guard)  {reason}\n"
        )
    note(notify.send(target, f"(guard) {reason}"))
    emit({"markers_present": False, "exit_code": guard_rc, "summary": reason})
    sys.exit(1)

# --- 2. the harness, APPENDED -------------------------------------------------
cmd = config.VALIDATE_CMD
tee.write(f"\nVALIDATE_CMD {cmd}\n")
try:
    p = subprocess.run(
        shlex.split(cmd, posix=(os.name != "nt")),
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=2100,
    )
    out = (p.stdout or "") + (p.stderr or "")
    rc = p.returncode
except subprocess.TimeoutExpired:
    out, rc = f"\nTIMEOUT after 2100s\nGATE_FAILED: timeout\n", 124
except OSError as e:
    out, rc = f"\ncould not run {cmd!r}: {e}\nGATE_FAILED: launch\n", 127

tee.write(out)
tee.write(f"\nVALIDATE_EXIT={rc}\n")
tee.flush()

log = gate_log.read_text(encoding="utf-8", errors="replace")
missing = [m for m in config.REQUIRED_MARKERS if m not in log]
present = not missing

if not log.strip():
    # EMPTY IS NOT PASS, applied to the log itself. A validate command that produced
    # no output at all did not run, and "did anything fail?" would read that as
    # success.
    summary = "the validation run produced no output at all"
elif missing:
    summary = "missing markers: " + " ".join(missing)
else:
    summary = f"all {len(config.REQUIRED_MARKERS)} required markers present, harness exit {rc}"

note(f"GATE_RUN_DONE {summary}")
emit({"markers_present": present, "exit_code": rc, "summary": summary})
