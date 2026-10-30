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

Two hypotheses outside the Vaillant that the new data must confirm or rule out:
1. **Loxone mode toggling.** Step 9 of `plans/ebusd-pv-heating-optimization.md` is still pending,
   and Observation 1 there shows Loxone still flips `mc/OperatingMode` `on`⇄`low`. Each flip moves
   the flow setpoint, which can force a stop or a start.
2. **Room valves closing.** When Loxone closes per-room valves, the circulating water volume drops,
   so the flow temperature rises faster and the hysteresis stop comes sooner.

## Answer to "what else should I change" (Vaillant side, manual, after a baseline)

Change one value at a time, then give each change at least 3 comparable-weather days:

| Setting | Now | Suggest | Why |
|---|---|---|---|
| `CompHysteresis` (C8) | read it | +1…2 K at a time, keep flow ≤ `FlowTempMax` 35 °C | **Main lever for run length.** Pushes back the forced stop |
| `CompIntegral` | −180 | up to −300…−400 if runs are still short | Fewer starts; the slab buffers the deficit easily |
| `BackupIntegral` | read it | keep `BackupModeHc` = without backup heater ("ohne ZH") | Backup heater starts at BackupIntegral + CompIntegral, so a deeper integral must not make it start |
| Heating curve | 0.15 | **leave it** | Already low; lowering it further only shortens runs |
| `NumberCompStarts` | read it | 3 | Upper limit only; not the cause at 1 start/h |
| Loxone | writes mode | finish step 9 (stop writing `OperatingMode`) | Removes hypothesis 1 |
| Room valves | Loxone | keep the large zones fully open in mild weather | Removes hypothesis 2; more water volume = longer runs |

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
| Spread (flow − return) | existing sensors | Very large spread = little water moving (valves) |
| Mode flips | `sensor.geotherm_heating_hvac_mode` changes | Should be near 0 once Loxone stops writing |
| Daily efficiency | `ehp/YieldTotal` Δ / Shelly `Heizung Energy` Δ | Rises as runs get longer (coarse, kWh resolution) |

## Implementation (read-only; HA writes nothing)

### 1. `packages/heating_pv_boost.yaml` — MQTT sensors (same patterns as the existing ones)

- Model these on `Heating Temp Desired Low`: `default_entity_id`, `device: *ebusd_geotherm`,
  `value | trim | float(none)` guard, inline field docs.
- Live: `ehp/Integral` (°min, measurement) and `ehp/CompDemand` (binary sensor; accepts both
  `yes`/`1` per the enum rule in the notes).
- `mc/Status0a`: parse field 4 `flowtempdesired` positionally.
- Settings (read only): `ehp/CompIntegral`, `ehp/CompHysteresis`, `ehp/NumberCompStarts`,
  `ehp/BackupIntegral`, `mc/HeatingCurve`.
- Counters (`total_increasing`): `ehp/CompStartsHc`, `ehp/CompHoursHc`, `ehp/YieldTotal` (kWh).
- Register names and decodes were checked against the live catalog (`08.ehp.csv`, `50.ehp.mc.csv`
  on ebus.github.io). Not yet checked: whether this unit answers each one, and payload shapes
  (`HeatingCurve` sits behind `[cfgheatsinktype=1]`). Mark each as unverified until it is seen
  live.

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
- Trigger template `sensor.heating_compressor_last_run_minutes`: on `to: off` from `on`, compute the
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
- `packages/notes/heating_pv_boost.md`: the tuning registers and the reasoning above about start vs
  stop criteria (marked as hypothesis).
- README package section.
- Update the Status section of the repo plan file.

## Verification

- yamllint, `.github/scripts/fix_yaml_style.py .`, `resolve_ha_yaml.py`, `extract_templates.py`.
- `check_config` against the pinned image (Dockerfile `FROM`).
- CI pytest.
- After deploy (user): confirm each topic publishes, then record a 3-day baseline (starts per day,
  average run, Integral at start and at stop, overshoot at stop, mode flips). Only then change
  `CompHysteresis`. Log the findings under Observations.

Per CLAUDE.MD: implement step by step and wait for approval after each step.

## Status

- [x] 0. Plan file (this file)
- [ ] 1. MQTT sensors for integral, demand, flow setpoint, tuning settings, counters
- [ ] 2. Poll-registration tiers
- [ ] 3. Derived sensors (starts/day, duty cycle, run lengths, daily efficiency)
- [ ] 4. Dashboard card
- [ ] 5. Tests, notes, README
- [ ] 6. 3-day baseline after deploy (user), then tune `CompHysteresis` one step at a time
