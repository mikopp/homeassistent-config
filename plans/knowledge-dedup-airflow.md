# Knowledge dedup: airflow_cooling

**Status:** PLAN ONLY. Follow-up 4 of 5 from `plans/claude-knowledge-structure.md` (section 9, D6).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** base plan step 13 merged (`doc/airflow/design.md` with §4 and §7.2 fixed, bypass
section added, `background.md`, `sources/`). Also needs `.github/scripts/yaml_semantic_equal.py`
(victron plan step 1). Branch `claude/knowledge-dedup-airflow` off `master`.
**Line numbers** below are from `master` `da0d742` (2026-11-07). Re-check them first.

## Overview
`packages/airflow_cooling.yaml` is 1494 lines, and 41 % of its bytes (≈ 8.3k tokens) are comments.
Only about 10 % is history. The rest is cross-cutting rules repeated in many blocks:
- the boost edge rule is written 7 times
- the single-decision rule 6 times
- rate invariants 1-3 twice

Target: each rule lives once, in `doc/airflow/design.md` (IDs such as `AF-6`, `AF-7.1`, `AF-7.2`)
or in the note. The YAML keeps the automation `description:` (shown in the HA UI) plus one-line
comments with pointers.

Expected cost: about 22.6k → about 18.7k tokens per edit. No behaviour change.

## Steps

### Phase A: YAML comments (comment-only)
1. [TODO] Per block:
   | Lines | Content | Action |
   |---|---|---|
   | `:1258-1269`, `:1295-1299`, `:1321-1324`, `:1361-1368` | boost edge rule | one-line trigger comments + `→ #AF-7.2`; `description:` `:1278-1286` stays as the summary |
   | `:247-258`, `:1088-1091`, `:1258-1260` | single decision sensor | one copy at `:247` + `→ #AF-6`; others one line |
   | `:1092-1101` | rate invariants 1-3 | 2 lines + `→ #AF-7.1` |
   | `:1287-1289` | why the mode is queued (story) | one-line why; story → background |
   | `:205`, `:423`, `:1331` | "previously inlined", "was an RH gate", "no longer block" | drop (background if not already there) |
2. [TODO] Fix the yamllint comment warnings: `:329`, `:403`, `:558`, `:623` (comments-indentation),
   `:657-659` (missing space), `:683`, `:950`, `:952`, plus any others in touched blocks.
3. [x] DONE in base step 13 (2026-11-07). Note: shrink the "stranded `ventilation_low_needed`" and "(2026-10-23)" incidents to
   one-line whys (story → background); check that the design link is present.
4. [TODO] `custom_templates/airflow_decision.jinja`: leave its 24 `{# #}` lines alone. They are
   template text; changing them belongs to a behaviour PR with tests.

### Phase B: verify and close
5. [TODO] Run each check:
   - `yaml_semantic_equal.py master packages/airflow_cooling.yaml` passes.
   - `ci-local.sh` passes, with fewer comment warnings than before.
   - `git ls-files --eol` is clean.
   - Push; CI is green (`tests/test_airflow.py`).
6. [TODO] Close: every removed fact has a home. Delete this plan in the PR's last commit.

## Risks
- `heating_cooling_indicator.yaml` is out of scope: it is all current and small. Its thresholds
  are documented in design §4 after base step 13.
- `description:` strings are YAML values. Editing them changes the data tree, and the semantic
  check will fail. Only shorten them deliberately, and approve that separately.
