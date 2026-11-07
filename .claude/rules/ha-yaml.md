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
- Never derive an entity ID from `unique_id:` (or `name:`).
- Use `default_entity_id:` from the defining block, or look the ID up via ha-mcp `ha_get_entity(unique_id=...)`.
- A wrong ID fails silently as "entity not available".
- Full rules: `ha-mqtt` skill.

## Template `device:` key
- The `device:` key is NOT supported in template YAML — it causes a config error. Assign template
  entities to a device via the UI instead.
