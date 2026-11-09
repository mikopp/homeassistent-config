# Plan: consistent knowledge behaviour for every agent

## Status
- [DONE] Problem found, first drafts tried and verified for loading, then reverted from `claude/happy-cannon-mxtn3f` on the owner's request, to be redone here
- [TODO] Step 1 inventory, awaiting approval
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
- K-3 is stale: it names `tests/test_<pkg>.py`, but the tests now live in `tests/ha/test_<pkg>.py`,
  and Step 3 of `plans/test-execution.md` adds `tests/e2e/`.
- There is no home for the background of a cross-package topic. K-1 lists background only per
  package. The test framework (`plans/test-execution.md` Step 5) needs one, e.g. `doc/tests/background.md`.

**Constraint: one home per fact (K-6).** A trigger may only point to the home; it never copies it.
The owner rejected putting the K-5 comment rule into `ha-yaml.md` as a duplicate.

## Architecture / design approach
- **Separate the conventions from the triggers.** Conventions keep one home each (KNOWLEDGE.md,
  the plan conventions, `record-learning`). Triggers are short pointers that fire at the right
  moment and name the K-section to read.
- **Trigger mechanisms available** (K-8):
  - root `CLAUDE.md`, always loaded, but under 100 lines and already at 101;
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
  6. creating or changing a note, rule, skill or design doc.
- **Candidate designs**, drafted and reverted in this session; reuse them as input to Step 2,
  not as decisions:
  - `.claude/rules/plans.md` (`paths: plans/**`) as the single source of plan format, status and
    close, with `/new-plan` reduced to "read that rule and follow it", and CLAUDE.md
    constraint 1 saying to read it before creating a plan (a path rule loads too late for a new
    file). The close procedure stays in K-6; the rule points to it.
  - `.claude/rules/knowledge.md` (paths: `packages/notes/**`, `.claude/rules/**`,
    `.claude/skills/**`, `doc/**/design.md`, `doc/KNOWLEDGE.md`) saying "read `doc/KNOWLEDGE.md`
    first", with a one-line index of the K-sections.
  - The CLAUDE.md pointer line replaced in place by "Before creating, moving or deleting knowledge
    (note, rule, skill, design doc, a plan's close step), read `doc/KNOWLEDGE.md`."
  - The K-7 loading check passed for both rules (absent with no file touched, present after
    reading a matching file, absent after reading `README.md`). Behaviour was NOT tested.
  - Open gap in those drafts: moments 2–4. Nothing fires when package YAML or code is written,
    so comments and findings can still land in the wrong home.

## Steps

### Step 1 – Inventory (read-only) [TODO]
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
- Dependencies: none. Output: a table in this plan.

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
- Include the two KNOWLEDGE.md fixes: K-3 test paths (`tests/ha/`, `tests/e2e/`), and a home for
  cross-topic background (`doc/<topic>/background.md`) covered by the existing guard
  `Read(/doc/**/background*.md)`.
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
- `doc/KNOWLEDGE.md` (K-1, K-3, K-6, possibly K-5 and K-8)
- `.claude/rules/` (new or changed rules)
- `.claude/commands/new-plan.md`
- `.claude/skills/record-learning/`
- possibly the package notes' Related sections

## Related
- `plans/test-execution.md` Step 5 depends on the K-3 path fix and on the topic-background home.
