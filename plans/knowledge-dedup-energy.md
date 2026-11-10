# Knowledge dedup: energy

**Status:** PLAN ONLY. Follow-up 5 of 5 from PR #141 (knowledge structure, merged).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** satisfied by PR #141 (the `ha-mqtt` skill holds the Loxone empty-payload rule).
Needs `.github/scripts/yaml_semantic_equal.py` (added by PR #144; the
`--ignore-jinja-comments` mode comes with PR #152). Branch
`claude/knowledge-dedup-energy` off `master`.
**Line numbers** below are from `master` `da0d742` (2026-11-07); re-check them first.

**Paths:** the note is `doc/energy/notes.md`.

## Overview
`packages/energy.yaml` has 355 lines. 40 % of its bytes are comments (≈ 1.5k tokens), and almost
all of that is current. Energy stays below the design-doc threshold, so it gets a note only and no
background file. This plan is small; it could be folded into another dedup PR if the user prefers.

## Steps
1. [TODO] `:1-37` header (device map): move it into the note as a table, and keep 3-5 header lines
   plus a note pointer in the YAML.
2. [TODO] `:28-37`, `:198-200` (Loxone: no expire_after, empty payload): reduce to one line plus
   `→ .claude/skills/ha-mqtt/SKILL.md`.
3. [TODO] `:301` "previous source: evcc (removed)": keep as a one-liner.
4. [TODO] Bring the note to the template (all current; check the size).
5. [TODO] Jinja `{# #}` comments: `packages/energy.yaml` has none today (re-count with
   `grep -c '{#' packages/energy.yaml`). If any exist when this plan is run, dedup them with the
   same rules as `plans/knowledge-dedup-jinja-comments.md` (what + one-line why, no history, no
   rules already in `ha-yaml.md` / the `ha-mqtt` skill, no `background.md` pointers).
6. [TODO] Verify. YAML `#`-only edits: `yaml_semantic_equal.py master packages/energy.yaml` must
   pass. If ANY Jinja comment was edited, that check will fail by design; the gate is then
   `.venv/bin/python .github/scripts/yaml_semantic_equal.py --ignore-jinja-comments master packages/energy.yaml`,
   which MUST print `OK` (it proves only comment text changed and no template code was touched;
   a `DIFF` means revert that hunk). Also `ci-local.sh`, `git ls-files --eol`, CI green
   (`tests/test_wallbox.py`). Delete this plan in the PR's last commit.

## Status
- [TODO] Plan only; steps are tracked in the sections above (see the **Status:** line at the top)

## Close
- [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`)
