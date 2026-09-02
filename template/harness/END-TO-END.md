# End-to-end journeys

<!--
  YOURS TO WRITE. This file and MISSION.md are the two the factory cannot fill in.

  An agent reads this every validation run, drives your app, and reports what it
  saw. There is no script to keep in sync, so a journey stays true to the product
  as the product changes.

  Write journeys, not test cases. A journey is the whole path a person takes to
  get something they wanted, start to finish.
-->

## How to write one

Each journey is a `##` heading and a numbered list of steps. Write them the way
you would tell a person on a call. The agent decides how to click, type or curl.

**Name the value you expect.** "The page loads" passes against an app that
returns an empty body forever. "Ana is owed exactly 666" does not.

**Assert what a person would notice and complain about.** Wrong total, missing
row, a button that does nothing, the wrong name on the receipt.

**Use values that appear nowhere else in the repo.** A string the builder can
grep is a string it can special-case.

**Two to five journeys is right.** More than that and you are writing a test
suite, which is what `unit` is for.

---

<!-- SCAFFOLD_EXAMPLE_DELETE_THIS_LINE_WHEN_YOU_WRITE_YOUR_OWN -->
<!--
  Everything below is an example against a small task service. Delete it and the
  marker line above once these are your journeys. `factory doctor` blocks level 2
  until you do, because a gate that is green about the example product is worse
  than no gate: it is green.
-->

## A person captures a task and finishes it

1. Add a task called `refill the kalimba humidifier`.
2. Check it shows up on the list, still open.
3. Mark it done.
4. Reload the list. It is still marked done, and the open count went down by one.

**What would make this fail:** the task does not come back after the reload, the
count is stale, or completing one task changes the state of another.

## The list survives a restart

1. Add two tasks with distinct names.
2. Complete one of them.
3. Restart the app.
4. Both tasks are still there, and exactly the one you completed is done.

**What would make this fail:** anything held only in memory, or a write that is
acknowledged before it is persisted.
