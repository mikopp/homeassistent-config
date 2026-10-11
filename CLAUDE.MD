# Home Assistant Config — Claude Instructions

## Important constraints for this project:
1. ALWAYS create/maintain a feature specific implementation plan file in the `plans` folder. 
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions and explicit approval before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS write comments that describe each part of the implementation in the source code file.
7. User will deploy via `git pull` on the HA host, NEVER do that yourself

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

### MQTT entities: `unique_id` is NOT the entity ID
- `unique_id:` is only HA's internal registry key. It never appears in `binary_sensor.xxx` /
  `sensor.xxx`. **Never derive an entity ID from it** (e.g. unique_id `heating_loxone_warm_enough`
  does NOT give `binary_sensor.heating_loxone_warm_enough`).
- The entity ID comes from `default_entity_id:` (YAML MQTT entities). Without it, HA builds it from
  the device name + entity name (e.g. device "Loxone Heating" + name "Heating Loxone Warm Enough"
  → `binary_sensor.loxone_heating_heating_loxone_warm_enough`), so entities with a `device:` block
  get a device prefix that is not in `unique_id`.
- `default_entity_id:` only applies when the entity is first created. If the entity already exists
  in the registry, a UI rename wins and the YAML value is ignored.
- **Every reference to an MQTT entity** (dashboards, templates, automations, groups, tests) must
  use the entity ID taken from `default_entity_id:` in the defining YAML block, or — when that is
  absent or the entity may have been renamed — the real ID looked up via ha-mcp:
  `ha_get_entity(unique_id="<unique_id>")` resolves a `unique_id` to its live `entity_id`.
- Never guess an ID from `name:` or `unique_id:`. A wrong ID fails silently as "entity not available".

### Template `device:` key
- The `device:` key is NOT supported in template YAML — it causes a config error. Assign template
  entities to a device via the UI instead.

> Package-specific notes are progressively loaded: `packages/CLAUDE.md` is an index pointing to one
> `packages/notes/<package>.md` per package. Read the matching note before touching a package, and put any
> new package knowledge there (never in this file). Add an index row for every new note.