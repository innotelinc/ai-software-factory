---
description: Address the validator's findings, one at a time, without weakening any check.
argument-hint: (no arguments -- reads $ARTIFACTS_DIR/findings.md)
---

# Fix the findings

> **THIS PROMPT IS THE PERSONALISATION LAYER.** Replace it with your own
> fix-review-findings step.

**Run the `piv-fix-review-findings` skill if this project has one.**

## What you get, and what you do not

- **`$ARTIFACTS_DIR/findings.md`** -- what the validator objected to. **Read this
  first, in full, before editing anything.**
- **`$ARTIFACTS_DIR/gate.log`** -- the raw output of the checks. Read it when a
  finding names a check: the log says what the check actually printed, the finding
  says what the judge made of it, and when they differ the log is the ground truth.
- **`$ARTIFACTS_DIR/issue.md`** -- the original ask, so the fix stays inside it.
- **`$ARTIFACTS_DIR/MISSION.md`** and **`FACTORY_RULES.md`** -- what you cannot do.

**You do not get the plan or the implementation report**, deliberately. A fix that
re-reads the plan tends to re-argue the plan rather than address the finding, and the
finding is the only thing that failed.

## Fix the cause, not the symptom

Take the findings **one at a time, highest severity first**. For each one:

1. Say what was actually wrong.
2. Fix it at the source.
3. Where the finding is a behaviour, add or extend a test that proves it -- in the
   project's own test directory, never in `harness/`.

## The prohibition that matters most here

When a check is red, the cheapest repair is always to make the check quieter.

**Deleting the assertion. Loosening the tolerance. Shrinking the sample. Adding a
special case for the test input. Catching the error and carrying on. Widening an
exact comparison into "not none".**

All of these turn the light off rather than fix the wiring, and all of them are an
auto-reject. `harness/`, `.factory/locks/` and `.factory/holdout/` are protected
paths, so the attempt fails rather than succeeding quietly -- **read that as the
design working, not as an obstacle.**

If fixing the finding genuinely requires changing a check, then the finding is not a
code bug, and the correct move is to **say so and stop**. Write what you found and
why the check itself is wrong. That is an escalation and it is a perfectly good
outcome -- a better one than a second failed cycle.

## Stay inside the ask

Fix what was found. Do not refactor around it, do not tidy adjacent code, do not
"improve" anything the findings did not mention. The guard's **file cap** enforces
this with a count: a fix that grows the PR by five unrelated files is rejected
outright, and you will have spent an attempt to get there.

## Then validate

Run the quick gate, exactly as written:

```
python harness/ci.py --quick
```

(or whatever `FACTORY_VALIDATE_QUICK` is in `factory/config.py`.)

**Do not substitute another way of running the tests.** Anything else you would
normally reach for is denied to this node, and a denied command is a fix that never
got checked -- the run then completes having committed something nobody executed.

## You do not commit, push, or re-label

There is no `git` and no `gh` here. A script commits your work, pushes it, bumps the
attempt counter and hands the PR back to the **independent validator**.

**A fix is never self-certified.** The node that made the change does not get to
decide the change worked.

## Report

Write `$ARTIFACTS_DIR/fix-report.md`:

```markdown
# Fix -- attempt N

## Findings addressed
- [severity] <finding> → <what changed, and where> → <the test that proves it>

## Findings NOT addressed
<each one, and why. "I disagree" is a legitimate entry -- say what the validator
missed. So is "this needs a check changed, which I may not do".>

## Validation
<the quick gate's output>

## Anything I was denied
<tools you asked for and could not have -- or "none">
```

If you do not believe the findings are fixable within scope, **say so now** rather
than spending the attempt on a guess. An escalation with a clear reason is worth more
than a second failed cycle.
