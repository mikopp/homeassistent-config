---
paths:
  - "plans/**"
---

# Plan files (`plans/<feature>.md`)

The single source for how a plan looks and is closed. The `/new-plan` command and root `CLAUDE.md`
constraint 1 point here; do not copy this list elsewhere. Read this file before creating a plan:
it loads by itself only once a file under `plans/` is touched.

## Creating a plan
A plan file has:
1. A clear overview of the project.
2. The architecture/design approach.
3. Numbered steps in logical phases.
4. Dependencies and notes for each step.
5. Steps marked `[TODO]`, `[IN_PROGRESS]` or `[DONE]`, and a `## Status` section.
6. Which knowledge homes it will update (`doc/KNOWLEDGE.md#K-1`).
7. A last step named `Close`, done per `doc/KNOWLEDGE.md#K-6`.

The plan follows the conventions in `doc/KNOWLEDGE.md`: open work and hypotheses only, hypotheses
marked as such, no learnings until CONFIRMED. `.github/scripts/check_knowledge_layout.py` fails
CI for a plan without a Status section or a `Close:` step.

## Working on a plan
Confirmed bugs and learnings: invoke the `record-learning` skill; it routes them to their home.

## Closing a plan
At the last step, read `doc/KNOWLEDGE.md` (K-1, K-2, K-6) and follow K-6's last-step procedure.
