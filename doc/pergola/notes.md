---
paths:
  - "packages/pergola.yaml"
  - "tests/ha/test_pergola.py"
  - "dashboards/Pergola-management.yaml"
  - "dashboards/elements/pergola_card.yaml"
  - "doc/pergola/design.md"
---
# Pergola package notes (`packages/pergola.yaml`)

Read before touching `packages/pergola.yaml`, its tests or its dashboard. Scope: tilt control of
the two Somfy bioclimatic covers `cover.dach_links` / `cover.dach_rechts` (state machine, slat
formulas, rain/frost protection). Design (state machine, formulas, deadband, verification table):
`doc/pergola/design.md` (`PG-1` … `PG-8`), on demand: read it only to change the architecture or check an addition against it; for one rule, follow the `→ design.md#ID` at that line.
This note holds what you must not break.

## Invariants
- **Group + card sync.** Every new or removed pergola `input_*`, `sensor` or `binary_sensor` is
  added to or removed from `group.pergola_dach` (bottom of the YAML) AND
  `dashboards/elements/pergola_card.yaml` in the same change. Explicitly in neither (internal):
  `input_number.pergola_last_set_slat_angle`, `input_number.pergola_rain_recovery_step`.
- **No `device_id:` / `device:` on template entities**, and no UI device assignment: both fail
  (the YAML schema has neither key, source 2026.11.1; UI assignment OBSERVED to fail). Grouping
  is only via the group + card.
- **No template wrappers** around `input_*` helpers. Automations and templates use the
  `input_*` entity IDs directly.
- **State writers:** only those listed in `PG-2` (and on `input_select.pergola_automation_state`)
  write the state; a new writer is added to both.
- **Protected states** (frost, rain, rain_stopped, user_override) leave only via their own exit
  rule; only the recovery script leaves `rain_stopped` (frost/rain entry may abort it). Priority
  order: `PG-2.2`.
- **One cover mover.** `script.pergola_set_slat_angle` is the only place that converts slat
  angle → tilt and sends `cover.set_cover_tilt_position` (always both covers). Never inline the
  formula; `sensor.pergola_tilt_position` only mirrors it (`PG-4.6`).
- Master switch only stops cover movement, never gate a sensor on it (`PG-6.3`); watchdogs stay
  suppressed in the moving states (`PG-2.4`); the deadband compares tilt units (`PG-5.1`).

## Hardware / integration quirks
- Somfy: lock/timer changes are never pushed, HA sees them only after a forced state report
  (`PG-2.4`). Tilt reported while locked is unreliable: never base a decision on it.
- Weather station prefix is spelled `sensor.wheatherstation_` (sic).

## Entity map
Full map: `doc/pergola/design.md#PG-7`. Automation entity IDs (looked up live; neither `id:` nor
alias is a reliable source):

| Automation | Entity ID |
|---|---|
| Inactivity watchdogs | `automation.inactivity_watchdog_dach_links` / `_dach_rechts` |
| Lock responder links | `automation.update_cover_state_when_lock_originator_changes` (old name, fixed at registration) |
| Lock responder rechts | `automation.dach_rechts_update_state_when_lock_originator_changes` |
| Others | `automation.pergola_state_manager`, `_cover_response`, `_not_enough_sun_entry` / `_exit`, `_sync_heating_from_indicator` |

## Decisions in force
- `/5` time pattern instead of triggers on `sun.sun` attributes (they change every minute).
- Other decisions and their why: `PG-1` (season), `PG-2.1` / `PG-5.2` (per-state moves),
  `PG-4.3` (cooling sub-modes), `PG-6.1` (drain).

## Known biases / open issues
- Helper reads use fallback defaults (`| float(122)` …), against `.claude/rules/ha-yaml.md`:
  GitHub issue #142 (helper reads only). The sensor-read fail-safes are deliberate and stay:
  frost entry `float(99)` / exit `float(0)` (`PG-2.2`), sun_down `float(-1)`.
- Field calibration (PV factor, shading sensitivity, wall azimuth, drain angles, rain lock):
  `plans/pergola-field-calibration.md`.

## Tests (`tests/ha/test_pergola.py`)
- How the package is driven (real sun, seeded Somfy/weather, `_Ref`): module docstring.
- The cover response's 500 ms delay never comes due on the frozen clock: `_settle` reaches only
  delays ≤ `_SHORT_DELAY` (0.6 s); never raise it to 1 s (see its comment).

## Related
- `packages/heating_cooling_indicator.yaml`: source of the season.
- `packages/victron.yaml`: PV source sensor.
