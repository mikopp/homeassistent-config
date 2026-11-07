---
paths:
  - "packages/pergola.yaml"
  - "tests/test_pergola.py"
  - "dashboards/Pergola-management.yaml"
  - "dashboards/elements/pergola_card.yaml"
  - "doc/pergola/design.md"
  - "plans/pergola-*.md"
  - "plans/knowledge-dedup-pergola.md"
---
# Pergola package notes (`packages/pergola.yaml`)

Read before touching `packages/pergola.yaml`, its tests or its dashboard. Scope: tilt control of
the two Somfy bioclimatic covers `cover.dach_links` / `cover.dach_rechts` (state machine, slat
formulas, rain/frost protection). Design (state machine, formulas, deadband, verification table):
`doc/pergola/design.md` (`PG-1` … `PG-8`). This note holds what you must not break.

## Invariants
- **Group + card sync.** Every new or removed pergola entity (`input_*`, `sensor`,
  `binary_sensor`, `script`) is added to or removed from `group.pergola_dach` (bottom of the YAML)
  AND `dashboards/elements/pergola_card.yaml` in the same change. Card sections: *On/Off Toggles*,
  *State of Automation*, *States and Sensors*, *Parameters*. Exceptions today: the internal
  helpers `input_number.pergola_last_set_slat_angle` and `pergola_rain_recovery_step` are in
  neither (their sensors are).
- **No `device_id:` / `device:` on template entities**, and no UI device assignment: both fail
  (story → `doc/pergola/background.md#PG-B3`). Grouping is only via the group + card.
- **No template wrappers** around `input_*` helpers. Automations and templates use the
  `input_*` entity IDs directly.
- **One state writer set.** Only `pergola_state_manager`, `script.pergola_evaluate_state`,
  `script.pergola_exit_to_normal` and the two `pergola_not_enough_sun_*` automations write
  `input_select.pergola_automation_state` (plus the user, to break a deadlock).
- **State priority:** frost > rain > rain_stopped > user_override > sun_down >
  no_sun_behind_house > not_enough_sun > sun_automatik_heating > sun_automatik_cooling
  (`PG-2.2`). Protected states (frost, rain, rain_stopped, user_override) leave only via their
  own exit rule; only the recovery script exits `rain_stopped` (frost/rain entry may abort it).
- **One cover mover.** `script.pergola_set_slat_angle` is the only place that converts slat
  angle → tilt and sends `cover.set_cover_tilt_position` (always both covers). Never inline the
  formula; `sensor.pergola_tilt_position` only mirrors it. Correction is **6** below 20°, 5.5
  below 69°, 0.5 above (`PG-4.6`); any copy that says 7 is stale.
- **Master switch semantics.** `input_boolean.pergola_automatic_enabled` off only stops cover
  movement (the script's first condition), including the post-rain drain. The state machine and
  all template sensors keep computing; never gate a sensor on it.
- **`pergola_heating` comes from the indicator.** `automation.pergola_sync_heating_from_indicator`
  sets it from `sensor.heating_cooling_indicator` (on: `active_heating`, `neutral`; off:
  `passive_cooling`, `active_cooling`; untouched while unavailable). Manual toggles are
  overwritten at the next indicator change or HA start. It changes only the formula, not the
  state priority.
- **Watchdogs stay suppressed while moving** (states cooling, heating, rain_stopped), or their
  `stop_cover_tilt` aborts a movement mid-travel (`PG-2.4`).
- **Deadband compares tilt units**, max deviation of both covers (`PG-5`).

## Hardware / integration quirks
- The Somfy never pushes lock/timer changes; HA only sees them after a forced state report
  (watchdog every 5 min, lock-originator responders, or any movement command). Lock clear is seen
  ≤ 5 min after the 900 s countdown ends. Tilt reported while locked is unreliable.
- `sensor.victron_solar_yield_dc_watts` goes unavailable at night (MPPT stops publishing,
  `expire_after: 120`). `sensor.pergola_pv_power` then reports 0 while
  `sensor.victron_ac_load_total_power` is available, so `sun_down` works. Use the raw DC sensor,
  not the AC-referenced `sensor.solar_yield_watts` (factor is calibrated on panel output).
- Weather station prefix is spelled `sensor.wheatherstation_` (sic).

## Entity map (short)
| Entity | Role |
|---|---|
| `input_select.pergola_automation_state` | state machine, 9 options |
| `input_boolean.pergola_automatic_enabled` / `_heating` / `_cooling_optimized` | master / season / cooling sub-mode |
| `input_number.pergola_deadband_angle` | deadband and optimized-morning buffer |
| `input_number.pergola_max_tilt_angle`, `_wall_azimuth`, `_slat_width`, `_slat_pivot_spacing`, `_slat_thickness` | geometry |
| `input_number.pergola_pv_conversion_factor`, `_shading_sensitivity`, `_min_sun_elevation` | sun detection |
| `sensor.pergola_effective_sun_angle` | A_eff, main debug value |
| `sensor.pergola_slat_angle` / `_tilt_position` | target for the current state |
| `sensor.pergola_effective_slat_angle` | last angle actually commanded |
| `sensor.pergola_max_open_east_morning_cooling_angle` / `_max_open_west_cooling_angle` | moe / mow |
| `sensor.pergola_cooling_lower_bound` / `_min_heating_slat_angle` | derived floors (15° / 33.5°) |
| `binary_sensor.pergola_sun_shining` | shading needed |
| `sensor.dach_{links,rechts}_priority_lock_originator` / `_lock_timer` | Somfy lock |

Full table: `doc/pergola/design.md#PG-7`. Automation entity IDs come from their `id:` (e.g.
`automation.pergola_cover_response`); the watchdogs and lock responders have numeric ids.

## Decisions in force
- Season from the indicator only; room temperature is not used.
- Standard cooling is the default formula; optimized (safe-zone max-open) is opt-in via
  `pergola_cooling_optimized`. Flip range/afternoon use `mow − 5`, morning `moe + DB`
  (`PG-4.3`).
- `/5` time pattern instead of triggers on `sun.sun` attributes (they change every minute).
- Frost conditions are value-based with fail-safe defaults (entry `float(99)`, exit `float(0)`)
  so a dropped `numeric_state` trigger cannot strand the state (`PG-2.2`).
- `no_sun_behind_house` always sends 90°; `not_enough_sun` only moves if > 30° off; `sun_down`
  never moves (slats stay at night).
- Post-rain drain 8° → 15° (8° only if hourly rain > 0); calibration still open.

## Known biases / open issues
- **Helper fallback defaults contradict the repo rule (open, user decides).**
  `pergola.yaml:397-405` (and more templates in the file) read helpers with `| float(122)`,
  `| float(5)` etc. `.claude/rules/ha-yaml.md` forbids fallback defaults on `input_*` helpers and
  on guarded sensor reads. This is code, not a comment: fixing it needs a test run. Tracked in
  `plans/knowledge-dedup-pergola.md` step 4. → GitHub issue #142
- Field calibration (PV factor, shading sensitivity, wall azimuth, drain angles, rain lock):
  `plans/pergola-field-calibration.md`.
- YAML comments still point to the deleted `doc/pergola-roof-automation.md` /
  `doc/pergola-slat-formula-analysis.md` (`:2`, `:14`, `:322`), say "+7" (`:529`) and cite
  "plan Step N". Fix: `plans/knowledge-dedup-pergola.md`. Trust the code and design doc.
- Flaky test `test_sun_down_state` (effective angle 90 instead of 45, once in CI): GitHub issue #143 (cause UNPROVEN).

## Tests (`tests/test_pergola.py`)
- Formula tests seed `sensor.pergola_effective_sun_angle` directly (the sun integration can
  overwrite seeded `sun.sun` attributes), then trigger `automation.pergola_cover_response` with
  `skip_condition` and assert `sensor.pergola_effective_slat_angle`. Anchor A_eff = 67.9°:
  optimized 13.0°, standard 15.0°, heating 67.9°.
- `conftest.py` baseline: automatic on, heating off, optimized **on**, state
  `sun_automatik_cooling`, sync automation turned **off** (its own tests enable it).
- `test_sun_down_state` must first leave a protected state (the previous test can leave
  `user_override`) and wait for `sensor.pergola_pv_power == 0` before triggering.

## Related
- `doc/pergola/design.md`: current design. `doc/pergola/background.md`: history (guarded).
- `packages/heating_cooling_indicator.yaml`: source of the season.
- `packages/victron.yaml`: PV source sensor.
