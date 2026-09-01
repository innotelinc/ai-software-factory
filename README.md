# dark factory

**A repository that takes work in as an issue and ships validated code out, with
nobody at the keyboard.**

You file an issue. It gets triaged against your mission. It gets planned,
implemented, independently judged, and merged. A scheduled run re-tests what already
merged and files its own bugs. Nobody reads the diff.

That last sentence is the whole difficulty. Everything else is plumbing.

```bash
cd your-repo
darkfactory init
```

That is the install. It writes the governance files, the runner, the harness scaffold
and the workflow pack into your repo, creates the labels that are its state machine,
and **installs the workflow engine underneath if you do not already have it** — the
same way installing OpenClaw gets you Pi. You asked for a factory; the engine is an
implementation detail you are allowed to ignore until you want it.

Then it stops, and tells you the three things nobody can ship for you.

---

## Why this exists

For a year the answer to "how do I get one of these" was: build your own, because a
factory has to fit your process, your codebase, and your way of working. Use mine as
a reference.

That was right about the fit and wrong about what to do with it. **Assembly is not a
filter that keeps out people who would misuse a dark factory. It is a barrier that
keeps out people who would benefit from one.**

So this is one that works when you run it, with a set of opinions already baked in —
and it stays open enough to replace every one of them with yours. The prompts are
yours to rewrite; the plumbing is not, because the plumbing is the same in every
factory and its scars are expensive to rediscover.

---

## The five components

| # | Component | What ships | What is yours |
|---|-----------|-----------|---------------|
| 1 | **Workflow-driven repo** | five Archon workflows: triage · implement · validate · fix · regress, plus `/factory-*` skills that run the same steps by hand | the node prompts — your process, with the approvals removed |
| 2 | **The trigger** | a dumb, deterministic dispatcher on a timer | the interval, and when you turn it on |
| 3 | **Deployment** | a poll-build-healthcheck-swap skeleton | how your thing actually ships |
| 4 | **Guidance layer** | `FACTORY_RULES.md`, nearly complete | `MISSION.md` — what this is and must never become |
| 5 | **Validation harness** | the ladder, the markers, the drivers, the mutation runner | **every assertion.** This is the work |

**Component 4 ships nearly finished and component 5 ships empty, and that split is
the product.** The rules that make an unattended agent safe are the same in almost
every repository — a size cap, a protected list, an attempt cap, a fixed priority
order, a stop button that fails closed. What "working" means for *your* software is
the one thing nobody can write in advance.

---

## The three things that are yours

`darkfactory doctor` will fail on all three the moment you install, and **that is it
working.** It is a checklist, and working through it is the build.

**1. `MISSION.md` — and specifically its out-of-scope list.** This is how an agent
recognises that a plausible, well-argued, easy-to-implement feature request is *drift*
rather than a good idea. Without it, every request is arguably in scope, because
almost every feature is defensible in isolation. Aim for at least five things you
will never build, and make them things a reasonable person might ask for.

**2. `harness/e2e.py` — one journey, the most valuable one, as a real user takes it.**
Not a suite. Assert what a person would notice and object to, not a status code:
`200 OK` is not evidence the page said the right thing.

**3. `.factory/holdout/run.py` — the same product, composed, where the builder cannot
read it.** Everything in `harness/` sits inside the agent's optimisation loop: it can
read those checks and iterate until they are green. Given enough attempts it will.
The holdout is different only because the builder never sees it, and **that is the
only honest reason to merge code nobody reviewed.**

---

## The autonomy dial

```
0  workflows exist, run by hand              <- where every install starts
1  an accepted issue becomes a branch and an open PR
2  + the validator runs and writes a verdict
3  + the validator AUTO-MERGES when every structural gate is green   <- the target
4  + it triages its own issues, and the scheduled regression files its own bugs
5  + it writes its own issues from the mission
```

**Level 3 is the destination.** It is the first level where code merges without a
human reading it, and it is the whole point: a factory that stops at 2 is a code
generator with a queue, and the person is still the bottleneck they were trying to
remove. Everything expensive here exists to earn 3.

`darkfactory level 3` **refuses** until the doctor says the evidence supports it — a
real E2E, a holdout, a mutation set that has been shown to catch things, a ratchet
with numbers in it, and a channel that can actually reach you. A dial that outruns
its evidence is the failure this whole system exists to prevent.

---

## What is enforced in code, not in a prompt

A "gate" that is an instruction in a prompt is a suggestion with good manners. These
are not:

- **The merge.** A script reads a verdict file and branches on it. Never a model
  deciding to merge.
- **Proof the app ran.** `APP_STARTED` and `E2E_PASSED` must appear in the run output.
  A check that never ran produces no failures, and "did anything fail?" reads that as
  success.
- **The protected list.** A PR touching governance, the harness, the locks or the
  holdout is auto-rejected before anything else is evaluated — and the validator
  reads the rulebook from the **base branch**, so a PR cannot weaken the rules it is
  about to be judged against.
- **The scope leash.** A file count, not just a line count. The failure it catches is
  a six-file change that grows to eleven with five one-line "while I was in here"
  edits, well under the line cap the whole way.
- **The stop button.** A local file *and* a remote label, because they fail in
  different places — and the remote half fails **closed**: any error reading it counts
  as stopped.
- **The gate overrides the judge.** When the raw markers and the verdict disagree, the
  raw output wins and the PR escalates.
- **An unknown is never a pass.** Not in the gate, and not in the machinery either.
  When the dispatcher cannot get a straight answer about whether a run is alive, it
  keeps the lock. The version that guessed released every lock one tick after it was
  taken and escalated running work as dead, and nothing errored while it did.

And the part that checks the checker: `factory/_selftest.py` pins the invariants of the
factory's own parts — what counts as alive, what counts as passed, what may move — and
`doctor` runs it on every audit. Everything else here asks whether your software works.
That asks whether the thing deciding it does.

---

## The watchdog: what stops a loop nobody is watching

Every gate above judges ONE thing: this PR, this run, this diff. A tick is stateless
by design, and that has a consequence which is invisible until it bites.

**A process with no memory of its own actions cannot notice it is repeating itself.**

The per-target lock prevents two dispatches at the same time. Nothing prevented the
same dispatch happening 68 times in sequence, which is what happened on 2026-09-01:
one rejected pull request re-validated every tick for three and a half hours, $17.18,
while the rest of the queue was never reached. Every individual tick was correct. The
pathology existed only in the sequence, and the sequence was the one thing nothing
wrote down.

So the factory keeps a diary and reads it:

- **`factory/ledger.py`** — an append-only line per dispatch, settle, escalation and
  halt. Deliberately dumb: it records, it does not judge.
- **`factory/watchdog.py`** — runs at the top of every tick, second only to the stop
  button, and **halts** rather than warns. Warning is what the escalation already was,
  and the machine drove straight through it.

Seven detectors, each aimed at a different shape of stuck:

| detector | fires when |
|---|---|
| `repeat-dispatch` | one action+target 3x with no run completing, or 6x regardless |
| `escalation-ignored` | a target is dispatched *after* being escalated to a human |
| `all-failing` | 5 settled runs, none completed |
| `no-progress` | 8 dispatches, none completed — a loop spread across targets |
| `spend-cap` | more than $25 in the window |
| `spend-without-progress` | money buying no completions |
| `spend-blind` | WARN only: most settled runs carry no cost, so the two above are half-blind |

`escalation-ignored` is the incident's root cause expressed as a **behaviour** rather
than as a table, so it survives any future bug that produces the same effect by
another route.

**`assess()` is a pure function** of a list of events and a clock. It reads nothing and
asks no service anything, which is what makes every detector provable:
`factory/_test_watchdog.py` hands it synthetic histories and asserts each one fires,
asserts a *busy, healthy* hour produces no findings at all, and replays the real
incident from the run log. On that replay the watchdog halts at dispatch **#3**: $16.45
of the $17.20 never spent.

Both halves are then checked by things that can fail:

- the detector proofs run inside `factory/_selftest.py`, so `doctor` cannot report
  healthy machinery while the component that stops a runaway is broken;
- `bin/audit.py` asserts the watchdog exists, that `dispatch.py` actually **calls** it,
  and that its halt path writes the stop file — three separate claims, because "the
  guard fired" and "the machine stopped" are different things and this project has
  been burned by exactly that gap.

**Set the thresholds high.** A false halt costs a night of throughput and is obvious in
the morning; a missed runaway costs money continuously and looks like a working
factory. `FACTORY_WATCH_*` tunes every threshold.

---

## What holds a merge without stopping the work

The factory decides ordinary product values rather than stopping for them — a price,
a default, a name — and **records what it assumed.** The work is built, validated and
waiting, and a human answers a concrete question about a running thing instead of an
abstract one in the dark.

It never decides a **judgement** value: a floor, a tolerance, a sample size, a
deliberate defect, a required marker. Choosing one of those is tuning the judge, and a
factory that tunes its own judge is not being checked by anything.

Three things hold the auto-merge and fail nothing: a recorded assumption, a threshold
nobody has calibrated, and **ratchet slack** — the harness asserting more than the
floor requires, which is exactly how many assertions could be deleted with the gate
still green.

**A hold is a state, not a message.** The PR gets `factory:held`, which nothing
dispatches and no node may leave — `darkfactory accept <target>` archives the
assumptions and sends it back to `open`, so the merge still happens through a full
validation rather than by skipping one. Agreeing with a judgement is not the same as
skipping the gate that acts on it. The first version wrote the
explanation into a comment and set the PR to `passed`; the dispatcher merged it
forty-five seconds later, because `passed` is what a mergeable PR is called.

---

## Commands

```bash
darkfactory init          # install into this repo
darkfactory doctor        # the checklist. It will fail. That is it working.
darkfactory status        # what is in flight, what the dial is, what needs a human
darkfactory run implement gh:issue:4    # one lap, by hand, watching
darkfactory level 1       # raise the dial (refused without the evidence)
darkfactory arm           # install the schedule (refused below level 1)
darkfactory accept gh:pr:11   # agree with a held PR's recorded assumptions
darkfactory halt          # the stop button
```

And the three that check the factory rather than your software. Run them after editing
anything under `factory/`:

```bash
python factory/_selftest.py         # the machinery's own invariants (doctor runs it too)
python bin/audit.py --repo .        # cross-file invariants no single file can check
python bin/selfcheck-mutations.py   # and: would the self-test know if they broke?
```

---

## What it costs, honestly

A published controlled comparison on one task: a solo agent produced a
non-functional result in about twenty minutes for single-digit dollars; a
planner/generator/evaluator harness where the evaluator drove the live page produced a
working result in about six hours for roughly twenty times the cost.

Twenty times the cost, for the only version that worked. **That ratio is the price of
component 5**, and it is better to know it before the first invoice than after.

Instrument tokens on day one. Cost projections for this are wrong by 10–20× in the
same direction every time, and the only way to know what yours does is to have been
recording from the first lap.

---

## What it does not do

- **It does not push.** Filing an issue does not trigger a run. A scheduler wakes on a
  timer, reads the state, and dispatches. An issue filed at 09:01 waits for the next
  tick. A push trigger that breaks fails *silently* and looks exactly like a factory
  with nothing to do; a poll that breaks is a poll you can see not running.
- **It does not judge taste.** `MISSION.md` has a section for what is permanently
  human — whether it feels right, looks right, reads right. A green gate never means
  "the product is good". It means the layer a machine can check is intact.
- **It does not own your process.** The node prompts are the personalisation layer and
  you are meant to rewrite them. A user who recognises their own workflow in there
  will trust it and maintain it; one who has to learn a new pipeline will not.

---

## Layout

```
bin/darkfactory.py     the CLI
bin/sync-to.py         push template fixes into a repo that already installed
bin/audit.py           cross-file invariants no single file can check alone
template/              what init copies in
  factory/             the runtime: dispatcher, state machine, guard, gate, merge
  factory/_selftest.py the harness for that runtime, run by `doctor`
  harness/             component 5's plumbing. Every assertion in it is yours to write
  .archon/workflows/   the five workflows, their prompts and their scripts
  .claude/skills/      the same loop, by hand -- each points at the node prompt
                       above rather than copying it
  MISSION.md           yours
  FACTORY_RULES.md     nearly complete
docs/                  the longer explanations
```
