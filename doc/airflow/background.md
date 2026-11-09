Background only: not design-relevant; current design is design.md.

# Airflow cooling & humidity: background

History and superseded designs for `packages/airflow_cooling.yaml` and
`packages/heating_cooling_indicator.yaml`. Never cite this file as current behaviour; the current
design is `doc/airflow/design.md`, current package facts are in `doc/airflow/notes.md`.
IDs `AF-B<n>` are stable. Raw material (never edited, guarded): `doc/sources/airflow/`.

## AF-B1 Boost debounce: `delay_on` / `delay_off` on `drying_needed`

- `binary_sensor.airflow_humidity_drying_needed` once had a 10-min `delay_on` to stop weather-station
  noise spikes from falsely starting/stopping a boost. Smoothing the weather-station chain
  (`airflow_wheatherstation_outdoor_temp_5min`) replaced that debounce, and `delay_on` was removed.
- Effect on start latency: was flush 10 min + drying 10 min = 20 min; now ~10 min (flush only).
- The architecture doc then still said "`delay_off` 10 min kept to avoid premature boost stop".
  At the knowledge restructure (PR #141, 2026-11-07) the YAML had neither
  `delay_on` nor `delay_off` on this sensor, only a 0.3 °C `this.state` hysteresis; the doc was
  corrected to the YAML.
- The sensor also once self-gated on `NOT low_active` (moisture-low). Dropped once `low_needed`
  was gated OFF during a flush: the guard became redundant and would have formed a
  `low_needed → drying_needed → low_needed` cycle.

## AF-B2 Former profile Blocks 1-5 and the per-block matrix

The profile logic was once a set of Blocks 1-5, several of which had a `keep` row (hold the current
profile). A per-block transition matrix documented them, with `keep` traps C7/N3/C8/W1/W2/H6
(stuck-`cool` / stuck-`warm` states that needed recovery). The single stateless decision replaced
them: the former Blocks 3/4/5 collapse into decision row P5 (comfort), and no `keep` row is left
apart from P3's dry-retention hysteresis. The matrix is obsolete.

## AF-B3 Restart-stale `ventilation_low_needed`

`binary_sensor.airflow_ventilation_low_needed` (OR of moisture-low and heat-low) was once
trigger-based. After a HA restart it restored `off` while `heat_low` was `on`, and because its
inputs are slow binaries that did not change, it never recomputed: stale for hours, all day. The
state was `heat_protection` all day yet the preset stayed at medium, because the consumer read the
stale `off`. Fix: make it state-based; the general rule (derived-from-binaries ⇒ state-based) is in
the note and design AF-10.

## AF-B4 Why there is one decision sensor

Before `sensor.airflow_cooling_state`, several consumers each re-implemented the season rules
and disagreed; one result was free cooling being applied in active heating. The decision-table
example "active_heating + free cooling available → heating / warm / auto" carried the date
2026-10-23 in the architecture doc.

## AF-B5 Season thresholds were hard-coded

`sensor.heating_cooling_indicator` once used fixed thresholds on the 48h mean: active_heating
≤ 5 / exit ≥ 6 °C, passive_cooling ≥ 11 / exit ≤ 10 °C, active_cooling ≥ 16 / exit ≤ 15 °C. They are
now `input_number` helpers with a fixed 1 °C hysteresis (design AF-4).
