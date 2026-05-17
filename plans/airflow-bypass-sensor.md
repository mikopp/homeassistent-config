# Plan: ERV Bypass Percentage Sensor

**Status:** AWAITING APPROVAL  
**Target file:** `packages/airflow_cooling.yaml`  
**Reference:** `plans/estimated-bypass-percentage-evr.md`

---

## Overview

Add a template sensor that estimates the Zehnder ComfoAir Q350 bypass valve position (0–100%)
by measuring how far current ERV efficiency has degraded from its calibrated maximum.
Method: enthalpy-based linear interpolation between eff_max (bypass=0%) and eff_min (bypass=100%).

Output is a numeric `%` sensor. Exposed as attribute on the airflow climate entity.

---

## Architecture

```
ComfoConnect sensors (raw)
  ├── outdoor_air_temperature      → [already filtered: airflow_outdoor_temp_5min]
  ├── outdoor_air_humidity         → [NEW filter: airflow_outdoor_humidity_5min]
  ├── supply_air_temperature       → [NEW filter: airflow_supply_air_temp_5min]
  ├── supply_air_humidity          → [NEW filter: airflow_supply_air_humidity_5min]
  ├── extract_air_temperature      → [already filtered: used directly, no 5min yet — see Step 2]
  └── extract_air_humidity         → [already filtered: used directly, no 5min yet — see Step 2]

input_number helpers (calibration)
  ├── airflow_bypass_eff_max       (default 0.75)
  ├── airflow_bypass_eff_min       (default 0.05)
  └── airflow_bypass_p_atm         (default 101.3 kPa)

template sensor
  └── airflow_erv_bypass_percentage
        inputs: 6 smoothed sensors + 3 calibration helpers
        method: enthalpy efficiency → linear interpolation → clamp → round(1) %
        unavailable when: any input unavailable OR |h_ra - h_oa| < 0.5 kJ/kg

climate entity attribute
  └── erv_bypass_pct → reads airflow_erv_bypass_percentage

group
  └── + new filter sensors + template sensor + new input_numbers
```

---

## ⚠️ Entity IDs to Verify Before Implementation

The following 3 entity IDs are **inferred** from ComfoConnect naming conventions.
Must be confirmed via MCP entity lookup before Step 2.

| Role | Assumed entity ID | Verified? |
|---|---|---|
| RH_OA — outdoor air humidity | `sensor.comfoconnect_pro_outdoor_air_humidity` | ❌ |
| T_SA — supply air temperature | `sensor.comfoconnect_pro_supply_air_temperature` | ❌ |
| RH_SA — supply air humidity | `sensor.comfoconnect_pro_supply_air_humidity` | ❌ |

---

## Implementation Steps

### Phase 1 — Entity Discovery

**Step 1 [TODO]** Verify 3 ComfoConnect entity IDs via MCP  
- Look up: outdoor_air_humidity, supply_air_temperature, supply_air_humidity  
- Update table above with confirmed IDs  
- Dependency: none  

---

### Phase 2 — Filter Sensors (smoothed inputs)

**Step 2 [TODO]** Add 3 filter sensors to `packages/airflow_cooling.yaml` under `sensor:`

```yaml
# Smooth outdoor air humidity — needed for enthalpy bypass calculation
- platform: filter
  unique_id: airflow_outdoor_humidity_5min
  name: "Airflow Outdoor Humidity 5min"
  entity_id: sensor.comfoconnect_pro_outdoor_air_humidity   # VERIFY
  filters:
    - filter: time_simple_moving_average
      window_size: "00:05"
      precision: 1
    - filter: time_throttle
      window_size: "00:05"

# Smooth supply air temperature — post-ERV-core fresh air going to rooms
- platform: filter
  unique_id: airflow_supply_air_temp_5min
  name: "Airflow Supply Air Temp 5min"
  entity_id: sensor.comfoconnect_pro_supply_air_temperature   # VERIFY
  filters:
    - filter: time_simple_moving_average
      window_size: "00:05"
      precision: 2
    - filter: time_throttle
      window_size: "00:05"

# Smooth supply air humidity — post-ERV-core fresh air going to rooms
- platform: filter
  unique_id: airflow_supply_air_humidity_5min
  name: "Airflow Supply Air Humidity 5min"
  entity_id: sensor.comfoconnect_pro_supply_air_humidity   # VERIFY
  filters:
    - filter: time_simple_moving_average
      window_size: "00:05"
      precision: 1
    - filter: time_throttle
      window_size: "00:05"
```

Note: T_OA uses existing `airflow_outdoor_temp_5min`. T_RA and RH_RA are used raw from ComfoConnect
(extract air sensors) — acceptable since they are inside-house readings that change slowly.

---

### Phase 3 — Calibration Helpers

**Step 3 [TODO]** Add 3 `input_number` helpers to `packages/airflow_cooling.yaml`

```yaml
# ERV efficiency when bypass is confirmed 0% (full heat recovery)
airflow_bypass_eff_max:
  name: "Airflow Bypass Eff Max"
  min: 0.50
  max: 1.00
  step: 0.01
  unit_of_measurement: ""
  icon: mdi:heat-wave

# Residual ERV efficiency when bypass is 100% open (housing leakage gain)
airflow_bypass_eff_min:
  name: "Airflow Bypass Eff Min"
  min: 0.00
  max: 0.20
  step: 0.01
  unit_of_measurement: ""
  icon: mdi:valve-open

# Local atmospheric pressure for humidity ratio calculation
airflow_bypass_p_atm:
  name: "Airflow Bypass P Atm"
  min: 90.0
  max: 110.0
  step: 0.1
  unit_of_measurement: "kPa"
  icon: mdi:gauge
```

Default values (set in UI after deploy, not in YAML to allow persistence):
- eff_max: 0.75 (Q350 rated ~75% temperature efficiency)
- eff_min: 0.05 (estimated housing leakage gain)
- p_atm: 101.3 (standard sea level; adjust for local altitude)

---

### Phase 4 — Bypass Template Sensor

**Step 4 [TODO]** Add template sensor under `template: - sensor:` in `packages/airflow_cooling.yaml`

```yaml
# Estimates ERV bypass valve position via enthalpy efficiency degradation
# Formula: B = (eff_max - eff_curr) / (eff_max - eff_min), clamped 0–100%
- unique_id: airflow_erv_bypass_percentage
  name: "Airflow ERV Bypass Percentage"
  unit_of_measurement: "%"
  state_class: measurement
  icon: mdi:valve
  state: >
    {% set T_oa  = states('sensor.airflow_outdoor_temp_5min')          | float(none) %}
    {% set RH_oa = states('sensor.airflow_outdoor_humidity_5min')       | float(none) %}
    {% set T_sa  = states('sensor.airflow_supply_air_temp_5min')        | float(none) %}
    {% set RH_sa = states('sensor.airflow_supply_air_humidity_5min')    | float(none) %}
    {% set T_ra  = states('sensor.comfoconnect_pro_extract_air_temperature') | float(none) %}
    {% set RH_ra = states('sensor.comfoconnect_pro_extract_air_humidity')    | float(none) %}
    {% set P     = states('input_number.airflow_bypass_p_atm')          | float(101.3) %}
    {% set e_max = states('input_number.airflow_bypass_eff_max')        | float(0.75) %}
    {% set e_min = states('input_number.airflow_bypass_eff_min')        | float(0.05) %}

    {% if none in [T_oa, RH_oa, T_sa, RH_sa, T_ra, RH_ra] %}
      {{ none }}
    {% else %}
      {# Enthalpy for each air stream: h = 1.006·T + w·(2501 + 1.86·T), w = 0.622·pv/(P-pv) #}
      {% set ps_oa = 0.61078 * exp(17.27 * T_oa / (T_oa + 237.3)) %}
      {% set pv_oa = ps_oa * (RH_oa / 100.0) %}
      {% set w_oa  = 0.622 * (pv_oa / (P - pv_oa)) %}
      {% set h_oa  = 1.006 * T_oa + w_oa * (2501 + 1.86 * T_oa) %}

      {% set ps_sa = 0.61078 * exp(17.27 * T_sa / (T_sa + 237.3)) %}
      {% set pv_sa = ps_sa * (RH_sa / 100.0) %}
      {% set w_sa  = 0.622 * (pv_sa / (P - pv_sa)) %}
      {% set h_sa  = 1.006 * T_sa + w_sa * (2501 + 1.86 * T_sa) %}

      {% set ps_ra = 0.61078 * exp(17.27 * T_ra / (T_ra + 237.3)) %}
      {% set pv_ra = ps_ra * (RH_ra / 100.0) %}
      {% set w_ra  = 0.622 * (pv_ra / (P - pv_ra)) %}
      {% set h_ra  = 1.006 * T_ra + w_ra * (2501 + 1.86 * T_ra) %}

      {# Guard: indoor/outdoor energy gap too small to distinguish bypass state #}
      {% if (h_ra - h_oa) | abs < 0.5 %}
        {{ none }}
      {% else %}
        {% set eff_curr = (h_sa - h_oa) / (h_ra - h_oa) %}
        {% set b_raw    = (e_max - eff_curr) / (e_max - e_min) %}
        {% set b_pct    = [0, [1, b_raw] | min] | max * 100 %}
        {{ b_pct | round(1) }}
      {% endif %}
    {% endif %}
  availability: >
    {% set sensors = [
      'sensor.airflow_outdoor_temp_5min',
      'sensor.airflow_outdoor_humidity_5min',
      'sensor.airflow_supply_air_temp_5min',
      'sensor.airflow_supply_air_humidity_5min',
      'sensor.comfoconnect_pro_extract_air_temperature',
      'sensor.comfoconnect_pro_extract_air_humidity'
    ] %}
    {{ sensors | map('states') | map('float', none) | reject('none') | list | count == 6 }}
```

Note: Jinja2's `min`/`max` filters operate on lists. Clamp uses `[0, [1, b_raw]|min]|max`.
`exp()` is available in HA templates natively.

---

### Phase 5 — Climate Entity Attribute

**Step 5 [TODO]** Add `erv_bypass_pct` to the `attributes:` block of `climate.airflow_climate`

```yaml
erv_bypass_pct: "{{ states('sensor.airflow_erv_bypass_percentage') | float(none) }}"
```

---

### Phase 6 — Group Update

**Step 6 [TODO]** Add new entities to `group.airflow_cooling` entities list

```yaml
# New filter sensors
- sensor.airflow_outdoor_humidity_5min
- sensor.airflow_supply_air_temp_5min
- sensor.airflow_supply_air_humidity_5min
# ERV bypass sensor
- sensor.airflow_erv_bypass_percentage
# Calibration helpers
- input_number.airflow_bypass_eff_max
- input_number.airflow_bypass_eff_min
- input_number.airflow_bypass_p_atm
```

---

## Calibration Notes (post-deploy)

After deploy, calibrate by observing:
1. Set `eff_max` by reading efficiency during cold weather (bypass definitely 0%):
   `eff_max = (T_SA - T_OA) / (T_RA - T_OA)` — measure directly in HA dev tools
2. Set `eff_min` by reading efficiency on a hot summer day with bypass forced open
   (or use 0.05 as a conservative default — it only clips the 100% end)
3. `p_atm` = look up local altitude, subtract ~1.2 kPa per 100m above sea level

---

## Recorder

No new recorder exclusions needed — the bypass sensor is worth archiving for calibration and trending.
