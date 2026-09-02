---
description: The premium slot. Turn one issue into a context-rich, one-pass-ready implementation plan.
argument-hint: (no arguments -- reads $ARTIFACTS_DIR/issue.md and priming.md)
---

# Node 2 · Plan

> **THIS PROMPT IS THE PERSONALISATION LAYER.** Replace it with your own planning
> step -- the one you actually read today. What ships here is the shape.

**Run the `piv-plan-implementation` skill if this project has one.** Otherwise work
the structure below.

This is the step a human reads today, and everything downstream inherits whatever it
gets wrong. It holds the premium model for that reason, and it is the last node that
will ever go fully unattended.

**No code is written in this phase.** The goal is a plan context-rich enough that the
implement node succeeds on the first attempt without going looking for anything.

## Before anything: is there a previous attempt on this branch?

`$preflight.output.prior_attempt` is non-empty when this branch already carries commits
that are not on the base. That means a previous lap on this same issue committed work
and then failed -- usually blocked by the guard or the gate.

**Those commits are not merged and the issue is not done.** The worktree will look as
though the feature exists, because it does exist, on a branch nobody took. A lap that
checked and concluded "already implemented at HEAD" reported COMPLETE having changed
nothing, and the base had no such file.

So: read what is there, keep what is right, and work out what stopped it. That is
usually a small fix rather than a rewrite, and re-doing it from scratch throws away
work that was mostly correct.

## Inputs

- `$ARTIFACTS_DIR/issue.md` -- the issue, as filed. **This is the ticket.**
- `$ARTIFACTS_DIR/priming.md` -- node 1's orientation
- `$ARTIFACTS_DIR/MISSION.md` -- scope, invariants, and the definition of done
- `$ARTIFACTS_DIR/FACTORY_RULES.md` -- how this runs unattended
- `$ARTIFACTS_DIR/CLAUDE.md` -- conventions
- `$ARTIFACTS_DIR/decisions.md`, if present -- decisions already made. **Read it
  before you consider stopping for anything.**

## Inherit, do not re-decide

`MISSION.md`'s invariants and the constraints in `FACTORY_RULES.md` are **already
decided**. Plan within them. A plan that proposes changing one has misunderstood the
issue: say so and escalate rather than planning the change.

## You cannot run anything, and the implement node nearly cannot either

**You have Read, Glob, Grep and Write. No shell at all.** Do not plan to measure
something yourself; you will be refused, and the refusal is silent -- the request goes
to a human who is not there. State the measurement as the implement node's first task
instead.

**The implement node has** Read, Glob, Grep, Edit, Write, and a shell scoped to the
project's own tooling. It has no `git`, no `gh`. A task that needs anything else does
not fail loudly: the node asks for approval, nobody answers, and it stops having
changed nothing. **Write no task the next node cannot perform.**

## Write the plan to `$ARTIFACTS_DIR/plan.md`

Four sections matter more here than they do interactively, because no human reads
this before it executes.

**Out of scope / non-goals.** Name what a reasonable reader might assume is included
and is not. Unattended, this is the only thing standing between a two-file change and
a nine-file one -- and the guard's file cap will reject the nine-file version outright.

**Every task carries an executable validation command.** Not "verify it works". The
command, verbatim, as the implement node will type it. Those commands are all it has
to go on.

**The test task.** A bug fix comes with a regression test that fails on the base
branch and passes on this one. A feature comes with tests for its behaviour. Say
where they go -- the project's own test directory, never `harness/`, which is
protected because it is the definition of "working" and a builder that can edit its
own judge can make any claim true.

**The observability task.** If this change introduces a value that moves as a
consequence of use, exposing it somewhere the harness can see is **part of this
change**, not follow-up work. A value that moves and is not observable cannot be
proven to work by anybody, ever -- and in a repo that merges without review, that
means it cannot be built. This is the one hole in the harness that only a plan can
close: the gate will not catch it.

Use the full structure your `piv-plan-implementation` skill defines. At minimum:
feature description · problem · solution · out of scope · context references with
`file:line` · step-by-step tasks with `IMPLEMENT / PATTERN / GOTCHA / VALIDATE` ·
testing strategy · validation commands · acceptance criteria.

## Decide and proceed. Stopping is the exception, and the list is short.

**Your default is to make the call, build it, and say what you assumed.** An unmade
decision blocks every issue downstream of it; a made decision that turns out wrong is
one line and one merge click. Those are not the same risk and the factory does not
treat them as though they are.

### The two kinds of value, and only one of them stops you

- **A JUDGEMENT value decides what counts as passing** -- anything in
  `.factory/locks/`, a floor, a tolerance, a sample size, a required marker, a
  deliberate defect. **Never choose one. Ever.** Picking these is tuning the judge,
  and a factory that tunes its own judge is not being checked by anything.
- **A PRODUCT value decides what the software does** -- a price, a rate, a default, a
  copy string, a layout, a name. **Choose it, and record it.** A spec that leaves one
  open means "I have not decided", not "you may not propose".

### So: write `$ARTIFACTS_DIR/ASSUMPTIONS` and keep going

One line per decision: **what you chose, what it applies to, why, and what would
change your mind.**

```
<name>=<value>  | WHY: derived from <the invariant, rule or existing value it follows
                  from -- name it, so the reader can check the derivation rather than
                  your taste>. <what a nearby wrong value would break>.
                  CHANGE IF: <the observation that would make this the wrong call>.
```

The `CHANGE IF` line is the one that earns the merge. It tells the reader what to
look for rather than asking them to have an opinion cold, and it is the difference
between "do you like 1.5?" and "if the second tier feels compulsory in use, this is
the number to move".

That file does **not** stop the run. It rides through the build into the PR record,
and the gate **holds the merge** on it: the work is built, validated and waiting with
your reasoning at the top, and a human merges or replaces the number. They answer a
concrete question about a working thing instead of an abstract one in the dark.

### Build the part you can

An issue is rarely wholly blocked. If three quarters of it is buildable and one
quarter needs something on the stop list, **plan the three quarters** and write the
rest into `$ARTIFACTS_DIR/FOLLOWUP` as a follow-up issue. Downing tools on a whole
issue because one sub-question is open is the most expensive habit this node has.

### The stop list -- write `$ARTIFACTS_DIR/ESCALATE` and stop ONLY for these

1. **A judgement value would have to change** -- a lock, a floor, a tolerance, a
   sample size, a deliberate defect, a required marker. Including "just to make this
   pass".
2. **A protected file would have to change** (`FACTORY_RULES.md` §5).
3. **A MISSION invariant would have to change**, or the issue contradicts one.
4. **The blast radius is on the irreversible list** in `FACTORY_RULES.md` -- a schema
   migration, deletion, money, auth, anything reaching real users in a way a revert
   does not undo.
5. **Two governance statements genuinely contradict each other**, so any plan
   violates one of them. Name both.

**Not on the list, and therefore not a reason to stop:** an open question in MISSION,
an unspecified product value, an ambiguity you can resolve defensibly, or a thing you
would rather someone confirmed. Decide, record it in ASSUMPTIONS, and move.

**When you do escalate, propose an answer.** A question with a recommendation
attached is a yes/no; a bare question is a design session someone has to schedule.
Give your recommended value, your reasoning, and what you would do if overruled.

Check `decisions.md` first. If the decision you need is already answered there, **use
it and cite it** -- it is not open any more.

## Report

The path to the plan, the complexity, the key risks, and a confidence score out of 10
for one-pass success. **Below 6, escalate instead** -- a plan you do not believe in is
cheaper to abandon here than after three fix attempts.
