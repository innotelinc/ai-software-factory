# Holdout scenarios

<!--
  THE BUILDER CANNOT READ THIS FILE. That is the only thing that makes it worth
  anything, and it is the only honest reason to merge code nobody reviewed.

  Everything in `harness/` sits inside the builder's optimisation loop: it can read
  those checks, run them, and iterate until they are green. Given enough attempts it
  will. These scenarios are different only because it never sees them.

  Every workflow node runs with a deny list covering this directory, and `guard.py`
  treats it as protected so no pull request can edit it. Test the deny in BOTH
  directions before you trust it: without it a node returns this file's first line,
  with it the node returns blocked.

  Four rules, and the third is the one that earns its keep:

  1. WRITE THESE BEFORE THE WORK. A scenario written after seeing the
     implementation is a description of the implementation.
  2. DO NOT REUSE THE JOURNEYS. If it is already in harness/END-TO-END.md, the
     builder has read it, and repeating it here buys nothing.
  3. COMPOSE. The dominant real failure is not cheating, it is feature isolation:
     parts that are individually correct and never work together. Unit tests test
     features in isolation by definition, so what they measure is precisely the
     thing that is not broken. String features together the way a user would.
  4. USE VALUES THAT APPEAR NOWHERE ELSE IN THE REPO. A number the builder can
     grep is a number it can special-case.

  And state exact figures, not properties. A scenario that recorded five expenses
  and asserted "the balances sum to zero" was sailed past by a defect that dropped
  four of them, because one expense's balances sum to zero exactly as five do. Work
  the numbers out by hand and assert those.
-->

<!-- SCAFFOLD_EXAMPLE_DELETE_THIS_LINE_WHEN_YOU_WRITE_YOUR_OWN -->
<!--
  Example, against a small task service. Delete it and the marker line above once
  these are yours. `factory doctor` blocks level 3 until you do.
-->

## Three lists, one restart, and a rename in the middle

1. Create tasks `quarry-lantern`, `sable-ferry` and `nine-of-cups`.
2. Complete `sable-ferry`.
3. Rename `nine-of-cups` to `nine-of-swords`.
4. Restart the app.
5. Exactly three tasks exist. Exactly one is done, and it is `sable-ferry`.
   `nine-of-cups` does not appear anywhere. The open count is 2.

## Deleting the completed one does not resurrect it

1. Starting from the state above, delete `sable-ferry`.
2. The list has two tasks, both open, open count 2.
3. Restart the app.
4. Still two tasks, both open. `sable-ferry` is gone and the completed count is 0.
