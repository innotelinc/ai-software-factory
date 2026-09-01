# Incidents

Every rule in this repository exists because something broke. This is the list, so
that a factory rebuilt from the design alone does not rediscover all of it,
unattended, in production.

Read it if you are about to "simplify" something. Most of what looks like paranoia
here is a scar.

---

## Found while building this factory

### The merge that armed a revert in your checkout, every single time

**The worst one here, and it left no error behind.**

**What happened.** After an unattended merge, `git status` in the main checkout showed
the merged work as **staged deletions**. The index and the working tree still held the
commit *before* the merge, while `HEAD` had moved to the merge itself. Any `git commit`
in that state — by a human, for any reason — commits a revert of what just landed.

It did. A `git add -A && git commit` 74 seconds after a merge wiped a feature and 106
lines of its tests. The push succeeded. Nothing failed. I diagnosed it as my own bad
habit, wrote it up that way, and only found the real cause when the *same desync*
appeared after the next merge — with my hands nowhere near it.

**The cause.**

```python
if current == BASE_BRANCH:  git("merge", "--ff-only", ...)   # safe, almost never taken
else:                       git("update-ref", "refs/heads/main", "origin/main")
```

`update-ref` moves a branch pointer and touches neither the index nor the working tree.
When nothing has that branch checked out, that is exactly right. **The main checkout
always has the base branch checked out.** And `merge.py` runs from a validation
worktree, where the current branch is the validation branch — so the `else` was taken
on *every* merge, and the safe branch above essentially never ran.

**The rule.** Ask who has the branch checked out (`git worktree list --porcelain`,
which is the only source that knows about the checkout this process is not running
in), and fast-forward it **in its own checkout** so ref, index and files move together.
`git merge --ff-only` refuses when that tree has local changes, and refusing is the
right answer: leaving somebody's edits alone is strictly better than desynchronising
their repository behind their back. `update-ref` only when the branch is checked out
nowhere.

**Two things generalise.**

First: **a habit that triggers a trap is not the cause of the trap.** The first write-up
of this blamed `git add -A` and shipped a doctor check for a stale checkout. That check
is worth having, but it was treating a symptom, and it would have gone on treating it.

Second: unknown takes the safe path. If the worktree list cannot be read,
`worktree_holding` returns the main checkout rather than `""` — because being wrong
that way prints a note, and being wrong the other way silently arms a revert.



These are from the build itself — the first laps against a real repository, a real
GitHub, and a real workflow engine.

### The node that was blamed for a bug two nodes upstream

**What happened.** `gate-plan` failed with

```
'$preflight.output.target' references field 'target', but node 'preflight's output
is not a JSON object
```

`preflight` had run, done its job correctly, and exited 0. It also printed one
friendly line — `PREFLIGHT_OK secrets_ignored=4` — before its JSON payload, which
made the payload unparseable. The error surfaced on the *consumer*, so the first place
anyone looks is the file that is not broken.

**What made it worse.** The obvious fix — rewrite every `print()` in `preflight.py` —
did not work, and the reason is the interesting half: **the polluting line was not in
the script.** It came from `guard.preflight()`, a library function doing exactly the
right thing, printing a marker the gate greps when the guard runs as a CLI. Two
callers, two correct-but-incompatible meanings for one stream.

**The rule.** `factory/nodeio.py`. Importing it redirects `sys.stdout` to `sys.stderr`
for the whole process; `emit()` writes to the real stdout captured at import. Every
library a node imports is then safe by construction, **including ones written later by
someone who has never read that file.** A convention you have to remember is a
convention that fails on the day you are busy.

### The fix that was applied twice and never landed

**What happened.** After fixing the above, the same failure reproduced exactly. The
files on disk looked right. `git status` said clean.

`cp -r src/. dst/` on Git Bash for Windows reports success and leaves the destination
untouched. Two rounds of a genuine fix were lost to a copy that said it had worked.

**The rule.** `bin/sync-to.py` compares content, copies only what differs, and prints
what it changed. A sync that did nothing says so. Never trust a copy you did not
verify — especially the one that carries a fix into the place the fix is needed.

### The mutation that escaped, and the property that was too weak

**What happened.** The mutation set went 9/10. The escapee made the store return only
the *first* expense of a group (`LIMIT 1`), and it sailed through a holdout scenario
that recorded five expenses and asserted the balances summed to zero.

Because **one expense's balances sum to zero exactly as five do.** "Sums to zero" is a
property that holds for any *subset*, so a check that only asserts the property cannot
see work disappearing.

**The rule.** The holdout asserts the exact hand-computed figures, not the property.
Numbers derived independently, on paper, from the inputs — which is what makes it a
specification rather than a mirror of the implementation. And the mutation runner is
what found it: no amount of reading those assertions would have.

### Every rung green, one rung never shown to fail

**What happened.** The first complete mutation set scored 10/10 with six defects caught
`by unit`, one `by holdout`, one at app start — and **zero by the end-to-end rung.**
The number read as "the gate can fail". All it meant was "the unit suite can fail".

`ci.py` stops at the first red rung, so a defect that any earlier rung also catches
never exercises the later ones.

**The rule.** `defects.json` documents the intended rung per defect, the runner prints
which rung caught each one, and the file says plainly: if the column collapses onto
one rung, the set has stopped measuring what it was built to measure. A defect was
added aimed only at HTTP status semantics, which no unit test goes near.

### The gap that was stated instead of faked

Tally has a screen, and its mutation set has no *presentation* defect — a colour that
stops tracking state, an element that stays visible, a width pinned rather than
derived.

That rung does not exist, because the harness drives HTTP and not a browser. A defect
aimed at it would report ESCAPED and be telling the truth.

**The rule.** The gap is written down in `defects.json` rather than papered over.
Adding a browser rung is the work that closes it; a defect nothing can catch is worse
than the gap, because it turns an honest zero into a false alarm.

### A database that could not be locked, and a test suite that could not be trusted

**What happened.** Twenty-seven passing tests, fifteen errors on teardown:
`PermissionError: the process cannot access the file because it is being used by
another process`. `sqlite3`'s connection context manager commits or rolls back and
does **not** close the handle. On Linux nothing notices.

**The rule.** Wrap it. And note what the failure looked like: a permission error naming
a temp path, which explains nothing about connection lifetimes.

### The suite that could not run where it had to run

**What happened.** The global Python had a broken plugin registered with pytest, so
`python -m pytest` failed at import — in a repository with no pytest dependency of its
own.

The deeper problem was the one that decided the design: **the mutation runner copies
the project into a throwaway directory and runs the whole gate there with nothing but
the interpreter.** A suite that needs a project virtualenv cannot run in that copy —
and a mutation that could not run gets reported as a defect that escaped, which is the
most misleading number this system can produce.

**The rule.** Tally is stdlib-only and uses `unittest`, and `MISSION.md` makes that an
invariant with the reason attached rather than a preference.

---

### The empty answer that was read as a negative answer

**What happened.** The factory found its own regression, filed issue #6 about it,
triaged it critical, and dispatched an implement lap. Seventy-five seconds later the
next tick escalated that issue to `needs-human`:

```
ESCALATE gh:issue:6: left in 'in-progress' with no PR record and no run holding it;
                     an implement lap died before it opened one
```

The lap had not died. It ran for another twenty minutes and finished.

**The cause.** A detached run outlives the process that launched it, so the lock it
holds cannot be released by that process, and its PID proves nothing — it exits
immediately. `release_settled_locks()` therefore asked the engine what was still
running and matched the answer against each lock. It matched on **branch name**, and
the engine populates no branch in that payload. Every entry came back blank, the
blanks were filtered out as junk, and each lock was compared against an empty set.
`any()` over an empty set is `False`, so the conclusion was "no run holds this" — for
every lock, one tick after it was taken, unconditionally.

The reconcile sweep then did its job perfectly on a false premise: an item
`in-progress`, no PR, no lock. That is exactly what a died lap looks like.

Worth noticing what this cost *before* it was understood: it also produced
`could not move gh:pr:5 to 'validating'` earlier in the same build — two validations
racing for one PR, because the lock meant to stop that had already been dropped. One
bug, two symptoms, and neither of them looked like a locking problem.

**The rule.** **An empty answer is not a negative answer.** This is the same
"empty is not pass" the gate is built around, and it is easier to violate in the
machinery than in the harness, because nothing here has a marker to count. Every
unknown must keep the lock:

- The run list came back unreadable, empty, or with no usable ids → **keep**.
- This run id is not in the reported window → **keep**. Absence from a truncated list
  is not evidence a run ended.
- The status is one this engine has never been seen to emit → **keep**. Unknown means
  still running.
- Only a run id the engine positively reports as `completed` / `failed` / `cancelled`
  releases anything.

The costs are not symmetric, and that is the whole argument: a lock held too long
stalls one target until the age reaper frees it, and a lock dropped too early runs two
writers over one worktree and escalates work that was going fine.

**And match on an identifier both sides agree on.** The branch was never a shared
identifier; it was a name this code invented and hoped the engine would echo back. The
run id is printed by the dispatch and recorded on the lock, so the question asked is
about the same object the answer is about.

### The hold that was only a sentence

**What happened.** A lap ran cleanly and unattended: issue triaged, PR opened, gate
green, merged, issue closed. Reading the PR afterwards, the gate's own comment said:

```
## Factory Gate: PASS, merge HELD
Auto-merge is held because: ratchet slack (unit_tests+10); 63 recorded assumption(s).
```

It was merged forty-five seconds after that comment was posted.

**The cause.** The hold was a sentence. `gate.py` computed `automerge = False`,
composed a careful explanation, posted it — and then set the PR's state to `passed`,
because that is what a PR that passed every check is called. The dispatcher reads
states, not prose. `passed` is exactly what it merges.

**The most subtle gate in the system was defeated by the most obvious one**, and the
result looked like a clean unattended lap. Nothing errored, nothing escalated, and the
only trace was a comment nobody had to read.

Worth noting how it survived earlier testing: every previous hold happened while a
human was driving the workflows by hand. The hold was never once put in front of a
running dispatcher until the factory was left alone.

**The rule.** A hold is a **state**, not a message. `held` has its own label, is
reachable only from `validating`, and leaves only through `open` — which no node may
do, so a human raising the floor or accepting the assumptions is the single way
forward. `next_action` has no branch for it, so the factory carries on with other work
and the PR waits, which is the whole intent: a hold does not stop the factory, it stops
that merge.

And it gets its own line in `darkfactory status`. A hold is the one outcome that is
neither a failure nor an escalation — nothing is wrong — which makes it the easiest
thing in the system to never look at.

### Two laps for one issue, stopped by a lock that happened to still be held

**What happened.** PR #13 was held on ratchet slack. The very next dispatcher tick
answered:

```
NEXT implement gh:issue:12 (highest-priority accepted issue (medium))
```

That is the issue PR #13 was for. A second implement lap started, on a second branch,
for work that was already built and waiting on a person.

**Why it only nearly happened.** The validation's lock was still held, so the duplicate
could not take a slot on the tick I was watching — and then it did, one tick later,
once that lock cleared. The run was live for 58 seconds before I cancelled it. The
thing that "prevented" it the first time was a lock timing coincidence, which is luck
rather than a mechanism.

**The cause.** `next_action` selects an issue on its label alone, and `accepted` is
reachable while a PR for that issue is open — a person accepting an issue somebody
already built, or an issue walked back from `in-progress` after its PR opened. The
reconcile sweep already asks exactly this question about `in-progress` issues, using
`linked_issue`. The selection path did not ask it at all, so the two disagreed.

**The rule.** An issue that a live pull request already answers is not work. Same
question, same helper, both places — and once that PR is merged or rejected, the issue
is selectable again, which the self-test checks in both directions, because a filter
that is too broad strands the issue instead of duplicating it.

### The staleness check that called an unanswered question "current"

**What happened.** The check added *the same afternoon* to catch a stale checkout read:

```python
if rc_fetch == 0 and rc_count == 0 and behind > 0:  ...stale...
else:                                               ...OK, "level with origin/main"...
```

A failed fetch — offline, no remote, a branch that does not exist — took the `else`.
It printed **"checkout is current"** about a tree it had not compared to anything.

**Why this one is worth its own entry.** It is the exact failure this entire system is
built to prevent, written by someone who had spent the day fixing instances of it, into
the check whose whole purpose is catching it. "Did the comparison say we are behind?"
and "did the comparison happen?" are different questions, and collapsing them is the
default shape of an `if/else`.

**The rule.** Three branches, never two: **behind**, **level**, and **could not tell**.
Any check with a network call, a subprocess, or a parse in it has a third answer, and
the language will happily let you write only two.

### The default branch that was assumed, in a product whose pitch is "install it into your repo"

**What happened.** `main` was a string literal in a dozen places across the merge and
the deploy poller — `base = "origin/main"`, and a merge that refused any pull request
whose base was not literally `"main"`.

On a repository using `master`, or `develop`, or a release branch, this installs
cleanly, the doctor goes green, laps run, pull requests open — and every merge is
refused, forever, for a reason that reads like a configuration mistake. That is the
worst shape a bug can take in something sold as "install it into your repo".

**The rule.** `config.BASE_BRANCH`, read from `origin/HEAD` — what the remote itself
says its default is, which is the only answer that is not a guess — with
`FACTORY_BASE_BRANCH` to override and `main`/`master` probes as fallbacks. `bin/audit.py`
fails on a bare `'main'` literal anywhere in the machinery.

### The setting that could never reach an existing install

**What happened.** `BASE_BRANCH` was added to `config.py`, four modules were synced to
use it, and the sync reported success. The doctor then died:

```
AttributeError: module 'config' has no attribute 'BASE_BRANCH'
```

**The cause, and it is structural.** `factory/config.py` is on the sync's NEVER list
*because* it is the one file you edit — every project-specific value lives there and
overwriting it would throw them away. The consequence is not obvious until it bites: a
new setting can never reach an existing install, and the synced code that reads it
raises at runtime, on whatever path happens to touch it first.

**The rule.** The sync diffs the template's config against the target's and prints the
settings that are missing, with the code that defines them, for the operator to paste.
The file stays theirs; it is no longer allowed to be silently incomplete.

**And report what a setting DEPENDS on.** The first version listed
`BASE_BRANCH = _base_branch()` and nothing else — an instruction to paste a line into a
file with no `_base_branch` in it, turning an AttributeError into a NameError. A
setting is not portable without whatever computes it.

### The armed factory that never re-tested anything

**What happened.** `darkfactory arm` on Windows printed `ARMED`, created the scheduled
task, and the doctor reported `trigger armed: scheduled`. Everything agreed the factory
was running.

The **regression was never scheduled.** The cron backend installs two entries — the
dispatcher every thirty minutes and the weekly re-test of what already merged. The Task
Scheduler backend installed one, and returned success.

**So a Windows factory could be fully armed, fully green, and never once re-test its own
merged code** — the component whose entire job is noticing that something that used to
work stopped working simply was not there. And nothing reports a job that was never
created, so the only symptom is bugs not being found, which is indistinguishable from
there being none.

This is the "a fully built factory with nothing scheduled audits identically to a
running one" failure that the trigger check exists to prevent — reproduced one level
down, inside the thing that installs the trigger.

**The rule.** Both backends install both jobs, `remove()` deletes both, and
`bin/audit.py` checks the parity, because a missing scheduled job leaves no trace to
find at runtime.

**A note on how the check itself first failed.** It grepped the raw function text for
the regression, and a build with the call *deleted* still passed — the comment above
the call explained what it was for, and the grep matched the explanation. A check that
its own rationale satisfies is a check that cannot fail. It now reads the code with
comments and docstrings stripped, which is the same repair the lock-liveness check
needed, for the same reason.

### The race that was finally run, by accident

**What happened.** Two dispatcher loops ran against the same repository for
forty-five minutes, because an earlier one was never stopped. Every unit of work was
dispatched exactly once — triage, validation and the merge by one loop, the
implementation by the other, no duplicates and no overlap.

**Why it is worth writing down.** The O_EXCL lock exists for precisely this, and
nothing had ever tested it. `acquire()` uses `O_CREAT | O_EXCL` rather than
`if not exists: write` because the latter is a time-of-check-to-time-of-use race that
is entirely reachable — a tick that outlives the cron interval, or a human running the
dispatcher while the schedule fires. That argument was sound and completely
unevidenced until two loops collided by mistake.

**The lesson is about the evidence, not the lock.** Every other guarantee in this
system was tested by deliberately breaking something. This one was tested by an
accident, which is the only reason it has any evidence at all — and it is worth asking,
of every remaining "this cannot happen because", whether anything has ever made it try.

### The closing keyword that was formatted as code

**What happened.** A lap finished perfectly: PR merged, issue labelled `factory:done`.
The issue was still **open**.

**The cause.** The PR body said `` `Fixes #10` `` — with backticks. GitHub does not
treat a linkage keyword inside a code span as a closing reference, so it did nothing.
The previous PR had written `Fixes #8.` in plain prose and closed correctly.

Nothing errored. And the label made it worse rather than better: `factory:done` on an
open issue reads as finished on every board a person would look at.

**The rule.** A step that must happen does not depend on somebody else's markdown
parser agreeing with an agent's formatting. `set_state(issue, "done")` closes the issue
itself. `Fixes #N` stays in the body because it makes the PR readable; it is no longer
what does the work.

**The general shape**, and it is the third time it appears in this list: a load-bearing
step delegated to prose. The judge's verdict thrown away over an enum, the hold written
as a comment, and now the close written as a keyword — each time the mechanism was a
sentence, and each time the failure looked like success.

### The reaper whose docstring explained why it was safe, in a system where that was false

**What happened.** With the lock-release path fixed, an implement lap was escalated as
dead again — at 5 minutes 39 seconds, while it was running, and it ran on to open a
pull request. This time the run list was answering correctly: it said `running`. The
lock was gone anyway.

**The cause.** The *other* reaper. `reap_locks()` frees a lock when "the owning process
is gone AND the lock is older than GRACE", and its docstring said:

> A live long lap is never touched, because its PID is alive — that is the check that
> matters, and age is only the fallback for when the PID cannot be read.

**That sentence is false for every dispatch this system makes.** Dispatch is detached:
`archon workflow run` hands the work to a child and returns in seconds, so the recorded
pid is dead almost immediately while the run has another twenty minutes to go. The pid
test never protects anything. `GRACE` was the only thing standing between a live lap
and the reaper, and almost every implement lap is longer than five minutes.

**The rule.** The pid on the lock is the *dispatching* process, not the run. It is
meaningful for exactly one case: a lock that names **no run**, meaning the dispatch
died before it could record one — there the pid is the only owner there ever was. A
lock that names a run is freed by evidence about *that run*, or by the long stale cap,
which is the backstop for an engine that can no longer be asked.

**The general one is about the comment, not the code.** A docstring asserting the
property that makes something safe is worth more than most tests — right up until the
system changes underneath it and nothing re-reads it. This one described a foreground
dispatch. The code had been detached for a long time.

### The machinery that had a harness for everything except itself

**What happened.** The bug above lived in the file whose entire job is deciding what is
alive. It had no test. Every check in this repository pointed at the product: the
harness proves the software works, the mutation set proves the harness can fail, the
doctor proves the factory was given what it needs. Nothing proved the **factory's own
parts behave as written** — and a dispatcher that mis-decides which laps are alive
produces a repository that looks exactly like a quiet one.

**The rule.** `factory/_selftest.py`, run by the doctor on every audit. Fast, offline,
no GitHub. It pins the invariants that were once wrong in a way that read as normal
operation: an empty run list keeps a lock, an unrecognised status keeps a lock,
`needs-human` is terminal, `passed` does not lead back to `validating`, an empty log
yields no counts, and every state that is not defined by absence has a label.

It was mutation-tested the same day it was written — the original defect was injected
into a throwaway copy and the self-test went red, which is the only reason to believe
any of it can fail at all.

One check earns its place for a different reason: `import config` and
`from factory import config` produce **two module objects with separate state**. The
first draft of the self-test used the second form, so it configured a copy of the thing
it believed it was testing. Every call succeeded and three assertions came back false
for a reason that had nothing to do with the code under test.

### The transition table that governed only the callers that asked

**What happened.** A validation claimed a pull request that had been escalated to
`needs-human` three minutes earlier, moved it to `validating`, and ran. The table says
`needs-human` reaches nothing, and it is the one guarantee written as absolute:
*a node may never move an item out of needs-human.*

**Two causes, and both had to be fixed.**

The enforcement lived in `state.py`'s **command line wrapper**. Eleven callers import
`set_state` and call the function directly — the gate, the merge, the dispatcher — and
every one of them was governed by nothing. The guarantee was opt-in and read as
absolute.

And the check that did run compared against labels the node had read **at the start of
its work**. The escalation happened after that read. No table can fix a decision made
from data that predates the write.

**The rule.** Enforce at the write. `set_state` fetches at the moment it writes, which
is the latest anything can know, and refuses there — so the wrapper and the eleven
importers get the same answer. `force=True` exists for exactly one thing: parking at
`needs-human`, which must be allowed from anywhere, because an escalation a table
lookup can block is not an escalation.

**And the dispatcher must not dispatch what it just escalated.** GitHub does not
promise you read your own write. A tick escalated a PR at 19:21:55 and re-dispatched it
at 19:22:03, eight seconds later, straight back into the state a human had just been
told to look at. `escalate()` now returns every target it parked — the linked issue
included — and the tick excludes them.

### The judge that was thrown away for a word

**What happened.** `error_max_structured_output_retries` — five attempts, fifty-two
seconds of judging, and the run died. `apply` binds to `$judge.output`, a binding never
falls back to `if_skipped` for a *failed* producer, so the one node whose job is to
report an infrastructure failure could not run. A live worktree left behind, a human
paged, and no record of what the judge actually said.

**The rule.** **Constrain only what is branched on.** `factory/gate.py` reads exactly
one field to decide anything: `verdict`. `severity` and `category` reach the PR comment
through `f.get('severity', '?')` and change nothing. Every enum on a field nobody
branches on is a fresh chance *per finding* to fail the whole run for a synonym — eight
of them on a five-finding review. The vocabulary belongs in the prompt, where being off
it costs a slightly worse comment instead of a dead validation.

`verdict` keeps its enum, because a value outside that list has no defined behaviour
and must fail loudly. `issues_to_fix` and `rules_cited` stopped being required: a clean
approval has no findings and invokes no rule, and demanding an empty array as proof of
that is a fifth way to fail.

### Aimed at a rung, landed on another

**What happened.** The mutation set reported 10/10 with defects "aimed at" four rungs.
Two of them were being caught by the **unit** suite: the app-start defect broke a
module-level import that every unit test hits, and the e2e defect flipped a 409 to a
400 that `tests/` asserts directly. Both target rungs were still rungs nobody had ever
seen go red, and the score said nothing was wrong.

**The rule.** The runner reports **which rung caught each defect**, and that column is
the point. Aiming is not landing. A defect aimed at e2e must be invisible to the unit
suite or it measures the unit suite twice.

**And re-aiming found a weak assertion**, which is the part worth keeping. The new e2e
defect replaced the balances table with a bare div and **escaped**: step 1 asked whether
`<table` appeared anywhere in the page, two other tables were still in the markup, and
the check passed while the one screen the product exists for showed nothing.

That is the holdout's "balances sum to zero" failure exactly, one level up: **a property
that holds for a subset is not a check on the whole.** It appears wherever a check is
written as "something like this exists" rather than "this specific thing is here", and
the only thing that finds it is a defect aimed at that rung.

## Inherited from the factory this one was built from

These were paid for by an earlier experiment. They are not hypothetical either.

### The factory that was starved, not broken

Three months of silence. The last merge was in May, main had not moved, and it read as
"it died". It had not: the dispatcher ran every thirty minutes the whole time and
logged `nothing to dispatch` on each tick.

A benchmark run had labelled all seventeen open issues `in-progress` as a deliberate
lockout, and the lockout was never lifted. The factory then correctly found zero work,
forever.

**The rule.** Before concluding an autonomous system is broken, check whether its
*input queue* was closed rather than its machinery. A dispatcher logging "nothing to
do" on a cadence is a healthy dispatcher with an empty queue, and it looks identical
to a corpse from the outside. Anything that deliberately mutates shared state as a
lockout needs an owner and an expiry.

### The correct rejection that reached the filer as two characters

Triage rejected an out-of-scope issue perfectly: right verdict, right label, closed
not-planned, and a written rejection citing two rules by number with an appeal path.

What reached the filer was `@-`.

The reasoning had been assembled in a shell pipeline instead of going through the
comment helper, and on Windows the pipeline collapsed. Every state transition was
right. The call exited 0. The run reported success. The only thing lost was the entire
explanation — the part a human was ever going to read.

**The rule.** Every human-facing write goes through one helper, and the helper reads it
back. `exit 0` from the tool that posted a verdict proves the API call succeeded, not
that it carried anything.

### The lap where every node succeeded and the branch was empty

Every node reported OK. The guard correctly saw two changed files and thirty lines.
The branch ended up with nothing on it: the implement node had edited the worktree, and
the worktree was discarded when the run finished.

Driving the same lap by hand had hidden it completely, because **a human commits
without being told to.**

**The rule.** The commit is a node, and it asserts on the artifact rather than the exit
code. An empty diff fails the lap loudly, with any tool denials attached — because a
denial is the usual cause and correlating them an hour later in a log is not a process.

### The fix loop that could not be reached

One wrong arrow in the transition table — `failed → validating` instead of
`failed → open` — made the entire fix loop unreachable. The fix committed, the illegal
transition returned non-zero, the workflow died on that line, and no escalation ran.
The PR sat in `validating`, which the dispatcher does not look at, so it answered
`idle` from then on.

**The rule.** A factory wedged that way is indistinguishable from a factory with
nothing to do, which is the failure mode this whole system exists to avoid. `open` is
the right target on its own: a fixed PR is a PR waiting to be validated.

### The cap that silently did not apply

The runner passed `--max-turns` to every node. The agent accepted it, ignored it, and
exited 0. Every comment in the codebase claimed a cap was in force. No cap ever
applied, nothing errored, and the only reason it surfaced was somebody running
`--help`.

**The rule.** **A guard that silently does not apply is worse than no guard**, because
you stop watching the thing it was guarding. Verify a flag before writing it into a
workflow, and prefer a spend ceiling to a turn ceiling regardless.

### The lock that outlived its owner

The dispatch lock is released when the run finishes. It is not released when the
process is *killed* — a reboot, a sleeping machine, a closed terminal, the OOM killer.
The lock file survived, counted toward capacity forever, and every later tick logged
`at capacity (1/1), nothing dispatched` and exited 0.

**The rule.** Reap dead locks *before* counting capacity, and use two tests: the owning
process is gone AND the lock has had time to be real. PIDs get reused, and a liveness
check that gets it wrong kills a running lap.

### The stop button that only worked while the network did

"Remove a label to stop" cannot distinguish a missing label from an API call that
failed to list it, so a network blip reads as "carry on".

**The rule.** The stop button is a label you ADD, any error reading it counts as
stopped, and there is a local kill file too — because the local one works with the
network down, which is when you most want it.

### The three-dot diff

`git diff main` compares two *tips*, so a branch cut before main moved reports main's
later commits as this branch's work — and main's later commits routinely touch the
protected paths. Every such branch was auto-rejected for files it never went near: a
false positive in the most severe gate there is, firing more often the longer a branch
lives.

**The rule.** `main...HEAD`, always. Compare against the merge base.

### The escalation that took the success path

A triage run correctly decided `needs-human`, wrote the ledger line, and stopped —
because the notifier was only reached from the *failure* path, and a correct
escalation is not a failure.

Measured: seven probe issues, two correct `needs-human` decisions, **zero
notifications.** The stop list worked perfectly and nobody was told.

**The rule.** Every route into `needs-human` notifies. There are more of them than you
think: the runner, the gate, the fix cap, the dispatcher's stall sweep, and triage
itself.

## The escalation that fed the queue it was supposed to leave

**Symptom.** An unattended loop dispatched `darkfactory-validate` at one pull request
**68 times in three and a half hours**, every tick, each run failing in the same way.
Nothing else in the queue was ever reached.

**What was actually right.** The guard was correct: the PR changed 515 lines against a
500-line cap, so it was rejected on its merits. The gate set the PR to `rejected`,
commented, escalated the issue, and notified. All of that worked.

**The bug.** `PR_STATES` did not contain `needs-human`. `_state_from_labels` skips any
state that is an ISSUE state but not a PR state, so a pull request carrying
`factory:needs-human` fell through the entire table and returned the default: `open`.
`next_action` selects the oldest `open` PR as "awaiting the independent validator".

So escalation wrote the label, and the very next read handed the same PR back to the
dispatcher as fresh work. **The one state that means STOP was the one state that could
not be read back**, and the machine could not see the brake it was pressing.

`TRANSITIONS` had listed `needs-human` as a legal PR destination from the start. Two
tables disagreed, and every test only ever consulted the one that was right.

**Why nothing caught it.** Ten self-test invariants interrogate `TRANSITIONS`. Not one
asked whether a state written as a label reads back as itself. Writing and reading were
each tested against the table; they were never tested against **each other**.

**The fix.** `needs-human` and `held` added to `PR_STATES`, plus a round-trip invariant:
every state, written as its own label, must read back as itself for every kind that
declares it, and every destination reachable from a PR-only state must be declared in
`PR_STATES`.

**The second lesson, which is the sharper one.** The first version of that new check
**went vacuous instead of red**. It asked which kinds a state was declared for and
round-tripped those, so when `needs-human` was missing from `PR_STATES` the PR case was
simply never generated: 118 checks passing rather than 119 failing. A check that
evaporates in exactly the condition it exists to detect is worse than no check, because
it reports success. This is "empty is not pass" reappearing one level up, inside the
harness, and it is why the invariant is now STATED rather than derived from the list it
is auditing. Every new check must be run against the broken code before it is trusted.


## The safety system that fabricated its own evidence

**Found within an hour of shipping the watchdog, by the watchdog's own monitor.**

`factory/_selftest.py` proves the lock logic by driving `release_settled_locks()` with a
synthetic Archon payload. That function had just been instrumented to record a settle to
the ledger, and `ledger.LEDGER` was bound at import to the production path.

So **every `doctor` run appended invented history to the evidence the watchdog judges**:
run id `11111111-2222-3333-4444-555555555555`, alternating `completed`/`failed`, eleven
entries deep before it was noticed.

**Why it is worse than it sounds.** Fake evidence in a safety system turns the safety
system into the hazard. Those settles carried no cost, which is what surfaced it (the
`spend-blind` warning fired), but a slightly different fixture would have tripped
`all-failing` and halted a perfectly healthy factory. Nothing would have looked wrong:
the entries were well-formed, plausible, and written by the factory's own code.

**How it was caught.** Not by a test. The operator-side monitor reported a standing
`spend-blind` warning, and the ledger tail showed a run id no real dispatch could have.
The second layer earned itself on its first hour.

**The fix.** The ledger path resolves per call and is env-overridable; the self-test
redirects it to a temp file for the whole run; and three new invariants pin it: the
redirect must be in place, a recorded event must NOT reach the real ledger, and it MUST
reach the redirected one. That third one matters -- without it the check passes when the
write silently goes nowhere, which is the vacuous-check failure again.

**The general rule.** Instrumenting a function makes every existing caller of that
function a writer, tests included. When you add a side effect to shared machinery, the
question is not "is this correct" but "who else calls this, and do they mean it".


## The watchdog's first act was to halt a healthy factory

One hour after the runaway watchdog shipped, it fired for real:

    [HALT] all-failing: the last 5 settled runs all ended ['not_found'] with no
    completion. Nothing is getting through.

Three pull requests had merged during exactly that window. Nothing was wrong.

**The leak.** `not_found` had been added to `SETTLED_STATUSES` an hour earlier to fix
a different problem: `archon workflow runs --json` reports a window of 20 runs, so a
finished run ages out of it and its lock could not be released, wedging capacity to
zero for 180 minutes. Asking the engine about that run directly and treating
`not_found` as an answer is correct **for the lock question** -- nothing will ever
hold that lock again.

It is not an answer to the **progress** question. There, `not_found` is silence: the
run may have succeeded, failed, or never started. The status leaked from a question
where it means "no" to a question where it means "no idea", and the detector read
silence as failure.

**Why this is worse than a missed detection.** "Empty is not pass" exists because
assuming SUCCESS on no evidence hides defects. The mirror costs more: assuming
FAILURE on no evidence makes the safety system the outage. A watchdog that halts a
healthy factory is one people switch off, and a switched-off watchdog is worse than
one that was never built, because everyone believes it is watching.

**The fix.** `UNKNOWN_STATUSES = {"not_found"}`. All four progress detectors now
require positive evidence -- a settle that reported a real outcome, or a dispatch
whose run can be asked about. The regression is kept, and beside it the half that
must not be disarmed: real `failed` runs still trip the detector. Reintroducing the
exact bug is one of three mutations, all caught.

**What worked.** The halt MECHANISM was correct in every respect: STOP written,
notification sent, loop stopped, and the operator monitor reported it within seconds.
Only the detector's reasoning was wrong. That is the right way round for a first
live failure -- the plumbing is the part that is hard to fix under pressure.

**The generalisation.** A value that answers one question is not thereby an answer to
a neighbouring one. When a sentinel earns its meaning in a specific decision, check
every OTHER decision that reads the same field before adding it to a shared set.
