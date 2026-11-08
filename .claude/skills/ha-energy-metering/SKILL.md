---
name: ha-energy-metering
description: "Power→energy sensors, Energy Dashboard and entity migration: integration platform semantics, W→kWh accumulators, long-term statistics, moving an entity across platforms, deploy runbooks. Use when adding/changing kWh/Riemann/utility_meter sensors or a unique_id/platform/entity_id."
---

# Energy metering & entity migration

Grades: **CONFIRMED** = source read at the pinned version (`.github/ha-versions/ha/Dockerfile` `FROM`),
stack trace, or deterministic repro. **OBSERVED** / **UNPROVEN** = weaker; never promote without new evidence.

## Choosing the accumulator
- Source updates ≤ 1/min → trigger-based `template:` W→kWh accumulator (pattern in `ha-templates`).
- Source updates faster → `sensor: platform: integration` (Riemann/trapezoidal). Why: 1/min sampling is coarse at 1-2 s pushes (reason grid import/export moved to it).

## `sensor: platform: integration` semantics (CONFIRMED 2026.8.1, `components/integration/sensor.py::async_added_to_hass`)
- Subscribes to **both** `async_track_state_change_event` and `async_track_state_report_event`.
  - Why it matters: a same-value re-post drives it, unlike classic `template:` sensors.
- Without `max_sub_interval` it has **no timer**: the next source event integrates the whole gap as one trapezoid,
  `elapsed = new_state.last_updated - old_state.last_reported`. Why it matters: a long silent gap is billed at once.
- Gaps through `unavailable` are NOT billed. Why: `validate_states` can't parse the old value, so no area is added.
- Tolerates a source that doesn't exist yet at HA startup.
- **Rejects `device_class`/`state_class` as config keys** (CONFIRMED, real config-check failure:
  `'device_class' is an invalid option for 'sensor.integration'`). Why: the platform applies its own.
- **Running total lives in the entity's Python memory** (restored via `RestoreSensor`), not its HA-visible state.
  - Why it matters: a `set_state()` override shows briefly, then the next step overwrites it from the old internal value. Cannot be reset via `set_state()`; tests need a before/after baseline delta.
- **Replacing a trigger `total_increasing` sensor with it** (same entity_id after reclaim): it restarts at 0 with
  `state_class: total`, and the compiled statistics `sum` stepped down once by the old total (OBSERVED once,
  Victron #121). Fix: Developer Tools → Statistics, set that slot's *change* to ~0.001. Do not promise "no negative spike".

## Recorder vs Energy Dashboard
- `recorder: purge_keep_days` does NOT touch the Energy Dashboard. Why: the dashboard reads long-term statistics, a separate store retained indefinitely.

## Moving an entity across platforms / deploy runbook
- **Repointing across a platform change** (mqtt→template, template→integration) while keeping Energy Dashboard history (CONFIRMED 2026.8.1):
  1. Keep the exact same `unique_id`. Why: identity continuity for the new row.
  2. After deploy, ONE-TIME MANUAL registry reclaim: delete the orphaned old-platform row, rename the new entity onto the freed entity_id.
     Why: the registry key is `platform + unique_id` (`entity_platform.py::_async_derive_object_ids`); `default_entity_id:` only suggests, loses the collision, and you get `_2`.
  3. History follows the **entity_id string** (`recorder/entity_registry.py::_async_entity_id_changed`), so the rename carries it.
  4. Rename within ~5 min of restart. Why: `statistics_meta.py::update_statistic_id` refuses if the target statistic_id exists, so the `_2` entity must not have compiled statistics yet.
  - Worked example (history, Victron #121): `doc/victron/background.md#VIC-B3`, "Deploy runbook".
- **Derive deploy/migration docs from `git diff origin/master...HEAD` (and `git log -S`), never from the live system.**
  - Why: the HA host runs whatever was last pulled, so ha-mcp state and the registry describe the old world (a runbook once told the user to repoint helpers the branch had already deleted).
  - Use the live system only for values to record beforehand and UI-only `.storage` state (Energy Dashboard prefs, dashboards, UI helpers) not in the repo.
