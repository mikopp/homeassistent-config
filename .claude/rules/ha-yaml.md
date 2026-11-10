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

## Entity IDs (all integrations): never derive one, look it up
Applies to every entity (MQTT, template, `history_stats`, `utility_meter`, UI integrations), not only MQTT.
How HA picks the ID (CONFIRMED, source 2026.10.1 `helpers/entity_platform.py`, `helpers/entity_registry.py`):
1. An explicit ID wins, unprefixed: `default_entity_id:` (MQTT and template both support it).
2. Otherwise slugify of area + parent device + device + entity name, each part only when present
   (area from the entity, else from its device; a name that starts with the device name is unprefixed).
3. No name, device or area at all: `<platform>_<unique_id>`. Only then does `unique_id` appear in the ID.
4. Taken: `_2` suffix. The ID is fixed at first registration; later YAML or HA changes do not move
   it, so older entities may lack the area part that a new one would get.
Rules:
- Never derive an ID from `unique_id:` or `name:`. Use `default_entity_id:` from the defining block,
  or look the ID up via ha-mcp `ha_get_entity(unique_id=...)`.
- A wrong ID fails silently as "entity not available".
- MQTT specifics (`default_entity_id` vs UI rename): `ha-mqtt` skill.

## Template `device:` key
- The `device:` key is NOT supported in template YAML — it causes a config error. Assign template
  entities to a device via the UI instead.

## Comments and findings while you edit
- Comment style: `doc/KNOWLEDGE.md#K-5`. Jinja comments follow it too; do not repeat the
  availability-guard / no-`float`-default rule above in a comment.
- If a comment's why rests on a fact not visible in the YAML (measured value, hardware quirk,
  user-supplied reason) or you found a bug: invoke `record-learning` before you finish. The fact
  goes to its home; the comment only points there. Never point to a note you did not update.
