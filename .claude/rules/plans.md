---
paths:
  - "plans/**"
---

# Plan files (`plans/<feature>.md`)

The single source for how a plan looks, is kept and is closed. The `/new-plan` command and root
`CLAUDE.md` (constraints 1–5) point here; do not copy this list elsewhere. Read this file before
creating a plan: it loads by itself only once a file under `plans/` is touched.

## Creating a plan
Writing a plan is planning only: do NOT implement anything. After creating it, stop and wait for
the owner's approval.

A plan file has:
1. A clear overview of the project.
2. The architecture/design approach.
3. Numbered steps in logical phases.
4. Dependencies and notes for each step.
5. Steps marked `[TODO]`, `[IN_PROGRESS]` or `[DONE]`, and a Status section.
6. Which knowledge homes it will update (note, design doc, skill, rule, root `CLAUDE.md`;
   `doc/KNOWLEDGE.md#K-1`).
7. A last step: "Close: distil into note/design/skill, story → background, update pointers,
   delete this plan" (`doc/KNOWLEDGE.md#K-6`).

The plan follows the conventions in `doc/KNOWLEDGE.md`: open work and hypotheses only, hypotheses
marked as such, no learnings until CONFIRMED.

## Working on a plan
- Update the Status section after each step, and summarize before asking for the next one.
- Confirmed bugs not fixed now become GitHub issues; link the issue number from the plan.

## Closing a plan
At the last step, read `doc/KNOWLEDGE.md` (K-1, K-2, K-6) and follow K-6's last-step procedure. It
is the one home of that procedure. Record learnings only through the `record-learning` skill.
