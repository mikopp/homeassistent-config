# Plan: consistent knowledge behaviour for every agent

## Status
- [DONE] Problem found, first drafts tried and verified for loading, then reverted from `claude/happy-cannon-mxtn3f` on the owner's request, redone on `claude/serene-curie-d36oqw`
- [DONE] Step 0 plan brought to this branch and updated (owner-approved proposal, Steps 0-3)
- [DONE] Step 1 inventory (table below)
- [TODO] Step 2 design
- [TODO] Step 3 implement
- [TODO] Step 4 end-to-end verification
- [TODO] Step 5 close

## Overview
**Goal: consistent behaviour.** An agent that writes code or YAML must do more than read the
existing knowledge. It must also know, without being told in the moment:
- **when** to put knowledge down: while planning, during a step, at a plan's close, and after
  a bug or a confirmed finding;
- **where** to put it: package note, design doc, skill, rule, YAML comment, background,
  GitHub issue, or plan.

It must do this the same way every time, whether or not the owner calls `/new-plan` or
`record-learning`, and in subagents too.

**Today the conventions are good, but they reach the agent only by chance:**
- `doc/KNOWLEDGE.md` holds the conventions: homes and limits (K-1), current vs background (K-2),
  the note template (K-3), the design-doc threshold (K-4), the YAML comment style (K-5), how to
  extend (K-6), loading checks (K-7) and loading mechanics (K-8). But nothing makes an agent
  read it. Root `CLAUDE.md` only says "Details, limits and how to extend: `doc/KNOWLEDGE.md`",
  with no moment attached. In this session, an agent read that line and still skipped the file.
- The plan structure (knowledge homes, a Close step) lives only in `.claude/commands/new-plan.md`.
  It is used only when the owner types `/new-plan`. A plan created any other way has neither.
- CLAUDE.md constraint 6 ("ALWAYS write comments that describe each part") pushes towards long
  explanatory YAML comments. K-5 limits a comment to what + one-line why + pointer, but K-5 is
  not in view when YAML is edited: `ha-yaml.md` and the package notes do not mention it.
- `record-learning` covers recording a learning, but only when it is invoked.
- K-3 names `tests/test_<pkg>.py`. That is correct on `master`. The move to `tests/ha/` and the
  new `tests/e2e/` exist only on the unmerged test-execution branch, so K-3 stays untouched here:
  the test-execution PR updates its test paths when the tests move.
- There is no home for the background of a cross-package topic. K-1 lists background only per
  package. The test framework (`plans/test-execution.md` Step 5) needs one, e.g. `doc/tests/background.md`.

**Constraint: one home per fact (K-6).** A trigger may only point to the home; it never copies it.
The owner rejected putting the K-5 comment rule into `ha-yaml.md` as a duplicate.

## Architecture / design approach
- **Separate the conventions from the triggers.** Conventions keep one home each (KNOWLEDGE.md,
  the plan conventions, `record-learning`). Triggers are short pointers that fire at the right
  moment and name the K-section to read.
- **Trigger mechanisms available** (K-8):
  - root `CLAUDE.md`, always loaded, but under 100 lines and at 99 now, so lines are reworded in place;
  - path rules, which load on Read/Write/Edit of a matching file (not on Grep/Glob), also in
    subagents;
  - skill descriptions, always listed, with the body loaded when the skill is invoked;
  - commands, only when the user types them;
  - checks (`ci-local.sh`, CI), the only real enforcement.
- **Moments to cover:**
  1. creating a plan;
  2. working through a step (code, YAML, tests);
  3. writing a YAML or code comment;
  4. finding a bug or a confirmed fact;
  5. closing a plan;
  6. creating or changing a note, rule, skill or design doc;
  7. a change without a plan (a new file or an edit to an existing one).
- **Candidate designs**, drafted and reverted in this session; reuse them as input to Step 2,
  not as decisions:
  - `.claude/rules/plans.md` (`paths: plans/**`) as the single source of plan format, status and
    close, with `/new-plan` reduced to "read that rule and follow it", and CLAUDE.md
    constraint 1 saying to read it before creating a plan (a path rule loads too late for a new
    file). The close procedure stays in K-6; the rule points to it.
  - `.claude/rules/knowledge.md` (paths: `doc/**/notes.md`, `doc/**/design.md`,
    `doc/KNOWLEDGE.md`, `.claude/rules/**`, `.claude/skills/**`; notes moved from `packages/notes/`
    to `doc/<pkg>/notes.md` in #151) saying "read `doc/KNOWLEDGE.md`
    first", with a one-line index of the K-sections.
  - The CLAUDE.md pointer line replaced in place by "Before creating, moving or deleting knowledge
    (note, rule, skill, design doc, a plan's close step), read `doc/KNOWLEDGE.md`."
  - The K-7 loading check passed for both rules (absent with no file touched, present after
    reading a matching file, absent after reading `README.md`). Behaviour was NOT tested.
  - Open gap in those drafts: moments 2–4 and 7. Nothing fires when package YAML or code is
    written, so comments and findings can still land in the wrong home.

## What changed since the plan was first written
1. **Notes moved** (#151): they are `doc/<pkg>/notes.md`, symlinked as
   `.claude/rules/packages/<pkg>.md`. The reverted drafts used `packages/notes/**`, which is gone.
2. **Root `CLAUDE.md` is 99 lines**, not 101: reword in place to stay under 100.
3. **K-3 test path is correct on `master`** (`tests/test_<pkg>.py`). `tests/ha/` and `tests/e2e/`
   exist only on the test-execution branch. K-3 stays untouched here; that PR updates its paths.
4. **More evidence for moment 5:** 4 of the 8 plans on `master` have no Close step:
   `ci-test-speedups`, `heating-baseline-and-phase2-prerequisites`, `knowledge-dedup-energy`,
   `stateful-template-and-automation-tests`. (Step 3's check script is the final count.)
5. **A trigger the first version missed:** `packages/CLAUDE.md` is a nested `CLAUDE.md` that loads
   on demand when a file under `packages/` is read, also without a plan. It already says "A new
   package gets a note + symlink rule (K-6)". Yet `packages/heating_cooling_indicator.yaml` has no
   note or symlink. A context-only trigger is not enough: add a mechanical check.

## Moment 7: a change without a plan
An agent that edits YAML ad hoc, with no plan file, never gets the plan triggers (moments 1, 5).
It gets the YAML triggers (2-4) only by chance.

| Case | In context today | Trigger (pointer only) |
|---|---|---|
| existing YAML / template / test (packages, `automations.yaml`, `scripts.yaml`, `configuration.yaml`, blueprints, `custom_templates/`, dashboards, `tests/**/*.py`) | `ha-yaml.md` (its `paths:` cover all of these; Edit needs a prior Read, so it loads before an edit), the package note if one exists | a 2-line pointer section in `ha-yaml.md`: comments → K-5; bug or non-obvious fact → `record-learning`. It points, so the no-duplicate rule holds |
| new package YAML | `ha-yaml.md`, `packages/CLAUDE.md` (note + symlink, K-6); no note exists yet | the same pointer, plus a mechanical check: every `packages/*.yaml` has `.claude/rules/packages/<name>.md`. It fails today for `heating_cooling_indicator`, so this work creates that note + symlink |
| every file (backstop) | root `CLAUDE.md` | reworded constraint 6 (points to K-5) and the widened `record-learning` description, both always loaded, also in subagents |

Step 4 gets an extra behaviour test: "small YAML edit, no plan, no `/new-plan`".

## Steps

### Step 1 – Inventory (read-only) [DONE]
- List every place that states a knowledge convention or a trigger:
  - root `CLAUDE.md` (constraints 1–6, Learnings, Where knowledge lives);
  - `doc/KNOWLEDGE.md`;
  - `.claude/commands/new-plan.md`;
  - `.claude/skills/record-learning/`;
  - `.claude/rules/*.md`;
  - the package notes' Tests and Related sections;
  - `.claude/settings.json` guards.
- Mark each statement as a convention (its home) or a pointer, and list duplicates and conflicts,
  e.g. constraint 6 vs K-5, and the homes table in CLAUDE.md vs K-1.
- Map each of the six moments to what an agent has in context at that moment today.
- Dependencies: none. Output: the tables below.

- **Result** (verified against the files on `master` 204d567):

  | Statement | Lives in | Kind | Conflict / duplicate |
  |---|---|---|---|
  | plan format (overview, steps, status markers, homes, Close step) | `.claude/commands/new-plan.md` only | convention | unreachable without `/new-plan` |
  | status update / summarize / wait for approval | root `CLAUDE.md` 1-5 | convention | partly repeated in `new-plan.md` ("wait for my approval", status markers) |
  | "ALWAYS write comments that describe each part" | root `CLAUDE.md` 6 | convention | conflicts with K-5 (what + one-line why + pointer); K-5 is in view only via `ha-yaml.md`'s Comments section |
  | homes table | root `CLAUDE.md` + K-1 + `record-learning` §3 | 3 copies | `CLAUDE.md` is a summary, `record-learning` is routing (adds the issue/hypothesis/contradicted rows); K-1 is the home |
  | close procedure | K-6 "Every plan's last step" + `new-plan.md` item 7 | 2 copies | item 7 paraphrases K-6 |
  | background guard | `.claude/settings.json` `permissions.ask` + K-1 | convention + enforcement | consistent (prompt, not a wall; Grep not blocked) |
  | new package = note + symlink | `packages/CLAUDE.md`, K-6, `record-learning` §3 | convention | no mechanical check; `heating_cooling_indicator` has neither note nor symlink |
  | YAML comment style | K-5 | convention | `ha-yaml.md` "Comments" section restates it (exists on `master` since #152) |
  | learnings need evidence | root `CLAUDE.md` "Learnings", `record-learning` §1-2 | convention + pointer | the `CLAUDE.md` copy is a pointer |
  | loading check method | K-7, K-8 | convention | none |
  | notes' Tests / Related sections | `doc/<pkg>/notes.md` | package facts | none; K-3 names `tests/test_<pkg>.py`, correct on `master` |

- **Moments → what is in context today:**

  | Moment | In context today |
  |---|---|
  | 1 create a plan | nothing, unless the owner types `/new-plan`; root `CLAUDE.md` 1-5 only |
  | 2 write YAML / code | `ha-yaml.md` (Read before Edit), the package note, `packages/CLAUDE.md`, root `CLAUDE.md` 6 |
  | 3 write a comment | root `CLAUDE.md` 6 ("describe each part"), `ha-yaml.md` Comments section; K-5 itself is not loaded |
  | 4 find a bug / confirmed fact | root `CLAUDE.md` "Learnings" pointer and the `record-learning` description, which says "about to write down a lesson" |
  | 5 close a plan | only if the plan has a Close step (4 of 8 plans have none) |
  | 6 change a note / rule / skill / design doc | nothing; the `CLAUDE.md` pointer line "Details, limits and how to extend" has no moment attached |
  | 7 change without a plan | `ha-yaml.md` and the package note when a matching file is read; `packages/CLAUDE.md` under `packages/`; nothing for a new package beyond that |

### Step 2 – Design [TODO]
- For each moment, choose one trigger that points to exactly one home, with no copied content.
- Decide:
  - where plan conventions live (rule vs skill vs KNOWLEDGE.md section), and how `/new-plan` uses
    them without duplicating them;
  - how moments 2–4 are reached without copying K-5 into `ha-yaml.md`. Options: a pointer line
    in each existing rule; making `record-learning`'s description cover "found a fact or a bug";
    rewording constraint 6 to name K-5;
  - the CLAUDE.md line budget: reword in place, or move lines out;
  - what can be checked mechanically (e.g. a `ci-local.sh` check that every plan has a Close
    step, or a maximum length for YAML comment blocks) versus left to context.
- Include the KNOWLEDGE.md change: a home for cross-topic background (`doc/<topic>/background.md`)
  covered by the existing guard `Read(/doc/**/background*.md)`. K-3 stays untouched.
- Dependencies: Step 1. Output: the design in this plan, approved by the owner before Step 3.

### Step 3 – Implement [TODO]
- Make the approved changes. Every new or changed rule gets the K-7 loading check, and every
  changed skill the K-7 skill check.
- Run `.github/scripts/ci-local.sh` and `git ls-files --eol`.
- Dependencies: Step 2 approved.

### Step 4 – End-to-end verification [TODO]
- In fresh headless sessions on a scratch copy of the repo, with no hints in the prompt, check
  behaviour, not just loading. For each task, check where knowledge landed against KNOWLEDGE.md.
  - Plain prompt "plan feature X", without `/new-plan`: the plan has its knowledge homes and a
    Close step.
  - A small YAML change with a non-obvious why: the comment is in K-5 style, and the fact is in
    the note.
  - A confirmed bug found during a step: it becomes a GitHub issue draft or plan entry, not a
    comment.
  - Closing a small plan: content is distilled per K-6 and the plan deleted.
  - Repeat one task in a subagent.
- Each task runs at least 3 times; consistent means the same homes each time.
- Dependencies: Step 3.

### Step 5 – Close [TODO]
- Close: distil into note/design/skill, story → background, update pointers, delete this plan
  (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes this plan will update
- root `CLAUDE.md`
- `doc/KNOWLEDGE.md` (K-1, K-6, K-8; K-3 untouched)
- `.claude/rules/` (new or changed rules)
- `.claude/commands/new-plan.md`
- `.claude/skills/record-learning/`
- possibly the package notes' Related sections

## Related
- `plans/test-execution.md` (unmerged, branch `claude/happy-cannon-mxtn3f`) Step 5 depends on the
  topic-background home added here. That PR updates the K-3 test paths itself when the tests move.
- The happy-cannon PR should drop its copy of this plan file; this branch owns it.
