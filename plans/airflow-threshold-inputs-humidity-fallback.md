# Plan: Airflow Threshold Inputs + Humidity Fallback

## Status: IMPLEMENTED

## Goal
1. Expose `min_dew_diff` and `min_temp_diff` as user-settable `input_number` helpers
2. Wire them into `binary_sensor.airflow_free_cooling_available` (currently hardcoded locals)
3. Remove unused `variables:` block from the climate entity
4. Fall back to `sensor.comfoconnect_pro_extract_air_humidity` in `airflow_avg_indoor_humidity` when `label_entities('Indoor.Humidity')` returns nothing

---

## Findings

### Climate entity `variables:` block — UNUSED
Lines 167–170 define:
```yaml
variables:
  min_dew_diff: 2.0
  min_temp_diff: 1.5
```
None of the climate entity's templates reference these variables.
They were a comment placeholder, not functional. **Remove.**

### `label_entities('Indoor.Humidity')` — returns `[]`
Confirmed via MCP `ha_eval_template`. Fallback is required for the sensor to work at all.
Best ComfoConnect fallback: `sensor.comfoconnect_pro_extract_air_humidity`
(extract air = air pulled from inside the house; state: 54 %, unit: %)

---

## Changes — all in `packages/airflow_cooling.yaml`

### Step 1 — Add two input_number helpers

```yaml
input_number:
  airflow_min_dew_diff:
    name: "Airflow Min Dew Diff"
    min: 0
    max: 5
    step: 0.5
    unit_of_measurement: "°C"
    icon: mdi:water-thermometer

  airflow_min_temp_diff:
    name: "Airflow Min Temp Diff"
    min: 0
    max: 5
    step: 0.5
    unit_of_measurement: "°C"
    icon: mdi:thermometer-chevron-up
```

Default values will be set via HA UI after deploy (2.0 and 1.5 respectively).
The helpers have no `initial:` to avoid overwriting persisted values on restart.

### Step 2 — Update binary_sensor.airflow_free_cooling_available

Replace:
```jinja2
{% set min_dew_diff = 2.0 %}
{% set min_temp_diff = 1.5 %}
```
With:
```jinja2
{% set min_dew_diff = states('input_number.airflow_min_dew_diff') | float(2.0) %}
{% set min_temp_diff = states('input_number.airflow_min_temp_diff') | float(1.5) %}
```
Update comment on the binary sensor to remove the "internal constants" note.

### Step 3 — Remove unused variables block from climate entity

Remove lines:
```yaml
# Internal threshold constants; same values used in binary_sensor.airflow_free_cooling_available
variables:
  min_dew_diff: 2.0
  min_temp_diff: 1.5
```

### Step 4 — Add ComfoConnect fallback to airflow_avg_indoor_humidity template

Current state template:
```jinja2
{% set indoor_hums = label_entities('Indoor.Humidity')
  | map('states') | map('float', none) | reject('none') | list %}
{{ (indoor_hums | sum / indoor_hums | count) | round(1) if indoor_hums | count > 0 else 0 }}
```

New state template:
```jinja2
{% set indoor_hums = label_entities('Indoor.Humidity')
  | map('states') | map('float', none) | reject('none') | list %}
{% if indoor_hums | count > 0 %}
  {{ (indoor_hums | sum / indoor_hums | count) | round(1) }}
{% else %}
  {{ states('sensor.comfoconnect_pro_extract_air_humidity') | float(0) | round(1) }}
{% endif %}
```

New availability template:
```jinja2
{% set label_count = label_entities('Indoor.Humidity')
   | map('states') | map('float', none) | reject('none') | list | count %}
{{ label_count > 0 or states('sensor.comfoconnect_pro_extract_air_humidity') not in ['unavailable', 'unknown'] }}
```

### Step 5 — Add new helpers to group

Add to `group.airflow_cooling.entities`:
```yaml
- input_number.airflow_min_dew_diff
- input_number.airflow_min_temp_diff
```

---

## Post-deploy

Set initial values in HA UI (or via Developer Tools > States):
- `input_number.airflow_min_dew_diff` → 2.0
- `input_number.airflow_min_temp_diff` → 1.5
