---
description: Execute the plan task by task, validating as you go. Does not commit; a script does.
argument-hint: (no arguments -- reads $ARTIFACTS_DIR/plan.md)
---

# Node 3 · Implement

> **THIS PROMPT IS THE PERSONALISATION LAYER.** Replace it with your own
> implementation step. What ships here is the shape.

**Run the `piv-implement` skill if this project has one.** Otherwise work the plan
below directly.

Read `$ARTIFACTS_DIR/plan.md` in full before editing anything, then work its tasks
**in order, top to bottom**, running each task's validation command as you go.

You skim this step at best when you do it by hand, which is why it goes autonomous
early -- and why the prohibitions below are absolute rather than advisory.

## Absolute prohibitions

1. **Never modify a test, an assertion, a tolerance, a sample size or a lock to make
   something pass.** Fix the source. If a check is genuinely wrong, say so in your
   report and stop -- that is an escalation, not a change you make.
2. **Never touch a protected file.** Governance (`MISSION.md`, `FACTORY_RULES.md`,
   the conventions file), `factory/`, `harness/`, `.factory/locks/`,
   `.factory/holdout/`, `.github/`. Most are unreachable from this node by
   construction; this rule covers the rest, and the guard rejects the PR outright if
   one is touched -- no fix attempt, straight to a human.
3. **Never add a dependency** without saying in the report what it does, why what is
   already here does not work, and evidence it is maintained.
4. **Never build beyond what the plan asked for.** No opportunistic refactors, no
   "while I was in here". The plan's non-goals section is binding, and the guard's
   **file cap** enforces it: a six-file change that grows to eleven is rejected by a
   count, not by an opinion.
5. **Stay under the size cap.** Over it, stop and report -- the work needs splitting,
   and something nobody could review even in principle is not shippable here.

## New coverage goes in the project's test directory

Growing test coverage is expected and welcome. It just happens over there, never in
`harness/`. The harness *is* the definition of "working" for this repo, it is
protected, and a builder that can edit its own judge can make any claim true.

## Observability ships with the change

If this change introduces a value that moves as a consequence of use, expose it
somewhere the harness can assert **in this change**. A value that moves and is not
observable cannot be proven to work by anybody, ever, and in a repo that merges
without review that means it cannot be built.

If you added an assertion, say so in the report with the number the floor should
become. `.factory/locks/floor.json` is protected -- you cannot raise it, and you
should not try. Write the new value into the report for a human to apply. The gate
passes either way; the ratchet only requires observed ≥ floor.

## Validate as you go

After each task, run **exactly the command that task names**. Then, before you
finish, run the quick gate:

```
python harness/ci.py --quick
```

(or whatever `FACTORY_VALIDATE_QUICK` is set to in `factory/config.py` -- the plan
will have named it.)

**Do not run the full gate.** It belongs to the validator. A builder that can run the
gate it is judged by will iterate against the gate rather than against the problem,
and the two diverge exactly when it matters.

## You do not commit

There is no `git` and no `gh` on this node, and that is deliberate. A script commits
your work after you exit, and it **refuses an empty diff** -- so if you finish having
changed nothing, the lap fails loudly here rather than opening an empty PR.

If you were denied a tool you needed, **say so explicitly in the report**. A denied
tool does not make you exit non-zero; it makes you stop and ask a human who is not
there, and the run then completes "successfully" having done nothing. Naming it is
the difference between a five-minute fix and an afternoon.

## Report

Write `$ARTIFACTS_DIR/implementation.md`:

```markdown
# Implementation -- <feature>

**Plan**: $ARTIFACTS_DIR/plan.md   **Status**: COMPLETE | PARTIAL

## Summary
<2-4 sentences: what was built.>

## Tasks completed
- <task> → `path/to/file` (CREATE/UPDATE)

## Tests added
<files + cases + results>

## Validation results
<the quick gate's output: pass/fail with counts>

## Deviations from the plan
<what changed vs the plan and WHY -- or "none". This is the reviewer's signal of
intent: a documented deviation is a decision, an undocumented one is a bug.>

## Floor raise to apply
<if you added assertions, the new .factory/locks/floor.json values for a human to
commit, since that file is protected -- or "none">

## Tools I was denied
<anything you asked for and could not have -- or "none">
```
