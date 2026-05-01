# Plan: Ventilation Profile Automation

## Status: IMPLEMENTED

## Goal
Unified ventilation profile control driven by outdoor temperature mode + free cooling condition.

## New file: `packages/heating-cooling-indicator.yaml`
Template sensor `sensor.heating_cooling_indicator` based on `sensor.wheatherstation_outdoor_temperature`:
- `<= 5°C` → `active_heating`
- `> 5 and < 10°C` → `neutral`
- `>= 10 and < 15°C` → `passive_cooling`
- `>= 15°C` → `active_cooling`

## Changes: `packages/airflow-cooling.yaml`
1. Add `binary_sensor.free_cooling_active` (template) — same condition as old trigger, debounced:
   - `delay_on: 10 min` — avoids spurious eco activations
   - `delay_off: 15 min` — avoids flip-flop on borderline conditions
2. New automation "Ventilation: Set Temperature Profile" replaces both old automations:
   - `active_heating` → `warm`
   - `neutral` → `comfort`
   - `passive_cooling`/`active_cooling` + free cooling ON → `eco`
   - `passive_cooling`/`active_cooling` + free cooling OFF → `comfort`
3. Remove old "Optimized Bypass Control" and "Restore Normal Profile" automations.
4. Exclude `binary_sensor.free_cooling_active` from recorder.

## Profile mapping
| Indicator       | Free Cooling | Profile  |
|----------------|-------------|---------|
| active_heating  | any         | warm    |
| neutral         | any         | comfort |
| passive_cooling | off         | comfort |
| passive_cooling | on          | eco     |
| active_cooling  | off         | comfort |
| active_cooling  | on          | eco     |
