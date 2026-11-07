# Claude knowledge structure: rules, `@` imports, topic skills

**Status:** PLAN ONLY. Approved to start in a NEW Claude session (user, 2026-11-07); each step
still needs the usual step-by-step approval (root CLAUDE rules 2-5).
**Model:** `mikopp/homeassistant-innova-hrds` (path-scoped `.claude/rules/`, one home per topic,
"Where to find what" table). Analysis done 2026-11-07 (read-only; docs read at
code.claude.com/docs/en/memory and /skills on that day).
**Base:** branch off `master` once the victron notes cleanup (commit `a19711d` "remove old victron
plan" on `claude/loving-ride-3gd5zm`: `packages/notes/victron.md`, `packages/victron.yaml`
comment, deletion of `plans/victron-accumulator-gating-and-expiry-fixes.md`) has landed. Check
`git log origin/master` first; if `a19711d` (or its squash) is not there, ask the user whether to
build on `claude/loving-ride-3gd5zm` instead. The victron note's new "Venus OS MQTT publishes on
CHANGE only" section is package knowledge and stays in the note (not a skill).

### Self-contained: this plan is everything the new session needs
No context from the session that wrote it is required. Everything below was gathered there:
reference-repo study (section 2a), doc facts (section 2), file sizes and the entry-by-entry
mapping (sections 1 and 4). To re-check the reference repo, clone it into the scratchpad:
`gh repo clone mikopp/homeassistant-innova-hrds <scratchpad>/ref` (user's own repo, read only).
Before starting, read: root `CLAUDE.md`, `packages/CLAUDE.md`, `.claude/learnings.md`,
`.claude/skills/yaml/SKILL.md`, all `packages/notes/*.md` (they are the material being moved).

---

## 0. Status

| # | Step | Status |
|---|---|---|
| 0 | Canary: prove `@` imports in a path-scoped rule load, and only on a matching read | [x] DONE 2026-11-07: A FAILED (import loads eagerly), B WORKS → **symlink fallback** (section 7.1) |
| 1 | `git mv CLAUDE.MD CLAUDE.md` + fix references | [x] DONE 2026-11-07 (plain `git mv` worked; refs fixed in `packages/CLAUDE.md`, `plans/ci-test-speedups.md`, `plans/victron-ac-referenced-accounting.md`) |
| 2 | `.claude/rules/ha-yaml.md` (HA YAML / MQTT rules moved out of root) | [x] DONE 2026-11-07, verified: headless `claude -p` loads ha-yaml.md after reading `packages/energy.yaml`, not with no read or after `README.md` |
| 3 | `paths:` frontmatter in each note + `.claude/rules/packages/<pkg>.md` symlink to it (no `@` imports, see 7.1) | [x] DONE 2026-11-07, verified (headless, section 10 method) |
| 4 | Move package learnings into notes; de-duplicate | [ ] TODO |
| 5 | Topic skills; move topic learnings; `.claude/rules/tests.md` pointer | [ ] TODO |
| 6 | `record-learning` skill; slim root `CLAUDE.md`; slim `packages/CLAUDE.md` | [ ] TODO |
| 7 | Fix `yaml` skill conflict (`float(0)` defaults) | [ ] TODO |
| 8 | Delete `.claude/learnings.md`; repoint all references | [ ] TODO |
| 9 | Verify in a fresh session (`/context`, `/memory`) + `git ls-files --eol` | [ ] TODO |
| 10 | Knowledge-home conventions (`doc/KNOWLEDGE.md`): current/background test, layout, note template, heading IDs, comment style, size limits. Runs after step 3, before step 6 | [ ] TODO |
| 11 | Guards: `permissions.ask` on background/sources, root-table line, `doc/<pkg>/design.md` in rule `paths:` | [ ] TODO |
| 12 | Fix stale pointers (heating YAML → note, airflow doc §10, victron UNPROVEN comment) | [ ] TODO |
| 13 | `doc/` restructure (docs only, no YAML): pergola + airflow → `design.md` / `background.md` / `sources/`; pergola note + rule | [ ] TODO |
| 14 | Write follow-up plans `plans/knowledge-dedup-<pkg>.md` (victron, heating-pv-boost, pergola, airflow, energy); NOT executed here | [x] DONE 2026-11-07 |

Branch: `claude/knowledge-structure`, rebased onto `origin/master` `da0d742` (#140, CI on Python
3.15). The victron cleanup landed via squash-merged PR #138, so `a19711d` is not on master by hash
but its content is.

Local tooling (since #140): `.github/scripts/ci-local.sh` (yamllint, style fixer, resolved-config
lint, template extraction; `.venv` from `.github/workflows/requirements.txt`, Python 3.15.2,
yamllint 1.38.0). Passed on the rebased branch 2026-11-07. `check_config` + pytest need Docker and
run in CI only (no Docker/pytest locally). Every step that touches YAML runs `ci-local.sh`.
- #140 added a "Local CI checks" section to root `CLAUDE.MD`: it stays in root CLAUDE.md (always
  needed before pushing). Root rule 8 still says "dev machine is Windows"; it is macOS now. Keep
  the LF rule, fix the wording in step 6.
- yamllint already warns on comments today (e.g. `airflow_cooling.yaml:329,403,558,623`
  comments-indentation, `:657-659` missing space). The per-package comment-dedup plans fix these
  warnings in the blocks they touch.

---

## 1. Problem today

| File | ≈ tokens | Loads |
|---|---|---|
| `CLAUDE.MD` | 2.3k | always |
| `.claude/learnings.md` | 5.1k | "read before complex tasks" → in practice almost always |
| `packages/CLAUDE.md` | 0.4k | when a `packages/` file is touched |
| `packages/notes/<pkg>.md` | 0.6-5.9k | only if Claude obeys "read the note first" |

- learnings.md mixes general rules, package facts, topic facts (test harness, templates, energy,
  MQTT) and a dated Log that is history. All of it is paid for even when irrelevant.
- Notes depend on compliance, not on the loader.
- Duplicates: "one decision sensor" (learnings + airflow note), "REST-seeding delayed sensor"
  (learnings + airflow note), "verify via source at tag" (learnings + CLAUDE version gate), package
  list (root CLAUDE + `packages/CLAUDE.md`; root list is stale: 2 of 6 packages).
- Conflict: `.claude/skills/yaml/SKILL.md` says "ALWAYS use `| float(0)`" and uses `| float(16)` on
  `input_number`; root CLAUDE forbids both.
- Root file is tracked as `CLAUDE.MD`. Works on macOS (case-insensitive FS); on Linux (cloud
  sandbox, CI) it may not load. Not verified.

Typical cost before → after (estimate): always 2.35k (really ~7.5k with learnings) → **~1.7k**;
victron edit ~9.3k → ~4.2k; heating_pv_boost edit ~13.7k → ~8.6k (~5.6k with register split).

---

## 2. Claude Code mechanics this relies on

Documented (2026-11-07):
- `.claude/rules/**/*.md` without `paths:` load at launch; with `paths:` they load when Read/Write/
  Edit (or a single-file `cat`/`head`) touches a matching file. Grep/Glob do NOT trigger.
  Globs are relative to the repo root, `**` and `{a,b}` work. Broken frontmatter = always loaded.
- On-demand files (path rules, nested CLAUDE.md and their imports) are truncated above 40k chars
  (200K context).
- `@path` imports: relative to the importing file, max 4 hops, not inside backticks/code blocks.
  Imports do not save tokens by themselves; they load with the importing file.
- Skills: only name + description are always in context (~1 % of window shared); body loads on
  invocation. Skills support `paths:` too.

NOT documented, must be tested (step 0):
- **Whether `@` imports inside `.claude/rules/*.md` are expanded at all**, and whether a path rule's
  imports wait until the rule loads. The model repo does not use imports.
- Whether a skill's `paths:` auto-invokes the body or only makes it eligible.
- Whether path rules load inside subagents.

**Fallback if step 0 fails (user decision 2026-11-07): symlink.** The note stays the real file in
`packages/notes/<pkg>.md`; `.claude/rules/packages/<pkg>.md` becomes a relative symlink to it
(`ln -s ../../../packages/notes/<pkg>.md .claude/rules/packages/<pkg>.md`), and the `paths:`
frontmatter moves to the top of the note itself (the note then IS the rule). Known catch, recorded
in the model repo's ADR-0001: on a Windows checkout without `core.symlinks=true` (and Developer
Mode / admin), git writes the symlink as a small text file holding the target path, so the rule
loads as junk there. Current dev machine is macOS, so accepted; if Windows comes back, set
`git config core.symlinks true` before cloning. Canary step 0 tests the symlink variant too, so
the fallback is proven, not assumed.

## 2a. Reference repo facts (mikopp/homeassistant-innova-hrds, read 2026-11-07)

- Root `CLAUDE.md` (8 KB): summary, "Decisions are ADRs", one-line invariants citing ADR ids,
  code map, "Where to find what" table (one home per topic, linked, never restated; its ADR-0027).
- Nested `tests/CLAUDE.md`, `tests/ha/CLAUDE.md`, `tests/e2e/CLAUDE.md` (load when that dir is touched).
- `.claude/rules/` only path-scoped files, e.g. `entities.md` (`paths:` const.py, installer_params.py,
  translations/*.json), `changelog.md`, `adr-topics.md` (generated topic -> ADR-id map, ~450 tokens).
- `.claude/rules/adr/NNNN-*.md`: 31 accepted ADRs as real files, each with its own `paths:`
  (other frontmatter keys `status/date/decision-makers/topics` are only for its `tests/adr_check.py`).
  Brace globs used, e.g. `.../{sensor,binary_sensor,switch}.py`.
- `doc/adr/`: generated `README.md` index, `accepted` (symlink to `.claude/rules/adr`, browse only),
  `proposed/`, `superseded/` (never loaded; `.claude/settings.json` `permissions.ask` on reading them).
- Skills `adr` and `release-prep`; ADR bodies kept < 90 lines because they load on every governed read.
- No `@` imports anywhere. ADR-0001: "verified on Claude Code 2.1.306: a rule with paths loads when a
  matching file is read or created, not before"; symlinks into `.claude/rules` break on Windows.

---

## 3. Target structure

```
CLAUDE.md                          # renamed; general rules only (~5 KB, <100 lines)
packages/CLAUDE.md                 # only: "new package => note + rule"; index table removed
packages/notes/<pkg>.md            # stay where they are; absorb package learnings
.claude/rules/
  ha-yaml.md                       # path rule: helper/template/device-key + MQTT id rules
  tests.md                         # path rule: "invoke ha-test-harness skill before editing"
  packages/airflow-cooling.md      # path rule + @import of the note
  packages/energy.md
  packages/heating-pv-boost.md
  packages/victron.md
.claude/skills/
  yaml/SKILL.md                    # existing; conflict fixed
  ha-test-harness/SKILL.md
  ha-templates/SKILL.md
  ha-energy-metering/SKILL.md      # incl. entity migration / deploy runbook (merged, see D3)
  ha-mqtt/SKILL.md
  record-learning/SKILL.md         # learning workflow + evidence grades + routing table
.claude/learnings.md               # DELETED
```

**SUPERSEDED by the canary (7.1): the `@` import below loads eagerly. Real layout: the note itself
starts with this `paths:` frontmatter and `.claude/rules/packages/victron.md` is a symlink to it.**
Original example package rule (`.claude/rules/packages/victron.md`):

```
---
paths:
  - "packages/victron.yaml"
  - "tests/test_victron.py"
  - "plans/victron-*.md"
---
Victron package knowledge (loaded because a victron file was touched):
@../../../packages/notes/victron.md
```

The note itself is NOT in `paths` (would double-load). Path lists per package:
- airflow_cooling: `packages/airflow_cooling.yaml`, `custom_templates/airflow_decision.jinja`,
  `tests/test_airflow.py`, `dashboards/airflow-dashboard.yaml`. Links (not imports)
  `doc/airflow-cooling-architecture.md` (25 KB).
- energy: `packages/energy.yaml`, `tests/test_wallbox.py`.
- heating_pv_boost: `packages/heating_pv_boost.yaml`, `tests/test_heating_pv_boost.py`,
  `dashboards/heating-dashboard.yaml`, `plans/heating-*.md`, `plans/ebusd-*.md`.
- pergola / heating_cooling_indicator: no note, so no rule yet. Never import
  `doc/pergola-roof-automation.md` (71 KB > 40k limit).
(Exact dashboard/test file names to be confirmed with `ls` at implementation.)

`ha-yaml.md` paths: `packages/**/*.yaml`, `automations.yaml`, `scripts.yaml`,
`configuration.yaml`, `blueprints/**/*.yaml`, `custom_templates/**`, `dashboards/**`,
`tests/**/*.py` (MQTT entity-id rule matters in dashboards and tests).

---

## 4. Where every piece of content goes

### Root `CLAUDE.MD` → split
| Section | Goes to |
|---|---|
| Constraints 1-8 (incl. LF) | stays |
| HA version gate | stays, + one line "verify against source: `gh api repos/home-assistant/core/contents/<path>?ref=<tag>`" (absorbs the learnings duplicate) |
| MCP read-only | stays |
| Config structure | stays, without the stale package list |
| Persistent Memory | replaced by 3-line hard rule ("never write an unconfirmed learning; hypotheses go to `plans/`; use `/record-learning`") |
| new | "Deploy/migration docs come from `git diff origin/master...HEAD`, never the live system" |
| new | "Where knowledge lives" table: rules (by path) / notes (via rules) / skills (by topic) / `plans/` (hypotheses, open work) / `doc/` (design docs) |
| Helper rules, template sensor rules, template `device:` key | `.claude/rules/ha-yaml.md` |
| MQTT unique_id ≠ entity_id | short form in `ha-yaml.md`, full form in `ha-mqtt` skill |

### `.claude/learnings.md` → split, then delete
| Entry | Goes to |
|---|---|
| Evidence-grade header (CONFIRMED/OBSERVED/UNPROVEN) | `record-learning` |
| W→kWh accumulator; cross-tick baseline sibling (UNPROVEN); identical-value `set_state()`; custom `attributes:` (UNPROVEN); generic "one decision sensor" + "`variables:` render once"; `skip_condition` production consequence | `ha-templates` |
| `platform: integration` semantics; integration rejects device/state_class; integration total in memory; `purge_keep_days` ≠ LTS (from Log) | `ha-energy-metering` |
| Repointing an entity across platforms (runbook); derive deploy docs from branch diff (full) | `ha-energy-metering` (migration section) |
| MQTT `value_template` empty payload | `ha-mqtt` |
| All Test Harness patterns + anti-patterns; Docker cloud sandbox proxy CA + libfaketime (from Log); "check whether the harness is at fault first" | `ha-test-harness` |
| "One decision sensor" airflow specifics; `set_state()` pins in `test_airflow.py` latent fragility (from Log); clock-order dependency one-liner | `packages/notes/airflow_cooling.md` (de-duplicated) |
| `delay_off` clock dependency one-liner | `packages/notes/heating_pv_boost.md` |
| Pergola year-jump hang (DISPROVED) | dropped (already in `plans/ci-test-speedups.md`) |
| Log section (dated history) | dropped; git history keeps it (see D2) |
| "Verifying via source at tag" | merged into root version gate |

### Other fixes
- `packages/heating_pv_boost.yaml:183` comment cites ".claude/learnings.md, MQTT empty payload"
  → repoint to `.claude/skills/ha-mqtt/SKILL.md`.
- Plans citing learnings.md (`ci-test-speedups`, `heating-baseline-...`,
  `victron-multiplus-true-dc-power`, `victron-ac-referenced-accounting`): repoint to
  `record-learning` / the new homes (text-only).
- `yaml` skill: defaults only when there is no `availability:` guard, never on helpers; fix the
  `input_number | float(16)` examples; description adds "general style; project rules in
  `.claude/rules/ha-yaml.md`".
- `packages/CLAUDE.md` says "root `CLAUDE.MD`" → fix with the rename.

### Skill descriptions (first words carry the trigger)
- `ha-test-harness`: "Gotchas for this repo's pytest + ha_integration_test_harness suite (Docker HA,
  mocked clock, REST set_state seeding). Use when writing, debugging or reviewing tests/*.py,
  conftest.py, CI test steps, flaky/hanging CI, fast_forward/jump_to_next, pytest-timeout."
- `ha-templates`: "Runtime semantics of HA template sensors/automations at the pinned version:
  trigger vs state-based, this.state self-reference, re-render/propagation, variables,
  automation.trigger conditions. Use when designing or debugging template:/automation logic; not
  for YAML style (see yaml)."
- `ha-energy-metering`: "Power→energy sensors, Energy Dashboard and entity migration: integration
  platform semantics, W→kWh accumulators, long-term statistics, moving an entity across platforms,
  deploy runbooks. Use when adding/changing kWh/Riemann/utility_meter sensors or a
  unique_id/platform/entity_id."
- `ha-mqtt`: "MQTT sensors in this repo: unique_id vs entity_id/default_entity_id lookup,
  value_template empty-payload handling, expire_after. Use when adding or referencing an MQTT
  entity or writing its value_template."
- `record-learning`: "Record a proven learning/gotcha after a bug or feature. Use when about to write
  down a lesson, pattern, anti-pattern or root cause." Body: full "NEVER write an unconfirmed
  learning" text, evidence grades, routing table (package fact → note, create note + rule if
  missing; topic fact → matching skill or new skill; always-needed → root CLAUDE.md; hypothesis →
  `plans/`; contradicted → delete where it lives), "no dated logs; git/PRs are the log".

---

## 5. Decisions for the user

- **D1 ADRs:** recommend NOT adopting the ADR system now (needs `adr_check.py` tooling; design
  rationale here lives in `doc/` and `plans/`). Adopt only the cheap parts: one home per topic,
  "Where to find what" table, short path rules.
- **D2 Log section:** drop it (git keeps it) vs archive to `doc/archive/learnings-log-2026.md` with a
  `permissions.ask` guard on reads. Recommend drop.
- **D3 Skill count:** merge entity migration into `ha-energy-metering` (5 new skills) vs separate
  `ha-entity-migration` (6). Recommend merge.
- **D4 heating_pv_boost note (23.5 KB):** split register decodes into
  `packages/notes/heating_pv_boost-registers.md` (not imported, grep-able) vs keep whole. Recommend
  split (separate step, after this plan).
- **D5 Tests:** pointer rule `.claude/rules/tests.md` (deterministic) in addition to the skill's
  description. Recommend yes.

## 6. Risks

1. `@` in rules undocumented → step 0 canary first; fallback is a symlinked note (section 2).
2. Grep/Glob never trigger rules; a task that only searches gets no note until a file is read.
3. Skill auto-trigger by description is not guaranteed → pointer rules where it matters.
4. Path rules in subagents unknown.
5. Rename `CLAUDE.MD` → `CLAUDE.md` on a case-insensitive FS needs `git mv` (two-step if git
   refuses: `git mv CLAUDE.MD tmp && git mv tmp CLAUDE.md`).
6. Rules are context, not enforcement (LF rule could become a pre-commit/CI check; out of scope).

## 7. Step 0 canary (detail)

Rules are discovered at session start, so the canary needs TWO sessions: the implementing session
creates the files, the user then opens a SECOND fresh session to test. Do not commit the canary.

1. Variant A (`@` import):
   - `scratch-canary/a-trigger.txt` (any text), `scratch-canary/a-note.md` holding token
     `CANARY-A-7f3k` and nothing else that hints at it.
   - `.claude/rules/zz-canary-a.md`: frontmatter `paths: ["scratch-canary/a-trigger.txt"]`, body
     `@../../scratch-canary/a-note.md`.
2. Variant B (symlink fallback):
   - `scratch-canary/b-note.md` with frontmatter `paths: ["scratch-canary/b-trigger.txt"]` and token
     `CANARY-B-9q2m`; `scratch-canary/b-trigger.txt` any text.
   - `ln -s ../../scratch-canary/b-note.md .claude/rules/zz-canary-b.md`.
3. In the second session the user runs `/context` (or `/memory`): neither note may appear. Then asks:
   "Read scratch-canary/a-trigger.txt and tell me any CANARY token in your context, without reading
   other files", and the same for `b-trigger.txt`. Optionally repeat via a subagent (risk 4).
4. Outcomes: A works → use imports (section 3). A fails, B works → symlink fallback. Both fail →
   stop and ask the user.
5. Delete `scratch-canary/` and both `zz-canary-*` rules. Record the result in this plan (it is a
   CONFIRMED mechanism and goes into `record-learning`'s notes on how the structure works).

### 7.1 Canary result (CONFIRMED 2026-11-07, Claude Code session on Sonnet 5.5, macOS)
Second fresh session, user-run, screenshots reviewed:
- **Variant A (`@` import in a `paths:` rule): FAILS the goal.** `/memory` at session start already
  listed `scratch-canary/a-note.md` as "@-imported" under Project instructions, and the session
  reported `CANARY-A-7f3k` as loaded at start, before any matching read. Reading `a-trigger.txt`
  then showed "Loaded .claude/rules/zz-canary-a.md" (the rule body itself is lazy). So `@` imports
  inside a path rule are expanded eagerly at launch: no token saving, the note is always paid for.
- **Variant B (symlink note with its own `paths:` frontmatter): WORKS.** Not present at start;
  reading `b-trigger.txt` showed "Loaded scratch-canary/b-note.md" and `CANARY-B-9q2m` appeared.
- Not tested: path rules inside subagents (risk 4) stays open; re-check in step 9.
- Canary files deleted (never committed).

**Consequence for steps 3, 10, 11 and section 3:** use the symlink layout. Each note
`packages/notes/<pkg>.md` gets the `paths:` frontmatter at its top (it IS the rule);
`.claude/rules/packages/<pkg>.md` is a relative symlink
`ln -s ../../../packages/notes/<pkg>.md .claude/rules/packages/<pkg>.md`. Never use `@` imports in
any rule. `doc/KNOWLEDGE.md` and `record-learning` state this ("new package note = note with
`paths:` + symlink"). Windows caveat from section 2 applies (`core.symlinks=true`).
Also: `ha-yaml.md` and `tests.md` are ordinary rule files (no import needed). The follow-up plans'
"rule paths: add `doc/<pkg>/design.md`" means editing the note's frontmatter.

## 8. Open decisions to confirm at the start of the new session

**DECIDED 2026-11-07: D1-D8 all as recommended** (no ADRs; drop Log; merge migration into
`ha-energy-metering`; split heating registers (in its follow-up plan); `tests.md` pointer rule;
per-package dedup follow-ups; `permissions.ask`; conventions in `doc/KNOWLEDGE.md`). Step 10 also
updates `.claude/commands/new-plan.md` so every new plan reads `doc/KNOWLEDGE.md` and ends with the
"distil, update pointers, delete plan" step. The symlink fallback (section 2) is decided. Decided by the user (2026-11-07):
history/analysis that is not needed for the current design goes into a per-package background file
that agents do not read by default.

---

## 9. Design docs, YAML comments, current vs background (analysis 2026-11-07)

Read-only subagent analysis of `doc/`, all package YAML and the notes. Measured, ~4 chars/token.

### 9.1 Findings
| Package | Comment share of YAML | ≈ comment tokens / file | Share that is history | Design doc | Note |
|---|---|---|---|---|---|
| pergola | 55 % | 12.2k / 22.2k | ~10 % (rest restates doc) | 71 + 19 KB + 49 KB transcript | none |
| victron | 58 % | 8.0k / 13.9k | ~40 % | none; 90 KB IMPLEMENTED `plans/victron-ac-referenced-accounting.md` acts as one (13 YAML + 4 test refs) | 5.7 KB |
| heating_pv_boost | 48 % | 7.4k / 15.5k | ~25 % | none (note + `plans/ebusd-*`) | 23.5 KB |
| airflow_cooling | 41 % | 8.3k / 20.1k | ~10 % | 25 KB + bypass 5 KB, linked from nowhere | 5.7 KB |
| energy | 40 % | 1.5k / 3.9k | ~5 % | none | 2.4 KB |
| heating_cooling_indicator | — | 0.6k / 2.1k | ~0 | airflow doc §4 | none |

- Same fact in 2-7 places, and the copies have drifted: airflow boost-edge rule ×7 (doc §7.2 lacks
  #136 edges); single decision sensor ×6; pergola tilt correction ×6, 3 copies say +7 but code uses
  6 (`pergola.yaml:529` vs `:540`, `:1524`; `doc/pergola-roof-automation.md:16,459`;
  `doc/pergola-slat-formula-analysis.md:354`); A_eff ×3; vebus expire 600 s ×3; Loxone empty payload ×3.
- Stale: heating YAML `:8,:36,:299,:899` cite `packages/CLAUDE.md` (now the note); airflow doc §4
  hard-codes 5/6,10/11,15/16 °C (now helpers, `heating_cooling_indicator.yaml:28-31`), §10 points to
  `packages/CLAUDE.md`; pergola doc misses `sun_down`, says "no buffer" (YAML uses `mow − 5`),
  "25 %/50 %" drain (YAML 8°/15°), title still "Implementation Plan"; `pergola.yaml:1` "Phase 1" and
  "plan Step N" refs (`:38-40,:93,:108,:701,:781,:859`).
- Wrong claim in production YAML: `victron.yaml:838-843` states the declaration-order/#172847
  mechanism as fact; learnings grades it UNPROVEN.
- Code (not comment) conflict to note, not fix here: `pergola.yaml:398-405` `| float(122)` on helpers.

### 9.2 Current vs background: the test
- **Current** = what an agent needs to understand or change the package as it runs today
  (behaviour, invariants, formulas in force, hardware facts, entity map, open issues) + decisions
  still in force with a 1-2 line why.
- **Background** = history, CORRECTION/REPOINTED stories, dated STATUS entries, superseded designs,
  step logs, dropped alternatives, investigation logs, derivation work, snapshot values of one day.
- **Sources** = raw material never edited: LLM transcripts, spreadsheets, raw LLM answers.
- Test: "if background were deleted tomorrow, could an agent still change the package correctly?"
  If no, the fact is current and must not live only in background. A decision in force keeps its
  short why in note/design + link `(story → background.md#VIC-B2)`.

### 9.3 Layout and roles
```
packages/notes/<pkg>.md      # auto-loaded via path rule; current; ≤ 24 KB (~6k tokens); fixed template
doc/<pkg>/design.md          # current architecture/derivation results; on demand; ≤ 40k chars; stable IDs
doc/<pkg>/background.md      # history/alternatives/investigations; guarded; IDs <PKG>-B<n>
doc/<pkg>/sources/           # transcripts, xlsx, raw LLM answers; guarded; never edited
packages/<pkg>.yaml comments # what the block does + ≤1 line why + pointer "# → doc/<pkg>/design.md#PG-4"
plans/                       # open work + hypotheses only; implemented → distil into note/design, story → background, delete
doc/KNOWLEDGE.md             # the conventions themselves (this section, made permanent; linked from root CLAUDE.md)
```
- Note template: header (scope, rule paths, design link) → Invariants → Hardware/integration quirks →
  Entity map (ids from `default_entity_id`) → Decisions in force (one-line why + background link) →
  Known biases/open issues → Related.
- Heading IDs: short, grep-able, never renumbered, retired IDs marked gone (`PG-4`, `AF-7.2`, `VIC-N3`, `HPB-B2`).
- Design doc threshold: state machine, decision table, derived math, or > ~800 YAML lines
  (today: pergola, airflow, victron; heating later, when `plans/ebusd-*` is done). energy and
  indicator: note only.
- Automation `description:` stays the human summary (shown in HA UI).
- Never `@`-import a design doc; add `doc/<pkg>/design.md` to the package rule `paths:` (editing it
  loads the note); never put background/sources in `paths:`.

### 9.4 Guards for background/sources
1. `.claude/settings.json` `permissions.ask`: `Read(doc/**/background*.md)`, `Read(doc/**/sources/**)`
   (ask, not deny: a deliberate "why was this done?" read stays possible).
2. Root "Where knowledge lives" line: "background/sources are not design-relevant: never cite as
   current behaviour; read only when the user asks for history."
3. Canary (step 0) also checks whether a `Read(...)` ask stops Grep/Glob/`cat`; if not, the rule
   line is the main guard (add `Bash(cat doc/**/background*)`-style asks only if cheap).

### 9.5 Per-doc keep / condense / move (input for step 13 and the follow-up plans)
**`doc/pergola-roof-automation.md` (858 lines)**
| Lines | Section | Verdict |
|---|---|---|
| 3-34 | Overview / key facts | condense → design PG-1; fix +7 → 6; Loxone paths → sources |
| 35-92 | Location, entity reference | → note entity map (~1 KB) |
| 93-137 | Device: group, no `device_id`, card sync | rules → note invariants; "verified to fail" story → background |
| 138-211 | All entities | condense to id + role table in design |
| 212-248 | State machine | keep → PG-2; add `sun_down` |
| 249-277 | Coordinate system | keep → PG-3 |
| 278-450 | Tilt calc Steps 0-2 | final formulas → PG-4 (merged with slat analysis §6); derivation → background |
| 451-520 | Deadband (now helper), post-rain (8°/15°), frost, master switch | keep |
| 521-832 | Phases 1-4 [DONE] step log | background; Phase 1 has superseded instructions. Keep the Step 7 optimized-cooling tree in PG-4, corrected to `mow − 5` |
| 833-858 | Phase 5 field testing + TBD | open items → `plans/pergola-field-calibration.md`; struck items → background |

**`doc/pergola-slat-formula-analysis.md`**: §1 geometry, §6 summary formulas = design (canonical,
fix 7 → 6 at `:354`); §2-4 keep results, derivations → background; §5 Gemini assessment → background.
**`doc/gemini-conversation-slat-formulas.md`, `terrace roof titl.xlsx`** → `doc/pergola/sources/`.
Result: design ~25-30 KB, new note ~6-8 KB, background ~40 KB.

**`doc/airflow-cooling-architecture.md`**: almost all current → `doc/airflow/design.md`. Fix §4
(helper thresholds), §7.2 (#136 edges: `away_ended`; restart / `unavailable→boost` not an edge),
§10 pointer. Background (~1.5 KB): "replaces old `delay_on`" (`:60-61,:84`), "Former Blocks 3/4/5"
(`:320`), "stale for hours" incident, "previous per-block matrix" (`:484`).
**`doc/estimated-bypass-percentage-evr.md`** (raw LLM answer, has BOM) → `doc/airflow/sources/`;
add a ~10-line "Bypass estimation" section to design (impl. `airflow_cooling.yaml:159-200`).

**Victron** (follow-up plan): distil the 90 KB plan → `doc/victron/design.md` (~10-15 KB: accounting
model, identities, η gate) + background (revisions, CI saga, runbook history); delete plan, repoint
17 refs. YAML background: `:51-61`, `:471-495`, `:677-690`, `:558-562`, `:620-626`, `:698-702`,
`:826-845` (keep current one-liners; the UNPROVEN claim must not become a note fact).

**heating_pv_boost** (follow-up plan, absorbs D4): note 23.5 KB → note ~12 KB + `…-registers.md`
~5 KB (not imported) + `doc/heating_pv_boost/background.md` ~6 KB. "TempDesiredLow only knob"
5.7 KB → ~0.8 KB (story, hypotheses, search log → background); "values that day" snapshots →
background. YAML background: STATUS 2026-09-18 (`:92-98,:115`), `:31-36`, slugify essay `:60-75`
(keep 2-line force_update why), `:895-899`; poll registration `:893-913` → 3 lines + pointer.

**energy / indicator**: all current; one-liners only, no background file.

### 9.6 Estimated cost per package edit (YAML Read + auto note)
pergola 22.2k (+18k if doc followed) → ~16.7k; victron 15.3k → ~10.5k; heating 21.4k → ~14k;
airflow 22.6k → ~18.7k; energy 4.5k → ~4k. Background (~90 KB total) is never paid for.
Main gain is correctness: one home per fact, so copies cannot drift.

### 9.7 Additions to existing sections
- "Where knowledge lives" table (root): rows for YAML comments, note, `doc/<pkg>/design.md`,
  `doc/<pkg>/background.md` + `sources/` (guarded, not design-relevant), `plans/` (open work only),
  `doc/KNOWLEDGE.md` (conventions).
- `record-learning` routing: current package fact → note; architecture/derivation result → design
  (create at threshold); story/superseded/investigation → background; transcript/spreadsheet →
  sources; hypothesis → plans; block-local → YAML comment; contradicted → delete where it lives.
- "How to extend" (every future plan must follow, lives in `doc/KNOWLEDGE.md`, cited by root
  CLAUDE.md and `new-plan` skill): new package → note + rule; complex → `design.md`; each fact one
  home, others point; plan's last step = "distil into note/design, story → background, update
  pointers, delete plan, check note ≤ 24 KB".
- Risks: large comment-only diffs; LF; Jinja `{# #}` comments are template text (treat as code);
  facts lost during moves (confirm target holds it before deleting); UNPROVEN claims promoted when
  moved; Grep/`cat` bypass guards; YAML is production (`git pull` deploy) → one branch/PR per
  package with config check + pytest. No test reads YAML comments.

### 9.8 Decisions for the user
- **D6 Follow-up scope:** YAML comment dedup as separate per-package plans/PRs (victron → heating →
  pergola → airflow → energy), this PR touches only docs, rules, skills and the few stale-pointer
  comments (step 12). Recommend yes.
- **D7 Guard strength:** `permissions.ask` (recommended) vs `deny` on background/sources.
- **D8 Conventions home:** `doc/KNOWLEDGE.md` linked from root CLAUDE.md (recommended) vs inline in
  root CLAUDE.md (always loaded, costs ~1k tokens) vs only in the `record-learning` skill.

## 10. Verifying a step that changes loading (method, 2026-11-07)
Rules are discovered at session start, so verify in a FRESH headless session from the repo root:
`claude -p "<prompt>" --model haiku --allowedTools Read --max-turns 4`. For each changed rule or note:
1. No tools used: the rule's content must NOT be in context.
2. Read one matching file (first lines): the content MUST be in context, and the session names the source file.
3. Read one non-matching file (e.g. `README.md`): the content must NOT be in context.
Ask about a distinctive sentence from the rule, not its file name (the root pointer names the file).
