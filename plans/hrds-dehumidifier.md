# HRDS Dehumidifier + Airflow Coordination — Implementation Plan

> Status: **PLAN ONLY — do not implement yet** (CLAUDE.MD rules 2–3). Revision 2 (2026-10-24):
> rebuilt on what the HRDS integration and the reference unit now show (integration v0.9.5,
> `doc/references/UNIT_BEHAVIOUR.md` T11–T29). See "What changed since revision 1".

## Status

| Step | State |
|------|-------|
| 0. Plan revision 2 (this file), incl. hot-water pause | done, awaiting approval |
| 0b. Design doc [`doc/design/hrds_dehumidifier.md`](../doc/design/hrds_dehumidifier.md) (agreed design, for owner and agents) | done |
| 1. Pre-implementation checks on the live system (below) | open |
| 2. `climate_common.yaml` extraction + `airflow_cooling.yaml` repoint (regression gate: airflow tests) | open |
| 2b. Shared battery floor in `energy.yaml`, heating repointed (regression gate: heating tests) | open |
| 3. `airflow_cooling.yaml`: dehumidify hold (preset medium + moisture bypass), boost gating | open |
| 4. `hrds_dehumidifier.yaml` + `packages/notes/hrds_dehumidifier.md` + `heating_dhw_running` split in `heating_pv_boost.yaml` + tests | open |
| 5. Migration runbook on deploy day (user) | open |
| 6. Dry run on the device (user) | open |

## What changed since revision 1

Facts now established (integration repo `homeassistant-innova-hrds`, read-only for this work):

1. **Recirculation is fixed at about 150 m³/h whenever the HRDS runs.** Every DEU or INT request
   opens the damper and runs the fan (UNIT_BEHAVIOUR §9.3, T11; vendor V#44/V#76/V#78). The fan runs
   at the band minimum `PF28` = 50 % (T16, T18, T22); with `Q_max` 300 m³/h for the HRDS+ 30 that is
   **150 m³/h**. Home Assistant cannot set the fan speed: `PM20` is the unit's own value, writes have
   no effect or are refused (T23, T27, T28), the integration exposes the fan read-only (ADR-0034).
   Only the EEPROM band `PF28` can move it, which is an installer setting, not a control lever
   (ADR-0023).
2. **The total through the coil should be 300 m³/h** (HRDS+ 30 nominal, HB 2.4, §1.2): 150
   recirculation + **150 from the Q350 at preset medium**.
3. **Dehumidify (DEU) is a real, tested operation** (`switch.dehumidify`, register 1140, T11–T19):
   request → damper + V3V/pump within 28 s → fan 30–120 s later → compressor 6.5–8 min after the
   request (T11, T18); stop within about 1–2 min (T19). Supply air is reheated to about room
   temperature by the condenser (§2.2), so DEU dries, it does not cool.

Consequences for the plan:

- **The whole fan top-up design is dropped**: combined-airflow targets (150/200/250), the
  `%→m³/h` map, `hrds_required_fan_percent`, `hrds_fan_airflow_controller`, `hrds_max_recirc_airflow`,
  `hrds_fan_min_speed`, the fan-related hardware checks and risks I4/I5/I6. The fan is not ours.
- **The airflow automation must stand down while the HRDS dehumidifies** and hold the Q350 at
  **medium** (150) so the coil gets its 300 m³/h. No boost, no low, no auto schedule meanwhile.
- **Dehumidify only inside the boost time window** (`climate_boost_schedule_active`). Outside it
  the HRDS stays off; the airflow package alone handles moisture.
- **While dehumidifying, the Q350 bypass is used to keep incoming moisture low** (the Q350 has an
  enthalpy exchanger — see `sensor.airflow_bypass_estimation`): bypass open when the intake air is
  drier than indoor, bypass closed (full enthalpy recovery, which moves moisture out of the humid
  intake stream into the exhaust) when the intake is more humid.
- **Decision 3 is reversed in form, kept in spirit:** the airflow controller stays the **only writer
  of every Comfo output**; it gains a top-priority "HRDS dehumidify" owner branch. The HRDS package
  still never writes the Comfo.
- **The energy package part is obsolete:** `packages/energy.yaml` exists on master (metering; the
  Shelly migration is done) and the PV balance is owned by `packages/victron.yaml`
  (`sensor.victron_pv_net_power`). The HRDS PV gate lives in the HRDS package, built like
  `sensor.heating_pv_surplus`.
- **One battery floor for every PV-surplus load** (Decision 18): the heating package's
  `heating_pv_min_battery_soc` moves to `packages/energy.yaml` as the shared
  `input_number.energy_pv_min_battery_soc` + `binary_sensor.energy_pv_battery_ok`; heating and HRDS
  both read it. No HRDS-own SoC helper.

---

## Context

The **HRDS+ 30 H R K DC** (Innova DEH+ 30 / hej.luft, `innova_hrds` Modbus integration, headless,
brine circuit variant 6) sits on the **Comfo Q350** supply duct. Fresh supply air from the Q350 and,
while a request runs, about 150 m³/h of recirculated room air pass the evaporator. The HRDS has no
mode without recirculation and no fan control from Home Assistant.

Goal: a package `packages/hrds_dehumidifier.yaml` that dehumidifies when it is worth it, **only in
the boost time window**, plus a small, surgical change to `packages/airflow_cooling.yaml` so the
Q350 delivers medium airflow and the moisture-minimising bypass setting while the HRDS runs.

## How the two packages divide the work

| Owner | Writes | Reads from the other |
|-------|--------|----------------------|
| `hrds_dehumidifier.yaml` | `switch.dehumidify` (and `switch.unit_on_off` on only) — nothing else | `binary_sensor.airflow_humidity_drying_needed`, `sensor.heating_cooling_indicator`, `binary_sensor.heating_dhw_running` + `binary_sensor.heating_compressor_active` (heating package) |
| `airflow_cooling.yaml` (`airflow_ventilation_controller`, `airflow_humidity_drying_boost`) | every Comfo output: profile, preset, auto_mode, boost | `binary_sensor.hrds_dehumidify_active` |

No entity is written by both. No template sensor cycle: no airflow decision sensor reads an HRDS
sensor; only the airflow **automations** read `hrds_dehumidify_active`.

## Airflow states vs the HRDS (revised)

| Airflow state | HRDS behaviour | Comfo while HRDS dehumidifies |
|---|---|---|
| **Free cooling** (`airflow_free_cooling_available`) | Not a gate (Decision 19): HRDS runs above max, or above target on free PV, alongside free cooling. | medium; bypass per the moisture rule (intake is dry here, so open) |
| **Flush** (`airflow_humidity_flush_needed`) | Not a gate by itself. | medium; bypass open (flush implies intake drier than indoor) |
| **Drying boost** (`airflow_humidity_drying_needed`) | Below max: HRDS yields — a boost with dry outdoor air is free. Above max: HRDS runs and the boost is cancelled (preset write) and held off. | medium (boost cancelled); bypass open |
| **Moisture protect low** (`airflow_moisture_ventilation_low_needed`) | The HRDS's main case: indoor humid, outdoor too humid to flush. | **medium instead of low** (user requirement: 300 total); bypass **closed** so the enthalpy exchanger keeps intake moisture out |
| **Heat protect low** (`airflow_heat_ventilation_low_needed`) | Runs if needed. | medium instead of low — overrides heat protection for the run (accepted consequence, see I9) |
| **Away** (`switch.comfoconnect_pro_away_function`) | Runs if needed. | **untouched** — Away keeps owning the level (Decision 12); the HRDS works with less Comfo air (T12: fine at 100 m³/h) |

---

## Decisions

Kept from revision 1 (resolved with the user): **1** PV gate (now built in the HRDS package, see
below), **2** no extra outdoor-humidity guard on Comfo flush/boost (the dew gates already block it),
**4** shared `climate_*` package with history-preserving rename, **6** dehumidify also during Away,
**7** opportunistic branch off in `active_heating`, **9** HRDS has its own `hrds_off_dew_diff`.

Dropped: **3** (fan top-up only) and **5** (three combined-airflow targets) — the fan is not
controllable and recirculation is fixed. **8** (free cooling beats the opportunistic branch) —
superseded by Decision 19.

New (revision 2, from the user's instructions — confirm the ones marked *proposed*):

10. **Dehumidify only in the boost window.** Both branches (above max, and above target on free PV)
    require `binary_sensor.climate_boost_schedule_active`. Outside the window the HRDS is off even
    above max; the airflow package's flush/low logic is the only moisture control then.
    A run that is still inside its minimum runtime when the window closes finishes that runtime.
11. **Airflow stands down while dehumidifying.** While `binary_sensor.hrds_dehumidify_active` is on,
    the airflow controller holds `auto_mode off, preset medium`, runs no boost and writes no low;
    its normal Section 1/Section 2 logic resumes when it clears.
12. *Proposed:* **Away keeps priority.** During Away the controller does not force medium (Section 2
    already skips Away); the profile/bypass rule still applies (Section 1 runs during Away).
13. **Bypass keeps intake moisture low while dehumidifying.** Profile `cool` (bypass may open) when
    the intake is drier than indoor by a margin; profile `warm` (bypass closed, full enthalpy
    recovery) otherwise. Purely moisture-driven during the run; temperature does not decide it.
14. *Proposed:* **Boost vs HRDS.** Below max, a pending drying boost wins (HRDS need is gated off by
    `drying_needed`); above max, the HRDS wins and the boost is suspended. When the HRDS stops and
    `drying_needed` is still on, the boost automation starts the boost (new trigger).
15. *Proposed:* **Unit on/off.** The package only toggles `switch.dehumidify`. It switches the unit
    **on** before a request if it is off, and never switches it off (ON-standby keeps the hourly
    anti-stagnation pulses, T13; off-season shutdown stays a manual/seasonal action).
16. **Season.** No HRDS dehumidify in `active_heating` at all (brine circuit: active winter DEU is
    forbidden, HB 3.8.7; the integration's brine guard also refuses it). This tightens Decision 7:
    in heating season the above-max branch does not run either.
17. **Pause while the heat pump makes hot water.** While the geoTHERM charges the hot-water tank,
    the HRDS is switched off **at once** (the minimum runtime does not hold it), so
    `hrds_dehumidify_active` clears and airflow goes back to its normal logic. When the hot-water
    charge ends and dehumidify is still needed (window, humidity), the HRDS starts again with a fresh
    minimum runtime. The signal is the heating package's hot-water detection **without** the 25-min
    tail of `heating_dhw_active` (that tail exists only to mask the return-temperature reading), so
    the HRDS resumes as soon as the charge ends.
    Fail-safe when ebusd gives no answer: treat a running compressor
    (`binary_sensor.heating_compressor_active`, Shelly clamp, independent of ebusd) as possibly
    hot water and pause; with the compressor off there can be no hot-water charge.
    Related handbook note: on a heat-pump circuit with hot-water priority the handbook opens the
    HRDS `OFF` input during hot water (HB 3.8.6); here the same is done over Modbus.
18. **One battery SoC floor for all PV-surplus loads, owned by `packages/energy.yaml`.** The battery
    gets first call on surplus, whichever load wants it; two floors would let one load drain what
    the other protects. Home: `energy.yaml`, not `victron.yaml` — `victron.yaml` holds the Victron
    hardware readings (`sensor.victron_battery_soc`, `sensor.victron_pv_net_power`) and stays that
    way; the floor is a house energy **policy** that consumers share, which is what `energy.yaml`
    becomes the home for (next to its metering wrappers). New in `energy.yaml`:
    - `input_number.energy_pv_min_battery_soc` (%) — replaces `input_number.heating_pv_min_battery_soc`
      (same min/max/step/icon).
    - `binary_sensor.energy_pv_battery_ok` — state-based, `victron_battery_soc ≥ floor` (the
      heating package's current semantics: blocked only below the floor), availability on
      `sensor.victron_battery_soc`. Each consumer reads this one sensor, so the comparison exists
      once. No hysteresis of its own: both consumers already debounce (heating 15/20 min, HRDS 5 min).
    Each load keeps its own **surplus** figure and threshold (they add back their own draw, and their
    demands differ); only the battery floor is shared.
19. **Free cooling does not stop the HRDS.** Above target with free PV (and above max in any case),
    the HRDS runs even while `airflow_free_cooling_available` is on. Free PV makes the extra drying
    cheap, and free cooling alone only dries as far as the outdoor dew allows. Supersedes Decision 8.
    While the HRDS runs, its hold applies (medium, moisture bypass — open, since free cooling means
    the intake is dry); free cooling resumes its own preset logic when the run ends.

---

## Design

All `CLAUDE.MD` template/helper rules apply: availability guards, no `initial:`, no
`| float(default)` behind a guard or on helpers, a comment on every block.
`packages/notes/airflow_cooling.md` rules apply to the airflow edits (minimal, surgical controller
edits; derived-from-binaries sensors are state-based).

### Shared common package — `packages/climate_common.yaml` (NEW, unchanged in substance)

Moved from `airflow_cooling.yaml` and renamed to `climate_*` (rename map below):

- **Parameters:** `climate_target_humidity`, `climate_max_humidity`, `climate_target_temperature`
  (optionally `climate_min_humidity`). `airflow_min_dew_diff` stays airflow-only.
- **Thresholds:** `sensor.climate_dew_point_target`, `sensor.climate_dew_point_max`
  (optionally `_min`).
- **Indoor primitives:** `climate_avg_indoor_humidity`, `climate_avg_indoor_temp`,
  `climate_indoor_dew` and its `_5min` filter.
- **Boost window:** `schedule.climate_boost_workday` / `_non_workday` and a new state-based
  `binary_sensor.climate_boost_schedule_active` (the `in_schedule` expression now inlined in
  `airflow_humidity_drying_needed`). Both the drying boost and HRDS Decision 10 use it, so "the
  boost time frame" has one definition.

### Airflow changes — `packages/airflow_cooling.yaml` (EDIT, surgical)

1. **New decision sensor `binary_sensor.airflow_intake_drier`** (trigger-based, numeric inputs,
   `this.state` Schmitt + 10-min delay like the flush sensor): ON when
   `airflow_outdoor_dew_5min + airflow_min_dew_diff < climate_indoor_dew_5min`, released with the
   same 0.3 °C hysteresis. Uses the Q350 **intake** dew (after the ground duct) — that is the air
   that actually enters. Belongs to the airflow package because it decides a Comfo output.
   Physics: an enthalpy exchanger moves moisture from the wetter to the drier stream. Intake drier
   than indoor → heat recovery would hand indoor moisture back to the supply, so open the bypass.
   Intake wetter → recovery moves intake moisture into the exhaust, so keep the bypass closed.
2. **Controller Section 1, new Block 0 (first in the `choose`)** — HRDS dehumidify owner:
   condition `binary_sensor.hrds_dehumidify_active` on; desired profile `cool` if
   `airflow_intake_drier` on else `warm`; write only if it differs (idempotent), notify on change.
   Because it is first, Blocks 1–5 never run during a dehumidify run.
3. **Controller Section 2, new first branch (inside the Away guard)** — HRDS dehumidify owner:
   condition `hrds_dehumidify_active` on; desired `auto_mode off, preset medium`; act unless
   already there. Writing the preset cancels a running boost (notes: preset write cancels boost) —
   intended (Decision 14). It precedes the boost-owner branch, so the boost owner never re-enables
   auto meanwhile.
4. **Controller triggers:** add `binary_sensor.hrds_dehumidify_active` (any change) and
   `binary_sensor.airflow_intake_drier`. On `on → off` the normal blocks re-derive the full state
   (auto restored, low, medium, profile) — no special restore code.
5. **Boost automation `airflow_humidity_drying_boost`:** add condition "`hrds_dehumidify_active`
   off" to the start and re-arm paths; add a trigger `hrds_dehumidify_active` → `off` that starts the
   boost when `drying_needed` is on (Decision 14).
   `binary_sensor.airflow_humidity_drying_needed` itself stays unchanged (pure intent), which keeps
   it readable by the HRDS need without a cycle.
6. **Status:** `sensor.airflow_cooling_state` gets `hrds_dehumidify` (checked right after `off`),
   icon `mdi:water-off`.
7. The startup guard's `has_value` list gains `binary_sensor.hrds_dehumidify_active`; a missing or
   unavailable HRDS reads as "not active", so airflow runs normally (fail-safe).

### HRDS package — `packages/hrds_dehumidifier.yaml` (NEW)

**Integration entities** (object ids from `doc/entity-reference.md`; the live ids may carry a
device prefix — check 1): `switch.dehumidify`, `switch.unit_on_off`,
`binary_sensor.recirculation_active`, `binary_sensor.dehumidify_request`,
`binary_sensor.brine_temperature_guard`, `switch.operation_allowed`, `sensor.compressor_status`,
`sensor.operating_mode`, `sensor.supply_fan_airflow` (dashboard only).

**Helpers (`hrds_` prefix):**
- `input_boolean.hrds_automatic_enabled` — master enable.
- `input_number.hrds_power_demand` (W) — the unit's electrical draw while the compressor runs; the
  unit has no power register. Used to keep the PV gate invariant under the unit's own draw.
- `input_number.hrds_off_dew_diff` (°C) — stop hysteresis (Decision 9).
- `input_number.hrds_min_runtime` (min, suggested 45) — must clearly exceed the 6.5–8 min until the
  compressor starts (T11, T18), or a run can end before it dried anything.
- `timer.hrds_min_runtime`.
- (No SoC helper: the battery floor is the shared one in `energy.yaml`, Decision 18.)

**Sensors:**
- `sensor.hrds_pv_surplus` (W) — `victron_pv_net_power` **plus** `hrds_power_demand` while
  `compressor_status` is on, clamped at 0. Same pattern as `sensor.heating_pv_surplus`: without the
  add-back the run lowers measured surplus and switches itself off.
- `binary_sensor.hrds_pv_surplus_available` — `hrds_pv_surplus ≥ hrds_power_demand` **and**
  `binary_sensor.energy_pv_battery_ok` on; delay_on/off 5 min. Availability-guarded.
- `binary_sensor.hrds_indoor_above_max` — trigger-based Schmitt: on at
  `climate_indoor_dew_5min ≥ climate_dew_point_max`, off at `≤ max − hrds_off_dew_diff`.
- `binary_sensor.hrds_indoor_above_target` — same on `climate_dew_point_target`.
- `binary_sensor.hrds_paused_for_hot_water` — **state-based** (Decision 17):
  `heating_dhw_running` on, **or** `heating_dhw_running` has no value **and**
  `heating_compressor_active` on. No delay of its own: the ebus hot-water state does not flap, and
  the restart of the HRDS takes 6.5–8 min to reach the compressor anyway.
- `binary_sensor.hrds_dehumidify_needed` — **state-based** (inputs are binaries only; notes rule):
  ```
  window   = climate_boost_schedule_active                      # Decision 10
  season   = heating_cooling_indicator != active_heating        # Decision 16
  hot_wtr  = hrds_paused_for_hot_water                          # Decision 17
  urgent   = hrds_indoor_above_max                              # beats a pending boost
  opportun = hrds_indoor_above_target and hrds_pv_surplus_available
             and not airflow_humidity_drying_needed             # Decision 14
  needed   = window and season and not hot_wtr and (urgent or opportun)
  ```
- `binary_sensor.hrds_dehumidify_active` — **state-based**, the signal the airflow automations key
  on: `switch.dehumidify` on **or** `binary_sensor.recirculation_active` on. Covers our request from
  the moment it is written (before the fan starts) and any dehumidify or INT from elsewhere (manual,
  climate entity) while the unit actually recirculates. Unknown/unavailable → off.
- `sensor.hrds_state` — `off` / `outside_window` / `idle` / `dehumidify_max` / `dehumidify_pv` /
  `min_runtime` / `paused_hot_water` / `blocked` (brine guard, operation gate or refused write), for
  the dashboard.

**Heating package edit (`packages/heating_pv_boost.yaml`, behaviour-neutral):** split the
expression of `binary_sensor.heating_dhw_active` into a new state-based
`binary_sensor.heating_dhw_running` (`geotherm_heating_hvac_action == water` or
`geotherm_heating_hwc_active` on, **no** delay) and let `heating_dhw_active` read it with its
existing 25-min `delay_off`. One definition of "hot water is being made"; the heating logic and its
tests do not change.

**Automation `hrds_dehumidify_controller`** (`mode: queued`, gated by `hrds_automatic_enabled`;
triggers: `hrds_dehumidify_needed` change, `hrds_paused_for_hot_water` change, `timer.finished`,
HA start):
- **Start** (need on, `switch.dehumidify` off): `switch.unit_on_off` on if off; `switch.dehumidify`
  on; start `timer.hrds_min_runtime`; notify. The integration's `check_write_allowed` (operation
  gate, PH28, brine guard, season) may refuse the write: `continue_on_error`, report `blocked` and
  notify once, no retry loop.
- **Stop** (need off, `switch.dehumidify` on): only when the timer is idle; otherwise the
  `timer.finished` trigger re-evaluates. `switch.dehumidify` off; unit stays on (Decision 15).
- **Hot-water pause** (first branch; `hrds_paused_for_hot_water` on, `switch.dehumidify` on):
  `switch.dehumidify` off **immediately**, cancel `timer.hrds_min_runtime`. The unit's own compressor
  minimum on time `PE02` still applies inside the unit. No notification (hot water runs daily);
  `sensor.hrds_state` shows `paused_hot_water`.
- **Resume:** nothing special — when the pause clears, `hrds_dehumidify_needed` turns on again if
  the window and humidity still call for it, and the Start branch runs (new timer).
- Writes only on a state difference (integration invariant: no periodic writes, ADR-0006/0023).
- Never touches `switch.integration_request` (cooling stays the Comfo's job).

### Sequence of one run (expected)

1. Window open, indoor above max, outdoor humid → airflow is in moisture-protect (LOW, warm).
2. `hrds_dehumidify_needed` on → `switch.dehumidify` on → `hrds_dehumidify_active` on.
3. Airflow controller: auto off, preset **medium** (≈150) → total ≈300 once the fan runs; profile
   stays/turns **warm** (intake wetter → bypass closed). T18: the Q350 supply dips for about a minute
   when the HRDS fan starts and recovers (constant-flow fans).
4. Compressor 6.5–8 min after the request; the run lasts at least `hrds_min_runtime`.
5. Indoor dew falls below `max − hrds_off_dew_diff` (or the window closes) → stop once the timer is
   idle → `hrds_dehumidify_active` off after the fan's run-on (≈1–2 min, T19) → airflow re-derives
   its normal state (here: back to LOW + warm).

Hot-water interruption during step 4: `heating_dhw_running` on → `switch.dehumidify` off at once →
`hrds_dehumidify_active` off after the run-on → airflow back to its normal state (LOW + warm here,
or a pending drying boost) → hot-water charge ends → need on again → back to step 2.

---

## Interaction analysis (revised)

Still structurally safe: no shared actuator; no sensor cycle; `dew_min < dew_target` keeps "dry" and
"retain moisture" apart (HRDS needs indoor above target, Block 1A needs below min).

| # | Issue | Resolution |
|---|-------|------------|
| I1 | Heating-season cross-purpose | **Resolved, tightened:** no HRDS in `active_heating` (Decision 16) |
| I2 | Free-cooling overlap | **Resolved by Decision 19:** both run together; while the HRDS runs the Comfo holds medium and the bypass follows the moisture rule (open, the intake is dry under free cooling), so free cooling continues at medium and the HRDS dries the recirculated share. Costs compressor energy only when PV is free or indoor is above max |
| I3 | Shared hysteresis knob | **Resolved:** `hrds_off_dew_diff` |
| I4–I6 | Fan write chatter / open-loop flow / fan re-assert after off | **Obsolete:** no fan writes at all |
| I7 | Two controllers on one indoor-dew sensor | Documented. Now stronger: the HRDS run sets the Comfo state. Kept stable by the Schmitt bands, `hrds_min_runtime` and the 10-min airflow delays; `airflow_intake_drier` has its own 10-min delay so the profile does not chatter |
| I8 | **Boost cancel on hand-over.** The medium write cancels a running boost; the boost automation's re-arm could fight it | Boost start and re-arm gated on `hrds_dehumidify_active` off; preset branch precedes the boost-owner branch (Decision 14) |
| I9 | **Heat protection overridden.** On a hot day medium replaces LOW for the run: more warm air through the ground duct | Accepted by the user's 300 m³/h requirement; bounded to the boost window and the run length. `warm` profile recovers coolness when the intake is the wetter stream |
| I10 | **PV self-cancel.** The HRDS draw lowers the measured surplus | `hrds_pv_surplus` adds `hrds_power_demand` back while the compressor runs |
| I11 | **PV double booking with `heating_pv_boost`.** Both loads can see the same surplus at once | Documented; HRDS demand is small next to the heat pump. If it matters: subtract the other load's running draw in each surplus sensor (follow-up) |
| I12 | **Stale restore.** Derived binaries restoring stale after restart | `hrds_dehumidify_needed` and `hrds_dehumidify_active` are state-based (notes rule) |
| I13 | **Window ends mid-run.** | Run finishes `hrds_min_runtime`, then stops (at most one runtime past the window) |
| I14 | **Moisture outside the window.** Above max at night, no HRDS | Accepted (Decision 10); airflow flush/low still act |
| I15 | **Bypass vs Comfo's own logic.** `cool` lets the bypass open, it does not force it: the Q350 opens it only when that cools | Best effort. Observe with `sensor.airflow_bypass_estimation` in the dry run. When the intake is drier but warmer, the bypass stays closed and some indoor moisture is recovered — unavoidable without a forced-bypass control |
| I16 | **Hot-water pause cycles the HRDS.** Each hot-water charge stops a run and restarts it afterwards, airflow switches medium → normal → medium | Accepted (Decision 17). A charge lasts much longer than the HRDS start and stop (≈8 min, ≈2 min), and the airflow side only re-derives its state. If the hot-water detection ever flaps, add a short `delay_off` on `hrds_paused_for_hot_water` |
| I17 | **ebusd offline.** `heating_dhw_running` has no value | Fail-safe through the Shelly clamp: compressor on → pause; compressor off → no hot water possible, run normally |

---

## Files

- **New:** `packages/climate_common.yaml`.
- **Keep current:** `doc/design/hrds_dehumidifier.md` — change it with any design change during
  implementation; set its status to implemented at the end.
- **New:** `packages/hrds_dehumidifier.yaml`, `packages/notes/hrds_dehumidifier.md` (the hardware
  facts above: fixed 150 m³/h recirculation, no fan control, compressor start delay, stop timing),
  index row in `packages/CLAUDE.md`.
- **Edit:** `packages/airflow_cooling.yaml` — climate_* repoint; `airflow_intake_drier`; controller
  Block 0 (Section 1) and dehumidify branch (Section 2); new triggers; boost gating + hand-over
  trigger; `airflow_cooling_state`.
- **Edit:** `packages/notes/airflow_cooling.md` — the dehumidify owner rule (first branch in both
  sections, preset medium, profile by intake dew).
- **Edit:** `tests/conftest.py`, `tests/test_airflow.py`; **new** `tests/test_hrds.py` (+ innova_hrds
  stubs).
- **Edit:** `dashboards/airflow-dashboard.yaml` — renamed ids (an HRDS card is out of scope).
- **Edit:** `packages/heating_pv_boost.yaml` — new `binary_sensor.heating_dhw_running` (undelayed),
  `heating_dhw_active` reads it (behaviour unchanged); one line in `packages/notes/heating_pv_boost.md`
  naming the two signals; `tests/test_heating_pv_boost.py` as the regression gate.
- **Edit:** `packages/energy.yaml` — new "PV surplus policy" section with
  `input_number.energy_pv_min_battery_soc` and `binary_sensor.energy_pv_battery_ok` (Decision 18);
  `packages/notes/energy.md` gets the rule "one battery floor for every PV-surplus load; consumers
  read `energy_pv_battery_ok`, never compare the SoC themselves"; the `energy.yaml` row in
  `packages/CLAUDE.md` mentions the policy.
- **Edit:** `packages/heating_pv_boost.yaml` — remove `input_number.heating_pv_min_battery_soc`;
  `heating_slab_mode_wanted` reads `binary_sensor.energy_pv_battery_ok` instead of comparing
  `victron_battery_soc` (availability on that sensor instead of the SoC); the PV notification text
  and the group list follow. `dashboards/heating-dashboard.yaml` shows the new helper;
  `tests/conftest.py` seeds `input_number.energy_pv_min_battery_soc` instead of the heating one.
- Not touched: `packages/victron.yaml`.

### Rename map (Decision 4)

`airflow_target_humidity → climate_target_humidity` · `airflow_max_humidity → climate_max_humidity` ·
`airflow_cooling_target_temperature → climate_target_temperature` ·
`airflow_dew_point_target → climate_dew_point_target` · `airflow_dew_point_max → climate_dew_point_max` ·
`airflow_min_indoor_dew(_5min) → climate_indoor_dew(_5min)` ·
`airflow_avg_indoor_humidity(_5min) → climate_avg_indoor_humidity(_5min)` ·
`airflow_avg_indoor_temp(_5min) → climate_avg_indoor_temp(_5min)` ·
`airflow_boost_workday/_non_workday → climate_boost_workday/_non_workday` · **new**
`binary_sensor.climate_boost_schedule_active`. (Optionally `airflow_min_humidity` and
`airflow_dew_point_min`.) Repoint every reference in the decision sensors, the controller, the
climate entity, `airflow_cooling_state`, the dashboard and the tests; run the airflow tests as the
regression gate before step 3.

## Pre-implementation checks (live system, read-only)

The fan questions of revision 1 are settled (T16, T22–T28). What is left:

1. **Entity ids:** the live object ids of the HRDS entities (device prefix?) and the Comfo ids used
   above.
2. **Q350 medium = about 150 m³/h:** read `sensor.comfoconnect_pro_supply_fan_volume` at preset
   medium. If it differs, adjust the medium setpoint on the Q350 (not in HA) so medium + 150 ≈ 300.
3. **Write path open:** `switch.operation_allowed` on, `switch.enable_dehumidify_bms` (PH28) on,
   season summer (`sensor.operating_mode`), brine guard configured and passing.
4. **HRDS draw:** an estimate for `hrds_power_demand` (handbook technical data, or a clamp reading).
5. **Bypass response:** with profile `warm` vs `cool` during a run, does
   `sensor.airflow_bypass_estimation` move as expected?
6. **Hot-water signal:** across one hot-water charge, confirm `geotherm_heating_hvac_action` reads
   `water` and `geotherm_heating_hwc_active` turns on and off with the charge (and does not just mean
   "hot-water circuit enabled"). Note the typical charge length.

## Migration — history-preserving rename via `ha_mcp` (deploy day)

Unchanged from revision 1:

- **Template sensors** (registry entries with `unique_id`): keep each `unique_id` verbatim in
  `climate_common.yaml`; rename the entity_id in the registry first, so history moves with it.
- **YAML helpers** (`input_number`, `schedule`; no registry entry): snapshot the values, deploy,
  set them again.

The battery floor is such a YAML helper too: `input_number.heating_pv_min_battery_soc →
input_number.energy_pv_min_battery_soc` loses its value on deploy, so it is in the snapshot.

Runbook: (1) snapshot the renamed `input_number` values (incl. the battery floor); (2) registry-rename the template sensors
`sensor.airflow_* → sensor.climate_*`; (3) user deploys via `git pull`; (4) restore the values and
set the new `hrds_*` helpers; (5) verify continuous history and no orphaned `airflow_*` entities.

> `CLAUDE.MD` scopes `ha_mcp` to read-only. Steps 2 and 4 write — confirm that use for the migration
> window (or the user does them in the UI).

## Verification

1. **Unit tests — `tests/test_hrds.py`:**
   - need off outside the window even above max; on inside the window above max regardless of PV,
     and `drying_needed`;
   - above target: on only with PV surplus, also with free cooling on; off with `drying_needed`, in
     `active_heating`;
   - Schmitt: stays on between trigger and `trigger − hrds_off_dew_diff`;
   - min runtime: need clears with the timer active → no stop until `timer.finished`;
   - PV add-back: surplus stays above demand while the compressor runs;
   - `hrds_dehumidify_active` on from `switch.dehumidify` or `recirculation_active`, off on unknown;
   - hot water: `heating_dhw_running` on mid-run → dehumidify off at once even with the timer
     active, timer cancelled; off again → dehumidify back on while still needed; no restart if the
     window closed meanwhile; `heating_dhw_running` unknown + compressor on → paused, + compressor
     off → not paused.
   - `tests/test_heating_pv_boost.py`: `heating_dhw_active` still keeps its 25-min tail;
     `heating_dhw_running` follows the inputs with no delay; slab mode still blocked below the
     floor and allowed at the floor, now through `energy_pv_battery_ok` (existing SoC cases pass
     with the renamed helper).
   - energy: `energy_pv_battery_ok` off below the floor, on at and above it, unavailable without
     `victron_battery_soc`; the HRDS PV branch and slab mode both follow the one floor.
2. **Unit tests — `tests/test_airflow.py`:**
   - active on → auto off + medium from each prior state (auto, low, boost running → cancelled,
     heat_low, moisture_low); Away → preset untouched;
   - profile `warm` when intake wetter, `cool` when intake drier, Blocks 1–5 not run while active;
   - boost does not start or re-arm while active; starts on active → off with `drying_needed` on;
   - active → off restores the normal state (low/medium/auto and profile) without extra code;
   - all existing airflow tests pass with the renamed ids (regression gate).
3. **Template check** in Developer Tools for each new sensor.
4. **Dry run on the device** (user): enable `hrds_automatic_enabled`; inside the window watch
   `sensor.hrds_state`, `sensor.airflow_cooling_state`, preset/profile,
   `sensor.comfoconnect_pro_supply_fan_volume` + `sensor.supply_fan_airflow` (≈150 + 150),
   `sensor.compressor_status`, `sensor.airflow_bypass_estimation`.
5. User deploys via `git pull` on the HA host (never auto-deploy).

## Out of scope (this iteration)

- HRDS active cooling (`switch.integration_request`, INT).
- Changing the HRDS fan band `PF28` (installer setting).
- Dehumidify outside the boost window; winter dehumidify.
- A dashboard card for the HRDS.
