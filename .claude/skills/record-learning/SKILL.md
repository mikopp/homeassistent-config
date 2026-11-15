---
name: record-learning
description: Record a proven learning/gotcha after a bug or feature. Use when you find or confirm a bug, root cause, gotcha or non-obvious fact while working, when about to write down a lesson, pattern or anti-pattern, or when closing a plan.
---

# Record a learning

Conventions behind this skill: `doc/KNOWLEDGE.md` (homes K-1, current vs background K-2, extending K-6).

## 0. Is it worth writing? (before everything else)

Proven is not enough: a note is read in every future session that touches the package, so each
entry costs context. Write a learning only if ALL hold:

- A future session would act differently without it.
- It cannot be read from the YAML, the tests or `git log` (a `retain: false` publish, a visible
  hold timer, a template's own logic are all visible there).
- `grep` over the target note and the matching skill found no entry that already covers it.
  Reworded duplicates count as covered: extend or tighten the existing entry instead.

Do NOT record:
- Recovery steps for a one-off situation (first arming, a deploy slip, a manual retry). They go in
  the PR description.
- That a procedure worked because the user said so: that is an outcome, not a mechanism.
- Behaviour that follows directly from a config value you can see.

If unsure, ask the user before writing; skipping costs nothing, a useless entry stays.

For a design doc, also apply its own gate `doc/KNOWLEDGE.md#K-4.1` (architecture only, no
implementation detail, no history).

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
  reproduction. It grades the proven *mechanism*: "the user did X and it worked" is at most
  OBSERVED, and usually not a learning at all (section 0).
- **OBSERVED** = real data from a real run, but a plausible alternative explanation is still open.
- **UNPROVEN** = a hypothesis kept only so it is not re-litigated from scratch.

Never promote a learning a grade without new evidence. Write the grade next to any claim that is
not CONFIRMED.

## 3. Route it to its one home

Before editing any knowledge file: read `doc/KNOWLEDGE.md`, then `wc -c` the target. A note over
its cap (K-3: 24 KB) takes no new entry: split it (K-4) or have the entry replace something.

| The learning is… | Write it to |
|---|---|
| a current fact about one package that an editor needs before touching its YAML/tests (invariant, quirk, measured value, entity, owner value), even one behind a design decision | `doc/<pkg>/notes.md`, graded; a design doc cites it, never copies it (if missing: create the note + symlink rule, `doc/KNOWLEDGE.md#K-6`) |
| how a component works, a state machine or decision table, a decision with its rejected alternative, an invariant's mechanism, a contract with another package, an extension rule | `doc/<pkg>/design.md` (K-4.1 gate; create at the K-4 threshold), plus a one-line `→ design.md#ID` in the note if breaking it fails silently |
| a known architectural gap or accepted risk | a GitHub issue; link `#n` from the note AND the design doc's Known gaps |
| a story, superseded design or investigation | `doc/<pkg>/background.md` |
| a story about a cross-package topic (e.g. the test framework) | `doc/<topic>/background.md` |
| a transcript or spreadsheet | `doc/sources/<pkg>/` (never edited) |
| a cross-package topic fact (templates, MQTT, energy, tests …) | the matching skill in `.claude/skills/`, or a new skill |
| needed in every session | root `CLAUDE.md` (keep it < 100 lines) |
| a hypothesis | the feature's `plans/` file, marked UNPROVEN |
| a confirmed bug or flaky test not being fixed now | a GitHub issue (repo issues are enabled); link the issue number from the affected note. A plan file is created only when work starts |
| local to one YAML block | a YAML comment only, not also the note (`doc/KNOWLEDGE.md#K-1.1`, K-5) |
| contradicted | delete or strike through where it lives |

One home per fact: other places point to it, never copy it (the only fact with pointers in two
places is a gap: the issue is its home). Keep entries dense and actionable;
skip trivial details.

## 4. No dated logs

Do not append dated "what I did" entries anywhere. Git and PRs are the log.
