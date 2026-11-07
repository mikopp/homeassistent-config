# Home Assistant Config — Claude Instructions

## Important constraints for this project:
1. ALWAYS create/maintain a feature specific implementation plan file in the `plans` folder. 
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions and explicit approval before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS write comments that describe each part of the implementation in the source code file.
7. User will deploy via `git pull` on the HA host, NEVER do that yourself
8. ALL files use LF (Linux) line endings — never CRLF. The dev machine is Windows, so be careful:
   Python `open(p, 'w')` and PowerShell `Set-Content`/`Out-File` write CRLF by default. Use
   `open(p, 'w', newline='\n')` / `open(p, 'rb'/'wb')`, or the Edit/Write tools. Before committing run
   `git ls-files --eol` (nothing may show `w/crlf` or `i/crlf`). A CRLF write turns the whole file
   into one giant diff. Enforced by `.gitattributes` (`eol=lf`) and `.editorconfig`.

## Local CI checks
Run `.github/scripts/ci-local.sh` before pushing. It creates `.venv`, installs the CI Python deps and runs
the Docker-free checks (YAML style fixer, yamllint, resolved-config lint, template extraction). Needs
`brew install yamllint python@3.15`. `check_config` and pytest need Docker and only run in CI.

## HA version gate — check before trusting any info
The pinned HA version lives in the `FROM` line of `.github/ha-versions/ha/Dockerfile` (an image tag
like `ghcr.io/home-assistant/home-assistant:2026.10.1`; Dependabot bumps it). `.HA_VERSION` was
removed in #116 and must not be read. CI config check and the test harness both use this image. Before applying
ANY information from internet search, official HA docs, ha-mcp results, or even this repo's own
existing code/comments — check it's still accurate for that major version. HA changes fast: config
keys get renamed/removed, integrations get rewritten, YAML syntax shifts across major versions.

- Read the `FROM` line of `.github/ha-versions/ha/Dockerfile` first, at the start of any research into
  HA behavior/config/docs. The live instance may differ from the pin; check it with ha-mcp
  (`ha_get_system_health`, `homeassistant.info.version`) when that matters.
- When citing docs or web results, prefer version-pinned docs (e.g. `www.home-assistant.io/docs`
  reflects latest — verify against changelog/release notes if the feature is old or obscure) over
  version-less blog posts/forum answers, which may predate or postdate this install by years.
- If a found answer's version isn't stated, say so explicitly and flag it as unverified for this
  major version rather than presenting it as fact.
- Existing YAML in this repo reflects the version it was written under — don't assume patterns here
  are still current best practice without checking; note conflicts instead of silently "fixing" them.

## MCP usage (read-only)
The ha-mcp connection is available for DISCOVERY ONLY:
- Look up entity IDs, device names, areas, and current states
- Understand what integrations and devices exist
- Verify entity IDs before using them in automations

**Never call any ha-mcp tool that writes, changes state, or calls a service.**
Only use read tools: entity lookup, area listing, device listing, state queries.

## Config structure
This repo IS the Home Assistant config directory. All automations, scripts, blueprints, and helpers
are defined here in YAML files — not in the HA UI or via MCP tools.

### Global files (keep lean — no feature-specific content)
- `configuration.yaml` — loads packages, includes automations/scripts/scenes, global integrations only
- `automations.yaml` — only automations that span multiple features or have no natural feature home
- `scripts.yaml` — same principle as automations.yaml
- `blueprints/automation/mine/` — custom automation blueprints
- `custom_templates/` — Jinja macros imported by templates (`{% from 'x.jinja' import ... %}`);
  currently only `airflow_decision.jinja`, the airflow package's single decision

### Feature packages (`packages/<feature>.yaml`)
Each feature gets its own file under `packages/`. A package file may contain any combination of:
`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`,
`template`, `automation`, `script`, `sensor`, `binary_sensor`, etc.

HA merges all package keys into the global config automatically via:
```yaml
homeassistant:
  packages: !include_dir_named packages
```

**Rule:** When adding anything for a named feature (e.g. pergola, irrigation, alarm),
create or edit `packages/<feature>.yaml`. Do NOT add it to configuration.yaml or
the global automations/scripts files.

Current packages:
- `packages/pergola.yaml` — pergola roof automation (helpers, template sensors, automations, scripts)
- `packages/airflow_cooling.yaml` — ventilation/free-cooling + humidity flush/drying boost (ComfoConnect)

## Persistent Memory
- Before starting complex tasks, read and ingest `.claude/learnings.md`.
- After resolving non-obvious bugs or completing features:
  1. Open `.claude/learnings.md`.
  2. If a new pattern emerged, update the "Active Patterns" or "Anti-Patterns" sections.
  3. Append a dated entry to the "Log" section using the exact markdown schema.
  4. Keep insights dense, punchy, and actionable. Do not log trivial details.

### NEVER write an unconfirmed learning
An entry in `.claude/learnings.md` is a claim future sessions will act on without re-deriving it.
Only write one when the cause is **proven**, not when it is merely plausible.

- **A single green CI run is not proof.** Neither is "the symptom went away after I changed X" —
  that is correlation on a sample of one, and for an intermittent failure it is worth nothing.
- Acceptable evidence: a stack trace / thread dump / error naming the mechanism; the relevant
  source read at the pinned version (Dockerfile `FROM`); a config-check or test failure that reproduces
  deterministically; a bisect over several runs.
- If the cause is still a hypothesis, it belongs in the feature's `plans/` file marked as such —
  not in learnings.
- When a logged learning is later contradicted, **delete it** (or strike it through and say what
  disproved it). Do not leave a wrong entry standing next to its correction.

This rule exists because two entries in this file had to be removed as false positives: both were
plausible mechanisms fitted to one confirming run, and both sent later sessions down wrong paths.


HA YAML rules (helpers, template sensors, MQTT entity ids, device key) live in `.claude/rules/ha-yaml.md` and load automatically when a matching file is touched.

> Package-specific notes are progressively loaded: `packages/CLAUDE.md` is an index pointing to one
> `packages/notes/<package>.md` per package. Read the matching note before touching a package, and put any
> new package knowledge there (never in this file). Add an index row for every new note.