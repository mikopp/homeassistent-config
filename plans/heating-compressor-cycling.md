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
- **Room valves closing:** ruled out. Loxone does not control the room valves. The only throttling
  is the fixed hydraulic throttling of the bedrooms, which is static. It can make the circulating
  volume smaller, but it does not change from run to run.

So the cause is the Vaillant's own start/stop behaviour (integral + hysteresis) at a low setpoint.

## Step 0b — record the owner's manual changes in the slab plan (docs only)

None of these are in `plans/ebusd-pv-heating-optimization.md` or `packages/notes/heating_pv_boost.md`
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
  Vaillant's, so they normally agree. A boost only happens by day.
- Loxone still publishes `warm_enough` (owner-confirmed), so it stays the comfort input.
- **Bridge pattern (owner-supplied live config, 2026-10-30): an explicit per-topic allowlist.**
  - Each state topic HA reads gets its own `topic ebusd/<circuit>/<name> in 0` line.
  - Each poll registration gets its own `topic ebusd/<circuit>/<name>/get out 0` line.
  - `ebusd/global/running` and `ebusd/global/scan` are `in` only.
  - There are no wildcards. Only the topics HA needs are bridged.

  Where to record it:
  - `packages/notes/heating_pv_boost.md`: a new "Transport: the bridge is an allowlist" section.
    Write down the pattern and the rule, not the topic list. The rule: every new register this
    package reads needs **two** bridge lines (`in` for the state, `out` for `/get`), added on the
    HA broker host after deploy. Without the `in` line the sensor stays `unavailable`. Without the
    `out` line the `?N` poll registration never reaches ebusd.
  - Slab plan "Transport": replace the `topic ebusd/# in 0` snippet with the allowlist pattern,
    and note that the old snippet was never what got deployed.
- Loxone does **not** control room valves (owner-confirmed). Record this in the slab plan's
  "Division of responsibility" table and in the notes. Room valves are fixed hydraulic throttling
  only, with no automatic actuation.
- The time program gives two intended mode switches a day, at the day and night switch-over. These
  are expected, not cycling.

## Answer to "what else should I change" (Vaillant side, manual, after a baseline)

Change one value at a time, then give each change at least 3 comparable-weather days:

| Setting | Now | Suggest | Why |
|---|---|---|---|
| `CompHysteresis` (C8) | read it | +1…2 K at a time, keep flow ≤ `FlowTempMax` 35 °C | **Main lever for run length.** Pushes back the forced stop |
| `CompIntegral` | −180 | up to −300…−400 if runs are still short | Fewer starts; the slab buffers the deficit easily |
| `BackupIntegral` | read it | keep `BackupModeHc` = without backup heater ("ohne ZH") | Backup heater starts at BackupIntegral + CompIntegral, so a deeper integral must not make it start |
| Heating curve | 0.15 | **leave it** | Already low; lowering it further only shortens runs |
| `NumberCompStarts` | read it | 3 | Upper limit only; not the cause at 1 start/h |
| Loxone | no longer writes, no valve control (done) | — | Ruled out as a cause |
| Bedroom throttling | fixed, hydraulic | leave it unless the flow−return spread is very large | Less water moving means faster overshoot; it's static, so it's a minor factor |

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
| Spread (flow − return) | existing sensors | Very large spread = little water moving (pump speed or throttling) |
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
      recorded in `plans/ebusd-pv-heating-optimization.md` and `packages/notes/heating_pv_boost.md`
- [x] 1. 9 read-only MQTT sensors (integral, demand, flow setpoint, 3 settings, 3 counters)
- [x] 2. Poll registration: tier 4 (`?5`) and tier 5 (`?9`)
- [x] 3. Derived: history_stats (runs today, runtime today, 24 h duty cycle), average run today,
      last run (trigger template), daily utility meters (starts, yield, electricity), efficiency today
- [x] 4. Dashboard: "Compressor Cycling" entities card + "Why runs end" history graph
- [x] 5. Tests (`test_last_run_…`, `test_average_run_…`, `test_efficiency_…`), conftest seeds,
      notes, README
- [ ] 6. After deploy (owner): add the 18 bridge lines, restart Mosquitto, confirm each sensor
      publishes, verify `sensor.technikraum_heizung_heizung_energy` is the real Shelly energy id
- [ ] 7. 3-day baseline, then `CompHysteresis` +1 K; one change at a time, log under Observations

### Checks run locally (2026-10-30)

- yamllint (package, dashboard, resolved config), `fix_yaml_style.py` — clean; no CRLF
- `check_config` on the pinned image (2026.10.1) — passes (only warning: `climate_template` custom
  component not installed in that run); `--info all` lists all 19 new entities
- pytest against the pinned image (harness v0.11.0, Python 3.14): all 5 new tests and both
  template tests (strict + lenient) pass. `test_decision_stays_off_while_the_master_switch_is_off`
  and `test_return_temp_is_masked_while_making_hot_water` fail when `test_heating_pv_boost.py` runs
  on its own — **identically on `master`**, so not caused by this change (cause not investigated;
  CI runs the full suite)
