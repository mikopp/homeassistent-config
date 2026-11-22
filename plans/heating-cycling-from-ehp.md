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

### Registers (published catalog `08.ehp.csv`; decodes: `doc/devices/vaillant-vws-83-2/registers-ehp.md`)

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
- The geoTHERM has passive cooling only: the compressor never runs for cooling, so the row
  order (compressor before cooling) is safe (device VWS-14).
- UNKNOWN: where the hot-water run-on goes (a run-on of `HwcLaggingTime` follows the charge;
  which pump runs is open, device VWS-13). Expected: into the tank while the
  heating/hot-water valve (`HwcHcValve`) still points to hot water. The mode books it by
  `hvac_action`: `water` → hot water, else `passive_heating`. Its electricity is small
  (~83 W × 3 min ≈ 4 Wh per run). Settle after deploy: step 17.

### Booking energy to a mode

Use HA's `utility_meter` with `tariffs:` (daily cycle). An automation sets each meter's tariff
`select` whenever `sensor.heating_energy_mode` changes.

- Electricity: one meter on the Shelly energy with one tariff per mode (`active_heating`,
  `passive_heating`, `water_heating`, `cooling`, `off`). Heating electricity = active + passive.
- Yield and efficiencies: implemented; current state (one `space_heating` yield bucket for the
  active and passive heating cycle, `unknown` below the floor) in `doc/heating_pv_boost/notes.md`
  "Energy modes".

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
- `binary_sensor.heating_compressor_active` (Shelly > 500 W) was kept here as the electrical view and
  removed in step 12 (no consumer). `sensor.heating_pv_surplus` reads the clamp power itself.

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
   Post-deploy done (owner, 2026-11-21): the `Backup`/`BackupIntegral` bridge lines are removed;
   no backup entity is left in HA (step 16).

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
8. [DONE] `ci-local.sh --e2e` green. Deployed (checked live 2026-11-21, see Status). Three-day
   comparison done on 2026-11-18, 19 and 20 (ha-mcp, statistics only):
   - Starts vs the clamp: 2026-11-20 showed 7 runs above 500 W (02:25, 05:50, 09:25, 17:00,
     18:05, 20:15, 23:05); the meters say 5 heating + 2 hot water = 7. OBSERVED: they match, the
     hot-water run at 17:00 that rolls into a short heating tail (see below) is one start. Daily
     meters 2026-11-18 / 19 / 20: heating 3 / 4 / 5, hot water 2 / 2 / 2.
   - Electricity: per-mode meters add up to the Shelly daily total to the Wh on 2026-11-15 to 11-20
     (e.g. 11-20: 5.304 + 1.747 + 2.322 = 9.373 kWh; 11-18: 2.864 + 1.850 + 2.060 = 6.774 kWh);
     cooling and off read 0.
   - Yield split (space heating / hot water kWh): 11-18 12 / 6, 11-19 18 / 6, 11-20 26 / 4.
     Daily efficiency today reads 3.41 for space heating, `unknown` for hot water when no hot-water
     run happened yet (as designed).
   - `ehp/Comp` lag against the clamp (> ~500 W): OBSERVED on the 2026-11-20 18:05 run only,
     at 5 min statistics resolution (error about 1 min): clamp on ~18:09, `ehp/Comp` on ~18:11 (+2 min);
     clamp off ~18:50:50, `ehp/Comp` off ~18:51:50 (+1 min). The hot-water run ending ~17:27 shows the
     same +1 min at the stop. `heating_compressor_last_run` 40.9 min against ~42 min on the clamp.
     Not measured to the second: this needs raw state history (not available through ha-mcp).
   - Hot-water run-on: OBSERVED, 2 runs. 2026-11-20 05:50-06:16: power falls straight from ~3.1 kW to
     the ~81 W idle level, no separate run-on step. 2026-11-20 17:00 run: `hvac_action` flipped
     `water` → `heat` at 17:24:32 and the clamp stayed at ~1.8 kW (heating power, not the
     ~83 W pump) for about 2.5 min until `ehp/Comp` went off (~17:28). So the first minutes
     after a hot-water run are either nothing (idle pump level) or a short real heating segment,
     booked `active_heating`. The ~83 W pump run-on is not distinguishable from idle in the clamp.
     No `HwcHcValve` or tank data checked. HYPOTHESIS: `HwcLaggingTime` run-on has no power of
     its own at the clamp, so where it is booked does not matter (about 4 Wh per run).
   - Cooling: `hvac_action` has not read `cooling` in the data checked (outdoor 5.7 °C now);
     statistics cannot show enum history. Still UNPROVEN, see step 14.

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
    Checked 2026-11-21: no state for it in HA (see Status).
    Proposal (owner decided: remove, step 12): `binary_sensor.heating_compressor_active` had no
    consumer.
    OBSERVED: the Shelly clamp leads `ehp/Comp` by about 1-2 min (2026-11-14: 07:45:03 vs
    07:46:09; 2026-11-20 18:05 run: +2 min at the start, +1 min at the stop; two hot-water/heating
    edges at 5 min resolution). Open question settled enough: run lengths from `ehp/Comp` are
    ~1 min shorter than the clamp's.

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

12. [DONE] Remove `binary_sensor.heating_compressor_active` ("Compressor drawing > 500 W", Shelly
    clamp; owner decision 2026-11-14): no decision read it, `ehp/Comp` is the compressor. Removed
    from the package, the recorder list, the three dashboard places and the compressor table; the
    clamp-vs-`ehp/Comp` step in `test_last_run` stays (it checks the last run ignores clamp spikes).
    The clamp power sensor `sensor.technikraum_heizung_heizung_power` and the PV surplus are
    unchanged. If Phase 2 needs an electrical threshold it re-adds one. The HYPOTHESIS below (clamp
    leads `ehp/Comp` by about a minute) can still be measured on the power sensor directly.
    Post-deploy: delete the orphan entity `binary_sensor.heating_compressor_active` in the UI.

### Phase 7 — after deploy
14. [TODO] First cooling period: confirm `hvac_action` reads `cooling` (`ehp/Status` hcmode `1`);
    if not, switch the cooling row to `uih/CoolingActive` (owner; not before cooling season).
    Also log the outdoor temperature, `mc/OtShutdownLimit` and `CoolingStartOffsetHc2` at the first
    cooling start and stop (settles the release, device VWS-16 [ASSUMED]), whether a
    `TempDesired` change moves it, and that cooling keeps running with heating mode `off`
    (device VWS-15, design HPB-1 Known gaps).
15. [TODO] Owner: delete the two restored entities `sensor.heating_yield_by_mode_active_heating`
    and `_passive_heating` (unavailable) from the UI and statistics, but NOT before 30 days after
    #164 reached the system (the 30-day yield sum reads them; `space_heating_yield_30d` still
    reports `days` 8.9 on 2026-11-21, so earliest about 2026-12-12; check that attribute first).
16. [DONE] Bridge lines for `ebusd/ehp/Backup` and `ebusd/ehp/BackupIntegral` removed (owner,
    2026-11-21). Orphan check (ha-mcp, 2026-11-21): no backup entity, and the removed
    `binary_sensor.heating_compressor_heating_active`, `heating_dhw_active`,
    `heating_compressor_active` and `sensor.heating_compressor_runs_today` have no state. The only
    leftovers are the two step-15 yield meters, kept on purpose. ha-mcp cannot read the entity
    registry: a "not provided" row in Settings > Entities would still be possible (owner glance).

17. [TODO] Where the hot-water run-on goes (device VWS-13, design HPB-2 Known gaps): for three
    hot-water ends, watch `ehp/Hc1Pump`, `hvac_action`, `HwcHcValve` (forced read) and the tank
    temperature for the `HwcLaggingTime` minutes after the compressor stops. Which pump runs, and
    whether the valve still points to hot water. Result → device `runs.md` (T row); if the pump
    is not `Hc1Pump`, revisit the HPB-2 run-on row. Depends on: nothing (heating season).

### Close
13. [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
   plan (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes this plan will update

- `doc/heating_pv_boost/notes.md`: entity map (new entities), the energy-mode decision, the
  baseline method's "Starts per day" and efficiency lines, the "Tests" section.
- `doc/devices/vaillant-vws-83-2/registers-ehp.md`: `CompStartsHwc`, `Comp`, `Hc1Pump` (done in the
  device-doc move).
- `.claude/skills/ha-test-harness/SKILL.md`: the stubbed-action gotcha (real `select` domain).
- YAML comments in `packages/heating_pv_boost.yaml` (K-5).

## Status

Checked live with ha-mcp (read-only) on 2026-11-21. Merged: #161 (this plan), #163, #164, #168 and
later; all deployed.

Done:
- Steps 1-7 and 9-12 implemented and deployed. OBSERVED live: `sensor.heating_energy_mode`
  (`passive_heating` now), `binary_sensor.geotherm_heating_compressor_running`,
  `binary_sensor.geotherm_heating_circuit_pump` (on), `sensor.hot_water_compressor_starts_daily`,
  the five per-mode electricity meters and the yield meters, `select.heating_electricity_by_mode`,
  `select.heating_yield_by_mode`, space-heating / hot-water / combined efficiency today and 30d all
  report values. So the bridge lines for `Comp`, `Hc1Pump` and `CompStartsHwc` are in.
- Orphans `binary_sensor.heating_compressor_heating_active`, `heating_dhw_active`,
  `heating_compressor_active` and `sensor.heating_compressor_runs_today` have no state in HA
  (checked with a template and search); no backup-heater binary sensors exist either.
  HA cannot show whether a registry row is left: owner glance in the UI.
- Step 8 comparison done (numbers in step 8): meters match the clamp runs, per-mode electricity
  sums to the Shelly total, `ehp/Comp` lags the clamp by about 1-2 min, no hot-water run-on of its
  own seen, no phantom runs under 1 min since 2026-11-15 (daily minimum of last run 11.1 min).

Left, in order:
1. Step 17 (hot-water run-on destination): any time in the heating season.
2. Step 14 (cooling check): waits for cooling season.
3. Step 15 (owner): delete the two pre-merge yield meters, earliest about 2026-12-12.
4. Step 13 Close (Claude): after 14, 15 and 17 or after the owner agrees to close without the cooling
   check (then note it as UNPROVEN in notes).

Observation, not a bug: `sensor.heating_efficiency_30d` (2.48) is lower than space heating (3.29)
and equal to hot water (2.47) because its window is the full 30 d (674 kWh yield) while the per-mode
30 d sensors hold only 8.9 days of data (202 + 48 kWh) until the window fills.
