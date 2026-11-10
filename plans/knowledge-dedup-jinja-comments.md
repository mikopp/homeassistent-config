# Knowledge dedup: Jinja comments in already-deduped packages

**Status:** PLAN ONLY. Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** PR #152 (adds `yaml_semantic_equal.py --ignore-jinja-comments` and the comment
style in `doc/KNOWLEDGE.md` K-5 and `.claude/rules/ha-yaml.md`). Branch
`claude/knowledge-dedup-jinja` off `master`, after #152 is merged.
**Counts** below are from branch `claude/dreamy-hopper-jvw4rw` (2026-11-09); re-count first with
`grep -rc '{#' packages custom_templates`.

## Overview
The earlier dedup PRs (victron #144, heating_pv_boost #145, pergola #150, airflow #152) only
touched YAML `#` comments. Jinja `{# #}` comments inside templates were left alone because they
are template text. #152 showed they hold the same kind of duplication (repeated "no default
needed", "was ...", rules already in design/notes). This plan applies the same dedup to them for
the packages that are otherwise done. No behaviour change.

| File | `{#` comments | Notes |
|---|---|---|
| `packages/victron.yaml` | 4 (`:305`, `:331`, `:482`, `:496`) | `float(0)` rationale for expiring MQTT sensors (ha-mqtt skill), "gate identical to ..." pair |
| `packages/heating_pv_boost.yaml` | 3 (`:580`, `:584`, `:848`) | PV net/clamp explanation, boost-season gate with a dated "owner decision 2026-10-30" |
| `packages/heating_cooling_indicator.yaml` | 3 (`:99`, `:104`, `:118`) | thresholds / hysteresis, already in design AF-4; was out of scope of the airflow plan |
| `packages/pergola.yaml`, `packages/energy.yaml` | 0 | nothing to do today; `energy` has its own plan |

## The safety gate (run for every file, every step)
Jinja comments are template text, so editing them changes the YAML data tree. Two checks, and both
MUST pass before a commit:

1. **Render-equivalence (the one that proves the code is untouched):**
   ```bash
   .venv/bin/python .github/scripts/yaml_semantic_equal.py --ignore-jinja-comments master \
     packages/victron.yaml packages/heating_pv_boost.yaml packages/heating_cooling_indicator.yaml
   ```
   Must print `OK` for every file. It strips `{# ... #}` and collapses whitespace in every string,
   then compares the data trees: any change to template code, quoted literals, keys, values or
   statement order prints `DIFF` with the first differing path. **If it reports `DIFF`, stop:
   a code character was touched. Revert that hunk. Never "fix" the check.**
2. **Negative test, once per PR:** temporarily change one template expression (e.g. add
   `float(1)`), confirm the command prints `DIFF`, then revert. This proves the gate works on the
   changed file.

The flag-less `yaml_semantic_equal.py master <file>` is expected to FAIL after a Jinja comment
edit (comment text is data). Do not use it as the gate for this plan. Use it only to confirm YAML
`#`-only edits.

Also run `.github/scripts/ci-local.sh`, `git ls-files --eol` (no `w/crlf`/`i/crlf`), and let CI run
the behavioural tests (`tests/test_victron.py`, `tests/test_heating_pv_boost.py`,
`tests/test_heating_cooling_indicator.py`). Docker-based `check_config` and pytest cannot run
locally.

## Rules for each comment (same as `doc/KNOWLEDGE.md` K-5)
- Keep: what + at most one line of why for a current fact, with a `→ doc/<pkg>/...#ID` pointer
  when the rule is held elsewhere.
- Drop: history ("was", "no longer", dates, "owner decision <date>"), and rules already written
  in `.claude/rules/ha-yaml.md`, the `ha-mqtt` skill, design or notes. Never point to
  `background.md`.
- Before deleting a current fact, confirm the target note/design/skill holds it; if not, add it
  there first (one home per fact). Never promote an unproven claim while moving it.
- Only touch text between `{#` and `#}`. Do not touch `{%`/`{{` lines, quotes or whitespace
  control markers (`{%-`, `-%}`) next to a comment.

## Steps
1. [TODO] Re-count `{#` per file; confirm #152 is merged and the flag exists on `master`.
2. [TODO] `victron.yaml`: dedupe the 4 comments (point the `float(0)` reasoning at the `ha-mqtt`
   skill / note; merge the two "gate identical to ..." comments into one cross-reference). Run the
   gate. Update this plan's status.
3. [TODO] `heating_pv_boost.yaml`: dedupe the 3 comments (PV net/clamp pointer to the design
   section that holds it; drop the dated owner decision, keeping only the current rule). Run the
   gate.
4. [TODO] `heating_cooling_indicator.yaml`: dedupe the 3 comments against design AF-4 (airflow
   design holds the thresholds and hysteresis). Run the gate.
5. [TODO] Run the negative test of the gate (see above), `ci-local.sh`, `git ls-files --eol`.
6. [TODO] Review: one sonnet agent checks that no current fact was lost; a second sonnet agent
   challenges its findings; apply corrections.
7. [TODO] Push; CI green. Close: every removed fact has a home. Delete this plan in the PR's last
   commit.

## Risks
- Whitespace: the check collapses whitespace, so it cannot prove that the exact output whitespace
  of a template is unchanged. The comment-bearing templates here output numbers or booleans that
  HA strips. If a comment sits in a template whose text output matters (notification messages),
  leave it and say so.
- `{#-` / `-#}` markers strip surrounding whitespace in the rendered template. Deleting such a
  comment keeps neighbours' own markers, but keep the marker style of the line when shortening.
- A `DIFF` is always a stop sign: the only edits allowed are inside `{# #}`.

## Status
- [TODO] Plan only; steps are tracked in the sections above (see the **Status:** line at the top)
