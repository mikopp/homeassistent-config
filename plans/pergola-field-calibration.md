# Pergola field calibration

**Status:** PLAN ONLY (open since the original implementation; was "Phase 5 Step 6" of the old
design doc). Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** `packages/pergola.yaml` deployed and running for at least one sunny and one
rainy day.

## Overview
The pergola automation runs with values that were estimated, not measured on site. This plan
tunes them in the field. Values are set in the HA UI (helpers have no `initial:`); a changed
constant inside the YAML (drain angles) is a code change with a test run.

## Design approach
Observe, adjust the helper in the UI, write the value that worked into the note. No formula
changes; if a formula turns out wrong, open a separate plan.

## Steps

### Phase 1: sun detection
1. [TODO] PV conversion factor (now 3.2): on a clear morning adjust
   `input_number.pergola_pv_conversion_factor` until `sensor.pergola_pv_power / factor ≈
   sensor.wheatherstation_solar_radiation`. Design: `doc/pergola/design.md#PG-8`.
2. [TODO] Shading sensitivity (now 0.9): on a partly cloudy afternoon check that the on/off
   boundary of `binary_sensor.pergola_sun_shining` feels right; adjust
   `input_number.pergola_shading_sensitivity`.
3. [TODO] Sun azimuth window: observe shadows; fine-tune `input_number.pergola_wall_azimuth` if
   needed (window and A_eff re-derive). Design: `#PG-3`.

### Phase 2: rain
4. [TODO] Post-rain drain angles (8° / 15°, `#PG-6.1`): after the first real rain confirm the
   slats drain; if not, change the angles in `script.pergola_post_rain_recovery` (code change,
   run `tests/test_pergola.py`).
5. [TODO] Rain lock originator: log `sensor.dach_links_priority_lock_originator` during rain and
   verify the covers move again after rain stops (`#PG-2.4`).

### Phase 3: close
6. [TODO] Close: write the calibrated values and any observed hardware quirk into
   `doc/pergola/notes.md` (current facts) and `doc/pergola/design.md` if a design value
   changed; story → `doc/pergola/background.md`; update pointers; check the note is ≤ 24 KB;
   delete this plan (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes updated
`doc/pergola/notes.md` (calibrated values, decisions), `doc/pergola/design.md` (drain angles
or thresholds if they change), `doc/pergola/background.md` (calibration story).
