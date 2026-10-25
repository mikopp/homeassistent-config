# HRDS Dehumidifier + Airflow Coordination — Implementation Plan

> Status: **PLAN ONLY — do not implement yet** (CLAUDE.MD rules 2–3). Revision 3 (2026-10-25).
> The agreed design is described for owner and agents in
> [`doc/design/hrds_dehumidifier.md`](../doc/design/hrds_dehumidifier.md); this file holds the
> work steps, decision history, risks, deploy and tests.

## Status

| Step | State |
|------|-------|
| 0. Plan (this file) and design doc | done; open: Decisions 12, 14, 15 and starting values (below) |
| 1. Pre-implementation checks on the live system (below) | open |
| 2. `airflow_cooling.yaml`: shared boost-window sensor (regression gate: airflow tests) | open |
| 2b. Shared battery floor in `energy.yaml`, heating repointed (regression gate: heating tests) | open |
| 3. `airflow_cooling.yaml`: dehumidify hold (preset medium + moisture bypass), boost gating, quiet hand-back | open |
| 4. `hrds_dehumidifier.yaml` + notes + `heating_dhw_running` split + tests | open |
| 5. `dashboards/hrds-dashboard.yaml` + registration | open |
| 6. Deploy by hand (instructions in the PR description) | open |
| 7. Dry run on the device (user) | open |

## Revision history

- **Rev 1** (2026-06): PV-gated dehumidify with HRDS fan top-up to combined-airflow targets;
  shared `climate_*` package; new energy package.
- **Rev 2** (2026-10-24): rebuilt on the integration's hardware findings (v0.9.5, UNIT_BEHAVIOUR
  T11–T29): recirculation fixed at about 150 m³/h, fan not controllable → top-up dropped; airflow
  holds medium while the HRDS runs; moisture-driven bypass; boost window only; hot-water pause;
  one shared battery floor.
- **Rev 3** (2026-10-25): free cooling no longer stops the HRDS (19); keep the `airflow_*` names,
  no `climate_*` package (20; refactor in [`todo.md`](todo.md)); only start and end notifications
  (21); HRDS dashboard (22); deploy by hand, no `ha_mcp` writes (23); PV priority between loads
  deferred to [`todo.md`](todo.md).

## The facts this rests on

From the integration repo `mikopp/homeassistant-innova-hrds` (read-only for this work):

1. **Recirculation is fixed at about 150 m³/h whenever the HRDS runs.** Every DEU or INT request
   opens the damper and runs the fan (UNIT_BEHAVIOUR §9.3, T11; vendor V#44/V#76/V#78). The fan runs
   at the band minimum `PF28` = 50 % (T16, T18, T22); with `Q_max` 300 m³/h that is **150 m³/h**.
   Home Assistant cannot set the fan speed (T23, T27, T28; ADR-0034). Only the EEPROM band `PF28`
   moves it — an installer setting (ADR-0023).
2. **The total through the coil should be 300 m³/h** (HRDS+ 30 nominal, HB 2.4): 150 recirculation
   + **150 from the Q350 at preset medium**.
3. **Dehumidify (DEU) is tested** (`switch.dehumidify`, register 1140, T11–T19): request → damper +
   V3V/pump within 28 s → fan 30–120 s later → compressor 6.5–8 min after the request (T11, T18);
   stop within about 1–2 min (T19). Supply air is reheated to about room temperature (§2.2).
4. **Brine circuit, variant 6:** active winter dehumidification is forbidden (HB 3.8.7).
5. **Power:** handbook maximum 820 W (690 W compressor + 120 W fan); the compressor settled at about
   25–27 % in both runs (T12, T18), so the steady draw is lower. No power register.

## Context

The **HRDS+ 30 H R K DC** (headless, brine circuit variant 6) sits on the **Comfo Q350** supply
duct. Goal: a package `packages/hrds_dehumidifier.yaml` that dehumidifies when it is worth it,
**only in the boost time window**, plus surgical changes to `packages/airflow_cooling.yaml` so the
Q350 delivers medium airflow and the moisture-minimising bypass setting while the HRDS runs.

## How the packages divide the work

| Owner | Writes | Reads from the others |
|-------|--------|-----------------------|
| `hrds_dehumidifier.yaml` | `switch.dehumidify` (and `switch.unit_on_off` on only) — nothing else | `binary_sensor.airflow_boost_window_active`, `binary_sensor.airflow_humidity_drying_needed`, the airflow dew sensors, `sensor.heating_cooling_indicator`, `binary_sensor.heating_dhw_running`, `binary_sensor.heating_compressor_active`, `binary_sensor.energy_pv_battery_ok` |
| `airflow_cooling.yaml` (`airflow_ventilation_controller`, `airflow_humidity_drying_boost`) | every Comfo output: profile, preset, auto_mode, boost | `binary_sensor.hrds_dehumidify_active` |

No entity is written by both. No template sensor cycle: no airflow decision sensor reads an HRDS
sensor; only the airflow **automations** read `hrds_dehumidify_active`. The HRDS is a new
dependency of the airflow package (Decision 20).

## Airflow states vs the HRDS

| Airflow state | HRDS behaviour | Comfo while HRDS dehumidifies |
|---|---|---|
| **Free cooling** | Not a gate (19) | medium; bypass open (intake is dry) |
| **Flush** | Not a gate | medium; bypass open (flush implies intake drier than indoor) |
| **Drying boost** (`drying_needed`) | Below max: HRDS yields — the boost is free. Above max: HRDS runs, boost cancelled and held off | medium; bypass open |
| **Moisture protect low** | The main case: indoor humid, outdoor too humid to flush | **medium instead of low**; bypass **closed** — enthalpy recovery keeps intake moisture out |
| **Heat protect low** | Runs if needed | medium instead of low (accepted, I9) |
| **Away** | Runs if needed (6) | untouched — Away keeps the level (12, proposed); bypass rule applies |

---

## Decisions

From revision 1, still valid: **1** PV gate (now built in the HRDS package), **2** no extra
outdoor-humidity guard on Comfo flush/boost (the dew gates already block it), **6** dehumidify also
during Away, **7** opportunistic branch off in `active_heating` (tightened by 16), **9** HRDS has its
own `hrds_off_dew_diff`.

Dropped: **3** fan top-up and **5** combined-airflow targets (fan not controllable), **4** shared
`climate_*` package (superseded by 20), **8** free cooling beats the opportunistic branch (superseded
by 19).

10. **Dehumidify only in the boost window** — *confirmed*. Both reasons require
    `binary_sensor.airflow_boost_window_active`. Outside the window the HRDS is off even above max;
    `airflow_cooling.yaml`'s flush/low logic handles moisture then. A run still inside its minimum
    runtime when the window closes finishes that runtime.
11. **Airflow stands down while dehumidifying.** While `hrds_dehumidify_active` is on, the
    controller holds `auto_mode off, preset medium`, runs no boost and writes no low; its normal
    logic resumes when it clears.
12. *Proposed:* **Away keeps priority.** During Away the controller does not force medium
    (Section 2 already skips Away); the bypass rule still applies (Section 1 runs during Away).
13. **Bypass keeps intake moisture low while dehumidifying.** Profile `cool` (bypass may open) when
    the intake is drier than indoor by a margin; `warm` (bypass closed, full enthalpy recovery)
    otherwise. Purely moisture-driven during the run.
14. *Proposed:* **Boost vs HRDS.** Below max a pending drying boost wins (the HRDS reason is gated
    off by `drying_needed`); above max the HRDS wins and the boost is suspended. When the HRDS stops
    and `drying_needed` is still on, the boost automation starts the boost.
15. *Proposed:* **Unit on/off.** The package switches the unit **on** before a request if it is off
    and never switches it off (ON-standby keeps the hourly anti-stagnation pulses, T13).
16. **Season.** No HRDS dehumidify in `active_heating` (brine; the integration's brine guard also
    refuses it).
17. **Pause while the heat pump makes hot water.** The HRDS is switched off **at once** (the minimum
    runtime does not hold it); airflow goes back to normal; when the charge ends and the run is still
    wanted, the HRDS starts again with a fresh minimum runtime. Signal: the heating package's
    hot-water detection **without** the 25-min tail of `heating_dhw_active`
    (`heating_dhw_running`). Fail-safe when ebusd has no value: a running compressor
    (`heating_compressor_active`, Shelly clamp) counts as possibly hot water.
18. **One battery SoC floor for all PV-surplus loads, in `packages/energy.yaml`:**
    `input_number.energy_pv_min_battery_soc` (replaces `heating_pv_min_battery_soc`) and the
    state-based `binary_sensor.energy_pv_battery_ok` (`victron_battery_soc ≥ floor`, availability on
    the SoC). Every consumer reads the binary; each keeps its own surplus figure and threshold.
    `victron.yaml` keeps the hardware readings only.
19. **Free cooling does not stop the HRDS.** Above target with free PV (and above max in any case)
    the HRDS runs while free cooling is available. Free PV makes the drying cheap; free cooling only
    dries as far as the outdoor dew allows.
20. **Keep the `airflow_*` names; the HRDS is a new dependency of the airflow package** — *confirmed*.
    The HRDS reads the airflow humidity thresholds and indoor dew as they are
    (`sensor.airflow_dew_point_target/_max`, `sensor.airflow_min_indoor_dew_5min`,
    `input_number.airflow_*_humidity`). Only the **boost window** is shared as a new sensor:
    `binary_sensor.airflow_boost_window_active` in `airflow_cooling.yaml`, extracted from the inline
    `in_schedule` expression of `airflow_humidity_drying_needed`, which then consumes it. No renames,
    no migration. A neutral shared package is a future refactor ([`todo.md`](todo.md)).
21. **Notifications: only start and end of a run** — *confirmed*.
    - HRDS: one notification when a run starts (reason: above max / PV, indoor RH and dew) and one
      when it ends (reason: humidity reached / window closed / automatic control off / refused,
      duration). A hot-water pause and resume inside a run are silent. A refused request ends the
      run with reason "refused"; `sensor.hrds_state` shows `blocked`.
    - Airflow: silent while it holds for the HRDS and while it hands back. The controller's existing
      notifications are skipped while `hrds_dehumidify_active` is on and for 3 minutes after it
      clears (covers the hand-back and the route-to-auto re-run it may cause).
22. **HRDS dashboard** — *confirmed*: a new `dashboards/hrds-dashboard.yaml` with the integration's
    essentials plus this package's entities (content below).
23. **Deploy by hand, no `ha_mcp` writes** — *confirmed*. With Decision 20 there are no entity
    renames; the only value to carry over is the battery floor. Deploy instructions go in the PR
    description.

Deferred to [`todo.md`](todo.md): **PV priority between loads** (the heating PV boost and the HRDS
can see the same surplus at once; I11).

**Starting values** (set by hand on deploy; still to confirm): `hrds_power_demand` 500 W,
`hrds_min_runtime` 45 min, `hrds_off_dew_diff` 0.5–1.0 °C.

---

## Design

All `CLAUDE.MD` template/helper rules apply: availability guards, no `initial:`, no
`| float(default)` behind a guard or on helpers, a comment on every block.
`packages/notes/airflow_cooling.md` rules apply to the airflow edits (minimal, surgical controller
edits; derived-from-binaries sensors are state-based).

### Airflow changes — `packages/airflow_cooling.yaml` (EDIT, surgical)

1. **Shared boost window `binary_sensor.airflow_boost_window_active`** (state-based): workday +
   `schedule.airflow_boost_workday` or non-workday + `schedule.airflow_boost_non_workday`.
   `airflow_humidity_drying_needed` reads it instead of its inline `in_schedule` block; its
   workday/schedule triggers are replaced by one trigger on the new sensor. Behaviour unchanged.
2. **New decision sensor `binary_sensor.airflow_intake_drier`** (trigger-based, numeric inputs,
   `this.state` Schmitt + 10-min delay like the flush sensor): ON when
   `airflow_outdoor_dew_5min + airflow_min_dew_diff < airflow_min_indoor_dew_5min`, released with
   the same 0.3 °C hysteresis. The Q350 **intake** dew (after the ground duct) is the air that
   enters. An enthalpy exchanger moves moisture from the wetter to the drier stream: intake drier →
   open the bypass; intake wetter → keep it closed.
3. **Controller Section 1, new Block 0 (first)** — HRDS dehumidify owner: `hrds_dehumidify_active`
   on → profile `cool` if `airflow_intake_drier` on, else `warm`; write only if it differs; no
   notification (21). Blocks 1–5 never run during a run.
4. **Controller Section 2, new first branch (inside the Away guard)** — HRDS dehumidify owner:
   `hrds_dehumidify_active` on → `auto_mode off, preset medium` unless already there; no
   notification. The preset write cancels a running boost (14). It precedes the boost-owner branch.
5. **Controller triggers:** add `hrds_dehumidify_active` (any change) and `airflow_intake_drier`.
   On `on → off` the normal blocks re-derive the full state — no restore code.
6. **Quiet hand-back (21):** a controller variable `quiet` = `hrds_dehumidify_active` on, or its
   `last_changed` less than 3 min ago; every existing `notify` step is wrapped in `if: not quiet`.
7. **Boost automation `airflow_humidity_drying_boost`:** condition "`hrds_dehumidify_active` off" on
   the start and re-arm paths; new trigger `hrds_dehumidify_active` → `off` that starts the boost
   when `drying_needed` is on (14). `drying_needed` itself stays pure intent.
8. **Status:** `sensor.airflow_cooling_state` gets `hrds_dehumidify` (right after `off`), icon
   `mdi:water-off`.
9. The startup guard's `has_value` list gains `hrds_dehumidify_active`; an unavailable HRDS reads
   as "not active", so airflow runs normally (fail-safe).

### Energy change — `packages/energy.yaml` (EDIT)

New "PV surplus policy" section: `input_number.energy_pv_min_battery_soc` (same min/max/step/icon
as the heating helper it replaces) and `binary_sensor.energy_pv_battery_ok` (Decision 18).

### Heating changes — `packages/heating_pv_boost.yaml` (EDIT, behaviour-neutral)

- Split `binary_sensor.heating_dhw_active` into a new state-based `binary_sensor.heating_dhw_running`
  (`geotherm_heating_hvac_action == water` or `geotherm_heating_hwc_active` on, **no** delay);
  `heating_dhw_active` reads it with its existing 25-min `delay_off`.
- Remove `input_number.heating_pv_min_battery_soc`; `heating_slab_mode_wanted` reads
  `binary_sensor.energy_pv_battery_ok` (availability on it instead of the SoC); notification text
  and group follow.

### HRDS package — `packages/hrds_dehumidifier.yaml` (NEW)

**Integration entities** (keys from the integration's `doc/entity-reference.md`; the live ids carry
the device prefix, likely `hrds_` — check 1): `switch.dehumidify`, `switch.unit_on_off`,
`binary_sensor.recirculation_active`, `binary_sensor.dehumidify_request`,
`binary_sensor.brine_temperature_guard`, `switch.operation_allowed`, `sensor.compressor_status`,
`sensor.operating_mode`.

**Helpers (`hrds_` prefix):**
- `input_boolean.hrds_automatic_enabled` — master enable.
- `input_number.hrds_power_demand` (W) — the unit's draw while running; keeps the PV gate invariant.
- `input_number.hrds_off_dew_diff` (°C) — stop hysteresis.
- `input_number.hrds_min_runtime` (min) — must clearly exceed the 6.5–8 min to compressor start.
- `timer.hrds_min_runtime`.
- `input_boolean.hrds_run_open` — internal: marks a run between its start and end notification, so
  a hot-water restart is not a new run. Not on the dashboard's settings card.

**Sensors:**
- `sensor.hrds_pv_surplus` (W) — `victron_pv_net_power` **plus** `hrds_power_demand` while
  `compressor_status` is on, clamped at 0 (same pattern as `sensor.heating_pv_surplus`).
- `binary_sensor.hrds_pv_surplus_available` — `hrds_pv_surplus ≥ hrds_power_demand` **and**
  `energy_pv_battery_ok` on; delay_on/off 5 min. Availability-guarded.
- `binary_sensor.hrds_indoor_above_max` — trigger-based Schmitt: on at
  `airflow_min_indoor_dew_5min ≥ airflow_dew_point_max`, off at `≤ max − hrds_off_dew_diff`.
- `binary_sensor.hrds_indoor_above_target` — same on `airflow_dew_point_target`.
- `binary_sensor.hrds_paused_for_hot_water` — state-based: `heating_dhw_running` on, or no value and
  `heating_compressor_active` on.
- `binary_sensor.hrds_dehumidify_wanted` — state-based, the run's reasons without hot water:
  ```
  window   = airflow_boost_window_active                        # 10
  season   = heating_cooling_indicator != active_heating        # 16
  urgent   = hrds_indoor_above_max                              # beats a pending boost
  opportun = hrds_indoor_above_target and hrds_pv_surplus_available
             and not airflow_humidity_drying_needed             # 14
  wanted   = window and season and (urgent or opportun)
  ```
- `binary_sensor.hrds_dehumidify_needed` — state-based: `wanted and not hrds_paused_for_hot_water`.
- `binary_sensor.hrds_dehumidify_active` — state-based, what airflow keys on: `switch.dehumidify` on
  **or** `recirculation_active` on (also a dehumidify started by hand — *confirmed*). Unknown → off.
- `sensor.hrds_state` — `off` / `outside_window` / `idle` / `dehumidify_max` / `dehumidify_pv` /
  `min_runtime` / `paused_hot_water` / `blocked`.

**Automation `hrds_dehumidify_controller`** (`mode: queued`, gated by `hrds_automatic_enabled`
except for the end notification when it is turned off; triggers: `needed`, `wanted`,
`paused_for_hot_water`, `timer.finished`, `hrds_automatic_enabled`, HA start):
- **Hot-water pause** (first): paused and `switch.dehumidify` on → `switch.dehumidify` off at once,
  cancel the timer. Silent.
- **Start:** needed and `switch.dehumidify` off → `switch.unit_on_off` on if off;
  `switch.dehumidify` on; start the timer; if `hrds_run_open` off → set it, send the start
  notification. A refused write (`continue_on_error`): state `blocked`, end the run ("refused").
- **Stop:** not needed, not paused, `switch.dehumidify` on, timer idle → `switch.dehumidify` off;
  end the run.
- **Run ends while paused:** `wanted` off while paused (window closed, humidity reached) → end the
  run.
- **End the run** = if `hrds_run_open` on: clear it, send the end notification with reason and
  duration. Also when `hrds_automatic_enabled` is turned off during a run (dehumidify off first).
- Writes only on a state difference; never `switch.integration_request`.

### Dashboard — `dashboards/hrds-dashboard.yaml` (NEW, Decision 22)

Registered in `configuration.yaml` under `lovelace: dashboards:` as `hrds-dehumidifier`
(`mode: yaml`, title "Dehumidifier", icon `mdi:air-humidifier`, in the sidebar). Same style as
`dashboards/airflow-dashboard.yaml`. One view, cards:

1. **Unit** — `climate.hrds_climate` (thermostat card).
2. **Automation** — `sensor.hrds_state`, `input_boolean.hrds_automatic_enabled`,
   `binary_sensor.hrds_dehumidify_needed`, `_active`, the reasons (`hrds_indoor_above_max`,
   `_above_target`, `hrds_pv_surplus_available`), `airflow_boost_window_active`,
   `hrds_paused_for_hot_water`, `timer.hrds_min_runtime`.
3. **What the unit does** — unit status, `switch.dehumidify`, dehumidify request, compressor status
   and output, fan running / status / output, fan airflow, recirculation active, damper, water
   valve/pump, water temperature, evaporator temperature, season.
4. **Can it run** — operation allowed, brine temperature guard, setup check, water check, alarm
   active (with the individual alarms as a conditional section when any is on).
5. **Ventilation during a run** — `sensor.airflow_cooling_state`, Comfo supply volume, preset,
   profile, `binary_sensor.airflow_intake_drier`, bypass gauge (`sensor.airflow_bypass_estimation`).
6. **Moisture** — history graph (24 h): indoor dew vs `airflow_dew_point_target` / `_max`, intake
   dew; indoor RH.
7. **Solar** — `sensor.hrds_pv_surplus`, `sensor.victron_pv_net_power`, battery SoC,
   `binary_sensor.energy_pv_battery_ok`.
8. **Settings** — `hrds_power_demand`, `hrds_off_dew_diff`, `hrds_min_runtime`,
   `energy_pv_min_battery_soc`, the two boost schedules, `airflow_target_humidity` / `_max`.
9. **Logbook** (24 h) — `hrds_dehumidify_active`, `switch.dehumidify`, `sensor.hrds_state`.

### Sequence of one run (expected)

1. Window open, indoor above max, outdoor humid → airflow is in moisture-protect (LOW, warm).
2. `needed` on → `switch.dehumidify` on → start notification → `hrds_dehumidify_active` on.
3. Airflow (silent): auto off, preset **medium** → total ≈300 once the fan runs; profile **warm**.
   The Q350 supply dips for about a minute when the HRDS fan starts (T18).
4. Compressor 6.5–8 min after the request; the run lasts at least `hrds_min_runtime`.
5. Indoor dew below `max − hrds_off_dew_diff` (or window closed) → stop once the timer is idle → end
   notification → `hrds_dehumidify_active` off after the run-on (≈1–2 min) → airflow re-derives its
   normal state silently (LOW + warm here).

Hot-water interruption during step 4: dehumidify off at once, airflow back to normal (silent),
charge ends → dehumidify on again, no new notification, fresh minimum runtime.

---

## Interaction analysis

Structurally safe: no shared actuator; no sensor cycle; `dew_min < dew_target` keeps "dry" and
"retain moisture" apart.

| # | Issue | Resolution |
|---|-------|------------|
| I1 | Heating-season cross-purpose | No HRDS in `active_heating` (16) |
| I2 | Free-cooling overlap | Both run (19); hold at medium, bypass open on dry intake |
| I3 | Shared hysteresis knob | `hrds_off_dew_diff` |
| I4–I6 | Fan writes | Obsolete: no fan writes |
| I7 | Two controllers on one indoor-dew sensor | Schmitt bands, `hrds_min_runtime`, 10-min airflow delays; `airflow_intake_drier` has its own 10-min delay |
| I8 | Boost cancel on hand-over | Boost start/re-arm gated on `hrds_dehumidify_active` off; HRDS branch precedes the boost-owner branch (14) |
| I9 | Heat protection overridden | Accepted (300 m³/h requirement); bounded to window and run |
| I10 | PV self-cancel | `hrds_pv_surplus` adds the HRDS draw back while it runs |
| I11 | PV double booking with `heating_pv_boost` | Deferred: [`todo.md`](todo.md) |
| I12 | Stale restore | `wanted`, `needed`, `active`, `paused_for_hot_water` are state-based |
| I13 | Window ends mid-run | Run finishes `hrds_min_runtime`, then stops |
| I14 | Moisture outside the window | Confirmed (10); airflow flush/low act |
| I15 | Bypass vs the Q350's own logic | `cool` permits, does not force; observe with the bypass estimate |
| I16 | Hot-water pause cycles the HRDS | Accepted (17); silent (21) |
| I17 | ebusd offline | Shelly fallback (17) |
| I18 | Notification suppression hides an airflow change | Only within a run and 3 min after; the airflow state is on the dashboard and in `airflow_cooling_state` |

---

## Files

- **New:** `packages/hrds_dehumidifier.yaml`; `packages/notes/hrds_dehumidifier.md` (hardware facts:
  fixed 150 m³/h recirculation, no fan control, start delay, stop timing); index row in
  `packages/CLAUDE.md`.
- **New:** `dashboards/hrds-dashboard.yaml`; **edit** `configuration.yaml` (dashboard registration).
- **Edit:** `packages/airflow_cooling.yaml` (above); `packages/notes/airflow_cooling.md` — the
  dehumidify owner rule and the quiet hand-back.
- **Edit:** `packages/energy.yaml`, `packages/notes/energy.md` ("one battery floor for every
  PV-surplus load; consumers read `energy_pv_battery_ok`"), the `energy.yaml` row in
  `packages/CLAUDE.md`.
- **Edit:** `packages/heating_pv_boost.yaml` (above), one line in `packages/notes/heating_pv_boost.md`,
  `dashboards/heating-dashboard.yaml` (new floor helper).
- **Edit:** `tests/conftest.py` (seeds: new helpers, HRDS stubs, `energy_pv_min_battery_soc`),
  `tests/test_airflow.py`, `tests/test_heating_pv_boost.py`; **new** `tests/test_hrds.py`.
- **Keep current:** `doc/design/hrds_dehumidifier.md` — set its status to implemented at the end.
- Not touched: `packages/victron.yaml`, `dashboards/airflow-dashboard.yaml` (no renames).

## Pre-implementation checks (live system, read-only)

1. **Entity ids:** the live ids of the HRDS entities (device prefix) and the Comfo ids used above.
2. **Q350 medium ≈ 150 m³/h:** `sensor.comfoconnect_pro_supply_fan_volume` at preset medium. If it
   differs, adjust the medium setpoint on the Q350.
3. **Write path open:** `switch.operation_allowed` on, PH28 enable on, season summer, brine guard
   configured and passing.
4. **HRDS draw:** confirm or measure the 500 W starting value.
5. **Bypass response:** does `sensor.airflow_bypass_estimation` follow `warm` vs `cool` during a run?
6. **Hot-water signal:** across one charge, `geotherm_heating_hvac_action` reads `water` and
   `geotherm_heating_hwc_active` turns on and off with the charge (not "hot water enabled").

## Deploy

By hand (Decision 23). The step-by-step instructions are in the PR description. The only carried
value is the battery floor (`heating_pv_min_battery_soc` → `energy_pv_min_battery_soc`); the new
`hrds_*` helpers get the starting values above; `hrds_automatic_enabled` stays off until the
checks pass.

## Verification

1. **`tests/test_hrds.py`:**
   - not wanted outside the window even above max; wanted inside the window above max regardless of
     PV and `drying_needed`;
   - above target: wanted only with PV surplus, also with free cooling on; not with `drying_needed`,
     not in `active_heating`;
   - Schmitt: stays on between trigger and `trigger − hrds_off_dew_diff`;
   - min runtime: need clears with the timer active → no stop until `timer.finished`;
   - PV add-back; battery floor through `energy_pv_battery_ok`;
   - `hrds_dehumidify_active` on from `switch.dehumidify` or `recirculation_active`, off on unknown;
   - hot water: off at once even with the timer active; back on afterwards while still wanted; no
     restart once the window closed; unknown + compressor on → paused, compressor off → not;
   - notifications: exactly one start and one end per run, also across a hot-water pause; end
     reasons (humidity reached, window closed, automatic off, refused).
2. **`tests/test_airflow.py`:**
   - `airflow_boost_window_active` matches the old `in_schedule`; `drying_needed` unchanged;
   - active on → auto off + medium from each prior state (auto, low, boost running → cancelled,
     heat_low, moisture_low); Away → preset untouched;
   - profile `warm` when intake wetter, `cool` when drier; Blocks 1–5 not run while active;
   - boost does not start or re-arm while active; starts on active → off with `drying_needed` on;
   - active → off restores the normal state; no airflow notification while active and for 3 min;
   - all existing airflow tests pass (regression gate).
3. **`tests/test_heating_pv_boost.py`:** `heating_dhw_active` keeps its 25-min tail;
   `heating_dhw_running` has none; slab mode blocked below the floor, allowed at it.
4. **Template check** in Developer Tools for each new sensor; the dashboard renders.
5. **Dry run on the device** (user): with `hrds_automatic_enabled` on, inside the window watch the
   HRDS dashboard: `sensor.hrds_state`, preset/profile, Comfo volume + HRDS fan airflow (≈150 + 150),
   compressor status, bypass estimate, the two notifications.

## Out of scope (this iteration)

- HRDS active cooling (`switch.integration_request`, INT).
- Changing the HRDS fan band `PF28`.
- Dehumidify outside the boost window; winter dehumidify.
- PV priority between loads; the shared `climate_*` refactor ([`todo.md`](todo.md)).
