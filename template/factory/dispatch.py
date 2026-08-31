"""The dispatcher. Component 2, built last on purpose.

    python factory/dispatch.py              dispatch at most MAX_PARALLEL things, exit
    python factory/dispatch.py --dry-run    say what it would do, do nothing

It answers exactly one question -- "what, if anything, should run right now?" --
from a fixed priority order and the labels on GitHub. NO MODEL IS CONSULTED.

That is not a stylistic preference. A model asked "what work is pending?" will
invent dispatches for issues that were never filed and PRs that do not exist. It is
a plausible-sounding answer with nothing behind it, and the factory then acts on it.
The dumbest component in the system is the one where a wrong answer is worse than no
answer.

NOTHING PUSHES. Filing an issue does not trigger a run. There is no webhook and
there is not meant to be one: a scheduler wakes on a timer, reads the state, and
dispatches. An issue filed at 09:01 waits for the next tick. A push trigger that
breaks fails SILENTLY and looks exactly like a factory with nothing to do; a poll
that breaks is a poll you can see not running.

From cron, once the dial is above 0. Slower than feels right:
    */30 * * * * cd /path/to/repo && python factory/dispatch.py >> factory.log 2>&1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import notify  # noqa: E402
import state  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

DRY_RUN = "--dry-run" in sys.argv

# Every action, and the dial level it requires. The dial is enforced HERE, in code,
# rather than documented in a file -- raising it is then a deliberate act rather
# than a note nobody read.
REQUIRES_LEVEL = {
    "implement": 1,
    "fix": 1,
    "validate": 2,
    "merge": 3,
    "triage": 4,
}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}", flush=True)


def ledger(target: str, why: str) -> None:
    config.NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with config.NEEDS_HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {target}  "
            f"(dispatcher)  {why}\n"
        )


def escalate(target: str, why: str) -> None:
    """Park it, record it, tell someone. All three, or it is not an escalation."""
    log(f"ESCALATE {target}: {why}")
    if DRY_RUN:
        return
    try:
        state.set_state(target, "needs-human")
    except Exception as e:  # noqa: BLE001
        log(f"  (could not label {target}: {e})")
    ledger(target, why)
    # AND THE ITEM BEHIND IT. A PR parked at needs-human whose issue still reads
    # `in-progress` is an escalation nothing can see: `next` moves on to unrelated
    # work while the escalated issue sits in a state that means "being worked on"
    # with nothing working on it.
    try:
        if target.startswith("gh:pr:"):
            issue = state.linked_issue(target)
            if issue:
                state.set_state(issue, "needs-human")
                ledger(issue, f"its PR {target} escalated: {why}")
    except Exception:  # noqa: BLE001
        pass
    log(notify.send(target, why))


# --- locks --------------------------------------------------------------------
# Labels are good shared state and a BAD LOCK. There is no compare-and-swap: two
# dispatchers reading `factory:accepted` both claim the issue, because read-then-
# write is not atomic and nothing in the API makes it so. So the mutex lives here,
# on disk, per (workflow, target) pair.


def lock_path(action: str, target: str) -> Path:
    key = f"{action}-{target}".replace("/", "-").replace(".", "-").replace(":", "-")
    return config.LOCKS_RUNTIME / f"{key}.lock"


def acquire(path: Path) -> bool:
    """Atomically, or not at all.

    `if not exists: write` is a time-of-check-to-time-of-use race, and it is not
    theoretical: two dispatchers started in the same second both pass the test and
    both dispatch on the same PR, so two runs edit one worktree and the second
    judges a tree the first is still writing. Reachable whenever a tick outlives the
    cron interval, or a human runs the dispatcher while cron fires.

    O_EXCL makes exactly one of the racers the winner.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    return True


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def reap_locks() -> None:
    """Reap dead locks BEFORE counting capacity.

    THE WEDGE THIS REMOVES, and it is the most likely one on a real machine. The
    lock is released when the dispatch finishes. It is NOT released when the process
    is KILLED: a reboot, the machine sleeping, a power cut, someone closing the
    terminal, the OOM killer. The lock file then survives its owner, counts toward
    capacity forever, and every subsequent tick logs "at capacity, nothing
    dispatched" and exits 0 -- indistinguishable from a factory with nothing to do,
    which is the one failure mode this whole system exists to avoid.

    Two tests, and BOTH must hold before an early reap, because PIDs are reused: the
    owning process is gone, AND the lock has had GRACE minutes to become real. A
    live long lap is never touched, because its PID is alive -- that is the check
    that matters, and age is only the fallback for when the PID cannot be read.
    """
    config.LOCKS_RUNTIME.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for lock in config.LOCKS_RUNTIME.glob("*.lock"):
        try:
            age_min = (now - lock.stat().st_mtime) / 60
            first = lock.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except (OSError, IndexError):
            continue
        if age_min > config.LOCK_STALE_MINUTES:
            log(f"LOCK_REAPED {lock.name} - older than {config.LOCK_STALE_MINUTES}m, so its run is gone. Held since: {first}")
            lock.unlink(missing_ok=True)
            continue
        if age_min > config.LOCK_GRACE_MINUTES:
            head = first.split(" ")[0]
            if head.isdigit() and not pid_alive(int(head)):
                log(f"LOCK_REAPED {lock.name} - its process ({head}) is gone and the lock is over {config.LOCK_GRACE_MINUTES}m old")
                lock.unlink(missing_ok=True)


def in_flight() -> list[Path]:
    config.LOCKS_RUNTIME.mkdir(parents=True, exist_ok=True)
    return sorted(config.LOCKS_RUNTIME.glob("*.lock"))


# --- dispatch -----------------------------------------------------------------

WORKFLOW_FOR = {
    "triage": config.WORKFLOW_TRIAGE,
    "implement": config.WORKFLOW_IMPLEMENT,
    "fix": config.WORKFLOW_FIX,
    "validate": config.WORKFLOW_VALIDATE,
}

# Which actions need their own git worktree. Triage is advisory -- it reads the
# repo, writes a label and a comment, and never touches the checkout -- so giving it
# a worktree buys nothing and costs a checkout on every untriaged issue. Everything
# that edits or checks out a branch gets isolation.
NEEDS_WORKTREE = {"implement", "fix", "validate"}


def dispatch(action: str, target: str) -> bool:
    """Hand ONE unit of work to Archon, detached, and return.

    The dispatcher never waits: a tick that blocks for twenty minutes is a tick that
    overlaps the next one. Archon owns the run from here; the labels are how we find
    out what happened.
    """
    workflow = WORKFLOW_FOR[action]
    branch = f"factory/{action}-{target.replace('gh:', '').replace(':', '-')}"
    lock = lock_path(action, target)

    if DRY_RUN:
        if lock.exists():
            log(f"DRY-RUN would SKIP {action} {target} - already in flight")
            return False
        where = f"branch {branch}" if action in NEEDS_WORKTREE else "in place (no worktree)"
        log(f"DRY-RUN would dispatch: {workflow} {target} ({where})")
        return True

    if not acquire(lock):
        log(f"SKIP {action} {target} - already in flight")
        return False

    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    logfile = config.RUNS_DIR / f"{action}-{target.replace(':', '-')}.log"

    cmd = [config.ARCHON_BIN, "workflow", "run", workflow]
    if action in NEEDS_WORKTREE:
        cmd += ["--branch", branch]
    else:
        cmd += ["--no-worktree"]
    cmd += ["--detach", f"{action} {target}"]
    log(f"DISPATCH {workflow} {target} -> {logfile.name}")
    try:
        with logfile.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.now(timezone.utc).isoformat()} {' '.join(cmd)}\n")
            fh.flush()
            p = subprocess.run(
                cmd,
                cwd=str(config.ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=300,
                env={**os.environ, "IS_SANDBOX": "1"},
            )
    except (OSError, subprocess.SubprocessError) as e:
        lock.unlink(missing_ok=True)
        escalate(target, f"could not dispatch {workflow}: {e}")
        return False

    # THE RUNNER'S EXIT STATUS IS NOT THE WORK'S VERDICT, and it must still be read.
    # A dispatch that could not even start is a fault in the machinery, and it looks
    # exactly like a factory with nothing to do unless somebody says so.
    if p.returncode != 0:
        lock.unlink(missing_ok=True)
        tail = ""
        try:
            tail = logfile.read_text(encoding="utf-8", errors="replace")[-600:]
        except OSError:
            pass
        escalate(
            target,
            f"{workflow} could not be dispatched (exit {p.returncode}). Last output: {tail[-300:]}",
        )
        return False

    # Detached: Archon owns it now. The lock is released by the run's own completion
    # hook, or reaped by age/PID above -- deliberately NOT here, because returning
    # from a detached launch does not mean the work finished.
    log(f"DISPATCHED {workflow} {target} (detached; lock {lock.name} held until the run settles)")
    return True


def release_settled_locks() -> None:
    """A lock whose run is no longer in Archon's active list is a lock to release.

    Detached runs outlive this process, so the lock cannot be released by the
    dispatch that took it. Asking Archon what is still running is the honest test,
    and it degrades safely: if the question cannot be answered, the age/PID reaper
    above still frees the lock eventually.
    """
    locks = in_flight()
    if not locks:
        return
    try:
        out = subprocess.run(
            [config.ARCHON_BIN, "workflow", "runs", "--json"],
            cwd=str(config.ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        if out.returncode != 0:
            return
        payload = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return

    runs = payload.get("runs", payload if isinstance(payload, list) else [])
    active_branches = {
        (r.get("branch") or r.get("worktreeBranch") or "")
        for r in runs
        if str(r.get("status", "")).lower() in ("running", "pending", "paused", "queued")
    }
    for lock in locks:
        # The lock name encodes the target; the branch encodes it the same way.
        stem = lock.stem  # e.g. validate-gh-pr-14
        target_part = stem.split("-", 1)[1] if "-" in stem else stem
        if not any(target_part in b for b in active_branches if b):
            log(f"LOCK_RELEASED {lock.name} - no active Archon run holds it any more")
            lock.unlink(missing_ok=True)


def main() -> int:
    # =========================================================================
    # 1. THE STOP BUTTON. Checked first, every time, before anything else is read.
    # =========================================================================
    stopped, why = state.stop_requested()
    if stopped:
        log(f"STOPPED: {why}. Remove it to resume.")
        return 0
    log(f"STOP_CHECK ok ({why})")

    # =========================================================================
    # 2. RECONCILE ON ENTRY. A sweep, not a dispatch, and it runs on EVERY tick.
    # =========================================================================
    # A stalled item is not work to schedule against other work -- it is a fault to
    # report. Doing it as a case in the priority order below was wrong in a way only
    # running it showed: `next` answers with ONE thing, so a single untriaged issue
    # at a dial below 4 outranks the stall forever. The tick then logs a HOLD and
    # exits 0: nothing dispatched, nothing escalated, and a dead PR invisible behind
    # a queue that could not move either. Two wedges, each hiding the other.
    #
    # So it is reported unconditionally, before the dial and before the capacity
    # check, and it never consumes the tick's dispatch budget.
    release_settled_locks()
    reap_locks()
    held = {p.stem for p in in_flight()}

    if not DRY_RUN:
        for pr in state._list("prs", "validating"):
            key = f"validate-{pr['_target']}".replace(":", "-")
            if key in held:
                log(f"IN_FLIGHT {pr['_target']} is 'validating' and a run still holds its lock")
                continue
            escalate(
                pr["_target"],
                "left in 'validating' with no run holding it; a validation died between "
                "the tripwire and the verdict",
            )
        for issue in state._list("issues", "in-progress"):
            key = f"implement-{issue['_target']}".replace(":", "-")
            if key in held:
                continue
            referenced = False
            for pr in state._list("prs"):
                try:
                    if state.linked_issue(pr["_target"]) == issue["_target"]:
                        referenced = True
                        break
                except Exception:  # noqa: BLE001
                    pass
            if not referenced:
                escalate(
                    issue["_target"],
                    "left in 'in-progress' with no PR record and no run holding it; an "
                    "implement lap died before it opened one",
                )

    # =========================================================================
    # 3. THE AUTONOMY DIAL.
    # =========================================================================
    if config.AUTONOMY < 1:
        action, target, why = state.next_action()
        log("AUTONOMY=0: nothing dispatches. Set FACTORY_AUTONOMY=1 when a lap has been proven by hand.")
        log(f"  would run: {action} {target} ({why})")
        return 0

    # =========================================================================
    # 4. CONCURRENCY.
    # =========================================================================
    running = in_flight()
    if len(running) >= config.MAX_PARALLEL:
        log(f"at capacity ({len(running)}/{config.MAX_PARALLEL}), nothing dispatched")
        log("  held by: " + " ".join(p.name for p in running))
        log(f"  a lock with no running workflow is reaped after {config.LOCK_STALE_MINUTES}m")
        return 0

    # =========================================================================
    # 5. PRIORITY ORDER. Load-bearing: finish in-flight work before starting new.
    # =========================================================================
    # THE LOOP EXISTS SO MAX_PARALLEL MEANS SOMETHING. `next` names ONE thing, and a
    # target already in flight would otherwise consume the whole tick: ask, get the
    # head of the queue, find its lock taken, stop. A knob that silently does
    # nothing is worse than one that is not offered. Targets that could not be
    # locked are EXCLUDED and the question is asked again, so the priority order
    # still lives entirely in state.py.
    exclude: set[str] = set()
    slots = max(1, config.MAX_PARALLEL - len(running))

    while slots > 0:
        slots -= 1
        action, target, why = state.next_action(exclude)

        if action == "idle":
            log("nothing to do")
            break

        needed = REQUIRES_LEVEL.get(action)
        if needed is not None and config.AUTONOMY < needed:
            log(f"HOLD {action} {target} - requires autonomy >= {needed}, currently {config.AUTONOMY}")
            if action == "merge":
                log("  The PR passed every gate and is waiting for a human. This is level 2 working.")
            break

        if action in ("fix", "validate", "implement", "triage"):
            log(f"NEXT {action} {target} ({why})")
            dispatch(action, target)
            exclude.add(target)
            continue

        # Everything below is a decision about the whole queue, made once.
        slots = 0

        if action == "escalate":
            escalate(target, f"fix-attempt cap reached (FACTORY_RULES 8): {why}")

        elif action == "merge":
            log(f"MERGE {target}")
            if DRY_RUN:
                continue
            rc = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "merge.py"), target],
                cwd=str(config.ROOT),
            ).returncode
            if rc == 0:
                deploy = Path(__file__).parent / "deploy.py"
                if deploy.exists():
                    subprocess.run([sys.executable, str(deploy)], cwd=str(config.ROOT))
            elif rc == 2:
                # ALREADY HANDLED. The branch went stale while it was in flight --
                # somebody pushed to main, which on any repo with velocity is Tuesday
                # -- and merge.py requeued it for revalidation, which is the designed
                # remedy. Escalating on top would send it straight to needs-human,
                # which is TERMINAL for nodes: a recovery that undid itself, and a
                # person woken for a situation the factory had already resolved.
                log(f"REQUEUED {target} - the branch was behind base; it will be rebased and re-judged")
            else:
                # Everything else: merge.py printed the reason and could not recover.
                escalate(target, "merge refused for a PR that passed every gate; see the log above")

        elif action in ("stalled-pr", "stalled-issue"):
            # Reported by state.py, acted on here -- only the dispatcher holds the
            # runtime lock and can tell "still running" from "died". The reconcile
            # sweep above has usually handled it; reaching here means it did not.
            log(f"STALLED {target} ({why}) - handled by the reconcile sweep on the next tick")

        else:
            log(f"UNKNOWN action '{action}' from state.py - refusing to guess")
            return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except state.GhError as e:
        # The dispatcher is the scheduled entry point. Nothing supervises it: cron
        # starts it, it exits, and the exit code goes nowhere anyone looks. So a
        # failure here does not lose one workflow, it loses THE WHOLE TICK -- and a
        # factory that has been dead for a week looks exactly like a factory with
        # nothing to do. Make the ending say why, and tell a human.
        log(f"DISPATCHER_FAULT: {e}")
        ledger("dispatcher", f"the dispatcher itself failed: {e}")
        log(notify.send("dispatcher", f"the dispatcher itself failed: {e}"))
        sys.exit(1)
