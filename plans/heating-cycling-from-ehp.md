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
| Runtime per mode | `ehp/CompHoursHc` / `ehp/CompHoursHwc` | whole hours only; `CompHoursHwc` not added (owner) |
| Compressor on/off now | `ehp/Comp` | new; replaces the Shelly for run edges |
| Heat output | `ehp/YieldTotal` | the only yield register: no per-mode yield exists |
| Electricity | Shelly Pro 3EM "Heizung" energy | the only electrical meter |

### Energy mode (one decision, `ha-templates` "one decision sensor")

Five modes, defined by the owner. A template sensor `sensor.heating_energy_mode`:

| Condition (first match wins) | Mode | Energy bucket |
|---|---|---|
| `ehp/Comp` on and `hvac_action` = `water` | `water_heating` | hot water |
| `ehp/Comp` on (not water) | `active_heating` | heating |
| `hvac_action` = `cooling` and `ehp/Hc1Pump` on | `cooling` | cooling |
| `ehp/Hc1Pump` on, no cooling | `passive_heating` | heating |
| none of the above (standby) | `off` | off |

- Pump state comes from `ehp/Hc1Pump` ("Status Heizkreispumpe: AN/AUS"), as in the owner's
  Loxone logic, so every mode is read from the ehp.
- Cooling = `hvac_action` `cooling` (`ehp/Status` hcmode `1`): what the generator does now. Not
  `binary_sensor.heating_cooling_active`: that OR also includes the cooling NEED
  (`uih/CoolingDemand`) and REQUEST (`mc/CoolingRequestHc2`), which can be on while nothing runs.
  The interlock keeps using the OR (safer). UNPROVEN: `hcmode` has never been seen reading
  `cooling` on this unit (heating season since the package exists); confirm in the first cooling
  period, with `uih/CoolingActive` as the fallback signal.
- The geoTHERM has passive cooling only (owner): the compressor never runs for cooling, so the row
  order (compressor before cooling) is safe.
- UNKNOWN: where the hot-water run-on goes (`HwcLaggingTime` 3 min, catalog "WP Nachlaufzeit WW";
  the pump keeps running after the compressor stops). Expected: into the tank while the
  heating/hot-water valve (`HwcHcValve`) still points to hot water. The mode books it by
  `hvac_action`: `water` → hot water, else `passive_heating`. Its electricity is small
  (~83 W × 3 min ≈ 4 Wh per run). Settle after deploy: watch `hvac_action`, `HwcHcValve` and the
  tank temperature for the minutes after a hot-water run ends.

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
1. [DONE] MQTT sensors for `ehp/CompStartsHwc`, `ehp/Comp` and `ehp/Hc1Pump`; add them to the
   poll-registration automation. Depends on: nothing.
   PR post-deploy steps: for each of the three, `topic ebusd/ehp/<name> in 0` and
   `topic ebusd/ehp/<name>/get out 0`, then restart Mosquitto.
2. [DONE] Remove the backup-heater indicators (owner: the backup heater is never used here).
   Scope (b): both MQTT sensors, the alert automation, the controller-state branch, the
   slab-decision gate, the poll registrations, dashboard rows and the notes invariant.
   PR post-deploy steps: the bridge lines for `ebusd/ehp/Backup` and `ebusd/ehp/BackupIntegral`
   can be removed; the two orphaned entities can be deleted in the UI.

### Phase 2 — mode and run source
3. [DONE] `sensor.heating_energy_mode` per the table above. Tests: every row, the row order
   (compressor before cooling before pump), raw enum numbers, unavailable inputs.
4. [DONE] Change `binary_sensor.heating_compressor_heating_active` to mode `active_heating`.
   Update tests `test_compressor_table`, `test_last_run` and `test_cycling_history_stats`.

### Phase 3 — energy split
5. [DONE] Tariff `utility_meter`s for electricity and yield, the tariff automation, and the two
   efficiency sensors. The combined `heating_efficiency_today` stays (owner).
   Tests on the frozen clock: each of the five modes books to its own tariff, heating efficiency
   uses active + passive, no cooling/off efficiency, midnight reset.
6. [DONE] Daily starts meter for hot water.

### Phase 4 — dashboard
7. [DONE] Drop the name overrides on the starts/runs rows so each row and its popup say the
   same thing (entity names kept: renaming would change the ids on a fresh registry). Show the current energy mode; heating and hot water side by side (starts, energy,
   yield, efficiency); heating energy also split active / passive; cooling and off energy rows.

### Phase 5 — verification
8. [IN_PROGRESS] `ci-local.sh` green (incl. e2e: see Status). After deploy, compare for 3 days: starts vs the graph, run edges
   vs the Shelly, `heating + hot_water + cooling` electricity vs the total, and the yield split.

### Close
9. [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
   plan (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes this plan will update

- `doc/heating_pv_boost/notes.md`: entity map (new entities), the energy-mode decision, the
  baseline method's "Starts per day" and efficiency lines, the "Tests" section.
- `doc/heating_pv_boost/registers.md`: `CompStartsHwc`, `Comp`, `Hc1Pump`.
- `.claude/skills/ha-test-harness/SKILL.md`: the stubbed-action gotcha (real `select` domain).
- YAML comments in `packages/heating_pv_boost.yaml` (K-5).

## Status

- Approved by the owner; steps 1-7 implemented, tests and notes updated.
- Five modes defined by the owner (active/passive heating, water heating, cooling, off).
- Owner answers: pump from `ehp/Hc1Pump`; passive cooling only; keep the combined efficiency;
  no `CompHoursHwc`; remove the backup-heater indicators.
- Backup removal: scope (b), everything.
- Next: deploy, add the bridge lines, then the 3-day comparison (step 8). Still to settle with
  live data: `hvac_action` reading `cooling` (first cooling period), where the hot-water run-on
  goes, `YieldTotal` misbooking at mode switches, and the `ehp/Comp` reporting lag vs the Shelly.
