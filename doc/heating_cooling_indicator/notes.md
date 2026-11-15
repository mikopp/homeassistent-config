---
paths:
  - "packages/heating_cooling_indicator.yaml"
  - "tests/ha/test_heating_cooling_indicator.py"
---
# heating_cooling_indicator.yaml — outdoor-temperature mode indicator

Notes for `packages/heating_cooling_indicator.yaml`. Classifies the 48 h mean outdoor temperature
into four modes for ventilation automations. No design doc. Thresholds, clamp, hysteresis, cold
start and history loading are in the YAML comments.

## Invariants
- The 15min filter and the 48h statistics mean are named "Weatherstation ..." but referenced as
  `sensor.wheatherstation_...` (the misspelled prefix of the source). A fresh registry derives
  `sensor.weatherstation_...` (CONFIRMED: `tests/ha/conftest.py`, every fresh test HA), so the live
  ids exist only in `.storage`. Any re-registration breaks the chain silently: the 48h mean reads a
  missing `..._15min` and the indicator goes unavailable for all consumers. Fix = `default_entity_id`
  (same class as #146, which covers only MQTT sensors).
  The misspelling is accepted (owner decision): do not rename it; it is live in several packages.

## Hardware / integration quirks
- None beyond the YAML comments.

## Entity map
No `default_entity_id` in this package. "live" = found via ha-mcp search; "used by" = read by config
outside this package.
- Source `sensor.wheatherstation_outdoor_temperature` (live; defined elsewhere, friendly name
  carries the misspelling)
- `sensor.wheatherstation_outdoor_temperature_15min` (live; registry-dependent, see Invariants)
- `sensor.wheatherstation_outdoor_temperature_48h_mean` (live; used by heating dashboard;
  registry-dependent, see Invariants)
- `sensor.weatherstation_outdoor_temperature_48h_forecast_mean` (live; correct spelling although its
  `unique_id` is `wheatherstation_...`; only consumer is the group)
- `group.heating_cooling_indicator` (no consumer in config or live automations; state `unknown`
  because all members are sensors/input_numbers)
- `sensor.heating_cooling_indicator` (used by pergola, airflow_cooling, airflow_decision.jinja,
  heating_pv_boost, dashboards), `sensor.heating_indicator_passive_cooling_effective`,
  `sensor.heating_indicator_active_cooling_effective` (used by heating dashboard)
- `input_number.heating_indicator_heating_below`, `input_number.heating_indicator_passive_cooling_above`,
  `input_number.heating_indicator_active_cooling_above` (used by heating dashboard)

## Decisions in force
- None beyond the YAML comments.

## Known biases / open issues
- The `wheatherstation_` prefix comes from the Ecowitt device, user-named "Wheatherstation" (live
  `name_by_user`); all its ~50 entities carry it. The 15min/48h-mean ids copy it only via `.storage`
  (see Invariants). Renaming them needs a live UI rename plus a matching YAML/test change in one
  deploy; not done.

## Tests (`tests/ha/test_heating_cooling_indicator.py`, in-process)
- The forecast sensor and the passive/active hysteresis exits are not tested.

## Related
- Skills `ha-templates`, `ha-test-harness`.
- Consumers of `sensor.heating_cooling_indicator` (check before renaming a state):
  `packages/pergola.yaml` (heating season sync), `packages/airflow_cooling.yaml` +
  `custom_templates/airflow_decision.jinja` (season input), `packages/heating_pv_boost.yaml`
  (heating-season gate), `dashboards/heating-dashboard.yaml`, `dashboards/airflow-dashboard.yaml`.
