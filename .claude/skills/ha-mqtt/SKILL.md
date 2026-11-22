---
name: ha-mqtt
description: "MQTT sensors in this repo: unique_id vs entity_id/default_entity_id lookup, value_template empty-payload handling, expire_after. Use when adding or referencing an MQTT entity or writing its value_template."
---

# MQTT entities

Grades: **CONFIRMED** = source read at the pinned version (`.github/ha-versions/ha/Dockerfile` `FROM`),
stack trace, or deterministic repro. Never promote a grade without new evidence.

## `unique_id` is NOT the entity ID
General rule (never derive an ID from `unique_id:` or `name:`; look it up): `.claude/rules/ha-yaml.md`
"Entity IDs (all integrations)", loaded with any package edit. MQTT specifics:
- Use `default_entity_id:` of the defining block. Without it, a `device:` block adds the device name
  as a prefix that is not in `unique_id` (device "Loxone Heating" + name "Heating Loxone Warm Enough"
  → `binary_sensor.loxone_heating_heating_loxone_warm_enough`); `suggested_area` can add an area
  prefix on a new registration.
- `default_entity_id:` only applies at first creation; for an existing entity a UI rename wins.
  When absent or possibly renamed: ha-mcp `ha_get_entity(unique_id="<unique_id>")`.

## `value_template` and empty payloads (CONFIRMED 2026.10.1, `components/mqtt/sensor.py::_update_state`, corroborated by sensor.mqtt docs)
- On a sensor with `device_class`/`unit_of_measurement`/`state_class`:
  - rendered `''` → IGNORED (debug log only, last value kept);
  - rendered `'None'` → state becomes `unknown`;
  - bare `| float` on an empty payload RAISES (WARNING per message).
- Guard: `{{ '' if value | trim == '' else value | float | round(3) }}`. Why: keeps the last value, no log spam.
- Use `none` only when `unknown` is actually wanted. Why: wrong for idle appliances.
- Text sensor (no `device_class`, `unit_of_measurement`, `state_class`, `suggested_display_precision`):
  rendered `''` is STORED as the value, not ignored (CONFIRMED 2026.11.1, same function +
  `components/sensor/entity.py::_numeric_state_expected`). Map empty to a real value in the template.
- Applied to the Loxone appliance sensors in `packages/energy.yaml` and `packages/heating_pv_boost.yaml`.

## `expire_after`
- Idle appliances without `expire_after` must keep their last value, so their `value_template` returns `''`, not `none`. Why: `none` would flip them to `unknown` on every empty message.
- Restart restore (CONFIRMED 2026.11.1, `components/mqtt/sensor.py::mqtt_async_added_to_hass`, identical
  at 2026.10.1): an MQTT sensor restores its last value only if `expire_after > 0`, the last state was not
  `unknown`/`unavailable` and `last_changed + expire_after` is still in the future; the remaining time is
  then the new expiry. Otherwise it starts expired (`unavailable`) or, without `expire_after`, `unknown`
  until a message arrives. Restore on a YAML reload: same code path, UNVERIFIED.
