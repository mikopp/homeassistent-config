# Heating — compressor short-cycling: observe, then tune


## Context

In mild weather the geoTHERM starts about once an hour and runs about 5 minutes. That is close to
`ehp/TimeCompOnMin` (240 s), so most runs are near the minimum length. This is the worst pattern for
COP and for wear. For example, 24 starts a day is roughly 9 000 starts a season, and each start runs
a few minutes in a poor transient (high pressure difference, oil not yet circulated).

The owner raised `ehp/CompIntegral` from −150 to −180 °min. The heating curve is **0.15**, which is
already very flat. So in mild weather the flow setpoint sits only a few K above room temperature.

**Why −180 alone will not fix it (reasoned, not yet measured).** `CompIntegral` sets only *when* a
run **starts** (the deficit in °min). It does not set how long a run lasts. A run ends when either
(a) the energy integral is paid back, or (b) flow > flow-setpoint + `CompHysteresis` (the forced
stop; it applies on hydraulic plans 1/3, i.e. no buffer, which is this house). The compressor's
fixed ~7 kW thermal output goes into a low setpoint and a small volume of moving water. So the
flow temperature overshoots within minutes, and (b) cuts the run. Going −150 → −180 makes the pause
about 20 % longer, but each run stays about 5 min.

Causes outside the Vaillant, ruled out by the owner (2026-10-30):
- **Loxone mode toggling:** ruled out. Loxone no longer writes `mc/OperatingMode`. The geoTHERM
  runs `auto` on its own day/night time program.
- **Room valves closing:** ruled out. Loxone does not control the room valves.
- **Throttling / closed loops:** ruled out (owner, 2026-11-06). The bedroom loops are **open**
  (no throttling) and **all valves are open**. Do not suggest opening throttling, loops or manifold
  valves again: the low water flow (≈ 8 K spread) is not caused by anything closed on the house side.

So the cause is the Vaillant's own start/stop behaviour (integral + hysteresis) at a low setpoint.

## Step 0b — record the owner's manual changes in the slab plan (docs only)

None of these are in `plans/ebusd-pv-heating-optimization.md` or `doc/heating_pv_boost/notes.md`
yet. Add them there:

- Status step 9: Loxone no longer writes `mc/OperatingMode` (owner, 2026-10-30). Also record whether
  it still publishes `warm_enough`.
- New: geoTHERM `mc/OperatingMode` = `auto`, with the Vaillant's own time program (`on` by day,
  `low` at night). Add an Observations entry.
- New: `ehp/CompIntegral` −150 → −180 °min (owner). Heating curve = 0.15.
- **Phase 2 mode decision (owner, 2026-10-30, recorded in the slab plan's "Control law"):** `auto`
  is normal operation. HA writes `on` only when Loxone says "not warm enough" or a boost is
  wanted, then returns to `auto`. HA never writes `low` any more. By day `auto` and `on` give the
  same setpoint, so there are no on/low setpoint flips. At night Loxone's schedule matches the
  Vaillant's, so they normally agree. A boost only happens by day, and only in `active_heating`.
  In cooling season (`passive_cooling`/`active_cooling`) the heating mode is set to `off`, and
  back to `auto` in `neutral`/`active_heating`.
- Loxone still publishes `warm_enough` (owner-confirmed), so it stays the comfort input.
- **Bridge pattern (owner-supplied live config, 2026-10-30): an explicit per-topic allowlist.**
  - Each state topic HA reads gets its own `topic ebusd/<circuit>/<name> in 0` line.
  - Each poll registration gets its own `topic ebusd/<circuit>/<name>/get out 0` line.
  - `ebusd/global/running` and `ebusd/global/scan` are `in` only.
  - There are no wildcards. Only the topics HA needs are bridged.

  Where to record it:
  - `doc/heating_pv_boost/notes.md`: a new "Transport: the bridge is an allowlist" section.
    Write down the pattern and the rule, not the topic list. The rule: every new register this
    package reads needs **two** bridge lines (`in` for the state, `out` for `/get`), added on the
    HA broker host after deploy. Without the `in` line the sensor stays `unavailable`. Without the
    `out` line the `?N` poll registration never reaches ebusd.
  - Slab plan "Transport": replace the `topic ebusd/# in 0` snippet with the allowlist pattern,
    and note that the old snippet was never what got deployed.
- Loxone does **not** control room valves (owner-confirmed). Record this in the slab plan's
  "Division of responsibility" table and in the notes. No automatic valve actuation.
  (Superseded 2026-11-06: there is no bedroom throttling; all loops and valves are open.)
- The time program gives two intended mode switches a day, at the day and night switch-over. These
  are expected, not cycling.

## Tuning table: what to change on the Vaillant (manual, in this order)

Change one value at a time, then give each change at least 3 nights of similar outdoor temperature.
Judge by the night runs at setpoint ≤ 26 °C (see Observations 2026-11-06).

| # | Setting | Now | Suggest | How | Why |
|---|---|---|---|---|---|
| 1 | Heating-circuit pump speed | fixed: **not settable over ebus** (SW 0383 < 407, step 9a) | ≈ 4–5 K spread during a run | Only physically: look at the internal heating-circuit pump's head for a speed selector (unverified whether this model has one; installer question). Have the installer check the dirt filter / strainer at the same visit | Would be the main lever (lower flow temp *and* longer runs), but there is no software path on this unit |
| 0 | Night room setpoint `mc/TempDesiredLow` (night setback) | 21 °C (day 22 °C) | 22 °C (no setback) | Vaillant operator menu, night/reduced room temperature | **First test, nights only.** The 1 K setback lowers the flow setpoint 27 → 26 °C, which is exactly the difference between ≈ 30 min day runs and ≈ 10–15 min night runs. With the slab the saving is likely negligible (hypothesis, see Observations) |
| 2 | `CompHysteresis` (C8) | 7 K | 8 K | Vaillant menu C8 | **Best available software lever** now that #1 is fixed. Do it after #0; it also covers mild middays at setpoint 26 °C. The flow during a run stays return + spread; only the last part of each run gets up to ≈ 1 K hotter. Each 1 K of headroom ≈ 20–25 min more run (Observations) |
| 3 | `CompIntegral` | −180 | −240…−300 | Vaillant menu C8 "Kompr. Start in" | Only **after** #2, once runs end on the integral (integral back near 0 at stop). While the hysteresis cuts runs off it does not reduce starts |
| — | `BackupModeHc` | `no_backup` | keep | — | Backup heater starts at BackupIntegral + CompIntegral; must stay disabled when #2 deepens the integral |
| — | Heating curve | 0.15 | leave it | — | Lowering it shortens runs further |
| — | `NumberCompStarts` | not read | leave it | — | Upper limit only; not the cause |
| — | Loxone, room valves, bedroom loops, manifold | no writes; all open (owner) | — | — | Ruled out |

The planned PV slab boost (Phase 3) is the structural fix: one long midday run instead of hourly
short runs.

## What to observe (and what this change adds to HA)

| Signal | Source | What a good value looks like |
|---|---|---|
| Starts per day (heating) | `ehp/CompStartsHc` counter, plus HA count | < 8–10 |
| Average / last run length | HA, from `binary_sensor.heating_compressor_active` | ≥ 20–30 min |
| Duty cycle (24 h) | HA history_stats ratio | Rises as starts fall |
| Energy integral | `ehp/Integral` (°min) | Shows the start point and how runs end |
| Compressor demand | `ehp/CompDemand` | Who asked for the start |
| Flow setpoint vs actual | `mc/Status0a` field 4 vs `ehp/Status` field 0 | Overshoot at the stop ≈ hysteresis → hysteresis is the cut-off |
| Spread (flow − return) | existing sensors | Very large spread = little water moving (pump speed; valves are all open) |
| Mode flips | `sensor.geotherm_heating_hvac_mode` changes | Should be near 0 once Loxone stops writing |
| Daily efficiency | `ehp/YieldTotal` Δ / Shelly `Heizung Energy` Δ | Rises as runs get longer (coarse, kWh resolution) |

## Implementation (read-only; HA writes nothing)

### 1. `packages/heating_pv_boost.yaml` — MQTT sensors (same patterns as the existing ones)

- Model these on `Heating Temp Desired Low`: `default_entity_id`, `device: *ebusd_geotherm`,
  `value | trim | float(none)` guard, inline field docs.
- Live: `ehp/Integral` (°min, measurement) and `ehp/CompDemand` (binary sensor; accepts both
  `yes`/`1` per the enum rule in the notes).
- `mc/Status0a`: parse field 4 `flowtempdesired` positionally.
- Settings (read only): `ehp/CompIntegral`, `ehp/CompHysteresis`, `ehp/BackupIntegral`.
  Dropped: `mc/HeatingCurve` (owner knows it is 0.15, and it is conditional in the catalog) and
  `NumberCompStarts` (not the cause). Each bridged register costs two bridge lines, so keep the
  list minimal.
- Counters (`total_increasing`): `ehp/CompStartsHc`, `ehp/CompHoursHc`, `ehp/YieldTotal` (kWh).
- That is **9 new registers**. Register names and decodes were checked against the live catalog
  (`08.ehp.csv`, `50.ehp.mc.csv` on ebus.github.io). Not yet checked: whether this unit answers each
  one, and the payload shapes. Mark each as unverified until it is seen live.

### 2. `heating_ebusd_poll_registration` — new poll tiers

- Integral, CompDemand and Status0a at `?5`.
- Settings and counters at `?9`.
- Update the "nine/ten registers" comments.

### 3. Derived sensors

- `history_stats`:
  - starts today (`count`, on)
  - compressor on-time today (`time`)
  - duty cycle over the last 24 h (`ratio`)
- Template sensor: average run today = on-time ÷ starts. Add an `availability:` guard.
- Trigger template `sensor.heating_compressor_last_run`: on `to: off` from `on`, compute the
  run length from `trigger.from_state.last_changed`.
- `utility_meter` (daily) on `CompStartsHc` and `YieldTotal`, plus a daily
  efficiency template (yield Δ ÷ `Heizung Energy` Δ). Check the Shelly energy entity id via
  `default_entity_id` or ha-mcp first.

### 4. Dashboard

Add a "Compressor cycling" card to `dashboards/heating-dashboard.yaml`:
- the new numbers
- a history graph of Integral, flow, flow setpoint and compressor-active

### 5. Tests and docs

- `tests/conftest.py`: seed every new MQTT entity in `baseline_states`.
- `tests/test_heating_pv_boost.py`: cases for average run length, last-run minutes and efficiency
  (including the zero-starts case).
- `doc/heating_pv_boost/notes.md`: the tuning registers and the reasoning above about start vs
  stop criteria (marked as hypothesis).
- README package section.
- Update the Status section of the repo plan file.

### 6. Commit, push, open the PR (owner asked for it)

Commit all steps to `claude/heating-slab-pump-tuning-y2g8se`, then open a PR against `master`. The PR
body has a **"After deployment (manual, on the HA host / Vaillant)"** checklist:
1. **Mosquitto bridge:** add 18 lines on the HA broker host, then restart Mosquitto (a reload does
   not load bridge changes). For each of the 9 registers (`ehp/Integral`, `ehp/CompDemand`,
   `mc/Status0a`, `ehp/CompIntegral`, `ehp/CompHysteresis`, `ehp/BackupIntegral`,
   `ehp/CompStartsHc`, `ehp/CompHoursHc`, `ehp/YieldTotal`):
   - `topic ebusd/<c>/<n> in 0`
   - `topic ebusd/<c>/<n>/get out 0`

   List them literally in the PR, ready to paste.
2. Restart HA, or wait for an ebusd rescan, so `heating_ebusd_poll_registration` registers the new
   polls.
3. Confirm that each new sensor leaves `unavailable`. If one never publishes, the unit may not
   answer that register; note it.
4. Check `BackupModeHc` on the Vaillant (no backup heater) before deepening `CompIntegral`.
5. Record a 3-day baseline, then change `CompHysteresis` by +1 K. Change one setting at a time.

## Observations

### 2026-11-06 — baseline week and why runs end (from HA history, read via ha-mcp)

Data (heating starts = Δ `CompStartsHc`, hours = Δ `CompHoursHc`, integer resolution):

| Day | Outdoor mean | Starts | Hours |
|---|---|---|---|
| 10-31 | 7.4 °C | 9 | 2 |
| 11-01 | 6.3 | 9 | 3 |
| 11-02 | 5.5 | 10 | 2 |
| 11-03 | 5.1 | 11 | 3 |
| 11-04 | 5.2 | 10 | 4 |
| 11-05 | 4.4 | 10 | 3 |
| 11-06 | 2.2 | 10 | ≈ 3.6 |

The days are not comparable: it got ≈ 5 K colder. Flow setpoint mean rose 24.3 → 25.7 °C with the
curve (the 27 → 29 °C step at 20:35 on 11-06 = outdoor drop to ≈ 0.5 °C plus the evening mode switch).

**Run anatomy (measured 11-06):**
- Night run 01:05–01:15, setpoint 26 → forced stop at 33 °C. Return stayed at 24.94 °C, flow jumped
  to 33.1–33.3 °C within ≈ 5 min, i.e. **flow = return + ≈ 8.3 K spread**, already at the stop
  temperature. Integral went only −180 → ≈ −125, then stop. Runs at setpoint 26 (night *and* 10:45,
  12:05) are all ≈ 10–15 min.
- Day run 07:25–07:55, setpoint 27 → stop at 34 °C. Same ≈ 8 K spread; the extra 1 K of headroom let
  the return creep 25.2 → 26.25 °C (≈ 0.04 K/min) for ≈ 30 min; the integral was fully repaid (+8).

**Model (hypothesis, fits both runs):**
- During a run, flow ≈ return + spread. The return is held by the slab and rises only ≈ 0.04 K/min.
- Headroom H = (setpoint + hysteresis) − (return + spread). Run length ≈ H / return rise rate,
  capped by the integral being repaid. At setpoint 26: H ≈ −0.2 K → minimum-length runs. At 27:
  H ≈ +0.8 K → ≈ 25–30 min.
- When the hysteresis cuts a run off, only ≈ 55 °min of deficit is repaid. The integral then drains
  at ≈ 0.8 °min/min, so the next start comes ≈ 70 min later **whatever the start threshold is**. So
  a deeper `CompIntegral` does not reduce starts while runs are hysteresis-limited. It only helps
  once runs end on the integral.

**Consequence: the real lever is the spread, not hysteresis or the integral.**
- 8 K is large for slab heating at a fixed ≈ 7–8 kW thermal output (≈ 1.8 kW electrical measured,
  COP unverified). It means low water flow, ≈ 750–850 l/h. All house-side loops and valves are open
  (owner), so the flow is set by the heating-circuit pump.
- Halving the spread to ≈ 4 K: flow during a run ≈ 29 °C instead of 33 °C (better COP), and H ≈ +3 K
  at setpoint 26. The run then ends on the integral, not the cutoff. Because the integral counts
  flow above setpoint, a cooler flow repays it more slowly, so runs get longer still (rough estimate
  ≈ 45 min, ≈ 5–6 starts/day; unverified).
- Only then does deepening `CompIntegral` add fewer, longer runs.
- How to raise the flow rate: the heating-circuit pump speed (tuning table #1). The ebusd catalog
  `50.ehp.mc.csv` (not `08.ehp.csv`) has, for unit software ≥ 407:
  - `HcPumpStatus`: 0 = high-efficiency (speed-controlled) pump OK, 1 = its error, ≥ 2 = no HEP
    (a fixed-speed pump, so no ebus speed control)
  - `HcPumpPWM`: actual pump speed in % (7 % = off)
  - `Hc1PumpSpeedControlDirectCircuit`: pump speed setpoint while the compressor runs, %, writable
    (installer level)
  - `Hc1PumpSpeedControlDirectCircuitWhileO` (SW ≥ 414): the same while the compressor is off
  - `Hc1PumpSpeedControlHeatBuffer`: only with a buffer, not relevant here

  **Result (owner, 2026-11-06): none of them exist on this unit.** `ebusctl info`: address 08/23/25/50
  = `EHP00`, `SW=0383`, `HW=7201`, below the SW ≥ 407 the registers need. So the heating-circuit pump
  speed cannot be read or set over ebus. Only a physical speed selector on the pump (unverified) or
  a clogged dirt filter / strainer (installer check) are left on the flow side.
- With the flow fixed, the remaining software lever is the stop point: `CompHysteresis` +1 K.
  A curve parallel shift raises the stop point the same way but also raises the whole setpoint
  (more heat, warmer rooms), so the hysteresis is the cleaner of the two.
- Fallbacks that raise only the end-of-run flow temperature by ≈ the return rise: `CompHysteresis`
  +1 K, or a ≈ 1 K parallel shift of the curve / smaller night setback. Structural: PV slab boost
  (Phase 3).

**Night setback (hypothesis, 2026-11-06):**
- The day/night difference is the room setpoint: 22 °C by day, 21 °C at night (`TempDesiredLow`).
  At this curve that moves the flow setpoint ≈ 1 K (27 → 26 °C) and the forced stop 34 → 33 °C.
  The flow during a run is return + ≈ 8 K ≈ 33 °C either way, so at night the stop comes almost at
  once.
- Saving: the slab stores days of heat. A 1 K setback over a night barely changes room temperature
  or losses, and the slab must be topped up again in the morning. Cost: ≈ 4–5 extra starts a night
  plus wear. Neither side is measured.
- Test: `TempDesiredLow` 21 → 22 °C for 3 nights, hysteresis unchanged at 7 K. Expect night runs
  like today's day runs (≈ 25–30 min, integral ≈ 0 at the stop). Compare night starts, run length,
  integral at the stop and daily yield / electricity. Flow during the run is unchanged; only the end
  of each run is ≈ 1 K warmer, as by day.
- Does not help mild middays (10:45 and 12:05 on 11-06 also ran at setpoint 26 °C); that is what
  `CompHysteresis` 8 K is for, as the next separate step.

**Buffer tank (assessed 2026-11-06, not recommended now):**
- A parallel buffer (own charging logic, own pump) adds stored heat ≈ volume × ≈ 5 K usable ×
  1.16 Wh/(l·K). At ≈ 8 kW output and ≈ 2 kW load (≈ 6 kW net): 100 l ≈ 0.6 kWh ≈ +6 min per run,
  300 l ≈ 1.7 kWh ≈ +17 min, 1000 l ≈ 5.8 kWh ≈ +60 min. Rough estimates.
- Costs: it must be charged a few K above what the slab needs (≈ 5–8 % lower COP, estimate), plus
  standby and mixing losses; second pump, hydraulic change, Vaillant reconfigured to a buffer
  hydraulic plan (with a buffer the controller switches on buffer temperature, not this
  integral/hysteresis logic; unverified for SW 0383), space, roughly €1,500–3,000+ (unverified).
- A series buffer without its own pump does not help: it does not change the ≈ 8 K spread.
- The slab already is a large store. The problem is the low water flow putting the flow at the stop
  point immediately, not missing storage. Consider a buffer only if the free levers fail. A future
  replacement heat pump with a variable-speed (inverter) compressor solves it at the source.

**Hot water (DHW) runs the same compressor:**
- 11-06 had two DHW charges: 05:50–06:15 (it followed straight on from the 05:35 heating run, so
  one compressor run, two modes) and 17:00–17:20 (its own start). Flow 50–62 °C, `mc` setpoint 0.
- During a DHW charge the heating integral is frozen (−104 and −130). Afterwards the heating flow
  restarts from a slab warmed by the DHW tail (integral jumped −104 → −72 after 06:15).
- Wear counts **all** starts: ≈ 10 heating + 1–2 DHW a day. `CompStartsHc` (and so
  `sensor.heating_compressor_starts_daily`) counts heating only; the catalog also has
  `ehp/CompStartsHwc`, `ehp/CompHoursHwc` (and the total `ehp/CompStarts`, `ehp/CompHours`).
- `YieldTotal` and the Shelly energy include DHW, which runs at 50–60 °C at a much lower COP. So
  "efficiency today" mixes in DHW; a day with an extra DHW charge looks worse with no change to
  heating.
- Idea (not analysed): a DHW charge that follows straight on from a heating run (like 05:35) saves
  one start. Aligning the DHW time window with a likely heating run could cut 1 start a day.

**Measurement gaps:**
- `binary_sensor.heating_compressor_active` counts heating and DHW runs together. At the baseline
  `runs_today` was 12 vs 10–11 heating starts, and "average run today" and "last run" mixed in DHW
  runs. Step 8 split them; since 2026-11-14 `runs_today` is gone, runtime today, duty cycle and last
  run follow `ehp/Comp` and the average run is that runtime over the machine's heating + hot-water starts
  (`plans/heating-cycling-from-ehp.md` step 9).
- Outdoor temperature (`sensor.wheatherstation_outdoor_temperature`) is not on the "Why runs end"
  graph. The return temperature should be on it too, to read the spread.

## Verification

- yamllint, `.github/scripts/fix_yaml_style.py .`, `resolve_ha_yaml.py`, `extract_templates.py`.
- `check_config` against the pinned image (Dockerfile `FROM`).
- CI pytest.
- After deploy (user): confirm each topic publishes, then record a 3-day baseline (starts per day,
  average run, Integral at start and at stop, overshoot at stop, mode flips). Only then change
  `CompHysteresis`. Log the findings under Observations.


## Status

- [x] 0. Plan file (this file)
- [x] 0b. Owner's manual changes, the bridge allowlist pattern and the Phase 2 mode decision
      recorded in `plans/ebusd-pv-heating-optimization.md` and `doc/heating_pv_boost/notes.md`
- [x] 1. 9 read-only MQTT sensors (integral, demand, flow setpoint, 3 settings, 3 counters)
- [x] 2. Poll registration: tier 4 (`?5`) and tier 5 (`?9`)
- [x] 3. Derived: history_stats (runtime today, 24 h duty cycle; runs today dropped 2026-11-14), average run today,
      last run (trigger template), daily utility meters (starts, yield, electricity), efficiency today
- [x] 4. Dashboard: "Compressor Cycling" entities card + "Why runs end" history graph
- [x] 5. Tests (`test_last_run_…`, `test_average_run_…`, `test_efficiency_…`), conftest seeds,
      notes, README
- [x] 6. After deploy (owner): add the 18 bridge lines, restart Mosquitto, confirm each sensor
      publishes, verify `sensor.technikraum_heizung_heizung_energy` is the real Shelly energy id
      (2026-11-06: all 9 registers live; `sensor.heating_efficiency_today` = 3.35, so the energy id works)
- [x] 7-pre. Baseline week analysed (2026-11-06, see Observations). Result: runs are cut off because
      the ≈ 8 K flow−return spread puts the flow at the stop temperature right away. Bedroom loops
      and all valves are open (owner), so the lever is the pump speed (tuning table #1), **before**
      changing `CompHysteresis`.
- [x] 8. (approved; implemented 2026-11-06, not yet deployed/CI-verified: no Python/Docker on the dev Mac,
      so yamllint/check_config/pytest were not run locally) New
      `binary_sensor.heating_compressor_heating_active` repoints the 3 history_stats and the last-run (since 2026-11-14 they read `ehp/Comp` again, any mode; step 9 of `heating-cycling-from-ehp.md`)
      trigger; dashboard graph gets heating-only line + outdoor temp (return temp was already there);
      4 new tests; notes/README updated. **Exclude DHW runs** from the cycling sensors (reversed 2026-11-14: they are about the compressor, any mode); do not count them
      separately (owner, 2026-11-06). One new template binary sensor "Heating Compressor Heating
      Active" = `binary_sensor.heating_compressor_active` on **and**
      `sensor.geotherm_heating_hvac_action` ≠ `water` (not `binary_sensor.heating_dhw_active` — since dropped, `plans/heating-cycling-from-ehp.md` step 11 — whose
      25 min `delay_off` would drop the next heating run). Repoint the three history_stats and the
      last-run trigger to it; average run follows automatically. No new registers, no bridge lines.
      `sensor.heating_compressor_starts_daily` (`CompStartsHc`) is already heating-only. Efficiency
      stays incl. DHW (no DHW-free yield register); say so in its comment. Also add return temp
      and outdoor temp to the "Why runs end" graph. Update the tests.
- [x] 9a. (owner, 2026-11-06) `ebusctl info`: `EHP00 SW=0383 HW=7201`. The pump-speed registers
      (SW ≥ 407) do not exist. Tuning table #1 has no software path.
- [ ] 10. **Next (owner, manual):** night setback test, tuning table #0. Set `TempDesiredLow` 21 → 22 °C,
      leave `CompHysteresis` at 7 K, run 3 nights, log night starts / run length / integral at the
      stop / daily yield and electricity under Observations. Then tuning table #2 (`CompHysteresis`
      8 K) as a separate step for mild middays. A buffer tank is assessed and parked (Observations).
      Step 8 also needs: commit + PR so CI runs the checks (git does not work on this Mac either:
      xcode-select), and after deploy, check that "last run" never shows < 1 min phantom runs at
      DHW charge ends (if it does: short `delay_on` on the heating-active sensor).
- [x] 6a. `BackupModeHc` checked (owner, 2026-10-30): `no_backup`; `BackupIntegral` −600. Safe to
      deepen `CompIntegral`.
- [x] 6b. All 9 registers answer `ebusctl read` (owner, 2026-10-30). Snapshot: hysteresis 7.00 K,
      start integral −180, integral 5, demand no, heating starts 13385, heating hours 13277
      (lifetime average run ≈ 60 min), yield 127550 kWh, flow 23.94 °C vs setpoint 24 °C. Forced stop
      at 24 + 7 = 31 °C; `FlowTempMax` 35 °C leaves about 4 K of hysteresis headroom at this setpoint.
- [ ] 7. 3-day baseline (done, see 7-pre), then `CompHysteresis` +1 K — now **after** step 10's
      setback test; one change at a time, log under Observations.
      First full baseline day is 2026-10-31. Recorder retention is raised to 14 d and the counting
      rules are in `plans/heating-baseline-and-phase2-prerequisites.md` (steps 1 and 4).
      Keep it moderate (8–9 K): the setting does not adapt to the weather. On the first cold days,
      check run-end flow temperatures on the "Why runs end" graph and step back 1 K if they approach
      35 °C (`FlowTempMax`). See `doc/heating_pv_boost/notes.md` "Cold weather".
- [x] 7a. `sensor.heating_compressor_stop_temp` (flow setpoint + hysteresis) added to the dashboard
      card and the "Why runs end" graph (owner request, 2026-10-30), with a test. Owner declined
      reading `BackupModeHc` (backup heater stays disabled) and a flow > 34 °C notification.

### Checks run locally (2026-10-30)

- yamllint (package, dashboard, resolved config), `fix_yaml_style.py` — clean; no CRLF
- `check_config` on the pinned image (2026.10.1) — passes (only warning: `climate_template` custom
  component not installed in that run); `--info all` lists all 19 new entities
- pytest against the pinned image (harness v0.11.0, Python 3.14): all 5 new tests and both
  template tests (strict + lenient) pass. CI (full suite) is green: 193 passed, 1 skipped.
- Fixed a hidden order dependency: `test_decision_stays_off_while_the_master_switch_is_off` and
  `test_return_temp_is_masked_while_making_hot_water` passed in CI only because earlier test files
  had moved the mocked clock past their sensors' `delay_off` windows; run alone they failed (also on
  `master`). Each now advances the clock 26 min itself; `test_heating_pv_boost.py` alone: 20/20 pass.

## Close
- [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`)
