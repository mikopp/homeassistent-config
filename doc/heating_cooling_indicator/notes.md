---
paths:
  - "packages/heating_cooling_indicator.yaml"
  - "tests/ha/test_heating_cooling_indicator.py"
---
# heating_cooling_indicator.yaml — outdoor-temperature mode indicator

Notes for `packages/heating_cooling_indicator.yaml`. Classifies the 48 h mean outdoor temperature
into four modes for ventilation automations. No design doc.

## Invariants
- States of `sensor.heating_cooling_indicator`: `active_heating`, `neutral`, `passive_cooling`,
  `active_cooling`.
- Input is `sensor.wheatherstation_outdoor_temperature_48h_mean` (statistics, mean of the 15 min
  filtered weatherstation temperature). The indicator is unavailable while that mean or either
  effective-threshold sensor has no value (avoids cascade jumps during reload).
- Three thresholds are `input_number` helpers: heating below, passive cooling above, active cooling
  above. No `initial:`; chosen values 12 / 16 / 20, set once in the UI after deploy.
- Order heating < passive < active is enforced by the `*_effective` sensors: passive is at least
  heating + 2, active at least effective passive + 2. The template reads only the effective sensors
  for passive/active and the helper for heating.
- Hysteresis is not a setting: fixed 1 °C relative to each threshold. The template reads its own
  previous state (`this.state`):
  - `active_heating` → `neutral` at mean >= heat + 1
  - `neutral` → `active_heating` at mean <= heat; → `passive_cooling` at mean >= passive
  - `passive_cooling` → `neutral` at mean <= passive - 1; → `active_cooling` at mean >= active
  - `active_cooling` → `passive_cooling` at mean <= active - 1
- Cold start (no previous state): classified at the midpoint of each band (heat + 0.5,
  passive - 0.5, active - 0.5).

## Hardware / integration quirks
- The source sensor is `sensor.wheatherstation_outdoor_temperature` (spelled so; referenced by
  `pergola`, `airflow_cooling`, `heating_pv_boost` and the heating dashboard).
- The statistics sensor needs `max_age: 48:00:00` to pre-load history from the recorder on restart;
  `sampling_size` alone does not load history. `sampling_size: 192` (4/h x 48 h) is only a cap.
- The 15 min sensor is a `filter` (`time_simple_moving_average` then `time_throttle`, 15 min) so the
  statistics sensor sees one sample per 15 min.
- The forecast mean uses `weather.get_forecasts` (hourly, `weather.home`); the forecast is no longer
  an attribute, so it is a trigger-based template (every hour and on HA start).

## Entity map
The package sets no `default_entity_id`, so IDs of named sensors are derived by HA from the name.
CONFIRMED = referenced by working config outside this package (grep over `packages/`, `dashboards/`).
- Source `sensor.wheatherstation_outdoor_temperature` (confirmed; defined elsewhere)
- `sensor.wheatherstation_outdoor_temperature_48h_mean` (confirmed: heating dashboard)
- `sensor.wheatherstation_outdoor_temperature_15min`: unverified (derived from name; confirm via
  ha-mcp lookup)
- `sensor.wheatherstation_outdoor_temperature_48h_forecast_mean`: unverified (derived from name;
  confirm via ha-mcp lookup); mean of forecast hours from now - 1 h to now + 48 h, `unknown` with
  fewer than 48 usable hours
- `sensor.heating_cooling_indicator` (confirmed: pergola, airflow_cooling, heating_pv_boost,
  dashboards), `sensor.heating_indicator_passive_cooling_effective`,
  `sensor.heating_indicator_active_cooling_effective` (confirmed: heating dashboard)
- `input_number.heating_indicator_heating_below`, `input_number.heating_indicator_passive_cooling_above`,
  `input_number.heating_indicator_active_cooling_above` (confirmed: heating dashboard; 5-25 °C,
  step 0.5, box mode)
- Group `group.heating_cooling_indicator` lists all of the above.

## Decisions in force
- Effective sensors are shown on the dashboard so a clamp is visible next to the typed value.
- The forecast mean is not wired into the indicator yet.

## Known biases / open issues
- None recorded.

## Tests (`tests/test_heating_cooling_indicator.py`)
- The template re-renders on any dependency change and reads its own state, so each test sets the
  helpers, waits for the `*_effective` sensors, sets the mean, pins the indicator with `set_state`,
  then moves the mean across the boundary under test. Pin AFTER setting the mean, otherwise a late
  re-render changes the pinned state.
- Covered: each threshold taken from its helper, the +1 °C heating hysteresis, the order clamp
  (passive typed below heating; passive/active typed low). The forecast sensor and the
  passive/active hysteresis exits are not tested.

## Related
- `doc/KNOWLEDGE.md` (K-3 template); skills `ha-templates`, `ha-test-harness`.
- Consumers of `sensor.heating_cooling_indicator`: `packages/pergola.yaml` (heating season sync),
  `packages/airflow_cooling.yaml` (season input), `packages/heating_pv_boost.yaml` (heating-season
  gate), `dashboards/heating-dashboard.yaml`.
