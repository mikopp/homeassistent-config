# HRDS Dehumidifier + Airflow Coordination — Implementation Plan

> Status: **PLAN ONLY — do not implement yet** (CLAUDE.MD rules 2–3). Revision 4 (2026-10-26).
> **Stacked on PR #131** (`claude/friendly-meitner-m9kv9h`, airflow single decision): PR #89's base
> is that branch, and #131 merges and deploys first.
> The agreed design is described for owner and agents in
> [`doc/design/hrds_dehumidifier.md`](../doc/design/hrds_dehumidifier.md); this file holds the
> work steps, decision history, risks, deploy and tests.

## Status

| Step | State |
|------|-------|
| 0. Plan (this file) and design doc | done; rev 4b on #131 — all decisions confirmed; next: step 1 |
| 0c. PR #131 merged and deployed (prerequisite) | open |
| 1. Pre-implementation checks on the live system — hand-off block below, answered in its Results table | open |
| 2. `airflow_cooling.yaml`: shared boost-window sensor (regression gate: airflow tests) | open |
| 2b. Shared battery floor in `energy.yaml`, heating repointed (regression gate: heating tests) | open |
| 3. Airflow: HRDS layer in `custom_templates/airflow_decision.jinja`, `base_state` attribute, controller dehumidify branch + Away lift, quiet hand-back | open |
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
- **Rev 3b** (2026-10-25): HRDS in Away — no boost window, runs on PV or alongside an airflow
  flush (24); the package never switches the unit, runs only while it is on, own enable switch
  (15 revised); Away keeps the ventilation level (12 confirmed).
- **Rev 3c** (2026-10-25): the Away level is too little air for the coil — during a run the Q350
  goes to medium in Away too, by lifting Away for the run (25; supersedes 12).
- **Rev 3d** (2026-10-25): the Q350 treats Away as a preset; the lift stays explicit; Away is a
  manual action (HA or ComfoConnect) — Away set during a run is lifted again (25); above max is not
  an Away reason (24 confirmed).
- **Rev 3e** (2026-10-25): Decision 14 and the starting values confirmed; plan complete.
- **Rev 3f** (2026-10-26): the Q350 hold is stated as its goal — medium airflow plus the profile
  (warm or cool, by airflow state) that brings in the least moisture (13); the intake sensor is
  `airflow_intake_dry_enough` and also respects the max-humidity dew point.
- **Rev 4** (2026-10-26): stacked on PR #131 (26). The hold is an HRDS layer in the airflow
  decision (`airflow_decision.jinja`): state `hrds_dehumidify`, profile by the moisture test,
  ventilation `dehumidify`; new attribute `base_state` (the decision without the HRDS) is what the
  HRDS reads instead of the airflow indicators. The boost hand-over follows the decision.
- **Rev 4b** (2026-10-26): Decision 27 answered — the HRDS also runs with the airflow automation
  off, and the hold (medium, moisture profile, Away lift) still applies; after such a run the Q350
  goes back to its state from before the run.

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
Q350 is held where it helps the run: medium airflow for the coil and the profile (warm or cool, by
airflow state) that brings in the least moisture.

## How the packages divide the work

| Owner | Writes | Reads from the others |
|-------|--------|-----------------------|
| `hrds_dehumidifier.yaml` | `switch.dehumidify` — nothing else | `sensor.airflow_cooling_state` attribute `base_state` (pending boost, flush), `binary_sensor.airflow_boost_window_active`, `binary_sensor.airflow_away_active`, the airflow dew sensors, `sensor.heating_cooling_indicator`, `binary_sensor.heating_dhw_running`, `binary_sensor.heating_compressor_active`, `binary_sensor.energy_pv_battery_ok` |
| `airflow_cooling.yaml` (decision `sensor.airflow_cooling_state` via `custom_templates/airflow_decision.jinja`; `airflow_ventilation_controller`, `airflow_humidity_drying_boost`) | every Comfo output: profile, preset, auto_mode, boost, away (lift) | the decision reads `binary_sensor.hrds_dehumidify_active` and `input_boolean.hrds_automatic_enabled` |

No entity is written by both. Following #131's rule, the HRDS is folded into the **decision**, not
wired into the automations: the decision reads `hrds_dehumidify_active` (an input, like the season)
and the controller and boost automation only apply the decision. No cycle: the HRDS reads only
`base_state`, the decision **without** the HRDS layer, which never depends on any HRDS entity. The
HRDS is a new dependency of the airflow package (Decision 20).

## Airflow states vs the HRDS

Airflow decision (#131 states of `sensor.airflow_cooling_state`, here as `base_state`):

| Airflow decision (`base_state`) | HRDS behaviour | Comfo while HRDS dehumidifies (state `hrds_dehumidify`) |
|---|---|---|
| **`free_cooling`** | Not a gate (19) | medium; **`cool`** (bypass may open) — intake is dry enough |
| **`moisture_flush_cooling`** (flush) | Not a gate at home; an Away reason (24) | medium; **`cool`** — flush implies intake clearly drier than indoor |
| **`moisture_flush_boost`** (drying boost) | Below max: HRDS yields — the boost is free. Above max: HRDS runs; the decision leaves `boost`, so the boost automation stops the boost, and restarts it when the run ends | medium; **`cool`** (a boost implies a flush) |
| **`moisture_protection`** (low) | The main case: indoor humid, outdoor too humid to flush | **medium instead of low**; **`warm`** (bypass closed) — enthalpy recovery keeps intake moisture out |
| **`heat_protection`** (low) | Runs if needed | medium instead of low (accepted, I9); **`cool` or `warm` by the moisture test** — heat protection says nothing about moisture, the Q350 itself opens the bypass only if that cools |
| **`comfort`** | Runs if needed | medium; **`cool` or `warm` by the moisture test** |
| **`heating`**, **`moisture_retention`** | Does not run (active heating 16; dry indoor is below target) | — |
| **`off`** (airflow automation disabled) | Runs (27). No airflow decision, so no pending boost and no flush: at home above max or on PV, in Away on PV | medium and moisture profile as usual (the hold follows the HRDS automation, 27); after the run the Q350 returns to its state from before the run |
| **Away** | No boost window; runs above target on free PV or alongside a flush (24) | **medium** — Away is lifted for the run and restored after it (25); bypass rule applies; no boost (the boost never runs in Away) |

---

## Decisions

From revision 1, still valid: **1** PV gate (now built in the HRDS package), **2** no extra
outdoor-humidity guard on Comfo flush/boost (the dew gates already block it), **6** dehumidify also
during Away (refined by 24), **7** opportunistic branch off in `active_heating` (tightened by 16), **9** HRDS has its
own `hrds_off_dew_diff`.

Dropped: **3** fan top-up and **5** combined-airflow targets (fan not controllable), **4** shared
`climate_*` package (superseded by 20), **8** free cooling beats the opportunistic branch (superseded
by 19).

10. **Dehumidify only in the boost window** — *confirmed*. Both reasons require
    `binary_sensor.airflow_boost_window_active`. Outside the window the HRDS is off even above max;
    `airflow_cooling.yaml`'s flush/low logic handles moisture then. A run still inside its minimum
    runtime when the window closes finishes that runtime. Not in Away: there the window is ignored
    (24).
11. **Airflow stands down while dehumidifying.** While `hrds_dehumidify_active` is on, the airflow
    **decision** is `hrds_dehumidify` (ventilation `dehumidify`, profile by 13): the controller holds
    `auto_mode off, preset medium`, no boost is decided and no low is written; the normal decision
    returns when it clears (26).
12. ~~Away keeps priority over the ventilation level~~ — superseded by 25: the Away level gives
    the coil far less than 300 m³/h.
13. **Hold the Q350 so it helps dehumidify: medium airflow and the profile that brings in the least
    moisture** — *confirmed*. The preset is fixed (medium, for the coil); the profile depends on the
    airflow state and is `warm` (bypass closed, full enthalpy recovery) or `cool` (bypass may open):
    - flush / free cooling / boost → `cool`: the intake is clearly drier than indoor;
    - moisture protection (low) → `warm`: the intake is too humid to import;
    - any other state (heat protection, none) → by the same moisture test.
    One test covers all rows (`binary_sensor.airflow_intake_dry_enough`, below): `cool` when the
    intake dew point is at least `airflow_min_dew_diff` below indoor **and** below the max-humidity
    dew point, else `warm`. Moisture alone decides during a run; the temperature side is left to the
    Q350, which opens the bypass only when that also suits (I15).
14. **Boost vs HRDS (at home)** — *confirmed*. Below max a pending drying boost wins (the HRDS reason
    is gated off by `base_state == moisture_flush_boost`); above max the HRDS wins and the boost is
    suspended. With #131 the hand-over is the decision itself: during a run the decision is not
    `boost`, so the boost automation stops a decided boost; when the run ends the decision returns
    to `boost` and the automation starts it again. When the airflow package does **not** intend a
    boost, the HRDS runs on its own conditions (above max, or above target with free PV) — the
    boost only ever takes precedence while it is actually intended.
15. **The package never switches the unit on or off** — *confirmed*. Whether the HRDS is on is the
    owner's choice (`switch.unit_on_off`). The automation acts only while the unit is on
    (`sensor.unit_status` = on) **and** its own enable switch `input_boolean.hrds_automatic_enabled`
    is on, like every other automation in this repo. Unit off means the automation is off: no
    request, `sensor.hrds_state` = `unit_off`. If the unit is switched off during a run, the
    automation clears its own dehumidify request (so the unit does not start on a stale request when
    it is switched on again) and ends the run. ON-standby keeps the hourly anti-stagnation pulses
    (T13).
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
    `input_number.airflow_*_humidity`) — numeric thresholds, not decision indicators — and the
    airflow decision's `base_state` (26). Only the **boost window** is shared as a new sensor:
    `binary_sensor.airflow_boost_window_active` in `airflow_cooling.yaml`, extracted from the inline
    `in_schedule` expression of `airflow_humidity_drying_needed`, which then consumes it. No renames,
    no migration. A neutral shared package is a future refactor ([`todo.md`](todo.md)).
21. **Notifications: only start and end of a run** — *confirmed*.
    - HRDS: one notification when a run starts (reason: above max / PV, indoor RH and dew) and one
      when it ends (reason: humidity reached / window closed / automatic control off / refused,
      duration). A hot-water pause and resume inside a run are silent. A refused request ends the
      run with reason "refused"; `sensor.hrds_state` shows `blocked`.
    - Airflow: silent while it holds for the HRDS and while it hands back. The controller's and the
      boost automation's notifications are skipped while the decision is `hrds_dehumidify` and for
      3 minutes after `hrds_dehumidify_active` clears (covers the hand-back, the route-to-auto re-run
      and a boost stopped and restarted around the run).
22. **HRDS dashboard** — *confirmed*: a new `dashboards/hrds-dashboard.yaml` with the integration's
    essentials plus this package's entities (content below).
23. **Deploy by hand, no `ha_mcp` writes** — *confirmed*. With Decision 20 there are no entity
    renames; the only value to carry over is the battery floor. Deploy instructions go in the PR
    description.
24. **HRDS in Away** — *confirmed*. While `switch.comfoconnect_pro_away_function` is on nobody is
    home, so noise does not matter:
    - the **boost window is ignored**;
    - the HRDS runs when indoor is above target **and** either free PV is available **or** the
      airflow package wants to flush moisture (`base_state` `moisture_flush_cooling` or
      `moisture_flush_boost`: outdoor air drier than indoor). In the flush case the HRDS **doubles down**: the ventilation
      flushes dry air at **medium** (25), the HRDS dries the recirculated air, and the bypass rule
      lets the bypass open (a flush means the intake is dry enough);
    - a pending drying boost does not make the HRDS yield (Decision 14 is a home-mode rule);
    - season, hot-water pause, unit-on and the enable switch apply as at home.
    - **Above max is not an Away reason** — *confirmed*: in Away with neither PV nor a flush
      (outdoor humid) the HRDS does not run.
25. **Medium during a run, also in Away** — *confirmed requirement* (the HRDS needs 300 m³/h:
    150 recirculation + 150 from the Q350). Away otherwise keeps its level; only a run lifts it.
    Mechanism (the airflow controller does it: it is the only writer of Q350 outputs; Away is a
    controller guard in #131, not a decision input, so the lift stays in the controller):
    - **Run starts in Away:** set `input_boolean.airflow_away_lifted` (airflow package), turn
      `switch.comfoconnect_pro_away_function` **off**; the HRDS owner branch then holds medium as at
      home.
    - **Run ends** (`hrds_dehumidify_active` off) with the latch on: turn the away function **on**
      again, clear the latch. The Q350 is back at its Away level.
    - **"The house is Away"** for every rule = `binary_sensor.airflow_away_active` (airflow package,
      state-based): away function on **or** latch on. The HRDS Away rules (24), the boost gate and
      the airflow Away guards read it, so lifting Away for a run does not make the house look
      occupied (no boost window, no boost, no Section 2 normal logic after the run).
    - **Coming home during a run:** turning the away function off is not visible while it is lifted.
      The latch is shown on the HRDS dashboard as "Away (lifted for dehumidify)"; switching it off
      ends Away — the run continues under the home rules and Away is not restored afterwards.
    - **Explicit, although the Q350 would do it anyway** (owner): the Q350 treats Away as one of its
      levels (away / low / medium / high / boost), so writing preset medium alone would already leave
      Away. The controller still turns the away function off first, then writes medium, so the lift
      is a visible step with its latch rather than a side effect of the preset write.
    - **Away is a manual action**, from Home Assistant or directly from the ComfoConnect app; no
      automation sets it. **Away switched on during a run** (from either side): the house has just
      gone Away, so the controller sets the latch and lifts it again at once — the run keeps its
      air — and restores Away when the run ends.
    - Coming home from the **ComfoConnect app** during a run: the latch is not visible there, so
      Away comes back when the run ends; switch it off again. From Home Assistant: switch the latch
      off (above).

26. **Built on PR #131's single decision** — *confirmed* ("we build on top of 131"). PR #89 is
    stacked on #131. The HRDS hold is not a set of controller branches but a **layer of the
    decision** in `custom_templates/airflow_decision.jinja`:
    - the macro first computes the normal decision exactly as #131 does (`base_state`), then, if
      `binary_sensor.hrds_dehumidify_active` is on: state `hrds_dehumidify`, profile `cool` if
      `binary_sensor.airflow_intake_dry_enough` is on else `warm` (13), ventilation `dehumidify`;
    - it returns a fourth field, exposed as attribute `base_state`; HRDS rules read it instead of
      `drying_needed` / `flush_needed` (#131: never wire an indicator into a consumer);
    - the decision still never reads an output; the HRDS inputs are read fail-safe (`is_state`, an
      unknown HRDS = not running, unknown moisture test = `warm`) and are **not** added to the
      decision's availability, so an HRDS outage never stops the airflow automation.
27. **The HRDS does not need the airflow automation; the hold still applies** — *confirmed*. The
    HRDS runs whether `input_boolean.airflow_cooling_automatic_enabled` is on or off. With the
    airflow automation off, the HRDS run still gets the same hold as with it on (medium, the
    moisture profile, the Away lift). How:
    - **The hold belongs to the HRDS, the writes stay with the airflow controller.** The HRDS layer
      of the decision applies while **either** automation is enabled (airflow or HRDS); only with
      both off does nothing touch the Q350. So the airflow controller remains the only writer of
      Q350 outputs, and there is never a second writer to fight it when the airflow automation is
      switched back on.
    - With the airflow automation off and no run, the decision is `off` as in #131 and the
      controller's existing branches do nothing (none matches `off`).
    - **Restore after a run without the airflow automation.** At run start, if the airflow
      automation is off, the controller snapshots preset, auto_mode and profile
      (`scene.create` → `scene.airflow_before_hrds`, latch `input_boolean.airflow_hrds_snapshot`)
      before its first write. At run end, if the airflow automation is still off, it restores the
      snapshot (Away is restored by its own latch, 25) and clears the latch. If the snapshot is gone
      (Home Assistant restarted during the run) or the run started under the airflow automation,
      it hands the Q350 back to its own schedule (`auto_mode` on). If the airflow automation was
      switched on during the run, the snapshot is dropped and the normal decision applies.
    - With the airflow automation off there is no airflow decision, so `base_state` is `off`: no
      pending boost (none would run) and no flush, so in Away the HRDS runs on PV only.

Deferred to [`todo.md`](todo.md): **PV priority between loads** (the heating PV boost and the HRDS
can see the same surplus at once; I11).

**Starting values** — *confirmed* (set by hand on deploy): `hrds_power_demand` 500 W,
`hrds_min_runtime` 45 min, `hrds_off_dew_diff` 0.5 °C.

---

## Design

All `CLAUDE.MD` template/helper rules apply: availability guards, no `initial:`, no
`| float(default)` behind a guard or on helpers, a comment on every block.
`packages/notes/airflow_cooling.md` rules apply to the airflow edits (indicators feed only the
decision, consumers read only the decision; minimal, surgical controller edits; derived-from-binaries
sensors are state-based). Line numbers and names below refer to PR #131's version of the package.

### Airflow changes — `packages/airflow_cooling.yaml` (EDIT, surgical)

1. **Shared boost window `binary_sensor.airflow_boost_window_active`** (state-based): workday +
   `schedule.airflow_boost_workday` or non-workday + `schedule.airflow_boost_non_workday`.
   `airflow_humidity_drying_needed` reads it instead of its inline `in_schedule` block; its
   workday/schedule triggers are replaced by one trigger on the new sensor. Behaviour unchanged.
2. **New decision sensor `binary_sensor.airflow_intake_dry_enough`** (trigger-based, numeric inputs,
   `this.state` Schmitt + 10-min delay like the flush sensor): ON when
   `airflow_outdoor_dew_5min + airflow_min_dew_diff < airflow_min_indoor_dew_5min` **and**
   `airflow_outdoor_dew_5min < airflow_dew_point_max`, released with the same 0.3 °C hysteresis.
   These are the limits the flush sensor (Branch 1) and the moisture-protection sensor already use,
   so the sensor agrees with them: flush, free cooling and boost imply it, moisture protection
   (low) implies its opposite, and the remaining states are decided by it alone. The Q350
   **intake** dew (after the ground duct) is the air that enters. An enthalpy exchanger moves
   moisture from the wetter to the drier stream: dry enough → `cool` (bypass may open, the
   exchanger does not hand indoor moisture back); not → `warm` (bypass closed, the exchanger moves
   the intake moisture into the exhaust).
3. **Decision macro `custom_templates/airflow_decision.jinja` — HRDS layer (26).** After #131's
   state/profile/ventilation are computed (unchanged), keep them as `base_state`; then, when
   `is_state('binary_sensor.hrds_dehumidify_active', 'on')` and **either** automation is on
   (`airflow_cooling_automatic_enabled` or `hrds_automatic_enabled`, 27): state `hrds_dehumidify`,
   profile `cool` if `is_state('binary_sensor.airflow_intake_dry_enough', 'on')` else `warm`,
   ventilation `dehumidify`. Return `"<state>|<profile>|<ventilation>|<base_state>"`. With the
   airflow automation off, `base_state` is `off`; with both off everything is `off` (as in #131). Update the macro's header comment (inputs, return value, the HRDS layer).
4. **`sensor.airflow_cooling_state`:** new attribute `base_state` (field 4, same macro render as the
   other fields); icon `mdi:water-off` for `hrds_dehumidify`; availability unchanged (26).
5. **Controller Section 1:** unchanged — it already writes the decided `profile`, which is now the
   moisture profile during a run. Its notification is wrapped in `if: not quiet` (7).
6. **Controller condition:** runs while the airflow automation **or** the HRDS automation is on
   (27; before: airflow only). With only the HRDS automation on, every existing branch is inert
   (the decision is `off` outside a run), so the controller then acts only for the HRDS blocks below.
   The boost automation keeps its airflow-only condition.
   **Controller Section 2:** a new block **before** the Away guard:
   - **Dehumidify:** `ventilation == 'dehumidify'` and `switch.comfoconnect_pro_boost` off → if the
     away function is on: set `input_boolean.airflow_away_lifted`, away function off (25); then
     `auto_mode off`, preset `medium`, unless already (auto off, medium). No notification. A
     manual boost (switch on) is left alone: it gives more air than medium.
   - **Snapshot** (first step of a run, only with the airflow automation off): `scene.create`
     `airflow_before_hrds` from preset, auto_mode and profile; set
     `input_boolean.airflow_hrds_snapshot` (27).
   - **Away restore:** `ventilation != 'dehumidify'` and the latch on → away function on, clear the
     latch.
   - **Hold restore** (27): `ventilation != 'dehumidify'`, the snapshot latch on → if the airflow
     automation is off: `scene.turn_on` the snapshot (fallback `auto_mode` on when the scene is
     gone); clear the latch. Also when the run started under the airflow automation and that was
     switched off during the run (no snapshot): `auto_mode` on, so the Q350 does not stay at manual
     medium.
   The existing Away guard (and so the existing branches) reads `binary_sensor.airflow_away_active`
   instead of the away switch. The existing branches need no HRDS gate: none of them matches
   `ventilation == 'dehumidify'`. New trigger: away function → `on` (Away set by hand during a run is
   lifted again, 25); the decision trigger already covers the HRDS starting and stopping and the
   moisture test changing.
7. **Quiet hand-back (21):** a controller variable `quiet` = decision `hrds_dehumidify`, or
   `hrds_dehumidify_active` changed less than 3 min ago; every existing `notify` step is wrapped in
   `if: not quiet`. Same variable and wrapping in the boost automation.
8. **Boost automation `airflow_humidity_drying_boost`:** no HRDS gate — the decision leaves `boost`
   during a run (stop) and returns after it (start). Its Away condition reads
   `binary_sensor.airflow_away_active`, so no boost while Away is lifted. Notifications quiet (7).
9. **New `binary_sensor.airflow_away_active`** (state-based): away function on or
   `input_boolean.airflow_away_lifted` on. New helpers `input_boolean.airflow_away_lifted` and
   `input_boolean.airflow_hrds_snapshot` (internal). The controller triggers gain
   `input_boolean.airflow_cooling_automatic_enabled` and `input_boolean.hrds_automatic_enabled`.
10. **Climate `hvac_action_template`:** `hrds_dehumidify` → `drying`.
11. **Notes `packages/notes/airflow_cooling.md`:** the HRDS layer rule (the decision folds the HRDS
    in; consumers still read only the decision; the HRDS reads only `base_state`), the Away lift,
    the quiet hand-back.

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
`sensor.operating_mode`, `sensor.unit_status`. The package never writes `switch.unit_on_off` (15).

**Helpers (`hrds_` prefix):**
- `input_boolean.hrds_automatic_enabled` — the automation's own enable switch (repo convention).
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
  unit_on  = unit_status == on                                  # 15
  season   = heating_cooling_indicator != active_heating        # 16
  away     = airflow_away_active == on                          # 24, 25 (survives the lift)
  # home: inside the boost window
  base     = state_attr(airflow_cooling_state, 'base_state')    # 26 ('off' with the airflow automation off, 27)
  boost_pending = base == moisture_flush_boost
  flushing      = base in [moisture_flush_boost, moisture_flush_cooling]
  home     = airflow_boost_window_active                        # 10
             and (hrds_indoor_above_max                         # beats a pending boost
                  or (hrds_indoor_above_target and hrds_pv_surplus_available
                      and not boost_pending))                   # 14
  # away: no window; PV or double down on an airflow flush
  away_run = hrds_indoor_above_target
             and (hrds_pv_surplus_available or flushing)        # 24
  wanted   = unit_on and season
             and ((not away and home) or (away and away_run))
  # an unavailable decision has no base_state: no pending boost, no flush
  ```
- `binary_sensor.hrds_dehumidify_needed` — state-based: `wanted and not hrds_paused_for_hot_water`.
- `binary_sensor.hrds_dehumidify_active` — state-based, what airflow keys on: `switch.dehumidify` on
  **or** `recirculation_active` on (also a dehumidify started by hand — *confirmed*). Unknown → off.
- `sensor.hrds_state` — `off` (automation disabled) / `unit_off` / `outside_window` / `idle` /
  `dehumidify_max` / `dehumidify_pv` / `dehumidify_away_pv` / `dehumidify_away_flush` /
  `min_runtime` / `paused_hot_water` / `blocked`.

**Automation `hrds_dehumidify_controller`** (`mode: queued`; acts only while
`hrds_automatic_enabled` is on and the unit is on, except for ending a run when either turns off;
triggers: `needed`, `wanted`, `paused_for_hot_water`, `timer.finished`, `hrds_automatic_enabled`,
`sensor.unit_status`, Away, HA start):
- **Hot-water pause** (first): paused and `switch.dehumidify` on → `switch.dehumidify` off at once,
  cancel the timer. Silent.
- **Unit switched off during a run:** `switch.dehumidify` off (clear our request), cancel the
  timer, end the run ("unit switched off").
- **Start:** needed and `switch.dehumidify` off → `switch.dehumidify` on; start the timer; if `hrds_run_open` off → set it, send the start
  notification. A refused write (`continue_on_error`): state `blocked`, end the run ("refused").
- **Stop:** not needed, not paused, `switch.dehumidify` on, timer idle → `switch.dehumidify` off;
  end the run.
- **Run ends while paused:** `wanted` off while paused (window closed, humidity reached) → end the
  run.
- **End the run** = if `hrds_run_open` on: clear it, send the end notification with reason and
  duration. Also when `hrds_automatic_enabled` is turned off during a run (dehumidify off first).
- **Away switched on or off during a run:** no special step — `wanted` is re-evaluated with the
  other rule set; the run continues if that still wants it (same run, no new notification).
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
3. **What the unit does** — `switch.unit_on_off`, unit status, `switch.dehumidify`, dehumidify request, compressor status
   and output, fan running / status / output, fan airflow, recirculation active, damper, water
   valve/pump, water temperature, evaporator temperature, season.
4. **Can it run** — operation allowed, brine temperature guard, setup check, water check, alarm
   active (with the individual alarms as a conditional section when any is on).
5. **Ventilation during a run** — `sensor.airflow_cooling_state`, Comfo supply volume, preset,
   profile, `binary_sensor.airflow_intake_dry_enough`, bypass gauge (`sensor.airflow_bypass_estimation`).
6. **Moisture** — history graph (24 h): indoor dew vs `airflow_dew_point_target` / `_max`, intake
   dew; indoor RH.
7. **Solar** — `sensor.hrds_pv_surplus`, `sensor.victron_pv_net_power`, battery SoC,
   `binary_sensor.energy_pv_battery_ok`.
8. **Settings** — `input_boolean.airflow_away_lifted` ("Away (lifted for dehumidify)"), `hrds_power_demand`, `hrds_off_dew_diff`, `hrds_min_runtime`,
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

Away, outdoor drier than indoor: `flush_needed` on and indoor above target → HRDS runs (start
notification "away: flush") → airflow lifts Away, preset **medium**, profile `cool` (intake dry enough)
→ both dry the house until the HRDS reasons clear → run ends → Away restored (Q350 back at its
Away level). Away switched on by hand during a run: lifted again at once, restored at the end.

Hot-water interruption during step 4: dehumidify off at once, airflow back to normal (silent),
charge ends → dehumidify on again, no new notification, fresh minimum runtime.

---

## Interaction analysis

Structurally safe: no shared actuator; no sensor cycle; `dew_min < dew_target` keeps "dry" and
"retain moisture" apart.

| # | Issue | Resolution |
|---|-------|------------|
| I1 | Heating-season cross-purpose | No HRDS in `active_heating` (16) |
| I2 | Free-cooling overlap | Both run (19); hold at medium, `cool` (intake dry enough) |
| I3 | Shared hysteresis knob | `hrds_off_dew_diff` |
| I4–I6 | Fan writes | Obsolete: no fan writes |
| I7 | Two controllers on one indoor-dew sensor | Schmitt bands, `hrds_min_runtime`, 10-min airflow delays; `airflow_intake_dry_enough` has its own 10-min delay |
| I8 | Boost cancel on hand-over | The decision leaves `boost` during a run, so the boost automation stops it and restarts it after (14, 26); a manual boost is left alone |
| I9 | Heat protection overridden | Accepted (300 m³/h requirement); bounded to window and run |
| I10 | PV self-cancel | `hrds_pv_surplus` adds the HRDS draw back while it runs |
| I11 | PV double booking with `heating_pv_boost` | Deferred: [`todo.md`](todo.md) |
| I12 | Stale restore | `wanted`, `needed`, `active`, `paused_for_hot_water` are state-based |
| I13 | Window ends mid-run | Run finishes `hrds_min_runtime`, then stops |
| I14 | Moisture outside the window | Confirmed (10); airflow flush/low act |
| I15 | Bypass vs the Q350's own logic | `cool` permits, does not force: the Q350 opens the bypass only when that also cools. With dry but warm intake air the bypass stays closed and some indoor moisture is recovered. Observe with the bypass estimate |
| I23 | **The moisture test and the airflow states disagree at their edges** (hysteresis, 10-min delays) | The test uses the same limits as the states and its own 0.3 °C band and 10-min delay; a brief mismatch moves the profile for one cycle, no actuator fights (during a run the decision has one profile) |
| I24 | **HRDS feedback through the decision.** The decision reads `hrds_dehumidify_active`, and the HRDS reads the decision | No loop: the HRDS reads only `base_state`, computed before the HRDS layer (26) |
| I26 | **Airflow automation toggled during a run** | Covered by the restore rules of 27: on → normal decision afterwards; off → `auto_mode` on afterwards |
| I27 | **Snapshot lost on restart** | `scene.create` scenes do not survive a restart; fallback `auto_mode` on (the Q350's own schedule) |
| I25 | **#131 changes before it merges** | This plan follows #131's head `59cafbe`; re-check the macro, controller and boost automation when #131 changes, and before step 3 |
| I16 | Hot-water pause cycles the HRDS | Accepted (17); silent (21) |
| I17 | ebusd offline | Shelly fallback (17) |
| I19 | **Away double-down feedback.** The run lowers indoor dew, which also clears `flush_needed` | Intended: both stop together once outdoor air can no longer help; the HRDS Schmitt band and minimum runtime keep the run from flapping |
| I20 | **Unit switched off by hand mid-run** | Our request is cleared and the run ended (15); airflow re-derives normally |
| I21 | **Away lifted during a run.** The Q350 leaves its Away level; someone coming home cannot see it in the away switch | Latch on the dashboard; the start notification says Away is lifted; switching the latch off ends Away (25) |
| I22 | **Hot-water pause in Away.** The pause clears `hrds_dehumidify_active`, so Away is restored and lifted again on resume | Accepted: a few charges a day; each toggle is one write. If it matters, key the lift on `hrds_dehumidify_wanted` instead |
| I18 | Notification suppression hides an airflow change | Only within a run and 3 min after; the airflow state is on the dashboard and in `airflow_cooling_state` |

---

## Files

- **New:** `packages/hrds_dehumidifier.yaml`; `packages/notes/hrds_dehumidifier.md` (hardware facts:
  fixed 150 m³/h recirculation, no fan control, start delay, stop timing); index row in
  `packages/CLAUDE.md`.
- **New:** `dashboards/hrds-dashboard.yaml`; **edit** `configuration.yaml` (dashboard registration).
- **Edit:** `packages/airflow_cooling.yaml` and `custom_templates/airflow_decision.jinja` (above);
  `packages/notes/airflow_cooling.md` — the HRDS layer, the Away lift and the quiet hand-back.
- **Edit:** `packages/energy.yaml`, `packages/notes/energy.md` ("one battery floor for every
  PV-surplus load; consumers read `energy_pv_battery_ok`"), the `energy.yaml` row in
  `packages/CLAUDE.md`.
- **Edit:** `packages/heating_pv_boost.yaml` (above), one line in `packages/notes/heating_pv_boost.md`,
  `dashboards/heating-dashboard.yaml` (new floor helper).
- **Edit:** `tests/conftest.py` (seeds: new helpers, HRDS stubs, `energy_pv_min_battery_soc`),
  `tests/test_airflow.py`, `tests/test_heating_pv_boost.py`; **new** `tests/test_hrds.py`.
- **Keep current:** `doc/design/hrds_dehumidifier.md` — set its status to implemented at the end.
- Not touched: `packages/victron.yaml`, `dashboards/airflow-dashboard.yaml` (no renames).

## Pre-implementation checks (step 1) — hand-off for a session with Home Assistant access

This block is written so that **a different session** (or the owner) can answer it without the
earlier conversation. Nothing in it needs the plan to be read top to bottom, but the decisions it
feeds are 10–25 above.

**Who and how**
- The session that answers needs the **ha-mcp connection**, used **read-only** (`CLAUDE.MD`: entity
  lookup, states, history, statistics; never a write or a service call). Checks marked **owner
  action** need a write or a physical action and are done by the owner, who reports the result.
- Answer by filling the **Results** table below on branch `claude/hdrs-dehumidifier-airflow-iiit7c`
  (the PR #89 branch) and committing only this file. Do not implement anything (`CLAUDE.MD` rules
  2–3), do not create a PR, do not touch other files. If an entity id differs from the plan, record
  it in the table and in the **Entity map**; the implementation step then uses the map.
- When every **blocking** check has a result, set row 1 of the Status table to done and say in the
  commit message which checks are open.

**Entity map** — every entity the plan uses. For each: does it exist, what is its exact id, and (for
the state-valued ones) which state strings does it use? Record differences in the Results table
(check 1).

| Group | Ids the plan assumes | Notes |
|-------|----------------------|-------|
| HRDS (integration `innova_hrds`; live ids likely carry the device prefix, e.g. `switch.hrds_dehumidify`) | `switch.dehumidify`, `switch.unit_on_off`, `sensor.unit_status`, `binary_sensor.recirculation_active`, `binary_sensor.dehumidify_request`, `binary_sensor.brine_temperature_guard`, `switch.operation_allowed`, `switch.enable_dehumidify_bms`, `sensor.compressor_status`, `sensor.compressor_output`, `sensor.operating_mode`, `sensor.supply_fan_airflow`, `sensor.supply_fan_output`, `sensor.setup_check`, `sensor.water_check`, `binary_sensor.alarm_active`, `climate.hrds_climate` | Keys are listed in the integration repo's `doc/entity-reference.md`. State strings to record: `sensor.unit_status` (the value for "on"), `sensor.compressor_status` (the value for running), `sensor.operating_mode` (summer) |
| Comfo Q350 | `switch.comfoconnect_pro_away_function`, `switch.comfoconnect_pro_boost`, `switch.comfoconnect_pro_auto_mode`, `select.comfoconnect_pro_ventilation_preset`, `select.comfoconnect_pro_temperature_profile`, `sensor.comfoconnect_pro_supply_fan_volume` | already used by `airflow_cooling.yaml` |
| Airflow package (after #131 is deployed) | `sensor.airflow_cooling_state` (state and attributes `profile`, `ventilation`), `sensor.airflow_bypass_estimation`, `sensor.airflow_outdoor_dew_5min`, `sensor.airflow_min_indoor_dew_5min`, `sensor.airflow_dew_point_target`, `sensor.airflow_dew_point_max`, `binary_sensor.airflow_humidity_flush_needed`, `binary_sensor.airflow_humidity_drying_needed`, `binary_sensor.workday`, `schedule.airflow_boost_workday`, `schedule.airflow_boost_non_workday` | exist in the repo; confirm they are live |
| Heating | `sensor.geotherm_heating_hvac_action`, `binary_sensor.geotherm_heating_hwc_active`, `binary_sensor.heating_compressor_active`, `binary_sensor.heating_dhw_active`, `sensor.technikraum_heizung_heizung_power`, `sensor.heating_cooling_indicator` | state strings to record: `hvac_action` values seen; `heating_cooling_indicator` values (`active_heating` in particular) |
| Victron | `sensor.victron_pv_net_power`, `sensor.victron_battery_soc` | |

**Checks**

1. **Entity ids** *(blocking; read-only)*. Look up every entity in the map (entity search by name or
   device). Record the live id for each HRDS entity (device prefix) and every id that differs or is
   missing. Also record the state strings listed in the map's notes column.
2. **Q350 medium ≈ 150 m³/h** *(blocking; read-only from history, otherwise owner action)*. Read
   `sensor.comfoconnect_pro_supply_fan_volume` from history/statistics for periods where
   `select.comfoconnect_pro_ventilation_preset` was `medium` and `switch.comfoconnect_pro_boost` was
   off (a mean over at least 30 min, away function off). Record the value for medium, and also for
   `low` and, if available, `high`. **Owner action** if there is no history at medium: set preset
   medium and read the volume after a few minutes.
   Pass: 130–170 m³/h. Fail: record the value. The plan then needs the Q350 medium setpoint changed
   on the Q350 itself (not in Home Assistant) so that medium + 150 ≈ 300, or the 150 assumption
   revised; say which.
3. **Write path open** *(blocking; read-only)*. Record the current state of: `sensor.unit_status`,
   `switch.unit_on_off`, `switch.operation_allowed`, `switch.enable_dehumidify_bms` (PH28),
   `sensor.operating_mode`, `binary_sensor.brine_temperature_guard`, `sensor.setup_check` (and its
   `issues` attribute), `sensor.water_check`, `binary_sensor.alarm_active`. Pass: unit on, operation
   allowed on, PH28 on, summer, guard not blocking, setup check `ok`. For each fail, say what the
   owner has to switch or fix before the dry run. Do not change anything.
4. **HRDS draw** *(not blocking; read-only, otherwise owner action)*. Look for any power reading for
   the HRDS in Home Assistant (a smart plug or clamp on the unit; search entities for the unit's
   name, `dehumid`, `hrds`). If there is one, record the draw during a run (compressor on): peak in
   the first 10 min and the steady value after. If there is none, take the compressor output
   (`sensor.compressor_output`, steady 25–27 % in the runs of 2026-10-22/23) and the handbook
   (820 W maximum = 690 W compressor + 120 W fan) and say whether 500 W is a sound starting value.
   An owner clamp reading during the next run settles it. Result feeds `hrds_power_demand`.
5. **Bypass response** *(not blocking; owner action, can wait for the dry run)*. During an HRDS run,
   with the Q350 at medium, switch `select.comfoconnect_pro_temperature_profile` between `warm` and
   `cool` and watch `sensor.airflow_bypass_estimation` (it moves in 15 % steps, delayed by its 5-min
   filters) for 15–20 min each, at a moment when the moisture test says `cool` (otherwise there is
   no bypass to open). Record whether it follows. If it does not, Decision 13 is
   best-effort (I15); nothing else in the plan changes.
6. **Hot-water signal** *(blocking; read-only from history)*. Read the history of
   `sensor.geotherm_heating_hvac_action`, `binary_sensor.geotherm_heating_hwc_active`,
   `sensor.technikraum_heizung_heizung_power` and `binary_sensor.heating_compressor_active` for the
   last 7 days. Pass: across each hot-water charge (power about 3.5 kW) `hvac_action` is `water` and
   `hwc_active` is on, and both are off outside charges. Record: the `hvac_action` values seen, how
   often and how long the charges are (typical and longest), whether `hwc_active` is on at other
   times ("hot water enabled"), and whether the two signals agree. If `hwc_active` is on outside
   charges, `heating_dhw_running` must use `hvac_action == water` alone — say so.

**Results** *(fill in; one row per check)*

| # | Blocking | Result (pass / fail / partial) | Values and ids found | Consequence for the plan | By, date |
|---|----------|--------------------------------|----------------------|--------------------------|----------|
| 1 | yes | open | | | |
| 2 | yes | open | | | |
| 3 | yes | open | | | |
| 4 | no | open | | | |
| 5 | no | open | | | |
| 6 | yes | open | | | |

## Deploy

By hand (Decision 23). PR #131 is merged and deployed first (it needs a restart for its
`custom_templates/` file). The step-by-step instructions are in the PR description. The only carried
value is the battery floor (`heating_pv_min_battery_soc` → `energy_pv_min_battery_soc`); the new
`hrds_*` helpers get the starting values above; `hrds_automatic_enabled` stays off until the
checks pass.

## Verification

1. **`tests/test_hrds.py`:**
   - not wanted outside the window even above max; wanted inside the window above max regardless of
     PV and a pending boost;
   - above target: wanted only with PV surplus, also with free cooling on; not with a pending boost
     (`base_state` `moisture_flush_boost`),
     not in `active_heating`;
   - Schmitt: stays on between trigger and `trigger − hrds_off_dew_diff`;
   - min runtime: need clears with the timer active → no stop until `timer.finished`;
   - PV add-back; battery floor through `energy_pv_battery_ok`;
   - `hrds_dehumidify_active` on from `switch.dehumidify` or `recirculation_active`, off on unknown;
   - hot water: off at once even with the timer active; back on afterwards while still wanted; no
     restart once the window closed; unknown + compressor on → paused, compressor off → not;
   - notifications: exactly one start and one end per run, also across a hot-water pause; end
     reasons (humidity reached, window closed, automatic off, unit switched off, refused);
   - unit off → nothing happens, state `unit_off`; unit switched off mid-run → request cleared, run
     ended; the package never writes `switch.unit_on_off`;
   - Away: wanted outside the window above target with PV; with a flush `base_state` and no PV; not
     with neither; not blocked by a pending boost; Away toggled mid-run keeps the same run;
   - airflow automation off: still wanted (above max / PV), no pending boost, no Away flush (27);
     an unavailable decision means no pending boost and no flush.
2. **`tests/test_airflow.py`** (#131's decision-table style, `_seed_indicators`):
   - `airflow_boost_window_active` matches the old `in_schedule`; `drying_needed` unchanged;
   - decision table: `hrds_dehumidify_active` on → state `hrds_dehumidify`, ventilation
     `dehumidify`, profile by the moisture test, `base_state` = #131's decision for every row;
     off → every #131 row unchanged; airflow automation off + HRDS automation on + HRDS active →
     `hrds_dehumidify` with `base_state` `off`; both automations off → `off` whatever the HRDS;
     unknown HRDS → normal decision; unknown moisture test during a run → `warm`;
   - airflow automation off (27): a run gets medium + profile (+ Away lift); the snapshot is taken
     before the first write and restored at the end; no snapshot (restart) → `auto_mode` on; airflow
     automation switched on during the run → snapshot dropped, normal decision; switched off
     during a run that started under it → `auto_mode` on at the end; outside a run nothing is
     written;
   - active on → auto off + medium from each prior state (auto, low, boost decided → stopped by the
     boost automation, heat_low, moisture_low); manual boost left alone; in Away: latch set, away off, medium, and at run end away on, latch
     cleared; latch switched off during a run → Away not restored; away switched on during a run →
     latch set, away off again, medium kept; away off is written before the preset;
     `airflow_away_active` on through the lift;
   - profile `cool` when the intake is dry enough, `warm` when it is wetter or at/above the
     max-humidity dew point; consistent with `flush_needed` (→ cool) and
     `moisture_ventilation_low_needed` (→ warm) wherever those are on; also with heat protection
     on and with no airflow state on;
   - boost not decided while active (stopped), not run while Away is lifted; decided again and
     started after the run with `drying_needed` on (at home);
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
