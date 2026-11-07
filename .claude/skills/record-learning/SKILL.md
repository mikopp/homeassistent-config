---
name: record-learning
description: Record a proven learning/gotcha after a bug or feature. Use when about to write down a lesson, pattern, anti-pattern or root cause.
---

# Record a learning

Conventions behind this skill: `doc/KNOWLEDGE.md` (homes K-1, current vs background K-2, extending K-6).

## 1. NEVER write an unconfirmed learning

A learning is a claim future sessions will act on without re-deriving it. Only write one when the
cause is **proven**, not when it is merely plausible.

- **A single green CI run is not proof.** Neither is "the symptom went away after I changed X":
  that is correlation on a sample of one, and for an intermittent failure it is worth nothing.
- Acceptable evidence: a stack trace / thread dump / error naming the mechanism; the relevant
  source read at the pinned version (`FROM` line of `.github/ha-versions/ha/Dockerfile`); a
  config-check or test failure that reproduces deterministically; a bisect over several runs.
- If the cause is still a hypothesis, it belongs in the feature's `plans/` file marked as such,
  not in any knowledge home.
- When a learning is later contradicted, **delete it** (or strike it through and say what
  disproved it). Do not leave a wrong entry standing next to its correction.

This rule exists because two learnings had to be removed as false positives: both were plausible
mechanisms fitted to one confirming run, and both sent later sessions down wrong paths.

## 2. Grade the evidence

- **CONFIRMED** = a stack trace, a source read at the pinned HA version, or a deterministic
  reproduction.
- **OBSERVED** = real data from a real run, but a plausible alternative explanation is still open.
- **UNPROVEN** = a hypothesis kept only so it is not re-litigated from scratch.

Never promote a learning a grade without new evidence. Write the grade next to any claim that is
not CONFIRMED.

## 3. Route it to its one home

| The learning is… | Write it to |
|---|---|
| a current fact about one package | `packages/notes/<pkg>.md` (if missing: create the note + symlink rule, `doc/KNOWLEDGE.md#K-6`) |
| architecture or a derivation result | `doc/<pkg>/design.md` (create at the K-4 threshold) |
| a story, superseded design or investigation | `doc/<pkg>/background.md` |
| a transcript or spreadsheet | `doc/sources/<pkg>/` (never edited) |
| a cross-package topic fact (templates, MQTT, energy, tests …) | the matching skill in `.claude/skills/`, or a new skill |
| needed in every session | root `CLAUDE.md` (keep it < 100 lines) |
| a hypothesis | the feature's `plans/` file, marked UNPROVEN |
| local to one YAML block | a YAML comment (`doc/KNOWLEDGE.md#K-5`) |
| contradicted | delete or strike through where it lives |

One home per fact: other places point to it, never copy it. Keep entries dense and actionable;
skip trivial details.

## 4. No dated logs

Do not append dated "what I did" entries anywhere. Git and PRs are the log.
