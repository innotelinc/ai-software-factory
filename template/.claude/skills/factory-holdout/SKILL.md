---
name: factory-holdout
description: Run the hidden holdout scenarios against the running app and report what you saw.
argument-hint: none
---

# factory-holdout

Same job as `factory-e2e`, against a different file, for a different reason.

The journeys in `harness/END-TO-END.md` are readable by whatever wrote the code
under test. Given enough attempts, a builder satisfies the checks it can read.
The scenarios you are about to run live in `.factory/holdout/`, which every
builder node is denied, so passing them means something the journeys cannot mean.

**This skill is public. The scenarios are not.** Knowing that the holdout composes
features and uses unguessable values does not help anybody pass it.

## What is different from factory-e2e

1. **Scenarios compose.** Each one strings several features together in a
   sequence a real user would perform. Report an assertion per checkable claim,
   not one per scenario.
2. **Process boundaries are part of the point.** Where a scenario says restart,
   restart it with the command in the prompt and then re-check. State that
   survives only in memory is exactly what this catches.
3. **Run the scenarios in order, and carry the state forward** unless a scenario
   says otherwise. Scenario 2 often starts from where scenario 1 ended, and
   resetting between them removes the thing being tested.
4. **Never look at the diff, the plan, or the builder's notes.** You are the
   independent reader. If they are in your context, ignore them.

## The result file

Same shape as `factory-e2e`, with `scenarios` in place of `journeys`:

```json
{
  "scenarios": [
    {
      "name": "Three lists, one restart, and a rename in the middle",
      "assertions": [
        {
          "name": "exactly three tasks survive the restart",
          "expected": "3 tasks, 1 done",
          "observed": "GET /tasks returned 3, done=1 (sable-ferry)",
          "ok": true
        }
      ]
    }
  ]
}
```

The same rules are enforced: all four keys on every assertion, a real `observed`
value, and zero assertions is a failure rather than a pass. The `blocked` escape
in `factory-e2e` applies here too, for the case where nothing ran at all.

If a scenario cannot run because the product no longer has the feature it names,
that is a failing assertion with the reason in `observed`. It is not your call to
decide the scenario is out of date. Someone protected this file on purpose.
