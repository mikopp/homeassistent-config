# Heating — run statistics from the ehp, energy and efficiency split by mode

## Overview

The "Compressor Cycling" dashboard counts runs from the Shelly clamp (> 500 W) together with
`hvac_action`. On 2026-11-11 it showed 8 heating runs against the machine's 6 heating starts
(`CompStartsHc`). The flow-temperature graph shows 6 heating runs and 2 hot-water runs. Rows and
their popups also use different words ("starts" vs "runs").

Owner direction:
1. Count starts from the ehp's own counters (`CompStartsHc`, `CompStartsHwc`), not from the Shelly.
2. Report energy and efficiency separately for **heating** and **hot water**.
3. Book the circulation pump's energy while the compressor is off (no hot water, no cooling) to
   **heating**.
4. Book energy while **cooling** is active to a separate cooling bucket. Cooling has no yield and
   no efficiency.

HYPOTHESIS (not checked against history): the 2 extra Shelly "runs" are short false heating
segments at the end of each hot-water run, where `hvac_action` flips back to heat while the clamp
still reads > 500 W. A short `unavailable` dropout of the Shelly or `hvac_action` in the middle of
a run would also split one run into two. This plan replaces the Shelly as the run source, so both
causes go away; the hypothesis does not need to be settled first.

## Design

### Registers (published catalog `08.ehp.csv`)

| Need | Register | Note |
|---|---|---|
| Heating starts | `ehp/CompStartsHc` | already read |
| Hot-water starts | `ehp/CompStartsHwc` | new; the owner's `ebusctl` read 9419 |
| Runtime per mode | `ehp/CompHoursHc` / `ehp/CompHoursHwc` | whole hours only, so used only as a daily cross-check |
| Compressor on/off now | `ehp/Comp` | new; replaces the Shelly for run edges |
| Heat output | `ehp/YieldTotal` | the only yield register: no per-mode yield exists |
| Electricity | Shelly Pro 3EM "Heizung" energy | the only electrical meter |

### Energy mode (one decision, `ha-templates` "one decision sensor")

Five modes, defined by the owner. A template sensor `sensor.heating_energy_mode`:

| Condition (first match wins) | Mode | Energy bucket |
|---|---|---|
| `ehp/Comp` on and `hvac_action` = `water` | `water_heating` | hot water |
| `ehp/Comp` on (not water) | `active_heating` | heating |
| cooling indicator on (`binary_sensor.heating_cooling_active`) and `ehp/Hc1Pump` on | `cooling` | cooling |
| `ehp/Hc1Pump` on, no cooling | `passive_heating` | heating |
| none of the above (standby) | `off` | off |

- Pump state comes from `ehp/Hc1Pump` ("Status Heizkreispumpe: AN/AUS", in the published
  catalog), so every mode is read from the ehp. Alternative: Shelly > ~40 W (idle circulation
  ~83 W, standby ~9 W). Owner to choose; the ehp register needs two more bridge lines.
- UNKNOWN: whether `hvac_action` = `water` already covers the hot-water pump lag after the
  compressor stops (`HwcLaggingTime` 3 min). If not, that lag books to `passive_heating`.
- UNKNOWN: cooling with the compressor running (active cooling) books to `active_heating` under
  this order. If active cooling is used, put the cooling row first.

### Booking energy to a mode

Use HA's `utility_meter` with `tariffs:` (daily cycle). An automation sets each meter's tariff
`select` whenever `sensor.heating_energy_mode` changes.

- Electricity: one meter on the Shelly energy with one tariff per mode (`active_heating`,
  `passive_heating`, `water_heating`, `cooling`, `off`). Heating electricity = active + passive.
- Yield: one meter on `YieldTotal`, same tariffs. Only `active_heating` and `water_heating` should
  grow; the others are a check (non-zero = yield booked to the wrong mode).
- Efficiency today: heating = heating yield ÷ (active + passive heating electricity); hot water =
  hot-water yield ÷ hot-water electricity. No efficiency for cooling or off. Keep the
  "under 1 kWh → 0" rule from the existing efficiency sensor.

HYPOTHESIS: `YieldTotal` arrives in whole kWh at the poll rate, so an increment that lands just
after a mode switch is booked to the wrong mode. Over a day with ~1 h hot-water runs this should
roughly balance. Check against the totals for a few days before relying on the split.

### Run statistics

- Starts per day: daily `utility_meter`s on `CompStartsHc` (exists) and `CompStartsHwc` (new).
- Runs, runtime, average run, last run, duty cycle: `binary_sensor.heating_compressor_heating_active`
  becomes "energy mode = `active_heating`" (instead of Shelly > 500 W). Keeps the entity ids, so history continues.
- `binary_sensor.heating_compressor_active` (Shelly) stays for the slab-boost surplus logic.
  Not changed here.

UNKNOWN: how quickly `ehp/Comp` reports a change at a given poll priority. If the lag is long,
runtimes shift by that lag. Measure it against the Shelly after deploy.

## Steps

### Phase 1 — inputs
1. [TODO] MQTT sensors for `ehp/CompStartsHwc`, `ehp/Comp` and `ehp/Hc1Pump`; add them to the
   poll-registration automation. Depends on: nothing.
   PR post-deploy steps: for each of the three, `topic ebusd/ehp/<name> in 0` and
   `topic ebusd/ehp/<name>/get out 0`, then restart Mosquitto.
2. [TODO] Optional: `ehp/CompHoursHwc` (+ its two bridge lines) for the daily cross-check.

### Phase 2 — mode and run source
3. [TODO] `sensor.heating_energy_mode` per the table above. Tests: every row, the row order
   (compressor before cooling before pump), raw enum numbers, unavailable inputs.
4. [TODO] Change `binary_sensor.heating_compressor_heating_active` to mode `active_heating`.
   Update tests `test_compressor_table`, `test_last_run` and `test_cycling_history_stats`.

### Phase 3 — energy split
5. [TODO] Tariff `utility_meter`s for electricity and yield, the tariff automation, and the two
   efficiency sensors. Replace or keep the combined `heating_efficiency_today` (owner decides).
   Tests on the frozen clock: each of the five modes books to its own tariff, heating efficiency
   uses active + passive, no cooling/off efficiency, midnight reset.
6. [TODO] Daily starts meter for hot water.

### Phase 4 — dashboard
7. [TODO] Rename the cycling rows and the entity names so each row and its popup say the same
   thing. Show the current energy mode; heating and hot water side by side (starts, energy,
   yield, efficiency); heating energy also split active / passive; cooling and off energy rows.

### Phase 5 — verification
8. [TODO] `ci-local.sh` green. After deploy, compare for 3 days: starts vs the graph, run edges
   vs the Shelly, `heating + hot_water + cooling` electricity vs the total, and the yield split.

### Close
9. [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
   plan (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes this plan will update

- `doc/heating_pv_boost/notes.md`: entity map (new entities), the energy-mode decision, the
  baseline method's "Starts per day" and efficiency lines, the "Tests" section.
- `doc/heating_pv_boost/registers.md`: `CompStartsHwc`, `Comp`, `CompHoursHwc`.
- YAML comments in `packages/heating_pv_boost.yaml` (K-5).

## Status

- Plan drafted; waiting for owner approval. Nothing implemented.
- Five modes defined by the owner (active/passive heating, water heating, cooling, off).
- Open questions: pump state from `ehp/Hc1Pump` or the Shelly?; is active cooling (compressor)
  used?; keep the combined efficiency sensor?; include `CompHoursHwc`?
