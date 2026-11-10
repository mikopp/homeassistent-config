# Plan: consistent knowledge behaviour for every agent

## Status
- [DONE] Problem found, first drafts tried and verified for loading, then reverted from `claude/happy-cannon-mxtn3f` on the owner's request, redone on `claude/serene-curie-d36oqw`
- [DONE] Step 0 plan brought to this branch and updated (owner-approved proposal, Steps 0-3)
- [DONE] Step 1 inventory (table below)
- [DONE] Step 2 design (approved by the owner via the proposal, Steps 0-3)
- [DONE] Step 3 implement (results below)
- [DONE] Step 4 end-to-end verification (results below; 21 headless runs, findings OBSERVED)
- [DONE] Review fixes (change list and T2 re-run under "Review fixes" below)
- [TODO] Step 5 close (awaiting owner decision on the Step 4 findings and the open decision below)

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
- **Moments to cover (seven):**
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
4. **More evidence for moment 5:** the check script (Step 3) found 6 of the 8 plans on `master`
   with no Close step: `ci-test-speedups`, `ebusd-pv-heating-optimization`,
   `heating-baseline-and-phase2-prerequisites`, `heating-compressor-cycling`,
   `knowledge-dedup-energy`, `stateful-template-and-automation-tests`. (An early manual count
   said 4.)
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
- Map each of the seven moments to what an agent has in context at that moment today.
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
  | 5 close a plan | only if the plan has a Close step (6 of 8 plans have none) |
  | 6 change a note / rule / skill / design doc | nothing; the `CLAUDE.md` pointer line "Details, limits and how to extend" has no moment attached |
  | 7 change without a plan | `ha-yaml.md` and the package note when a matching file is read; `packages/CLAUDE.md` under `packages/`; nothing for a new package beyond that |

### Step 2 – Design [DONE]
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

- **Result** (one trigger per moment, each pointing to exactly one home):

  | Moment | Trigger (pointer only) | Home |
  |---|---|---|
  | 1 create plan | root `CLAUDE.md` constraint 1 reworded: read `.claude/rules/plans.md` first; `/new-plan` becomes "read that rule and follow it" | new `.claude/rules/plans.md` (`paths: plans/**`) |
  | 2/3 YAML / code + comments | root `CLAUDE.md` constraint 6 reworded in place: what, one-line why, pointer, `doc/KNOWLEDGE.md#K-5` (removes the conflict; also loaded in subagents) | K-5 |
  | 4 bug / confirmed fact | `record-learning` description widened to "found or confirmed a bug, root cause, gotcha or non-obvious fact while working, or closing a plan" | `record-learning` §3 |
  | 5 close plan | `plans.md` "Closing" points to K-6 and `record-learning`; K-6 notes that `plans.md` and the CI check enforce a Close step | K-6 |
  | 6 edit knowledge | new `.claude/rules/knowledge.md`, paths `doc/**/notes.md`, `doc/**/design.md`, `doc/KNOWLEDGE.md`, `.claude/rules/**`, `.claude/skills/**`; root `CLAUDE.md` pointer line reworded | `doc/KNOWLEDGE.md` |
  | 7 change without a plan | 2-line pointer section in `ha-yaml.md` (comments → K-5; found a bug or non-obvious fact → `record-learning`); backstop = reworded constraint 6 + widened skill description | K-5 / `record-learning` |

- **Mechanical check (K-8 enforcement):** `.github/scripts/check_knowledge_layout.py`, stdlib only,
  wired into `ci-local.sh` and `ha_check.yaml` as a cheap early step. It fails if a `plans/*.md` has
  no `## Status` heading or no step/heading with "Close", or if a `packages/*.yaml` has no
  `.claude/rules/packages/<name>.md` symlink resolving to an existing file. No comment-length
  linter: too many false positives for multi-line Jinja.
- **Root `CLAUDE.md` budget:** reword in place, stay at <= 99 lines. The homes table row for rules
  names `plans.md` and `knowledge.md`.
- **`doc/KNOWLEDGE.md`:** K-1 table, K-6 and `record-learning` §3 gain the cross-package topic
  background home `doc/<topic>/background.md` (already guarded by `Read(/doc/**/background*.md)`).
  K-1 rules row lists `plans.md` and `knowledge.md`. **K-3 untouched.**
- **Backfill:** every plan lacking a Status section or a Close step gets one (text unchanged
  otherwise). New note + symlink for `heating_cooling_indicator` (K-3 template), which the check
  would otherwise fail.
- **Verification:** K-7 loading checks for `plans.md`, `knowledge.md`, the changed `ha-yaml.md` and
  the `record-learning` skill; `ci-local.sh`; the new check proven to fail on a plan without Close.

### Step 3 – Implement [DONE]
- Make the approved changes. Every new or changed rule gets the K-7 loading check, and every
  changed skill the K-7 skill check.
- Run `.github/scripts/ci-local.sh` and `git ls-files --eol`.
- Dependencies: Step 2 approved.

- **Result:** implemented as designed in Step 2: `.claude/rules/plans.md`, `.claude/rules/knowledge.md`,
  `/new-plan` reduced to a pointer, root `CLAUDE.md` constraints 1 and 6, pointer line and rules
  row (99 lines), `ha-yaml.md` pointer section, widened `record-learning` description,
  `doc/KNOWLEDGE.md` K-1/K-6/K-8 (K-3 untouched), `.github/scripts/check_knowledge_layout.py` in
  `ci-local.sh` and `ha_check.yaml`, 6 plans backfilled with a Close step (3 others got a Status
  placeholder, removed again in the review fixes), new `doc/heating_cooling_indicator/notes.md` + symlink.
- **Check proven:** removing a plan's Close step, its Status heading, or the
  `heating_cooling_indicator` symlink each made the script exit 1; restored, it exits 0.
- **K-7 loading checks** (fresh headless `claude -p --model haiku --allowedTools Read --max-turns 4`,
  repo root; the workspace-trust warning only ignores `permissions.allow`, rules still load):

  | Rule | No file touched | After reading a matching file | After reading `README.md` |
  |---|---|---|---|
  | `plans.md` | NOT IN CONTEXT | names `check_knowledge_layout.py`, source `.claude/rules/plans.md` (read `plans/ci-test-speedups.md`) | NOT IN CONTEXT |
  | `knowledge.md` | NOT IN CONTEXT | YES, source `.claude/rules/knowledge.md` (read `doc/energy/notes.md`) | NOT IN CONTEXT |
  | `ha-yaml.md` pointer section | NOT IN CONTEXT | YES, source `.claude/rules/ha-yaml.md` (read `packages/pergola.yaml`) | NOT IN CONTEXT |

  Skill (`--allowedTools Read,Skill,Grep,Glob`): the prompt "While editing packages/energy.yaml I
  found that a utility_meter reset silently drops the first sample ... make sure this gets written
  down" invoked `record-learning` without naming it; the unrelated prompt (capital of Austria) did not.

### Step 4 – End-to-end verification [DONE]
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

- **Result** (HEAD 73d8543, fresh scratch clone per run, `claude -p ... --model haiku --allowedTools
  Read,Write,Edit,Glob,Grep,Skill,Task --max-turns 25 --permission-mode acceptEdits`, no hints in
  the prompts; symlinks survived the clone). Haiku was strong enough for every task. All findings
  are **OBSERVED** (3 runs, non-deterministic model), not CONFIRMED.

  | Task | r1 | r2 | r3 | Consistent? |
  |---|---|---|---|---|
  | T1 plan, no `/new-plan` | PASS: `plans/pool-pump-frost-protection.md`, `## Status`, "Knowledge homes updated", Close step; no implementation | PASS (same, `check_knowledge_layout.py` ok) | PASS (same) | yes 3/3 |
  | T2 YAML change with non-obvious why | PASS: K-5 comment + sensor fact in `doc/heating_cooling_indicator/notes.md` (Hardware quirk + Decision) + tests adapted | FAIL: 2-line comment only, note untouched | FAIL: comment with a dangling `→ notes.md` pointer, note untouched | no (1/3) |
  | T3 rename a friendly name | PASS: one-line diff, no comment, no plan | PASS | PASS | yes 3/3 |
  | T4 new package, "implement directly" | PARTIAL: package + `doc/garage_door/notes.md` (K-3 shape) but NO symlink; a plan was created despite "directly"; layout check exit 1 | same (plan `garage-door-open-alert.md`) | same | yes 3/3 (same shortfalls) |
  | T5 confirmed bug, not fixed | PASS: issue drafted, nothing in YAML; asked approval for `gh issue create`, note edit held until the number exists | PASS but differs: issue drafted AND a "Confirmed bug" section already written into `doc/victron/notes.md` with "NOT YET FILED" | PASS: issue drafted, note link held | routing yes 3/3; note timing differs |
  | T6 close a small plan | PASS: fact to `doc/energy/notes.md`, story to new `doc/energy/background.md`, plan deleted; also edited `packages/energy.yaml` history comments (unrequested) | PASS; 3 % drift figure placed in the note as OBSERVED (story-ish) | PASS (cleanest) | yes 3/3 on homes; extras differ |
  | T7 T2 via subagent | NO CHANGE: subagent stopped and asked the owner how to apply the offset | NO CHANGE: same | FAIL: Jinja comment pointing to `doc/KNOWLEDGE.md#K-5` as if it were a content pointer, note untouched | no |

  T2 and T7 adapt the task: the file has no "passive heating" threshold, so the test used the
  real passive-cooling threshold (effective sensor, offset -0.5 °C) with the reason "sensor reads 0.5 °C low".

- **Evidence excerpts:**
  - T2 r1 note diff: `+- The weatherstation outdoor sensor reads about 0.5 °C low in summer (user measurement; ...)` under "Hardware / integration quirks".
  - T2 r2 only diff: `+        # Subtracts 0.5 °C: the weatherstation reads 0.5 °C low in summer (measured), so the passive threshold is lowered ...` and no other file.
  - T2 r3: `# Typed value minus 0.5 °C: the outdoor sensor reads low in summer (measured). → doc/heating_cooling_indicator/notes.md`, note not edited.
  - T7 r3: `{# Sensor reads 0.5 °C low in summer: ... (doc/KNOWLEDGE.md#K-5). #}`.
  - T4: the Write tool cannot create symlinks; the runs had no Bash (a harness limit, see below). All three said so and told the owner the `ln -s` command.

- **Observed failure patterns:**
  1. **Moment 2/3 trigger is weak (T2 2/3, T7 3/3).** When the why is a hardware fact, the agent writes it only as a comment, or adds a pointer to a note it did not edit. The `ha-yaml.md` pointer ("non-obvious fact: invoke `record-learning`") was in context (the file is read before editing) but `record-learning` was not applied in 2 of 3 T2 runs; a measured hardware quirk is apparently not seen as "a bug or non-obvious fact".
  2. **K-5 pointer misuse (T7 r3):** the agent points to `doc/KNOWLEDGE.md#K-5` (the style rule) instead of to a content home.
  3. **Subagents may stop and ask (T7 r1, r2)** instead of making the change; the offset has to touch two sensors and a clamp, so this is a task trait, not necessarily a knowledge failure, but the knowledge behaviour could not be graded for those runs.
  4. **"No plan" is overridden by CLAUDE.md constraint 1 (T4 3/3):** "Implement it directly" still produced a plan file each time. A new package without a plan therefore always carries a plan too. Owner decision needed: is that desired?
  5. **New package symlink (T4 3/3):** note content was right, the symlink was never created in these runs (Write cannot; no Bash allowed). Only `check_knowledge_layout.py` catches it, as designed; whether an agent with Bash creates it was NOT tested.
  6. **Scope creep at close (T6 r1):** edited package comments not asked for. **Story leakage (T6 r2):** a story figure kept in the note. Homes were right in all 3.
  7. **Works consistently:** T1 (plan structure without `/new-plan`), T3 (no comment or plan pollution), T5 routing (issue, not a comment), T6 homes (note / background / delete).

- **Triggers that worked:** `plans.md` via CLAUDE.md constraint 1 (T1 3/3, T4 plan has Status + Close); `record-learning` routing for a user-stated confirmed bug (T5 3/3); K-6 close procedure (T6 3/3); the note template K-3 for a new package (T4). **Not reliable:** the `ha-yaml.md` "Where knowledge goes while you edit" section for a measured fact (T2 1/3, T7 0/3 gradable).

- **Infrastructure notes:** `--allowedTools` without Bash blocked `gh` and `ln -s` (T4, T5: issue drafted but not filed; T6: layout check not run). Headless runs print the workspace-trust warning (`permissions.allow` ignored). Not tested: Bash allowed; sonnet instead of haiku; more than 3 runs; whether a stronger pointer (e.g. in `packages/CLAUDE.md`, loaded on package read) fixes pattern 1. These are options for Step 5, not decisions.

### Review fixes [DONE]
Applied after review of Steps 3 and 4, on this branch:
1. `plans.md`: item 7 is "A last step named `Close`, done per `doc/KNOWLEDGE.md#K-6`" (no
   paraphrase); the bullets restating CLAUDE.md constraints 2-5 and the K-1 GitHub-issue line are
   gone (the latter now points to `record-learning`); only constraint 1 points to the rule.
2. `doc/heating_cooling_indicator/notes.md`: entity map marks the derived IDs `_15min` and
   `_48h_forecast_mean` as unverified; IDs used by working config (grep) stay confirmed; the
   "(sic) in every entity ID" claim is replaced by the one confirmed source sensor.
3. `ha-yaml.md`: one short section "Comments and findings while you edit" replaces the two comment
   sections; it points to K-5, keeps the availability-guard rule, and has the findings trigger
   reworded for the Step 4 failure (a fact only in a comment, or a pointer to a note not edited).
4. `knowledge.md`: K-section prose index dropped; paths gain `doc/**/tests.md` and
   `.claude/commands/**`.
5. `check_knowledge_layout.py`: Close must be a `Close:` step line or a `Close` heading (outside
   fenced code, case-sensitive); Status may be `## Status` or a `**Status:**` line;
   `ha_ci_fixtures` is skipped explicitly.
6. The 3 placeholder Status sections are removed; `knowledge-dedup-jinja-comments.md` got its
   Close as its own step 8 so the stricter check passes.
7. CLAUDE.md constraint 6 now only names the style: "in the style of `doc/KNOWLEDGE.md#K-5`".
8. The indicator note's Related section lists the consumers (pergola, airflow_cooling,
   heating_pv_boost, heating dashboard).
9. This plan's counts corrected (6 Close backfills, 3 Status placeholders removed, seven moments).

**Deliberately skipped review findings:** (12) repeated "record learnings via `record-learning`"
pointers are intended triggers, one per moment; (13) `record-learning` overtriggering was not seen
in Step 4; (16) residual gaps are documented in Step 4 under infrastructure notes.

**OPEN owner decision (not changed):** Step 4 pattern 4. CLAUDE.md constraint 1 makes agents write a
plan file even when told "implement directly" (T4 3/3). Keep that, or allow plan-less work for small
changes?

**K-7 loading checks for the changed rules** (haiku, `--allowedTools Read --max-turns 4`, repo root,
HEAD e9acf3c; OBSERVED): `plans.md` absent with no read, present after reading
`plans/ci-test-speedups.md`, absent after `README.md` (a first README prompt let the agent read the
rule file itself; rerun with "without reading any other file" was absent). `knowledge.md`: absent,
present after `doc/energy/notes.md`, present after `.claude/commands/new-plan.md`, absent after
`README.md`. `ha-yaml.md`: absent, present after `packages/pergola.yaml`, absent after `README.md`.

**T2 re-run after the fixes (OBSERVED, 3 fresh clones of e9acf3c, same command and prompt as
Step 4):** 3/3 PASS, versus 1/3 before. Every run edited `doc/heating_cooling_indicator/notes.md`
with the measured 0.5 °C fact (graded OBSERVED, user measurement) and every YAML comment is a short
what + why; the two comments that point (run 2, run 3) point to the note that was edited.
r1: Known biases entry + compensation line, comment on the input_number and the template offset.
r2: transition lines, cold-start band and Known biases updated; comment `→ doc/heating_cooling_indicator/notes.md`.
r3: Decisions in force + Known biases entries; comment `→ doc/heating_cooling_indicator/notes.md`.
Caveat: 3 runs of one model on one task; T7 (subagent) was not re-run.

### Step 5 – Close [TODO, awaiting owner]
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
