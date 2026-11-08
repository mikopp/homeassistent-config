---
name: ha-mqtt
description: "MQTT sensors in this repo: unique_id vs entity_id/default_entity_id lookup, value_template empty-payload handling, expire_after. Use when adding or referencing an MQTT entity or writing its value_template."
---

# MQTT entities

Grades: **CONFIRMED** = source read at the pinned version (`.github/ha-versions/ha/Dockerfile` `FROM`),
stack trace, or deterministic repro. Never promote a grade without new evidence.

## `unique_id` is NOT the entity ID
- `unique_id:` is only HA's internal registry key. It never appears in `binary_sensor.xxx` /
  `sensor.xxx`. **Never derive an entity ID from it** (e.g. unique_id `heating_loxone_warm_enough`
  does NOT give `binary_sensor.heating_loxone_warm_enough`).
- The entity ID comes from `default_entity_id:` (YAML MQTT entities). Without it, HA builds it from
  the names like for any integration (rule "Entity IDs (all integrations)" in
  `.claude/rules/ha-yaml.md`), so entities with a `device:` block get a device prefix that is not
  in `unique_id` (e.g. device "Loxone Heating" + name "Heating Loxone Warm Enough" →
  `binary_sensor.loxone_heating_heating_loxone_warm_enough`). A device with `suggested_area` can
  add an area prefix on a new registration.
- `default_entity_id:` only applies when the entity is first created. If the entity already exists
  in the registry, a UI rename wins and the YAML value is ignored.
- **Every reference to an MQTT entity** (dashboards, templates, automations, groups, tests) must
  use the entity ID taken from `default_entity_id:` in the defining YAML block, or — when that is
  absent or the entity may have been renamed — the real ID looked up via ha-mcp:
  `ha_get_entity(unique_id="<unique_id>")` resolves a `unique_id` to its live `entity_id`.
- Never guess an ID from `name:` or `unique_id:`. A wrong ID fails silently as "entity not available".

## `value_template` and empty payloads (CONFIRMED 2026.10.1, `components/mqtt/sensor.py::_update_state`, corroborated by sensor.mqtt docs)
- On a sensor with `device_class`/`unit_of_measurement`/`state_class`:
  - rendered `''` → IGNORED (debug log only, last value kept);
  - rendered `'None'` → state becomes `unknown`;
  - bare `| float` on an empty payload RAISES (WARNING per message).
- Guard: `{{ '' if value | trim == '' else value | float | round(3) }}`. Why: keeps the last value, no log spam.
- Use `none` only when `unknown` is actually wanted. Why: wrong for idle appliances.
- Applied to the Loxone appliance sensors in `packages/energy.yaml` and `packages/heating_pv_boost.yaml`.

## `expire_after`
- Idle appliances without `expire_after` must keep their last value, so their `value_template` returns `''`, not `none`. Why: `none` would flip them to `unknown` on every empty message.
- No further `expire_after` facts are verified here yet; check the sensor.mqtt docs at the pinned version before relying on its semantics.
