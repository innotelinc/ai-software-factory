---
name: factory-fix
description: Address review findings on an existing pull request, and nothing else.
argument-hint: the pull request, e.g. `gh:pr:14`
---

# factory-fix

**The instructions for this step live in `.archon/workflows/factory/fix/commands/fix.md`. Read that file now and follow it.**
This skill exists so you can run the step by hand; it deliberately does not restate
the content, because a second copy is a second thing to keep true.

Two adjustments for running it interactively rather than as a workflow node:

1. **`$ARTIFACTS_DIR` does not exist here.** Where the file asks for an input from
   that directory, get the same thing from the repository: `MISSION.md`,
   `FACTORY_RULES.md` and `CLAUDE.md` are at the root, the issue is
   `gh issue view <n>`, and anything a previous step wrote is wherever you put it.
2. **The line telling you to defer to a `piv-*` skill is for the workflow node, not
   for you.** If this repository has that skill, running it is still the better
   answer. If it does not, work the shape in the file -- which is what the node does.

Everything else applies unchanged: the same inputs, the same output, the same
refusals. That is the point of pointing at one file instead of keeping two.

## Why the factory and you read the same prompt

The node prompts are the personalisation layer -- they are meant to be rewritten into
your process. If the interactive version were a copy, rewriting one would silently
leave the other saying something else, and the difference would first show up as an
unattended run doing something you thought you had changed.
