# The first hour

What to do after `darkfactory init`, in order, and what each step is actually for.

The short version: **the doctor is a checklist and working through it is the build.**
It fails on a fresh install. That is it working.

---

## 0. Read what it wrote

```bash
darkfactory doctor
```

Seven or eight failures, each naming the level it blocks. Nothing is wrong. The three
that matter are `MISSION.md`, `harness/e2e.py` and the holdout, and they are the three
nobody can ship for you.

Everything else — the dispatcher, the state machine, the guard, the gate, the merge,
the five workflows — is already there and already works.

---

## 1. `MISSION.md`, and mostly its out-of-scope list

Half an hour, and it is the highest-leverage half hour in the build.

The **in-scope** list is easy and you will get it roughly right first time. The
**out-of-scope** list is the one that does work, and it is the one people skip:

> This is how an agent recognises that a plausible, well-argued, easy-to-implement
> feature request is **drift** rather than a good idea.

Without it, every request is arguably in scope, because almost every feature is
defensible in isolation. Aim for at least five, and make them things a reasonable
person might genuinely ask for. "No payments" only earns its keep if somebody would
otherwise ask for payments.

**Sort your non-goals into three piles**, because a spec's non-goals are always a mix
and a human reading them just knows which is which. An agent does not:

- **Never.** Goes in `MISSION.md`.
- **Not yet.** Goes in the backlog and must **not** appear in `MISSION.md` — anything
  listed out-of-scope is refused forever, including the quarter it becomes the
  roadmap.
- **Never, and it is a property rather than a feature.** That is a hard invariant,
  and it goes in its own section.

Then write the section people forget: **what the factory does not own.** Whether it
feels right, looks right, reads right. A green gate never means "the product is good";
it means the layer a machine can check is intact. Saying so here is what stops anyone
reading it the other way.

---

## 2. `harness/e2e.py` — one journey, the most valuable one

Not a suite. The single most valuable thing someone does with your software, from the
first click to the thing they end up looking at.

**Assert what a person would notice and object to.** `200 OK` is not evidence the page
said the right thing; a test that only checks the status passes against an app that
returns an empty body forever. Name the number:

```python
check("the payer is owed exactly what she covered for the other two",
      by_name.get("Ana") == 666,
      f"Ana={by_name.get('Ana')} (1000 paid, 334 her own share, so 666)")
```

**The reachability constraint, and it is an architecture decision.** The harness
reaches software exactly three ways: `http`, `cli`, `library`. A rendered window, a
game loop, a canvas, a native UI is none of them. The rules have to live behind a
headless surface an E2E can drive. On a new project that is nearly free to arrange and
it is a rewrite afterwards.

---

## 3. `.factory/holdout/run.py` — the only honest reason to auto-merge

Everything in `harness/` sits inside the agent's optimisation loop: it can read those
checks, run them, and iterate until they are green. Given enough attempts it will.
That is what you asked for, and it is exactly why passing them proves less than it
feels like it does.

The holdout is different **only because the builder never sees it.** Verified, not
asserted: probe it in both directions and watch a node read the file without the deny
and fail to read it with one.

Four rules, and the third is the one that earns its keep:

1. **Write them before the work.** A scenario written after seeing the implementation
   is a description of the implementation.
2. **Duplicate, do not import.** Importing a helper from `harness/` re-couples the
   wall to code the builder can edit. The process driver is the one carve-out —
   starting a process is not an assertion.
3. **Compose.** The dominant real failure is not cheating, it is **feature
   isolation**: components individually correct that never work together. Unit tests
   test features in isolation by definition, so what they measure is precisely the
   thing that is not broken.
4. **Use values that appear nowhere else in the repo.** A number the builder can grep
   is a number it can special-case.

**And assert exact figures, not properties.** This one cost a real escape here: a
holdout that recorded five expenses and asserted "the balances sum to zero" was sailed
straight past by a defect that dropped four of them — because one expense's balances
sum to zero exactly as five do. The property holds for any subset. Compute the numbers
by hand and assert those.

---

## 4. The mutation set — the only thing that measures your *harness*

Six to ten deliberate defects, injected into real source on a throwaway copy. Each one
must make the gate go red.

Everything else in the gate answers "is this build good?". This answers "**would this
gate know if it were not?**" — and until you have run it, you have no evidence any of
your checks can fail at all.

**Aim one at each rung, and read which rung caught each one.** A set built only from
logic defects gets caught entirely by the unit suite, and the e2e, holdout and
app-start rungs are never once shown to be able to fail. A perfect score can mean "the
unit suite can fail" and nothing more.

**State the gaps rather than faking them.** If you have no browser rung, do not write
a presentation defect: it would report ESCAPED and be telling the truth. Write the gap
down instead.

---

## 5. The ratchet

Set the floors to what the gate just actually asserted. Then understand the one
failure mode:

**Slack is the gap between observed and floor, and it is exactly the number of
assertions that could be deleted with the gate still green.** It *grows* as the
harness improves, because raising the floor is a protected edit the factory cannot
make — measured on a real factory, a hole went from 7 to 33 in one cycle *because the
harness got better*.

So slack here **pins the dial** rather than printing a note. A note gets read once, by
the person who already knew.

---

## 6. The escalation channel

`FACTORY_NOTIFY_CMD` in `factory/config.py`. It receives the message on **stdin**;
`argv[1]` is only the target.

**"I'll just check the file" is not an answer.** Nobody checks the file — that is the
whole reason this exists. A factory whose only output is a file nobody opens is not
unattended, it is unmonitored.

Test it once on purpose: `python factory/notify.py --test`.

---

## 7. One lap by hand

```bash
darkfactory run implement gh:issue:1
```

Watch it. Read the plan it wrote, read the PR body, read the judge's verdict. **Do not
proceed on a factory that has never completed a lap.**

Then merge that first PR yourself, whatever the gate says. You are not testing the
merge yet; you are reading the work.

---

## 8. The dial, one notch at a time

```bash
darkfactory level 1     # an accepted issue becomes a PR
darkfactory level 2     # + the validator writes a verdict
darkfactory level 3     # + it merges without you reading the diff
```

Each is refused until the doctor says the evidence supports it. Watch one full cycle
at each before the next.

**Level 3 is the destination, not an option.** A factory that stops at 2 is a code
generator with a queue, and the person is still the bottleneck they were trying to
remove. Everything expensive in this build exists to earn 3.

Stopping below 3 is legitimate — an unmovable review requirement, a blast radius you
cannot absorb — but write into `FACTORY.md` what would have to be true to go further,
so it stays a decision rather than a dial nobody touched again.

---

## 9. The trigger, last

```bash
darkfactory arm
```

It refuses below level 1, because a scheduler at level 0 wakes up forever and
correctly does nothing — which is exactly how people convince themselves a factory is
running when it has never completed a lap.

**Nothing pushes.** Filing an issue does not trigger a run; the scheduler wakes on a
timer and reads the state. An issue filed at 09:01 waits for the next tick. That is
the trade: a push trigger that breaks fails silently and looks identical to a factory
with nothing to do, and a poll that breaks is a poll you can see not running.

---

## 10. Use the stop button, once, on purpose

```bash
darkfactory halt "testing the stop button"
darkfactory tick          # should refuse to dispatch anything
darkfactory resume
```

**A stop button that has never been used is a stop button nobody knows works.** Write
the date in `FACTORY.md`.

---

## Then: the thing that is actually left

Deployment. Until `FACTORY_DEPLOY_CMD` and `FACTORY_HEALTH_CMD` are set, merging is
where this stops — and **the loop is not closed until a stranger can see the change.**
Everything before that is a PR generator with very good gates.
