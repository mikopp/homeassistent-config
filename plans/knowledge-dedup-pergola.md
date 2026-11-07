# Knowledge dedup: pergola

**Status:** PLAN ONLY. Follow-up 3 of 5 from `plans/claude-knowledge-structure.md` (section 9, D6).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** base plan step 13 merged. It creates `doc/pergola/{design.md,background.md}`, `doc/sources/pergola/`,
`packages/notes/pergola.md`, `.claude/rules/packages/pergola.md`, and
`plans/pergola-field-calibration.md`. Also needs `.github/scripts/yaml_semantic_equal.py`
(victron plan step 1). Branch `claude/knowledge-dedup-pergola` off `master`.
**Line numbers** below are from `master` `da0d742` (2026-11-07). Re-check them first.

## Overview
`packages/pergola.yaml` is 1723 lines, and 55 % of its bytes (≈ 12.2k tokens) are comments. Only
about 10 % of the comments are history. Most of them restate the design doc: the A_eff derivation,
the 35-line slat dispatch essay, and "plan Step N" references that now point into the archived
step log. The tilt correction is written 6 times; 3 copies say +7, but the code uses 6.

Target: YAML keeps what each block does, a one-line why, and a pointer such as
`# → doc/pergola/design.md#PG-4`.

Expected cost: about 22.2k → about 16.7k tokens per edit (YAML plus the auto-loaded note), with
design read on demand only. No behaviour change.

## Steps

### Phase A: YAML comments (comment-only)
1. [TODO] Per block:
   | Lines | Content | Action |
   |---|---|---|
   | `:1` | "(Phase 1: Foundation)" | replace with a package summary + design link |
   | `:2`, `:14`, `:322` | pointers to deleted `doc/pergola-roof-automation.md` / `doc/pergola-slat-formula-analysis.md` | → `doc/pergola/design.md#PG-n` (`:14` group → note invariants) |
   | `:38-40`, `:93`, `:108`, `:701`, `:781`, `:859` | "plan Step N" refs | point to design IDs (`PG-n`) or drop |
   | `:311-322` | A_eff derivation | 3-5 lines + `→ #PG-4` |
   | `:355-389` | 35-line `slat_angle` dispatch comment | 3-5 lines + `→ #PG-4` |
   | `:529` | "+7 below 20°" | fix to 6 (matches code `:540`, `:1524`) |
   | `:53-63` | states list | keep, include `sun_down` (option at `:74`), pointer `#PG-2` |
   | `:1204`, `:1515-1518` | correction restated | one line + pointer |
2. [TODO] Fix yamllint comment warnings in touched blocks.
3. [TODO] Check that `dashboards/Pergola-management.yaml` and `pergola_card.yaml` comments are
   consistent with the note (card-sync invariant). Comment-only.

### Phase B: flag, do not fix
4. [TODO] `pergola.yaml:398-405` uses `| float(122)`-style defaults on `input_number`, which root
   CLAUDE forbids. This is code, not a comment. Record it in `plans/pergola-field-calibration.md` as
   an open item; the user decides whether to fix it separately (it needs a test run).

### Phase C: verify and close
5. [TODO] `yaml_semantic_equal.py master packages/pergola.yaml` passes; `ci-local.sh` passes;
   `git ls-files --eol` clean; `grep -n "Step [0-9]" packages/pergola.yaml` has no stale plan refs.
   Push; CI green (`tests/test_pergola.py`).
6. [TODO] Close: every removed fact has a home in note or design; delete this plan in the PR's last commit.

## Risks
- Jinja `{# #}` comments inside templates are template text: leave them (the semantic check catches edits).
- The design doc must already hold the corrected formulas (`mow − 5`, correction 6) before the YAML
  points at them. Base step 13 covers this; re-check it.
