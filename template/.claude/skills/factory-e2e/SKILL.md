---
name: factory-e2e
description: Drive the running app through the journeys in harness/END-TO-END.md and report what you saw.
argument-hint: none, or a single journey name to run just that one
---

# factory-e2e

You are testing a running application by using it, the way a person would. Then
you write down what you actually observed.

This runs on every validation lap. `harness/ci.py` starts the app, hands you this
file, and reads your result. It is also the rung a planted defect has to get past,
so a journey that reports "worked" without looking is the failure the whole gate
exists to prevent.

## What you are given

The prompt that invoked you contains:

- **the journeys**, from `harness/END-TO-END.md`
- **how to reach the app**: it is ALREADY RUNNING. Do not start another one. You
  get a base URL, or a command to invoke, or a module to import.
- **a restart command**, for journeys that need a process boundary
- **the result path** to write

## What you do

1. **Read the journeys.** Run every one of them unless the prompt named a single
   journey.
2. **Do each step for real.** Send the request, run the command, click the thing.
   Never predict what the app would return.
3. **Record each check as one assertion**, with the value you actually saw.
4. **Keep going after a failure.** A run that stops at the first problem reports
   one defect where there were four. Finish the journey if the next step is still
   meaningful, then move to the next journey.
5. **Write the result file** and stop.

## The result file

Write exactly this shape, and nothing else, to the path you were given:

```json
{
  "journeys": [
    {
      "name": "A person captures a task and finishes it",
      "assertions": [
        {
          "name": "the task comes back on the list, still open",
          "expected": "one open task named 'refill the kalimba humidifier'",
          "observed": "GET /tasks returned 1 task, name matched, done=false",
          "ok": true
        },
        {
          "name": "the open count drops after completing it",
          "expected": "open=0",
          "observed": "open=1, the counter did not move",
          "ok": false
        }
      ]
    }
  ]
}
```

**`observed` is the point of this whole file.** It is what you saw, in enough
detail that somebody reading the log at 3am can tell whether you looked. A run
where every `observed` restates the `expected` is a run that did not check
anything, and it is treated as a failure.

Rules the harness enforces, so there is no advantage in bending them:

- Every assertion needs all four keys. A missing `observed` fails the rung.
- `observed` must be a real value or a real message. Not "as expected", not "ok".
- Zero assertions is a failure, never a pass. A rung that ran nothing looks
  identical to a rung that passed unless somebody counts.

## If you cannot check anything at all

Not "a journey failed". This is the case where you could not issue a single
request: no shell, no HTTP client, nothing answering on the port. Say so as its
own thing, because "I could not check" and "it is broken" have different remedies
and the log has to name which one happened:

```json
{ "blocked": true,
  "blocked_reason": "every HTTP client was refused: curl, python and node all returned 'This command requires approval'",
  "journeys": [] }
```

Use it only when nothing ran. If you checked anything at all, report the
assertions instead and mark the ones that failed.

The harness re-probes the app itself before it believes you, so this does not get
you a pass either way. It decides which of you gets named.

## What you do not do

- **Do not edit the app, the tests, or the journeys.** You are reporting, not
  repairing. If a journey is impossible to run because the product changed,
  say so in a failing assertion and let a human read it.
- **Do not skip a journey because it looks unchanged.** You do not know what the
  diff touched, and that is deliberate.
