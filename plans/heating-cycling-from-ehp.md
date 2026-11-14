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
- `binary_sensor.heating_compressor_heating_active` (removed in step 10) became "energy mode = `active_heating`"
  (instead of Shelly > 500 W), now a display indicator only. As a run source it split a run that
  rolls heating → hot water → heating without the compressor stopping into two segments (seen
  2026-11-14: one run 05:30–06:52, hot water 05:50–06:30).
- Runtime today, duty cycle and last run: `binary_sensor.geotherm_heating_compressor_running`
  (`ehp/Comp`, any mode), so such a run is one continuous run (owner: these are about the
  compressor, not the mode). Average run today = runtime ÷ (heating + hot water starts today);
  the two machine counters add up to the Comp starts (owner).
- `sensor.heating_compressor_runs_today` is dropped: it counted the segments above (5 against 4
  starts on 2026-11-14) and nothing needs a segment count.
- `binary_sensor.heating_compressor_active` (Shelly) stays as the electrical view (no decision reads it yet, see step 10).
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
   (Superseded by step 9: the run statistics no longer read it.)

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

9. [DONE] Drop `sensor.heating_compressor_runs_today` (sensor, dashboard row, recorder entry,
   tests). Runtime today, the 24 h duty cycle and the last run read `ehp/Comp` (any mode); the
   average run divides runtime by the sum of the two daily start meters. Tests:
   `test_compressor_table` (average case over both meters), `test_last_run` (hot-water run counts,
   heating → hot water → heating is one 19 min run), `test_cycling_history_stats` (one 30 min
   run, 3 starts, 65 min, duty 65 min / 24 h).

### Phase 5 — verification
8. [IN_PROGRESS] `ci-local.sh --e2e` green (done). After deploy, compare for 3 days: starts vs the graph, run edges
   vs the Shelly, `heating + hot_water + cooling` electricity vs the total, and the yield split.

### Phase 6 — dashboard duplicates
10. [DONE] "Heating Status" card audit. Removed `binary_sensor.heating_compressor_heating_active`
    (a pure function of `sensor.heating_energy_mode`, only dashboard, recorder group and tests read
    it; the "Why runs end" graph now plots the energy mode). Every row relabelled with its source.
    Kept, not duplicates: Shelly clamp `heating_compressor_active` (other source; no decision
    reads it today, see proposal below), `heating_dhw_active` (25 min tail, `hwc/Status` input; dropped later, step 11),
    `heating_season_active` (2 of 4 indicator states), `heating_cooling_active` (interlock OR).
    Tests: heating-only cases now assert `sensor.heating_energy_mode` (`COMPRESSOR_CASES`).
    Post-deploy: delete the orphan entity `binary_sensor.heating_compressor_heating_active` in the
    UI (Settings > Entities). tests/ha not run on the dev Mac: CI must confirm.
    Proposal (NOT applied, owner decides): `binary_sensor.heating_compressor_active` has no
    consumer; either keep for Phase 2 or remove it and the clamp comparison.
    HYPOTHESIS: the Shelly clamp leads `ehp/Comp` by about a minute (one observation, 2026-11-14:
    07:45:03 vs 07:46:09); measure over several runs (open question above).

11. [DONE] Drop `binary_sensor.heating_dhw_active` ("Hot water active (masks return temp)"; owner:
    the energy mode says what runs). Consumers repointed to `sensor.heating_energy_mode`:
    `sensor.heating_circuit_return_temp_valid` is unavailable while the mode is `water_heating` or
    unavailable (no tail, no `hwc/Status` input), `sensor.heating_control_state` reads `hot_water`
    from the mode; dashboard rows and the activity graph entry removed. Tests:
    `test_return_temp_mask_follows_energy_mode` replaces `test_dhw_mask`.
    Evidence (7 hot-water runs, checked 2026-11-14; observed in 7 of 7, kept here as an observation
    until the owner promotes it): the raw `ehp/HcReturnTemp` rose from ~25 °C to 51-56 °C only while
    hot water ran and was back at the pre-run level (24.7-26 °C) within the 5 min bucket where it
    ended. Runs: 2026-11-13 17:00-17:25 and 2026-11-14 05:50-06:30 (both followed at once by a heating
    run; per-mode meter as the hot-water marker), and 2026-11-04, 07, 08, 09, 11 at ~17:00-17:30
    (each ends with the compressor stopping to ~80 W idle; Shelly power > ~2.9 kW as the marker,
    since the per-mode meters only exist from 2026-11-12). Residual values in the stop bucket
    were at most 28.25 °C (below `heating_return_temp_max` 30 °C). No thermal tail seen, so the
    old 25 min hold is dropped. Limits: 5 min statistics cannot show a lag of seconds at run start
    between `ehp/Comp` on and `hvac_action` `water` (the return was already 39-43 °C max in the first
    bucket); a brief unmasked reading is harmless to the slab decision because `delay_off` 20 min
    holds a charge through it. The old runs' energy mode is not historized, so a hot-water run-on
    (pump on, compressor off) is not visible separately; the return was at baseline during those
    minutes. Flow temp is polluted the same way but is not masked (it is only a liveness
    signal and the stop-temp line). If a run is ever seen with a lingering high return after the
    flip, add a short `delay_off` mask back on the energy mode.
    `binary_sensor.geotherm_heating_hwc_active` (raw `hwc/Status`) stays, display only; its bridge
    line and poll stay too (owner decides whether to drop it).
    Post-deploy: delete the orphan `binary_sensor.heating_dhw_active` in the UI.

### Close
12. [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
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
- Step 9 done 2026-11-14 (runs_today dropped; runtime, duty cycle, last run on `ehp/Comp`, average on machine starts);
  `tests/ha` not run on the dev Mac (no Python 3.14/mosquitto): CI must confirm.
- Step 10 done (dashboard duplicate removed, labels). Orphan to delete after deploy.
- Step 11 done 2026-11-14 (hot-water mask on the energy mode, `heating_dhw_active` dropped);
  second orphan to delete after deploy.
- Next: deploy, add the bridge lines, then the 3-day comparison (step 8). Still to settle with
  live data: `hvac_action` reading `cooling` (first cooling period), where the hot-water run-on
  goes, `YieldTotal` misbooking at mode switches, and the `ehp/Comp` reporting lag vs the Shelly.
