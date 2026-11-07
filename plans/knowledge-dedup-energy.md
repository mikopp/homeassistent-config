# Knowledge dedup: energy

**Status:** PLAN ONLY. Follow-up 5 of 5 from `plans/claude-knowledge-structure.md` (section 9, D6).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** base plan merged (the `ha-mqtt` skill holds the Loxone empty-payload rule).
Needs `.github/scripts/yaml_semantic_equal.py` (victron plan step 1). Branch
`claude/knowledge-dedup-energy` off `master`.
**Line numbers** below are from `master` `da0d742` (2026-11-07); re-check them first.

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
5. [TODO] Verify: `yaml_semantic_equal.py master packages/energy.yaml`, `ci-local.sh`,
   `git ls-files --eol`, CI green (`tests/test_wallbox.py`). Delete this plan in the PR's last
   commit.
