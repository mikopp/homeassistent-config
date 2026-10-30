# To do — future plans

Work that is agreed to be worth doing but is not part of any current plan. When an item is picked
up, create its own plan file in `plans/` and remove it here.

## PV priority between PV-surplus loads

The heating PV boost (`packages/heating_pv_boost.yaml`) and the HRDS dehumidifier
(`packages/hrds_dehumidifier.yaml`, planned) each compute their own surplus and can see the same
surplus at the same moment, so both may start on power that covers only one. They already share one
battery floor (`binary_sensor.energy_pv_battery_ok`, `packages/energy.yaml`). Open: which load has
priority, and how a load sees the surplus left after the others (e.g. subtract the running draw of
every other PV load). Raised in `plans/hrds-dehumidifier.md` (I11).

## Shared climate parameters package

The humidity and temperature thresholds (`input_number.airflow_target_humidity` / `_max` / `_min`,
`airflow_cooling_target_temperature`, the dew-point sensors, the indoor averages and dew, the boost
schedules and `binary_sensor.airflow_boost_window_active`) live in `packages/airflow_cooling.yaml`,
and the HRDS package depends on them. Move them to a neutral package (e.g. `climate_common.yaml`,
`climate_*` ids) so neither feature owns them. Needs a history-preserving migration: keep each
template sensor's `unique_id` and rename its entity id in the registry; snapshot and restore the
YAML helper values. Raised in `plans/hrds-dehumidifier.md` (Decision 20).
