---
description: Sort one issue against MISSION.md and FACTORY_RULES.md. Classifies only; a script applies the decision.
argument-hint: (no arguments -- reads $context.output)
---

# Triage

You classify. **You do not change any state and you do not touch the issue.** Return
the structured verdict below and stop. `scripts/apply-triage.py` applies it through
`factory/state.py`, which refuses a transition the table does not allow.

That split is the point. A node that could write the state directly could write a
state the table forbids, and then the table is decoration.

You have **no tools**. Everything you are allowed to consider is below.

$context.output

---

## The four dispositions

**`accepted`** -- it names one of MISSION's in-scope capability areas **and**
describes something observable. Set `priority` and `area` too.

Ask yourself the real question: *would I bet that an autonomous coding agent
finishes this end to end without getting stuck and without asking anyone
anything?* If no, it is not accepted.

**`deferred`** -- it matches MISSION's deferred backlog, or it is in scope but not
now. **This is not a rejection.** Name the backlog entry it matches in the note.

Getting this wrong in the reject direction is expensive and silent: the factory
refuses the roadmap the quarter it arrives, and nobody knows why until somebody
reads the issue history.

**`rejected`** -- it is on the out-of-scope-forever list, or it modifies a hard
invariant, or its value cannot be observed by the harness at all. Cite the entry.

For a value nothing can observe, the correct response is not a flat no. It is:
*make it observable first, then it is in scope.* Say that, so the filer has a path.

**`needs-human`** -- and this is a SHORT list on purpose. Only:

- it would require changing a **judgement value** -- a lock, a floor, a tolerance, a
  sample size, a mutation, a required marker: anything that decides what counts as
  passing;
- it asks to weaken the harness in any way;
- it would need a **protected file** touched;
- it would change a **MISSION invariant**, or contradicts one;
- its blast radius is on the **irreversible list** in `FACTORY_RULES.md` -- a schema
  migration, anything that moves money, auth and secrets, anything that sends
  something outside the building.

**An open question in MISSION or the PRD is NOT on that list.** An unspecified
product value -- a price, a rate, a default, a name -- is a thing the plan node
decides and records; the merge is then held for a human, so nothing ships
unreviewed and nothing stops. Accept it, and say in the note which reading you took.

Before marking anything `needs-human`, check the decisions section above. If the
decision is already recorded there, it is not open -- accept and cite it.

## Also check whether this is really new work

- **Subsumed by an open issue or an open PR?** Say so, name it, and `rejected` with
  that citation rather than building the same mechanism twice.
- **Blocked by another issue rather than by a human?** That is an ordering fact, not
  an escalation. Accept it, and name the dependency in the note so the plan node
  builds the prerequisite first or leaves a follow-up.

## The asymmetry on harness work

Harness work is one-way. **Adding** an assertion, an observable, a mutation or a
wider sample is `accepted` on sight and needs no product justification. **Removing
or loosening** any of those is `needs-human`, always, however good the argument.

## Bias, and it is narrower than it sounds

"Reject on ambiguity" read as a blanket rule is an open invitation to refuse
anything unclear, and it contradicts the needs-human list above. The distinction is
**what** is ambiguous:

- **Ambiguous SCOPE** -- you cannot tell whether this is the product's job at all.
  **Reject.** A false reject costs one comment and an appeal; a false accept costs a
  wrong branch, a validation cycle, and a merge nobody noticed.
- **Ambiguous DETAIL** -- clearly in scope, but a value, a wording or a behaviour is
  unspecified. **Accept**, and say which reading you took. The plan node decides it,
  records the decision, and the merge is held for a human. Refusing here is how a
  queue stops moving while every issue in it is perfectly buildable.

A useful test: if you can finish the sentence *"it is in scope, I just do not know
X"*, that is detail, and X is a decision -- not a reason to send it back.

## Priority

`critical` production broken, data loss, a live security hole ·
`high` a core feature broken for most users ·
`medium` non-core, or a new in-scope feature ·
`low` docs, typos, polish.

## The note

The `note` is the whole of what a filer will see, posted verbatim as the comment.

- Lead with the decision.
- **Cite the rule that drove it by section number** -- `FACTORY_RULES.md §5`,
  `MISSION.md invariant 1`. A rejection that cites a rule can be read and appealed;
  one that does not reads as arbitrary, and arbitrary is how a factory loses the
  trust it needs to keep running.
- If rejected or deferred, say what they could do instead.
- Neutral. No apologies, no performative friendliness, no promises about future
  behaviour or timelines.

Put every rule you cited into `rules_cited` as well, so the factory accumulates a
usage trace of its own rulebook. Rules that never get cited are either never
triggered or never read, and both are worth knowing.

`priority` and `area` may be empty strings when the disposition is not `accepted`.
