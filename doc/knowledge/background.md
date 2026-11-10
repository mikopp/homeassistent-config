# Knowledge consistency: history

Why the knowledge conventions were wired into agent context, how the wiring was tested, and what
is still unproven. All behaviour findings are **OBSERVED** (3 runs per task, one model: haiku,
fresh scratch clones, no hints in the prompts). None is CONFIRMED.

## Why

The conventions (homes, current vs background, note template, comment style, extending, loading)
were good but reached an agent only by chance:
- Root `CLAUDE.md` pointed to `doc/KNOWLEDGE.md` with no moment attached; an agent read the line
  and still skipped the file.
- The plan structure (homes, Close step) lived only in the `/new-plan` command. A plan made any
  other way had neither; 6 of 8 plans on master had no Close step.
- CLAUDE.md constraint 6 ("describe each part") pushed towards long comments, against the
  K-5 limit of what + one-line why + pointer.
- `record-learning` fired only when invoked.
- A new package could lack its note and symlink (`heating_cooling_indicator` did); only a
  mechanical check catches that.
- A cross-package topic (the test framework) had no background home.
Constraint kept throughout: one home per fact; a trigger only points to the home. The owner
rejected copying the K-5 comment rule into `ha-yaml.md`.

## The seven moments and the design (history)

| Moment | Trigger | Home |
|---|---|---|
| 1 create a plan | CLAUDE.md constraint 1: read `.claude/rules/plans.md` first; `/new-plan` reduced to a pointer | `plans.md` |
| 2/3 write YAML/code, comments | constraint 6 names the K-5 style; `ha-yaml.md` pointer section | K-5 |
| 4 find a bug or fact | `record-learning` description widened | `record-learning` |
| 5 close a plan | `plans.md` Close item; layout check fails a plan without Close | K-6 |
| 6 edit knowledge files | `.claude/rules/knowledge.md` on the knowledge paths | `doc/KNOWLEDGE.md` |
| 7 change without a plan | `ha-yaml.md` pointer, constraint 6, skill description, note-symlink check | K-5 / `record-learning` |

Enforcement: `.github/scripts/check_knowledge_layout.py` (in `ci-local.sh` and CI): plan has
Status and Close, every package has a symlinked note. No comment-length linter (false positives on
multi-line Jinja). K-3 was left untouched on purpose: its test paths are right on master and the
test-execution branch updates them when the tests move.

## Step 4 behaviour matrix (OBSERVED)

Command: `claude -p ... --model haiku --allowedTools Read,Write,Edit,Glob,Grep,Skill,Task
--max-turns 25 --permission-mode acceptEdits`, one fresh clone per run, 3 runs per task.

| Task | Result |
|---|---|
| T1 plan without `/new-plan` | 3/3: Status, knowledge homes, Close step, no implementation |
| T2 YAML change with a non-obvious why | 1/3: failures were a comment only, and a comment with a pointer to a note not edited |
| T3 rename a friendly name | 3/3: one-line diff, no comment, no plan |
| T4 new package, "implement directly" | 3/3 same shortfalls: note right, symlink missing, plan created anyway |
| T5 confirmed bug, not fixed | routing 3/3 (issue drafted, nothing in YAML); one run wrote the note section early |
| T6 close a small plan | homes 3/3 (note, background, delete); extras differ (unrequested comment edits, a story figure kept in the note) |
| T7 T2 via subagent | 0/3 gradable: two stopped to ask, one used the K-5 anchor as a content pointer |

T2/T7 used the real passive-cooling threshold with the reason "sensor reads 0.5 C low".

Failure patterns:
1. Moment 2/3 trigger weak for a measured hardware fact (T2, T7).
2. K-5 pointer misuse: pointing at the style rule instead of a content home (T7).
3. Subagents may stop and ask; a task trait, so knowledge behaviour was not gradable.
4. Constraint 1 overrode "implement directly" (T4 3/3), which led to the owner decision below.
5. Symlink never created: the Write tool cannot, and the runs had no Bash. Only the layout check
   catches it.
6. Scope creep and story leakage at close (T6), homes still right.
Worked: T1, T3, T5 routing, T6 homes, K-3 shape for a new package.
Infrastructure: without Bash, `gh` and `ln -s` were blocked (issues drafted, not filed).

## Review findings

Applied: `plans.md` stopped paraphrasing constraints and K-6; indicator note marks derived IDs
unverified; one short "Comments and findings while you edit" section in `ha-yaml.md`;
`knowledge.md` dropped its K-section index and gained `doc/**/tests.md` and `.claude/commands/**`
paths; stricter layout check (Close as a step line or heading outside code fences, Status as
heading or `**Status:**` line, `ha_ci_fixtures` skipped); placeholder Status sections removed;
constraint 6 reduced to naming the style; counts corrected.
Skipped: repeated "record via `record-learning`" pointers (one per moment is intended);
`record-learning` over-triggering (not seen in Step 4); residual gaps (listed below).

## T2 re-run (OBSERVED)

After rewording the `ha-yaml.md` findings trigger to name the concrete case (measured value,
hardware quirk, user-supplied reason), T2 went from 1/3 to 3/3: every run edited the indicator
note with the 0.5 C fact and wrote short what + why comments, pointing only to the note it
edited. 3 runs, one model, one task. T7 was not re-run.

## Owner decisions

- Small ad-hoc work needs no plan: constraint 1 now limits plans to feature work. Knowledge from
  plan-less work reaches its home via moment 7. Not re-tested headless.
- Commit trailers are left as they are (squash merge).
- The plan copy was dropped from `claude/happy-cannon-mxtn3f`; its `plans/test-execution.md` now
  points at `doc/<topic>/background.md` and owns the K-3 test-path fix.

## Untested / UNPROVEN

- T7 (subagent) variant after the findings-trigger fix.
- Symlink creation by an agent with Bash allowed.
- Headless re-test of the reworded CLAUDE.md constraint 1 (plan-less small work).
- Sonnet instead of haiku.
- More than 3 runs per task.
