---
description: Read the diff as code, then write the PR record. Does not open the PR.
argument-hint: (no arguments -- reads the diff and $ARTIFACTS_DIR)
---

# Node 4 · Review, and write the PR record

> **THIS PROMPT IS THE PERSONALISATION LAYER.** Replace it with your own review step.

**Run the `piv-review-changes` skill if this project has one.**

You rubber-stamp this when the gate is green and the diff is small, which is most of
the time -- so it goes autonomous early. It is still worth running, because it is the
only node in the lap that reads the diff **as code** rather than as a set of markers.

## Review

```bash
git diff $INPUTS_BASE...HEAD
git diff --stat $INPUTS_BASE...HEAD
```

Read each changed file **in full**, not just the hunks -- a diff shows you what moved,
not what the file now says. Look for:

- **Logic errors** -- off-by-one, an inverted conditional, a branch that cannot be
  reached, a missing error path
- **Things a type checker and a linter cannot see** -- an assumption about iteration
  order, mutation during iteration, an identity comparison where equality was meant.
  These are the ones that make a suite flake one run in fifty
- **Scope** -- anything here unrelated to the issue. Scope creep is a block even when
  the extra code is good
- **Conventions** -- against `$ARTIFACTS_DIR/CLAUDE.md`, not against your taste
- **Observability** -- a new value that moves, with nothing able to see it, is a block
- **Security** -- a new unauthenticated path, a widened permission, a secret in the
  diff, an input that reaches a query or a shell unescaped

Read `$ARTIFACTS_DIR/implementation.md` for the **documented deviations**. A
documented deviation is an *intentional decision* and is not a finding. Only flag
undocumented divergence.

## Then write `$ARTIFACTS_DIR/pr.md`

One file, at exactly that path. A script turns it into a real pull request after you
exit -- **you do not open it, and you are not given `gh`.** Same rule as the merge: a
model's only output is a record, and code decides what happens to it.

The front matter is read by that script. `issue` and `title` are load-bearing: a
rewrite that drops them produces a perfectly readable PR that nothing can validate.

```markdown
---
issue: <the issue number, digits only>
title: <the change, in the imperative, as a commit subject: "fix: ..." / "feat: ...">
---

## What changed
<2-4 sentences, in terms of the product, not the files.>

## Why
<the problem from the issue, in one or two lines.>

## Files
<path -- why it changed>

## Validation
<the counts from the self-check: static, unit, e2e steps, holdout, mutations.>

## Review findings
<severity / file:line / what and why -- or "none". Findings you are recording rather
than fixing: say why they are acceptable to ship.>

## Assumptions
<if the plan recorded any, restate them here so the human merging sees them without
opening another file -- or "none". These hold the auto-merge.>

## Floor raise to apply
<if assertions were added, the new .factory/locks/floor.json values for a human to
commit, since that file is protected -- or "none">
```

Keep the body readable by a human who has not seen the issue. It is the thing
somebody skims in six months when they are working out why the code looks like this.

**Do not merge, and do not approve.** Your only merge-related output is this record.
The gate and the merge decide, and they re-check the markers themselves rather than
trusting anything in this file.
