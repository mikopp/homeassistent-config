# Knowledge dedup: victron

**Status:** PLAN ONLY. Follow-up 1 of 5 from `plans/claude-knowledge-structure.md` (section 9, D6).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** base plan steps 10-13 merged to `master` (conventions in `doc/KNOWLEDGE.md`, guards,
`.claude/rules/packages/victron.md`). Branch `claude/knowledge-dedup-victron` off `master`.
**Line numbers** below are from the analysis at `master` `da0d742` (2026-11-07). Re-check them first.

## Overview
`packages/victron.yaml` is 929 lines; 58 % of its bytes (≈ 8k tokens) are comments, about 40 % of
those history (REPOINTED narratives, CORRECTION stories, "previous formula"). Victron has no design
doc: `plans/victron-ac-referenced-accounting.md` (90 KB, IMPLEMENTED) plays that role and is cited
13× from the YAML and 4× from `tests/test_victron.py`. Goal: one home per fact, following
`doc/KNOWLEDGE.md`:
- `doc/victron/design.md`: accounting model, identities, η gate (current, ≤ 40k chars, IDs `VIC-n`).
- `doc/victron/background.md`: plan revisions, CI fix saga, runbook history, incident stories (`VIC-Bn`).
- `packages/notes/victron.md`: note template, current facts only.
- YAML comments: what + one-line why + `# → doc/victron/design.md#VIC-n` or `# → note:VIC-Nn`.
Expected: Read + note 15.3k → ~10.5k tokens. No behaviour change.

## Steps

### Phase A: tooling
1. [TODO] **Semantic-equality helper** `.github/scripts/yaml_semantic_equal.py <before-ref> <file>`:
   loads `git show <ref>:<file>` and the working copy with a SafeLoader that accepts HA tags
   (`!include`, `!secret`, `!input`, …) as opaque scalars, and asserts both data trees are equal.
   Comment-only edits pass; any change to keys, values or template strings (including `{# #}` Jinja
   comments, which are template text) fails. Reused by all 5 dedup plans. Comments in the script
   explain each part (rule 6).

### Phase B: docs (no YAML)
2. [TODO] **Distil the 90 KB plan.** Current content → `doc/victron/design.md`; history → `background.md`.
   Test each fact: "background deleted tomorrow, can an agent still change victron correctly?"
3. [TODO] **Note to template.** Dated provenance (note `:40` "every key line dates from 2014-2024")
   and snapshot values → background. The 2026-10-17 evidence table stays short (it proves a current rule).
4. [TODO] **Rule paths:** add `doc/victron/design.md` to `.claude/rules/packages/victron.md`.

### Phase C: YAML comments (comment-only)
5. [TODO] Condense or move, per block:
   | Lines | Content | Action |
   |---|---|---|
   | `:1-22` | hardware, Austrian billing, energy flow, sign convention | keep, condense (hardware is in the note) |
   | `:25-45` | expire_after policy | note section; YAML 3 lines + pointer |
   | `:51-61`, `:471-495`, `:677-690` | REPOINTED narratives, migration warnings, kWh reset CORRECTION | background; keep one line "entity_id reused for Energy Dashboard continuity; state ≠ MPPT counter → note" |
   | `:144-145` | "the #126 bug" | keep the rule, drop the story |
   | `:151-160` | vebus current 600 s | 2 lines + note pointer |
   | `:558-562` | "previous formula was…" | background; keep identity `:564-566` |
   | `:620-626` | "grid import/export used to live here" | background |
   | `:698-702`, `:826-845` | attributes / #172847 / declaration-order story | background, **graded UNPROVEN** there; YAML keeps "baselines are declared after their consumers; reordering ⇒ re-run counter-delta tests" (base step 12 already flagged it) |
6. [TODO] Fix yamllint comment warnings in touched blocks.
7. [TODO] **Repoint** the 13 YAML and 4 test references from the plan to `doc/victron/design.md#VIC-n`
   (test edits are comment/docstring only), then `git rm plans/victron-ac-referenced-accounting.md`.

### Phase D: verify and close
8. [TODO] `yaml_semantic_equal.py master packages/victron.yaml` passes; `.github/scripts/ci-local.sh`
   passes; `git ls-files --eol` clean; `grep -rn victron-ac-referenced-accounting` empty; note ≤ 24 KB.
   Push; CI `check_config` + pytest green.
9. [TODO] Close: final check that every removed fact has a home; delete this plan in the PR's last commit.

## Risks
- Facts lost while moving: before deleting a comment, grep the target home for it.
- UNPROVEN mechanism must not become a note fact.
- Large comment-only diff: review with `git diff -w` and the semantic-equality check.
