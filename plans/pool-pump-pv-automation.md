# Pool Pump Package — Implementation Plan

**Status: IMPLEMENTED** on branch `claude/pool-pump-pv-automation-5l1wes`

## Context

The pool pump was monitored via `packages/shelly_pool_pump.yaml` (Shelly Plus Plug S, MQTT),
but had no HA control capability: the on/off schedule lived inside the Shelly device itself.

The HRDS plan (`plans/hrds-dehumidifier.md`, Decision 1) resolved the PV-surplus architecture:
a dedicated `packages/energy.yaml` owns the shared free-energy primitives and absorbs the Shelly
pool pump monitoring sensors. This plan implements `energy.yaml` ahead of the HRDS package so both
can reference the same canonical entities.

---

## Files changed

| Action | Path |
|--------|------|
| CREATE | `packages/energy.yaml` |
| CREATE | `packages/pool_pump.yaml` |
| DELETE | `packages/shelly_pool_pump.yaml` |
| CREATE | `tests/test_pool_pump.py` |
| MODIFY | `tests/conftest.py` |

No changes to `configuration.yaml`, `automations.yaml`, or any other package.

---

## VistaPool entity IDs (confirmed on live system)

Device name in HA: **"Mike"** (Vistapool by Sugar Valley, Firmware 1281, area: Terrasse)

| Entity | Description |
|--------|-------------|
| `sensor.mike_redox_potential` | ORP / Rx redox potential (mV) |
| `sensor.mike_ph` | pH value |
| `sensor.mike_temperature` | Pool water temperature (°C) |

The ORP alarm is implemented as a configurable template threshold
(`input_number.pool_orp_alarm_threshold`, default 650 mV) — the VistaPool integration
does not expose a built-in alarm binary sensor.

**Manual step required:** disable the Shelly's internal schedule in the Shelly web UI before
the HA-controlled schedule goes live, to prevent the device fighting HA commands.

---

## `packages/energy.yaml`

Shared energy layer — owned here, referenced by all load packages.

- **Shelly MQTT monitoring** (migrated verbatim from `shelly_pool_pump.yaml`):
  `sensor.pool_pump_power/energy/voltage/current/temperature`, `binary_sensor.pool_pump_switch`
  All `unique_id`s preserved → entity IDs and history unchanged.
- **MQTT switch** `switch.pool_pump` — HA commands the Shelly plug.
- **`input_number.energy_battery_soc_min`** (default 80 %) — shared SOC floor.
- **`input_number.energy_min_surplus`** (default 50 W) — noise floor for free-energy gate.
- **`sensor.energy_pv_surplus`** — mirrors `sensor.victron_grid_power_export` (non-negative W).
- **`binary_sensor.energy_free_available`** — surplus > noise floor AND SOC ≥ minimum.

---

## `packages/pool_pump.yaml`

All pool-specific logic.

### Helpers

| Helper | Default | Purpose |
|--------|---------|---------|
| `input_number.pool_pv_surplus_threshold` | 500 W | Minimum PV export for early start / energy gate |
| `input_number.pool_battery_soc_min` | 80 % | SOC floor for extended-run energy gate |
| `input_number.pool_temp_threshold` | 30 °C | Outdoor temp above which extended run is considered |
| `input_number.pool_orp_alarm_threshold` | 650 mV | ORP below this → alarm on |
| `input_boolean.pool_pump_extended_run` | — | Tracks that pump is running past schedule end |

### Template binary sensors

- **`binary_sensor.pool_pv_surplus_available`** — `energy_pv_surplus >= pool_pv_surplus_threshold`
- **`binary_sensor.pool_extended_run_energy_ok`** — surplus available OR SOC ≥ minimum
- **`binary_sensor.pool_orp_alarm`** — `mike_redox_potential < pool_orp_alarm_threshold`
- **`binary_sensor.pool_extended_run_conditions_met`** — temp > threshold AND orp_alarm AND energy_ok

All sensors have `availability:` guards.

### Schedule

`schedule.pool_pump_normal` — 11:00–17:30 daily (all 7 days). Replaces Shelly's internal schedule.

### Automations

| ID | Trigger | Condition | Action |
|----|---------|-----------|--------|
| `pool_pump_schedule_on` | schedule → on | — | turn on switch.pool_pump |
| `pool_pump_schedule_off` | schedule → off | pump is on | if conditions_met: set extended_run flag; else turn off pump |
| `pool_pump_early_start` | pv_surplus_available → on | schedule off AND time 08:00–11:00 | turn on pump |
| `pool_pump_early_stop` | pv_surplus_available → off | schedule off AND time 08:00–11:00 AND pump on | turn off pump |
| `pool_pump_extended_run_stop` | conditions_met → off OR extended_run → on | extended_run on AND conditions_met off | turn off pump, clear extended_run flag |

---

## Sensors referenced

| Entity | Source |
|--------|--------|
| `sensor.energy_pv_surplus` | `packages/energy.yaml` |
| `sensor.victron_battery_soc` | `packages/victron.yaml` (MQTT) |
| `sensor.victron_grid_power_export` | `packages/victron.yaml` (template) |
| `sensor.wheatherstation_outdoor_temperature` | `packages/pergola.yaml` (MQTT) |
| `sensor.mike_redox_potential` | VistaPool integration (UI), device "Mike" |
| `sensor.mike_ph` | VistaPool integration (UI), device "Mike" |
| `sensor.mike_temperature` | VistaPool integration (UI), device "Mike" |

---

## ORP alarm logic

The VistaPool integration exposes only raw sensor values — no built-in alarm entities.
The alarm is derived in HA:

```yaml
state: >
  {{ states('sensor.mike_redox_potential') | float(999)
     < states('input_number.pool_orp_alarm_threshold') | float }}
availability: >
  {{ states('sensor.mike_redox_potential') not in ['unavailable', 'unknown'] }}
```

- `| float(999)`: if the sensor is transiently unknown, 999 mV is above any threshold → no false alarm.
- `availability:` guard: when VistaPool cloud is offline the alarm becomes `unavailable`,
  which blocks `pool_extended_run_conditions_met` availability → extended run cannot start.
- Default threshold: 650 mV. Adjustable at runtime via `input_number.pool_orp_alarm_threshold`.

---

## Verification checklist

- [ ] Disable Shelly's internal schedule in Shelly web UI
- [ ] `switch.pool_pump` visible in HA and toggleable manually
- [ ] At 11:00: pump turns on via HA log
- [ ] At 17:30, low PV / low SoC / cool temp: pump turns off
- [ ] Before 11:00 with export ≥ 500 W: pump starts early
- [ ] PV drops before 11:00: pump stops again
- [ ] Near 17:30 with all conditions met: pump continues past schedule
- [ ] Clear one condition: pump stops, extended_run flag clears
