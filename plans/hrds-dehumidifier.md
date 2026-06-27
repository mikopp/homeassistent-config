# HRDS Dehumidifier + Airflow Coordination — Implementation Plan

> Status: **PLAN ONLY — not yet implemented.** Target implementation day is later.
> Stored at `plans/hrds-dehumidifier.md` per repo convention (CLAUDE.MD rule 1).

## Context

The **HRDS+** dehumidifier (Innova DEH+ / hej.luft, `innova_hrds` Modbus integration) sits on the
**Comfo Q350** supply pipe (fresh air going *into* the house). It has its own fan that, when on,
**recirculates indoor air in addition to the fresh air** the Comfo pushes — increasing the air volume
through the dehumidifier coil so it can dry (and cool) faster.

We want a **second Home Assistant package** next to the existing `packages/airflow_cooling.yaml` that:

1. **Dehumidifies on free solar:** if indoor humidity is above *target* **and** there is enough free PV
   surplus → run the HRDS in dehumidify.
2. **Dehumidifies unconditionally on high humidity:** if indoor humidity is above *max* → always run
   the HRDS in dehumidify (ignore PV).
3. **Guarantees a minimum combined airflow whenever the HRDS runs:** combined (Comfo supply + HRDS
   recirculation) must stay above a set value — **150 m³/h** normally. If the Comfo is below that, the
   HRDS recirc fan tops up the gap.
4. **Flushes faster when allowed:** while dehumidifying and inside the boost schedule, push combined
   airflow to **≥250 m³/h**.
5. **Never imports humid outdoor air to flush while dehumidifying:** once the HRDS is dehumidifying, do
   not flush/boost ventilation when outdoor humidity is above the max target.

The existing airflow package is a carefully-tuned, oscillation-resistant controller for the Comfo
(`packages/airflow_cooling.yaml`, with a pytest harness in `tests/`). The new package must **coordinate
with it, not fight it.**

---

## Analysis of the existing airflow states (and how the HRDS coordinates)

All airflow humidity decisions are made on **dew point (absolute humidity)**, not raw RH. The RH
set-points (`input_number.airflow_target_humidity` / `_max`) are the tunable source of truth, converted
to fixed dew-point thresholds at the target temperature via the Magnus sensors
`sensor.airflow_dew_point_target` / `sensor.airflow_dew_point_max`. Indoor dew is
`sensor.airflow_min_indoor_dew_5min`; outdoor dew is `sensor.airflow_outdoor_dew_5min`. The four
decision sensors (10-min debounced, Schmitt-hysteresis):

| State | Sensor | Meaning | HRDS interaction |
|------|--------|---------|------------------|
| **Free cooling** | `binary_sensor.airflow_free_cooling_available` | Outdoor cool **and** dry (`outdoor_dew ≤ dew_target`, cooler than target) → Comfo opens bypass, imports dry air | Importing dry air drops indoor dew → our `hrds_dehumidify_needed` naturally turns **OFF**. HRDS *yields* to free cooling automatically via shared dew thresholds — no explicit rule needed. |
| **Flush** | `binary_sensor.airflow_humidity_flush_needed` | Indoor too humid **and outdoor distinctly drier** (`outdoor_dew < dew_max`, branch1; `≤ dew_target`, branch2) → cool profile flushes moisture out | Only fires when outdoor is **drier** than indoor. Complements HRDS: when outdoor can help, ventilation flushes; when it can't, HRDS dries. |
| **Boost** | `binary_sensor.airflow_humidity_drying_needed` | Flush **+** real outdoor temp below target **+** inside boost schedule → Comfo boost ~250 m³/h | Subset of flush. When active, the Comfo already delivers ~250 m³/h, so the HRDS top-up backs off. |
| **Moisture protect (low)** | `binary_sensor.airflow_moisture_ventilation_low_needed` | Indoor humid **but outdoor too humid to import** (`outdoor_dew ≥ dew_max`) → Comfo drops to LOW (~60–100 m³/h) | **This is the HRDS's moment.** Comfo throttles down (below 150), so HRDS dehumidify runs and its recirc fan tops the combined airflow back up — to ≥150 normally, and **to 250 when indoor is above max and the boost schedule is active** (recirculating indoor air through the coil to dry faster — see below). |

**Two separate "boost" concepts — do not conflate them:**
- **Comfo flush/boost** *imports outdoor air*. It must avoid humid outdoor air — and it already does:
  flush `branch1` requires `outdoor_dew < dew_max`, `branch2` requires `outdoor_dew ≤ dew_target`. So in
  **absolute / dew-point terms the airflow package already refuses to flush/boost when outdoor dew is
  above the max-humidity dew point.** The original "never flush/boost when outdoor above max while
  dehumidifying" rule is about *this* path and is **already guaranteed** by existing logic.
- **HRDS 250 m³/h combined target** is reached by **boosting the HRDS recirculation fan, which
  recirculates *indoor* air through the dehumidifier coil.** It imports no outdoor air, so it is **NOT
  gated on outdoor humidity at all.** It dries the house faster. The trigger is simply: *HRDS
  dehumidifying AND indoor above max AND inside the boost schedule.* Moisture-protect (outdoor humid,
  Comfo low) is precisely when this is most valuable.
  - *Example A:* airflow in moisture-protect, indoor above max during a workday → Comfo ~100, HRDS fan
    adds ~150 → **250 combined**, circulating indoor air through the HRDS to dry faster.
  - *Example B:* airflow flush/boost active (Comfo ~300 m³/h), HRDS dehumidifying, boost schedule → gap
    to 250 is already met, so the **HRDS fan stays off/min** (top-up only fills the gap).

**Emergent coordination summary:** outdoor dry → Comfo flushes/free-cools, HRDS idle; outdoor humid →
Comfo goes LOW, HRDS dehumidifies recirculated air and maintains airflow. The two are linked purely
through shared dew-point thresholds and the Comfo's reported supply volume — no command contention.

---

## Decisions — all RESOLVED with the user

1. **PV "enough free energy" signal** → a new `packages/energy.yaml` owns `sensor.energy_pv_surplus`
   (= Victron grid **export** power) and `binary_sensor.energy_free_available` (surplus available **AND**
   battery SoC > `energy_battery_soc_min`). The HRDS gate `hrds_pv_surplus_available` =
   `energy_free_available` AND `surplus ≥ hrds_power_demand`, with on/off delay. The Shelly pool pump
   config is migrated into `energy.yaml`. See the "Energy package" section.
2. **"No Comfo flush/boost when outdoor humid"** → **rely on the existing dew gate; no edit to
   `airflow_cooling.yaml`.** The existing flush logic already blocks importing outdoor air above the max
   dew point. (Applies only to the Comfo outdoor-air path — never to the HRDS recirculation targets.)
3. **How combined airflow targets are reached** → **HRDS fan top-up only.** The package controls only
   the HRDS, reads `sensor.comfoconnect_pro_supply_fan_volume`, and fills the gap with the HRDS recirc
   fan. It never commands the Comfo (airflow package stays sole owner).
4. **Extracting shared params** → **rename to a neutral `climate_*` prefix** and repoint all references;
   history/values preserved via the `ha_mcp` migration runbook below.
5. **Three combined-flow targets (not two)** → baseline floor `hrds_target_airflow` (150) whenever the
   HRDS runs; `hrds_opportunistic_airflow` (~200) for the free-PV "above target" case — more air, low
   noise; `hrds_boost_airflow` (250) for serious moisture (above max) inside the boost schedule.

6. **Away mode → moisture protection stays active (CONFIRMED).** The HRDS keeps dehumidifying when the
   Comfo is in away mode — moisture protection does not pause because nobody is home. With Comfo airflow
   low while away, the HRDS recirc fan tops up to the active combined target as usual. (No away-gate on
   the HRDS dehumidify/fan logic.)

Additional assumptions (flag if wrong):
- HRDS is used for **dehumidify only** here; `active_cooling` stays OFF (cooling remains the Comfo
  free-cooling/bypass job). Can be extended later.
- Real HRDS entity_ids must be **verified on the live system** (ha-mcp, read-only) before coding. Per
  the integration README the object_ids are **un-prefixed** (`switch.dehumidify`, `switch.unit_on_off`,
  `switch.active_cooling`, `number.fan_manual_speed`, `number.fan_min_speed_dehumidify`,
  `number.fan_max_speed_dehumidify`, `sensor.supply_fan_output`, `sensor.supply_fan_status`,
  `binary_sensor.dehumidify_request`, `binary_sensor.fan_integration_active`, `climate.hrds_climate`) —
  the live ids most likely carry the **device-name prefix** from the config name (`HRDS+` → e.g.
  `switch.hrds_dehumidify`). Confirm the exact prefix before writing the package.

---

## Design

New file: **`packages/hrds_dehumidifier.yaml`** (mirrors `airflow_cooling.yaml` structure and the
`hrds_` naming convention). All HA template/helper rules from `CLAUDE.MD` apply (availability guards,
no `initial:`, no `| float(default)` behind a guard, comment every block).

### Shared common package — `packages/climate_common.yaml` (NEW)
The entities both `airflow_cooling.yaml` and the HRDS package need are extracted into a neutral
`climate_*` common package so neither feature "owns" them. Contents (renamed from `airflow_*`):

- **Parameters (`input_number`):** `climate_target_humidity`, `climate_max_humidity`,
  `climate_target_temperature` (the temp at which dew thresholds are evaluated), and
  `climate_min_dew_diff` — now shared: airflow's free-cooling/flush margin **and** the HRDS stop
  hysteresis (see below). `climate_min_humidity` may move here too for cohesion (airflow-only consumer).
- **Derived humidity thresholds (`template` sensor):** `climate_dew_point_target`,
  `climate_dew_point_max` (Magnus at the target temp), and `climate_dew_point_min` if min moves.
- **Indoor climate primitives:** `climate_avg_indoor_humidity`, `climate_avg_indoor_temp`,
  `climate_indoor_dew` (+ its `_5min` filter) — the measured indoor dew both packages compare.
- **Boost window:** `schedule.climate_boost_workday` / `_non_workday` **and** a new shared
  `binary_sensor.climate_boost_schedule_active` that extracts airflow's inline `in_schedule`
  expression (workday + the two schedules), referenced by both the airflow drying boost and the
  HRDS 250 m³/h window.

Both `airflow_cooling.yaml` and `hrds_dehumidifier.yaml` reference these `climate_*` ids.

**Near-duplicate consolidation (committed refactor, not just a move):**
- **Boost-schedule logic** is currently inlined inside `airflow_humidity_drying_needed` (the `in_schedule`
  expression over `binary_sensor.workday` + the two schedules) and would otherwise be re-derived in the
  HRDS package. Extract it **once** into `binary_sensor.climate_boost_schedule_active`. Then
  `airflow_humidity_drying_needed` is simplified to consume that sensor — drop its inline `in_schedule`
  block and replace its workday/schedule **triggers** with a single trigger on
  `binary_sensor.climate_boost_schedule_active`. The HRDS `hrds_boost_airflow_window` consumes the same
  sensor. One source of truth for "boost window is open."
- **Indoor-dew derivation chain** (`avg_indoor_humidity` → `avg_indoor_temp` → `min_indoor_dew` +
  `_5min` filter) moves wholesale into the common package as `climate_*`; every airflow consumer
  (free-cooling, flush, low, drying sensors, the climate entity) repoints to the `climate_*` ids. No
  parallel copy remains in `airflow_cooling.yaml`.

### Energy package — `packages/energy.yaml` (NEW)
A dedicated energy package that owns the PV-surplus / free-energy primitives and absorbs the existing
Shelly pool pump config.

- **Migrate Shelly pool pump:** move the entire `mqtt:` block from `packages/shelly_pool_pump.yaml` into
  `energy.yaml` **verbatim** (the five `sensor.pool_pump_*` + `binary_sensor.pool_pump_switch` all have
  `unique_id`s, so the entity_ids and history are preserved by the move — no rename needed), then delete
  `shelly_pool_pump.yaml`. (`!include_dir_named packages` auto-picks up the new file.)
- **`sensor.energy_pv_surplus`** (W) — surplus power available to loads. Default definition: the Victron
  grid **export** power (`sensor.victron_grid_power_export`) — i.e. true surplus after house load and
  battery charging. (Alt: computed `PV − house_load − battery_charge`.) Availability-guarded.
- **`input_number.energy_battery_soc_min`** (%) — battery-SoC floor ("X%"). New parameter, lives here.
- **`input_number.energy_min_surplus`** (W) — floor above which surplus counts as "available" (noise
  guard; small default).
- **`binary_sensor.energy_free_available`** — generic "free energy is available" signal:
  `energy_pv_surplus > energy_min_surplus` **AND** `sensor.victron_battery_soc > energy_battery_soc_min`.
  Availability-guarded on the Victron sensors. Reusable by any opportunistic load, not just the HRDS.

### Referenced (not extractable / package-specific)
- Comfo airflow: `sensor.comfoconnect_pro_supply_fan_volume` (m³/h integration entity; tests stub 150).
- PV / battery: `sensor.victron_grid_power_export`, `sensor.victron_battery_soc`.

### New helpers (`hrds_` prefix)
- `input_boolean.hrds_automatic_enabled` — master enable (default off).
- `input_number.hrds_power_demand` (W) — the HRDS's own electrical demand (compressor + fan). The unit
  exposes **no power/watt register** (only compressor/fan output %), so this is a parameter. (If the HRDS
  is ever fed from a metered smart plug, swap in that power sensor.)
- `input_number.hrds_target_airflow` (m³/h, default 150) — **baseline combined-flow floor whenever the
  HRDS runs (parameter).**
- `input_number.hrds_opportunistic_airflow` (m³/h, default ~200) — **combined-flow target for the
  free-PV "above target" case: more air, but quiet (parameter).**
- `input_number.hrds_boost_airflow` (m³/h, default 250) — **combined-flow target for serious moisture
  (above max) inside the boost schedule (parameter).**
- `input_number.hrds_max_recirc_airflow` (m³/h) — HRDS fan output at 100% (calibration for %→m³/h map).
- `input_number.hrds_fan_min_speed` (%, e.g. 20) — minimum fan while HRDS runs.
- `input_number.hrds_min_runtime` (minutes) — **anti-flip-flop:** once dehumidify starts, it may not
  stop until this elapses (compressor protection + stable behaviour).
- `timer.hrds_min_runtime` — started on dehumidify-on for `hrds_min_runtime` minutes; the controller's
  OFF path only fires once it is idle.

### Decision sensors (trigger-based binary_sensors, Schmitt + delay like airflow)
- `binary_sensor.hrds_pv_surplus_available` — the HRDS-specific free-energy gate:
  `binary_sensor.energy_free_available` (generic free energy, from `energy.yaml`) **AND**
  `sensor.energy_pv_surplus ≥ hrds_power_demand` (enough surplus to actually cover the unit). **delay_on
  / delay_off (~3–5 min, tunable) to prevent flip-flop** on this final gate, as requested.
- `binary_sensor.hrds_indoor_above_max` — **asymmetric Schmitt:** ON when
  `climate_indoor_dew ≥ climate_dew_point_max`; stays ON until
  `climate_indoor_dew ≤ climate_dew_point_max − climate_min_dew_diff` (start on the trigger, stop only
  once dew is `min_dew_diff` below it). The "serious moisture" signal; drives unconditional dehumidify
  and the 250 target.
- `binary_sensor.hrds_indoor_above_target` — **asymmetric Schmitt:** ON when
  `climate_indoor_dew > climate_dew_point_target`; stays ON until
  `climate_indoor_dew ≤ climate_dew_point_target − climate_min_dew_diff`.
- `binary_sensor.hrds_dehumidify_needed` — **core decision** (availability-guarded on the dew sensors):
  - ON if `hrds_indoor_above_max` (unconditional — high humidity), **or**
  - `hrds_indoor_above_target` **and** `hrds_pv_surplus_available` (free-PV opportunistic).
  - The asymmetric hysteresis above (per branch, using `climate_min_dew_diff`) is the primary
    anti-flip-flop; the minimum-runtime gate (below, in the controller) is the second layer.
- `binary_sensor.hrds_boost_airflow_window` — `hrds_indoor_above_max` ON **and**
  `binary_sensor.climate_boost_schedule_active` (the shared boost window). **No outdoor-humidity gate**
  — the 250 target recirculates indoor air through the HRDS. (PV-only opportunistic dehumidify stays at
  the 150 target; raise this to "`hrds_dehumidify_needed` AND schedule" only if you want opportunistic
  drying to also push 250.)

### Computed sensors
- `sensor.hrds_combined_airflow_target` — three-tier select (first match):
  1. `hrds_boost_airflow` (250) if `hrds_boost_airflow_window` (above max **and** boost schedule);
  2. else `hrds_opportunistic_airflow` (~200) if dehumidifying on the opportunistic branch
     (`hrds_indoor_above_target` and **not** `hrds_indoor_above_max`);
  3. else `hrds_target_airflow` (150) — the floor (covers above-max **outside** the boost schedule, kept
     quiet at night; tune if you'd rather serious moisture still pushed 200 off-schedule).
- `sensor.hrds_required_fan_percent` — `clamp((target − comfo_supply_volume) / max_recirc_airflow*100,
  fan_min, 100)`; meaningful only while running.
- `sensor.hrds_state` — reason string for the dashboard (off / dehumidify_pv / dehumidify_max /
  topup / boost_flush), mirroring `sensor.airflow_cooling_state`.
- `recorder: exclude:` the noisy intermediate computed sensors (as airflow does).

### Automations
- `automation.hrds_dehumidify_controller` (gated by `hrds_automatic_enabled`): on
  `hrds_dehumidify_needed` change / `timer.hrds_min_runtime` finished / start →
  - ON (need rises): `unit_on_off` on, `dehumidify` on, `active_cooling` off, **start
    `timer.hrds_min_runtime`** for `hrds_min_runtime` minutes.
  - OFF (need clears): only act **when the min-runtime timer is idle** (i.e. runtime satisfied) — then
    `dehumidify` off, `unit_on_off` off (stops the fan). If the need clears while the timer is still
    active, defer: the timer-finished trigger re-evaluates and stops it then if still not needed.
  - A `timer` helper is used rather than the switch's `last_changed` so the guard is explicit and the
    deferred-stop re-trigger is event-driven. (`timer.hrds_min_runtime` resets to idle on HA restart —
    acceptable: a restart implies a fresh start anyway.)
- `automation.hrds_fan_airflow_controller` (gated by `hrds_automatic_enabled`, `mode: queued`): on
  `sensor.hrds_required_fan_percent` change / dehumidify on-off →
  - Running: write `number.fan_manual_speed` (PM20, reg 1614) = required %, **with a deadband** (only
    write if it differs from current `sensor.supply_fan_output` by ≥5 %) to limit Modbus chatter.
  - Off: reset fan to device default/auto.
  - **⚠ MUST be verified on real hardware BEFORE implementation (see "Pre-implementation hardware
    checks" below).** Working hypothesis (to confirm): the **dehumidify fan band**
    `number.fan_min_speed_dehumidify` (PF28/1853, default 50 %) … `number.fan_max_speed_dehumidify`
    (PF10/1647, default 85 %) only bounds the fan **while it is actually running in integration
    (recirculation) mode** — and the unit can dehumidify with the **fan off**, relying on the Comfo's
    passive inflow (README §13.1/§13.4, `plans/todo.md`). If that holds, then `fan_manual_speed` (PM20)
    cleanly sets the recirculation airflow from off → 100 % and the band is irrelevant to our top-up.
    If instead PM20 is clamped to the band whenever dehumidify is on, the top-up must drive the **band
    registers** (`fan_max_speed_dehumidify` up toward 100 %, `fan_min_speed_dehumidify` down) instead.
    **The fan-control lever is chosen by this result, so it gates implementation.**

---

## Files
- **New:** `homeassistent-config/packages/climate_common.yaml` (shared parameters/primitives — see
  "Shared common package" above and the rename map below).
- **New:** `homeassistent-config/packages/energy.yaml` (PV surplus + free-energy signal + the migrated
  Shelly pool pump config).
- **Delete:** `homeassistent-config/packages/shelly_pool_pump.yaml` (its `mqtt:` block moves verbatim
  into `energy.yaml`; pool entity_ids/history preserved since the `unique_id`s are unchanged).
- **New:** `homeassistent-config/packages/hrds_dehumidifier.yaml` (the whole HRDS package).
- **Edit:** `homeassistent-config/packages/airflow_cooling.yaml` — remove the moved entities and
  repoint every reference to the new `climate_*` ids; replace the inline `in_schedule` expression in
  `airflow_humidity_drying_needed` with `binary_sensor.climate_boost_schedule_active`.
- **Edit:** `homeassistent-config/tests/conftest.py` + `tests/test_airflow.py` — update renamed ids;
  **add** `tests/test_hrds.py` (+ innova_hrds / victron stubs).
- **Edit:** `homeassistent-config/dashboards/airflow-dashboard.yaml` — update renamed ids.
- **New:** `homeassistent-config/plans/hrds-dehumidifier.md` (copy of this plan, repo convention).
- **Only if Decision 2 = explicit guard:** small edit to airflow flush+boost sensors. Default: none.

### Rename map (when Decision 4 = rename, recommended)
`airflow_target_humidity → climate_target_humidity` · `airflow_max_humidity → climate_max_humidity` ·
`airflow_cooling_target_temperature → climate_target_temperature` ·
`airflow_dew_point_target → climate_dew_point_target` · `airflow_dew_point_max → climate_dew_point_max` ·
`airflow_min_indoor_dew(_5min) → climate_indoor_dew(_5min)` ·
`airflow_avg_indoor_humidity → climate_avg_indoor_humidity` ·
`airflow_avg_indoor_temp → climate_avg_indoor_temp` ·
`airflow_min_dew_diff → climate_min_dew_diff` ·
`airflow_boost_workday/_non_workday → climate_boost_workday/_non_workday` · **new**
`binary_sensor.climate_boost_schedule_active`. (Optionally `airflow_min_humidity → climate_min_humidity`
and `airflow_dew_point_min → climate_dew_point_min`.) Update **every** reference in the four airflow
decision sensors, the ventilation controller, the climate entity, the dashboard, and the tests; then
re-run the airflow pytest suite as the regression gate before adding the HRDS package.

## Pre-implementation hardware checks (do these BEFORE writing the package)

The HRDS integration is documented from the manufacturer PDFs but **not yet verified on hardware**
(`README` status note + `plans/todo.md`). These few behaviours determine the fan-control design, so
confirm them on the real unit first — the user will run these:

1. **Fan-off dehumidify (the key one):** can the unit dehumidify with its own fan **off**, relying on
   the Comfo's passive inflow? Set climate to **Dry** with fan mode **off** (or `fan_manual_speed` = 0)
   and confirm dehumidification still runs (`compressor_status` / `dehumidify_request` on) while
   `supply_fan_status` = OFF. *Expected by the user; confirms recirculation is purely additive.*
2. **Manual fan vs. dehumidify band:** with dehumidify on, write `fan_manual_speed` to 30 / 60 / 95 %
   and read back `sensor.supply_fan_output`. If it tracks the setpoint → PM20 is our single top-up
   lever. If it clamps to `fan_min/max_speed_dehumidify` (50–85 %) → drive the **band registers**
   instead. (Hypothesis: the band only applies while the fan runs in integration/recirculation mode.)
3. **Entity-id prefix:** confirm the live object_ids (device-name prefix from config name `HRDS+`, e.g.
   `switch.hrds_dehumidify` vs the README's un-prefixed `switch.dehumidify`).
4. **Writes honoured:** confirm PH02/PH27/PH28 are auto-set so `unit_on_off` / `dehumidify` writes take.

The fan-controller section and verification step 4 depend on outcomes (1) and (2).

## Migration — history-preserving rename via `ha_mcp` (implementation day)

The rename must **not** lose recorder history or the user-tuned setpoint values. The `ha_mcp` MCP
server (which can rename entities) is used to migrate state. Two entity classes behave differently:

- **Template sensors (have a `unique_id`)** — e.g. `sensor.airflow_dew_point_*`,
  `airflow_min_indoor_dew(_5min)`, `airflow_avg_indoor_*`, and the new `climate_boost_schedule_active`.
  These live in the **entity registry**; renaming the entity_id there makes the recorder migrate
  history (`states_meta`) to the new id automatically.
  - **CRITICAL:** in `climate_common.yaml`, **reuse each entity's existing `unique_id` verbatim**. If
    the `unique_id` changes, HA treats it as a brand-new entity and orphans the history. The `unique_id`
    stays `airflow_*`-derived; only the entity_id is renamed. (Slightly inconsistent internally, but it
    is the price of zero history loss.)
- **YAML helpers (no `unique_id`, NOT in the registry)** — `input_number.airflow_target_humidity`,
  `airflow_max_humidity`, `airflow_cooling_target_temperature`, `airflow_min_dew_diff`
  (+ `airflow_min_humidity`), and the `schedule.airflow_boost_*`. These **cannot** be registry-renamed,
  and their RestoreState value is keyed by entity_id, so a rename resets them. Schedules are declarative
  (defined in YAML — no value loss). For the input_numbers, the user-set **value** is preserved by
  snapshot-and-restore.

### Runbook
1. **Snapshot (ha_mcp read):** record the current values of every YAML `input_number` being renamed.
2. **Registry rename (ha_mcp):** rename the template-sensor entity_ids `sensor.airflow_* → climate_*`
   (history migrates with them). Do this for all `unique_id`-backed entities in the rename map.
3. **Deploy (`git pull` on HA host):** the new `climate_common.yaml` (template entities reusing the
   original `unique_id`s → they re-bind to the just-renamed registry entries; new `climate_*`
   input_numbers/schedules/`climate_boost_schedule_active`), plus the edited `airflow_cooling.yaml` and
   the new `hrds_dehumidifier.yaml`, all referencing `climate_*` ids.
4. **Restore values (ha_mcp):** set each new `climate_*` input_number to its snapshotted value
   (`input_number.set_value`). Set the new HRDS parameters to their intended values.
5. **Verify:** history is continuous on the renamed `sensor.climate_*` entities; the input_numbers hold
   the restored values; no orphaned `airflow_*` entities remain `unavailable`.

> Note: `CLAUDE.MD` currently scopes `ha_mcp` to read-only discovery. This migration explicitly uses its
> entity-rename and `set_value` capabilities — confirm that elevated use is acceptable for the
> migration window (the user has authorised it for this task).

## Verification
1. **Entity-id check (step 0):** via ha-mcp (read-only) confirm the real `innova_hrds`, Victron, and
   Comfo entity_ids on the live system before writing templates.
2. **Unit tests:** add `tests/test_hrds.py`; assert, by setting indoor dew / max dew / grid export /
   comfo supply volume: dehumidify turns on at max regardless of PV; on above-target only with surplus;
   fan top-up math (e.g. comfo=100, target=150 → required ≈ (50/max_recirc)·100); the 250 target
   activates on indoor-above-max + boost schedule **regardless of outdoor humidity** (moisture-protect
   case: comfo≈100 + HRDS≈150 = 250); the opportunistic tier targets ~200 on above-target + free PV
   (below max); the 150 floor applies above-max off-schedule; HRDS fan stays off when comfo alone
   already exceeds the active target (e.g. comfo=300). **Anti-flip-flop:** assert dehumidify stays ON when indoor dew sits between the
   trigger and `trigger − climate_min_dew_diff` (only stops once it drops the full diff below), and that
   it does not stop while `timer.hrds_min_runtime` is active even after need clears. Update the airflow
   tests for the renamed `climate_*` ids and the simplified `airflow_humidity_drying_needed` (now
   consuming `climate_boost_schedule_active`). Run the existing pytest harness as the regression gate.
3. **Template validation:** HA Developer Tools → Template for each new sensor; toggle the input helpers.
4. **Dry run on device:** enable `hrds_automatic_enabled`, watch `sensor.hrds_state`,
   `number.fan_manual_speed`, `sensor.supply_fan_output`, and `sensor.comfoconnect_pro_supply_fan_volume`.
   **Critically, resolve the manual-vs-band question:** with dehumidify active, write `fan_manual_speed`
   to 30 %, 60 %, 95 % and read back `sensor.supply_fan_output` — if it clamps to the
   `fan_min/max_speed_dehumidify` band, switch the top-up lever to the band registers. This determines
   the fan-control implementation.
5. User deploys via `git pull` on the HA host (never auto-deploy).

## Out of scope (this iteration)
- HRDS active cooling / free-cooling assist.
- Editing the Comfo control path (unless Decision 3 changes).
- Dashboard card (can be added after, mirroring `dashboards/airflow-dashboard.yaml`).
