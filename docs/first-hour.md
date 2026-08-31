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

**Aiming is not landing, and only the report tells you which.** Both non-unit defects
here landed on the unit suite the first time: the app-start one broke a module-level
import every unit test hits, and the e2e one flipped a status code the unit tests
assert directly. 10/10, four rungs claimed, two of them never demonstrated. A defect
aimed at a rung must be **invisible to every rung above it**, or it measures the one
above twice.

**Expect re-aiming to find a hole in your assertions.** The corrected e2e defect
escaped, because the journey asked whether `<table` appeared anywhere in the page while
two other tables were still in the markup and the balances screen showed nothing. That
is the same failure as a holdout asserting "the balances sum to zero" — a property that
holds for a subset is not a check on the whole — and nothing but a defect aimed at that
rung will ever show it to you.

**State the gaps rather than faking them.** If you have no browser rung, do not write
a presentation defect: it would report ESCAPED and be telling the truth. Write the gap
down instead.

---

## 4b. The one thing you do not have to build

`factory/_selftest.py` ships done, and `doctor` runs it every time. It is the mutation
set aimed at the **factory** rather than at your software: an empty run list must keep
a lock, an unrecognised status must keep a lock, `needs-human` must stay terminal, an
empty log must yield no counts.

You do not write these. You do need to know they are running, because the failures they
pin do not look like failures — a dispatcher that mis-decides which laps are alive
produces a repository that looks exactly like a quiet one.

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

**And the hold is a state, not a note.** A held PR gets `factory:held`, which nothing
dispatches and no node may leave; `darkfactory status` names it on its own line. The
first version of this posted the explanation as a PR comment and set the PR to
`passed` — the dispatcher merged it forty-five seconds later, because `passed` is what
a mergeable PR is called. When you clear a hold you run `darkfactory accept <target>`, which archives the
assumptions and sends the PR back to `open` for a fresh validation rather than merging
the judgement you were holding. Raise the floor in the same sitting if slack was named
too, or the next run holds again for that reason.

**The accept path shipped a version after the hold did, and the gap is instructive:**
the gate re-reads the assumptions file every run, so a held PR held again on the next
validation, and the next. A hold nobody can clear is not a hold, it is a stall — and it
looks exactly like a factory with nothing to do.

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

**Check what it actually installed**, on Windows especially. `arm` schedules two jobs:
the dispatcher on the interval, and the weekly regression that re-tests what already
merged. The first version of this installed only the dispatcher on Windows and reported
`ARMED` — so the factory ran, the doctor said armed, and merged code was never re-tested.
Nothing reports a job that was never created.

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like "darkfactory-*" }
```
```bash
crontab -l | grep darkfactory
```

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

Then the remote half, which is the one you will actually reach for, because it works
from a phone:

```bash
gh issue edit <any open issue> --add-label factory:stop
```

**It is one tick behind.** GitHub does not guarantee you read your own write
immediately, so the tick right after you add the label can still dispatch. The local
file is instant and the label is eventually-instant; that is the trade for a button
that works when you are not at the machine. If you need it stopped *now* and you are
at the machine, use the file.

**A stop button that has never been used is a stop button nobody knows works.** Write
the date in `FACTORY.md`.

---

## Then: the thing that is actually left

Deployment. Until `FACTORY_DEPLOY_CMD` and `FACTORY_HEALTH_CMD` are set, merging is
where this stops — and **the loop is not closed until a stranger can see the change.**
Everything before that is a PR generator with very good gates.
