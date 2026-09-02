---
description: Prime the plan node. Scoped orientation, read-only, written to an artifact.
argument-hint: (no arguments -- reads the issue from $ARTIFACTS_DIR/issue.md)
---

# Node 1 · Prime

> **THIS PROMPT IS THE PERSONALISATION LAYER.** The factory's whole claim is that it
> runs *your* process with the approvals removed, so these four prompts should be
> recognisably your priming step, your planning step, your implementation step and
> your review step -- loading the skills, rules files and MCP servers you already load
> at each one. What ships here is a worked example. The shape is worth keeping; the
> words are yours to replace.

Orient on this codebase, scoped to what the issue actually touches. Then stop.

**Run the `prime-codebase` skill if this project has one.** Otherwise work the steps
below directly.

## Read

- `$ARTIFACTS_DIR/issue.md` -- the issue, exactly as it was filed. This is the ticket.
- `$ARTIFACTS_DIR/MISSION.md` -- scope, invariants, and what is permanently human
- `$ARTIFACTS_DIR/CLAUDE.md` (or `AGENTS.md`) -- the conventions
- `git ls-files`, `git log -12 --oneline`, `git status`
- `README.md`
- **The core module in full** -- the bottom of the dependency graph, the thing
  everything else reads. If you are not sure which that is, it is the one with the
  most inbound imports.
- The harness modules relevant to the issue's capability area (`harness/`), so the
  plan knows what "working" currently means
- `.factory/locks/floor.json` -- the thresholds a human has set, which the plan has to
  stay inside

**You cannot read `.factory/holdout/`.** That is enforced, not requested. Those are
the assertions this work will be judged against, and a builder that can read them can
write code aimed at exactly those assertions instead of at the problem.

## Write `$ARTIFACTS_DIR/priming.md`

Keep it scannable. The plan node is the expensive one; every minute of its budget you
spend on re-deriving what you already know here is a minute not spent on the plan.

- **What the issue touches** -- the capability area from `MISSION.md`, and the files,
  with paths
- **Existing patterns to mirror**, with `file:line`. Naming, how state threads
  through, how errors are raised and handled, how tests are written and named. Quote
  the two or three lines that show the pattern rather than describing them
- **The seams** -- where new code plugs in. This is what makes the plan *extend* the
  codebase instead of bolting onto it
- **How this project is checked** -- the exact commands, from `harness.config.json`
  and the conventions file, so the plan can put a real validation command on every
  task instead of "verify it works"
- **Current gate counts** -- what the last run asserted, so the plan knows what the
  ratchet floor is and never plans below it
- **Anything that looks already broken** in this area, distinct from the issue. **Do
  not fix it.** Name it, and say whether it is worth a separate issue

## You are read-only

If you find yourself wanting to edit something, that is a finding for the report, not
an action. The only file you write is `priming.md`.

## Report

One paragraph: what this issue touches, the two or three files that matter most, and
anything the plan node should be careful about.
