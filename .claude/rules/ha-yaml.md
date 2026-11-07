---
paths:
  - "packages/**/*.yaml"
  - "automations.yaml"
  - "scripts.yaml"
  - "configuration.yaml"
  - "blueprints/**/*.yaml"
  - "custom_templates/**"
  - "dashboards/**"
  - "tests/**/*.py"
---

HA YAML rules for this repo; loaded when a config, template, dashboard or test file is touched.

## `input_number` / `input_boolean` / `input_select` / `input_datetime`
- **Never add `| float(default)` or any fallback default** — helpers are always available once HA starts; defaults mask config errors.
- **Never set `initial:` values** — HA resets to `initial` on every restart, overwriting any user change. Set desired values once in the UI after deploy.

## Template sensors and binary sensors
- **Always add an `availability:` template** to any template sensor/binary sensor that reads from non-guaranteed sensors (e.g. device sensors, integrations that can go unavailable). Pattern:
  ```yaml
  availability: >
    {{ states('sensor.foo') not in ['unavailable', 'unknown'] and
       states('sensor.bar') not in ['unavailable', 'unknown'] }}
  ```
- **Never add `| float(default)` on sensor reads inside a `state:` template** when an `availability:` guard is already in place — if availability passes, the sensor is guaranteed numeric; the default hides real errors.
- When a sensor has no `availability:` guard (e.g. it is a computed template sensor itself), add the guard before removing defaults.

## MQTT entities: `unique_id` is NOT the entity ID
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

(Full MQTT gotchas move to the `ha-mqtt` skill in step 5; this short form stays.)

## Template `device:` key
- The `device:` key is NOT supported in template YAML — it causes a config error. Assign template
  entities to a device via the UI instead.
