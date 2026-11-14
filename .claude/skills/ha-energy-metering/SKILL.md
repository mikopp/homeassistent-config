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

## `utility_meter` with `tariffs:` (per-mode split) (CONFIRMED 2026.10.1, `utility_meter/sensor.py`, `select.py`)
- After a select change the **next source change is counted entirely to the new option**: `_change_status()`
  clears `_last_valid_state`, so the delta runs from the last value seen before the switch.
  - Why it matters: a coarse or slowly polled source (whole-kWh steps) books energy produced before the switch
    to the option after it (live: heat-pump yield of the compressor cycle landing in the pump-only mode).
  - Fix: give such a source fewer options (merge modes it can't separate); keep the split on a fine source.
- Re-selecting the option already set writes the same state, fires no `state_changed`, so nothing resets.
  Two modes mapped to one option therefore never misbook across their switch.
- Tariff sensors get `total_increasing` when the source is an energy sensor, so they compile long-term statistics.
- YAML `utility_meter` has no reload service: changing it needs an HA restart.

## Rolling N-day sums of kWh counters (CONFIRMED 2026.10.1, `statistics/sensor.py`, `sql/`)
- **Not a `statistics` sensor** (`change`, `max_age`): it rebuilds its window from raw history at startup, so
  `recorder: purge_keep_days` shorter than the window silently shrinks it after every restart.
- Use `sql:` sensors on long-term statistics (`statistics.sum` per `statistics_meta.statistic_id`, hourly, never
  purged; `sum` already absorbs meter resets): per id `MAX(sum) − MIN(sum)` over `start_ts >= cutoff`, summed
  over ids. Listing an old and a new statistic id carries the window across an entity rename/merge.
  - `query:` is a template: take the cutoff from Jinja `now()` (follows a frozen test clock; SQLite `'now'` does not).
  - A NULL result logs a WARNING on every poll: wrap columns in `COALESCE`.
  - The literal word `entity_id` in the query logs an error (full-table-scan guard, `sql/util.py`).
  - Extra result columns become attributes; `sql:` has no `default_entity_id` (id from `name:`).
  - Up to ~1 h behind (hourly compilation). Example: `packages/heating_pv_boost.yaml` 30-day sums.
  - Tests: render the query and run it on a standalone SQLite with a minimal two-table schema (no recorder statistics).

## Recorder vs Energy Dashboard
- `recorder: purge_keep_days` does NOT touch the Energy Dashboard. Why: the dashboard reads long-term statistics, a separate store retained indefinitely.

## Moving an entity across platforms / deploy runbook
- **Repointing across a platform change** (mqtt→template, template→integration) while keeping Energy Dashboard history (CONFIRMED 2026.8.1):
  1. Keep the exact same `unique_id`. Why: identity continuity for the new row.
  2. After deploy, ONE-TIME MANUAL registry reclaim: delete the orphaned old-platform row, rename the new entity onto the freed entity_id.
     Why: the registry key is `platform + unique_id` (`entity_platform.py::_async_derive_object_ids`); `default_entity_id:` only suggests, loses the collision, and you get `_2`.
  3. History follows the **entity_id string** (`recorder/entity_registry.py::_async_entity_id_changed`), so the rename carries it.
  4. Rename within ~5 min of restart. Why: `statistics_meta.py::update_statistic_id` refuses if the target statistic_id exists, so the `_2` entity must not have compiled statistics yet.
- **Derive deploy/migration docs from `git diff origin/master...HEAD` (and `git log -S`), never from the live system.**
  - Why: the HA host runs whatever was last pulled, so ha-mcp state and the registry describe the old world (a runbook once told the user to repoint helpers the branch had already deleted).
  - Use the live system only for values to record beforehand and UI-only `.storage` state (Energy Dashboard prefs, dashboards, UI helpers) not in the repo.
