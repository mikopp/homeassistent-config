# Home Assistant Config — Claude Instructions

## Important constraints for this project:
1. ALWAYS create/maintain a feature specific implementation plan file in the `plans` folder. 
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions and explicit approval before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS write comments that describe each part of the implementation in the source code file.
7. User will deploy via `git pull` on the HA host, NEVER do that yourself

## HA version gate — check before trusting any info
This repo's running HA version lives in `.HA_VERSION` (major.minor, e.g. `2026.8`). Before applying
ANY information from internet search, official HA docs, ha-mcp results, or even this repo's own
existing code/comments — check it's still accurate for that major version. HA changes fast: config
keys get renamed/removed, integrations get rewritten, YAML syntax shifts across major versions.

- Read `.HA_VERSION` first, at the start of any research into HA behavior/config/docs.
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
  source read at the pinned `.HA_VERSION`; a config-check or test failure that reproduces
  deterministically; a bisect over several runs.
- If the cause is still a hypothesis, it belongs in the feature's `plans/` file marked as such —
  not in learnings.
- When a logged learning is later contradicted, **delete it** (or strike it through and say what
  disproved it). Do not leave a wrong entry standing next to its correction.

This rule exists because two entries in this file had to be removed as false positives: both were
plausible mechanisms fitted to one confirming run, and both sent later sessions down wrong paths.


## HA template / helper rules

### `input_number` / `input_boolean` / `input_select` / `input_datetime`
- **Never add `| float(default)` or any fallback default** — helpers are always available once HA starts; defaults mask config errors.
- **Never set `initial:` values** — HA resets to `initial` on every restart, overwriting any user change. Set desired values once in the UI after deploy.

### Template sensors and binary sensors
- **Always add an `availability:` template** to any template sensor/binary sensor that reads from non-guaranteed sensors (e.g. device sensors, integrations that can go unavailable). Pattern:
  ```yaml
  availability: >
    {{ states('sensor.foo') not in ['unavailable', 'unknown'] and
       states('sensor.bar') not in ['unavailable', 'unknown'] }}
  ```
- **Never add `| float(default)` on sensor reads inside a `state:` template** when an `availability:` guard is already in place — if availability passes, the sensor is guaranteed numeric; the default hides real errors.
- When a sensor has no `availability:` guard (e.g. it is a computed template sensor itself), add the guard before removing defaults.

### Template `device:` key
- The `device:` key is NOT supported in template YAML — it causes a config error. Assign template
  entities to a device via the UI instead.

> Feature-specific notes live in directory-scoped files (e.g. `packages/CLAUDE.md`).