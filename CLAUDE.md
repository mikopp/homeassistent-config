# Home Assistant Config — Claude Instructions

## Important constraints for this project:
1. Feature work: ALWAYS create/maintain a plan file in `plans/`; read `.claude/rules/plans.md` first. Small ad-hoc changes the owner asks for directly need no plan.
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions and explicit approval before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS comment each part of the code in the style of `doc/KNOWLEDGE.md#K-5`.
7. User will deploy via `git pull` on the HA host, NEVER do that yourself
8. ALL files use LF (Linux) line endings — never CRLF. Before committing run `git ls-files --eol`
   (nothing may show `w/crlf` or `i/crlf`). Enforced by `.gitattributes` (`eol=lf`) and `.editorconfig`.

Deploy/migration docs come from `git diff origin/master...HEAD`, never the live system.

## Local CI checks
While developing, run the targeted form: `.github/scripts/ci-local.sh --package <pkg>` (that package's tests,
incl. cross-package ones) or `.github/scripts/ci-local.sh -- <pytest test id / args>`; `--yaml` = YAML checks only.
Before pushing / at the end of a task the full `.github/scripts/ci-local.sh` (no arguments) is mandatory: YAML
checks, knowledge-layout check and all of `tests/ha` (no Docker); `--e2e` adds the real-HA layer `tests/e2e`
(Docker). A targeted run never counts as verification. Usage: script header. CI runs both
(`tests.yaml`, `e2e.yaml`). Prerequisites: python3.15 (tooling; yamllint goes into `.venv`), python3.14
(what HA requires, pinned in `.github/ha-versions/ha-python.txt`) and mosquitto at the version pinned in
`.github/ha-versions/mosquitto/Dockerfile` (the HA Mosquitto app's broker; Linux:
`.github/scripts/install-mosquitto.sh`).

## HA version gate — check before trusting any info
The pinned HA version is the `FROM` line of `.github/ha-versions/ha/Dockerfile` (an image tag like
`ghcr.io/home-assistant/home-assistant:2026.11.1`; Dependabot bumps it; the e2e layer runs this image).
Never read `.HA_VERSION` (removed in #116). Before applying ANY info from web search, HA docs, ha-mcp
or even this repo's own code/comments, check it holds for that major version: HA renames/removes
config keys and shifts YAML syntax. The pytest-homeassistant
pin in `requirements_test.txt` (in-process tests; same release as the image), the Python and the mosquitto pins are guarded by
`tests/ha/test_versions.py`.

- Read the `FROM` line first, at the start of any research into HA behavior/config/docs. The live
  instance may differ from the pin; check it with ha-mcp (`ha_get_system_health`) when that matters.
- Verify behaviour against source at the pinned tag: `gh api repos/home-assistant/core/contents/<path>?ref=<tag>`
  (docs were ambiguous or silent every time it mattered).
- When citing docs or web results, prefer version-pinned docs over version-less blog/forum answers; flag
  an answer whose version isn't stated as unverified for this major version.
- Existing YAML reflects the version it was written under: note conflicts instead of silently "fixing" them.

## MCP usage (read-only)
ha-mcp is for DISCOVERY ONLY: look up and verify entity IDs, devices, areas, integrations and states.
**Never call any ha-mcp tool that writes, changes state, or calls a service.**

## Config structure
This repo IS the HA config directory: all automations, scripts, blueprints and helpers are YAML
here, never made in the HA UI or via MCP.

### Global files (keep lean — no feature-specific content)
- `configuration.yaml` — loads packages, includes automations/scripts/scenes, global integrations only
- `automations.yaml` — only automations that span multiple features or have no natural feature home
- `scripts.yaml` — same principle as automations.yaml
- `blueprints/automation/mine/` — custom automation blueprints
- `custom_templates/` — Jinja macros imported by templates (`{% from 'x.jinja' import ... %}`);
  currently only `airflow_decision.jinja`, the airflow package's single decision

### Feature packages (`packages/<feature>.yaml`)
One file per feature, any mix of keys (`input_*`, `template`, `automation`, `script`, `sensor` …),
merged into the global config by:
```yaml
homeassistant:
  packages: !include_dir_named packages
```

**Rule:** anything for a named feature (pergola, irrigation, alarm) goes in `packages/<feature>.yaml`,
never in configuration.yaml or the global automations/scripts files.

HA YAML rules (helpers, template sensors, entity ids, device key): `.claude/rules/ha-yaml.md`. Rules and notes load on Read/Edit, not on Grep/Glob: after searching, read the YAML or note before relying on package facts.

## Learnings — hard rule
**Never write an unconfirmed learning** (one green CI run or "symptom went away" is not proof).
Hypotheses go to the feature's `plans/` file, marked as such. To record anything learned, invoke the `record-learning` skill: it holds the evidence rules and routing.

## Where knowledge lives
Before creating, moving or deleting knowledge (note, rule, skill, design doc, a plan's close step), read `doc/KNOWLEDGE.md`.
Kinds (`doc/KNOWLEDGE.md#K-1`): **always** = in every session; **rule** = a Claude rule, auto-loads when a matching file is read/edited; **skill** = body loads when invoked; **reference** = never auto-loads, read only when a pointer's read-when condition applies; **guarded** = read only when the owner asks for history, never cited; **external** = outside the repo files.

| Home | Kind | Holds |
|---|---|---|
| `CLAUDE.md`, skill descriptions | always | this file; skill triggers |
| `doc/<pkg>/notes.md` | rule (symlink) | what to know before editing one package (invariants, quirks, entity map) |
| `.claude/rules/*.md` | rule | file-type rules (`ha-yaml.md`, `tests.md`, `plans.md`, `devices.md`, `knowledge.md`) |
| `.claude/skills/<topic>/SKILL.md` | skill | cross-package topic knowledge and workflows (`record-learning`, `device-knowledge`) |
| `doc/<pkg>/design.md` | reference | architecture, decisions, trade-offs, gaps of complex packages; no implementation detail |
| `doc/devices/<device>/` | reference | one physical unit independent of HA; tagged facts (`device-knowledge` skill) |
| skill `references/`, `doc/<pkg>/<topic>.md` | reference | detail split off a skill or note; listed in its index with a read-when condition |
| `plans/` | reference | open work and hypotheses only; deleted when done |
| `doc/<pkg>/background.md`, `doc/sources/<pkg>/` | guarded | history and raw material; never cite or link from agent knowledge |
| YAML comments | with the file | what + one-line why + pointer to note/design; never a copy of a note fact (`doc/KNOWLEDGE.md#K-1.1`) |
| GitHub issues; git / PRs | external | confirmed bugs/flaky tests not fixed now (`#n` linked from the note); the log (no dated logs elsewhere) |
