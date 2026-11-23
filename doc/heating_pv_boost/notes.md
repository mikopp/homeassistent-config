---
paths:
  - "packages/heating_pv_boost.yaml"
  - "tests/ha/test_heating_pv_boost.py"
  - "tests/ha/test_heating_pv_boost_comfort.py"
  - "tests/ha/test_heating_pv_boost_ebusd_registers.py"
  - "tests/ha/test_heating_pv_boost_rolling.py"
  - "tests/e2e/test_restart.py"
  - "dashboards/heating-dashboard.yaml"
  - "doc/heating_pv_boost/design.md"
---
# heating_pv_boost.yaml — Vaillant geoTHERM via ebusd

Current facts for `packages/heating_pv_boost.yaml` (PV slab charging; Phase 1 = read-only decision
layer, Phase 2 = comfort control, the only writer, off until armed; rollout in
`plans/ebusd-pv-heating-optimization.md`).
**Design** (on demand): `doc/heating_pv_boost/design.md`: HPB-1 control law (read it before
changing `sensor.heating_wanted_operating_mode`, `sensor.heating_target_temp` or
`automation.heating_comfort_control`), HPB-2 energy-mode table.
Device: `doc/devices/vaillant-vws-83-2/` (geoTHERM exclusiv VWS 83/2, `VWS-*` IDs) — read
`behaviour.md` before changing a write to the unit or reasoning about how it reacts (its parts
`runs.md`, `protections.md`, `cooling.md` per topic); `interface.md` before adding a register, a
poll, a write or a bridge line (catalog source, polling, wiring; register parts
`registers-ehp.md`, `registers-mc-uih.md`); `heating-curve.md` before reasoning about the flow
setpoint.

## Invariants

- **Every ebusd register HA reads, polls or writes needs its Mosquitto bridge lines** (`in`,
  `/get out`, `/set out`; broadcasts `in` only, never a `?N` poll) (device VWS-41, VWS-40): add
  them on the HA broker host, restart Mosquitto, list the exact lines in the PR's post-deploy
  steps, and prove a new `/set` line with an idempotent write of the CURRENT value only.
  `mc/TempDesired/set` takes the one-decimal payload both writers send (`22.0`, `22.5`)
  (device VWS-25). Keep the bridge narrow: never widen it to `ebusd/#`.
- **Every register HA reads gets a `?N` in `automation.heating_ebusd_poll_registration`** (and in
  the `_POLLS` literal of `tests/ha/test_heating_pv_boost_ebusd_registers.py`), or it is never
  polled; the automation re-asserts every priority because an ebusd restart drops them (device
  VWS-42).
- **Do NOT enable `--mqttjson`.** The Loxone integration consumes the same topics as plain
  values. Parse multi-field messages positionally (device VWS-45) and document the field list
  inline at every such sensor.
- **Every enum read maps both forms** (decoded name or raw number) through one table; unmapped →
  `unknown`. Writes send names; never echo a normalised read back on a write (device VWS-44).
- **Never register a poll priority while `ebusd/global/scan` reads `running`**: gate on
  `scan != 'running'`, never on an allowlist of resting values (device VWS-43).
- **`input_number.heating_comfort_temp` is the only comfort knob while the writer is armed.**
  Every setpoint the writer writes is derived from it. With the writer off, the owner sets
  `mc/TempDesired` by hand with `number.geotherm_heating_temp_desired`; it writes only on a
  change by hand, never on a read-back. While the writer is armed, `mc/TempDesired` or `mc/OperatingMode` set at the
  wall is overwritten when its read-back reaches HA: the mode once the 30 min hold allows (the
  hold's end re-triggers), the setpoint unless HA published one in the last 5 min (then only at
  the next input change: there is no periodic re-check). The target is always absolute, never
  "current + offset" (a relative write compounds on a retry or a restart mid-boost).
- **`mc/TempDesiredLow` gets no HA logic** (not read, derived from or written): it is the
  machine's frost floor (device VWS-6), set by hand at the panel. Deriving comfort from
  it would force it to comfort level and make `off` ineffective below 3 °C.
- **Two switches arm hardware writes.** `input_boolean.heating_comfort_control_enabled` arms the
  writer; with `input_boolean.heating_pv_boost_enabled` also on, a slab decision writes mode `on`
  and comfort + 1 + offset (HPB-1 row 3), so the slab boost acts through the Phase 2 writer
  without a Phase 3 automation.
- **No hysteresis or toggle faster than 20 min** (device VWS-10).

## Hardware and integration quirks

### What the package does about unit facts

- Never use `700`-circuit registers (`Hc1RoomCircuitMode`, `Z1DayTemp`): no VRC 700 here (device
  VWS-38). HA is the only automatic bus writer of `mc/OperatingMode` and `mc/TempDesired`: the VR 90 and
  the unit's menus write only on a manual change, and a written value stays (device VWS-24).
- Ignore catalog entries gated `[id_sw>=…]` above 383; do not plan on pump speed, it has no
  software path (device VWS-23).
- Read compressor state from `ehp/Comp`, never from hcmode, which stays `heat` between runs;
  pump state from `ehp/Hc1Pump`, as the owner's Loxone logic does (which also uses
  `ehp/ActualEnvironmentPower` > 1; HA does not) (device VWS-1).
- Use the Shelly clamp `sensor.technikraum_heizung_heizung_power` (Pro 3EM) as the only electrical
  measurement (PV surplus, per-mode electricity): no power or modulation register (device VWS-29).
- Read `ehp/HcReturnTemp` as the slab's charge state: no buffer, the slab is the only store
  (device VWS-19); mask it while hot water runs (device VWS-12).
- Keep `BackupModeHc` = `no_backup` while `CompIntegral` is deepened: the backup starts at
  BackupIntegral + CompIntegral (device VWS-20). Never used in this house (owner), so HA reads no
  backup register and has no backup gate.
- Treat `mc/FlowTempMax` and floor protection as limits, not tuning targets: FlowTempMax caps the
  setpoint (device VWS-8); a higher `CompHysteresis` also raises the error-72 limit
  (device VWS-7); `ehp/ReturnTempMax` blocks the compressor (device VWS-9).
- Plot the controller's flow from VF2 (`ehp/FlowTemp`); `ehp/Status` field 0 is the internal T6
  (device VWS-18). `sensor.heating_compressor_stop_temp` uses W (`uih/FlowTempDesired`) +
  hysteresis because the integral counts VF2 − W (device VWS-3); whether the unit's stop line
  uses W or the fine setpoint is UNPROVEN (device VWS-4).
- Interlock on the cooling activity signals (`uih/CoolingDemand`, `mc/CoolingRequestHc2`,
  `uih/CoolingActive`), **never on the setting** `mc/CoolingOperatingModeHc2`: it reads `On` all
  summer and would disable heating permanently if not maintained seasonally. `mc/OperatingMode`
  is heating only, cooling has its own setting; that `off` leaves cooling running is untested
  (device VWS-15); the outdoor cooling release, and whether `mc/TempDesired` moves it, is
  UNPROVEN (device VWS-16).
- Expect heating to stop above `mc/OtShutdownLimit` (device VWS-17); the owner changes it
  seasonally.
- Expect `off` to heat below 3 °C outdoor: frost protection heats towards `TempDesiredLow`; the
  dashboard then shows mode `off`, hcmode `heat`, `Hc1Pump` on, energy mode
  `passive_heating`/`active_heating`: correct, not a bug. HA cannot stop it; only a lower
  `TempDesiredLow` limits it (owner: accepted) (device VWS-6).
- Keep Raumaufschaltung `Keine` (device VWS-21): Loxone's `warm_enough` is the only comfort
  input; `Aufschaltung` would weaken a slab boost in a warm room, `Thermostat` would block it.
  `mc/RoomTempOffset` is no lever (device VWS-22).
- Read `Broadcast/Outsidetemp` as the unit's outdoor value; `ehp/OutsideTemp` is not read
  separately (device VWS-31).

## Owner-side configuration

- Loxone does **not** write `mc/OperatingMode`; it publishes `loxone/heating/warm_enough`
  **retained**, on change and re-sent **every hour** (owner). Loxone does not control room valves.
- **Loops: ground floor throttled a bit** from last year's balancing so the upper floor gets more
  flow; no flow-meter readings available (owner, 2026-11-21).
- `mc/OperatingMode` = **`on`**, set by hand until Phase 2 is armed.
- Frost protection kept small (set at the unit by the owner; HA does not read either):
  `uih/FrostOverRideTime` 3 h, `mc/TempDesiredLow` 20 °C (both read back 2026-11-23). The owner's reading "it then kicks in only every 3 h while `off`" is UNPROVEN:
  documented as a delay only (device VWS-6). Whether the room temperature is ignored then is
  UNPROVEN (likely, with Raumaufschaltung `Keine`). Both: `plans/ebusd-pv-heating-optimization.md`
  step 15.
- Outdoor calibration `ehp/OutsideTempOffset` 0 K (owner, 2026-11-21); `mc/OtShutdownLimit`
  15 °C at last read.
- Heating curve 0.14 since 2026-11-20 (0.15 until about 2026-11-14, then 0.13; owner,
  read-back confirmed), read by `sensor.geotherm_heating_curve`. `TempDesired` 22.5 (written by
  HA, 2026-11-20); the comfort control is off (owner) and Loxone `warm_enough` is ignored for now.
  Tuning: `plans/heating-curve-tuning.md`. `ehp/CompIntegral` −180 °min and `ehp/CompHysteresis` 7 K at last read:
  check `sensor.geotherm_heating_compressor_{start_integral,hysteresis}` before relying on them.

## Entity map (key entities)

| Entity | Source |
|---|---|
| `sensor.geotherm_heating_hvac_action` | `ehp/Status` field 3 (what the generator does now) |
| `sensor.geotherm_heating_hvac_mode` | `mc/OperatingMode` (configured setting) |
| `sensor.geotherm_heating_circuit_flow_temp` | `ehp/Status` field 0; liveness reference (`force_update`) |
| `sensor.geotherm_heating_flow_temp_vf2` | `ehp/FlowTemp`, VF2: the controller's flow input |
| `sensor.geotherm_heating_circuit_return_temp` | `ehp/HcReturnTemp`, slab saturation signal |
| `sensor.geotherm_heating_curve` | `mc/HeatingCurve` (slope) |
| `sensor.geotherm_heating_outdoor_temp` | `Broadcast/Outsidetemp`, the geoTHERM's own outdoor sensor; reads colder than the weatherstation (device VWS-31) |
| `sensor.geotherm_heating_circuit_flow_temp_desired_fine` | `mc/FlowTempDesired`, the curve output (0.5 K steps) |
| `sensor.geotherm_heating_circuit_flow_temp_desired` | `uih/FlowTempDesired`, its whole-degree floor W, 0 in hot water: what the integral and `sensor.heating_compressor_stop_temp` use (device VWS-33) |
| `number.geotherm_heating_temp_desired` | hand setter: read `mc/TempDesired`, write `mc/TempDesired/set` |
| `binary_sensor.geotherm_heating_compressor_running` | `ehp/Comp` |
| `binary_sensor.geotherm_heating_circuit_pump` | `ehp/Hc1Pump` |
| `sensor.geotherm_heating_energy_integral` | `ehp/Integral` (device VWS-34) |
| `sensor.geotherm_heating_compressor_start_integral`, `sensor.geotherm_heating_compressor_hysteresis` | `ehp/CompIntegral`, `ehp/CompHysteresis` (settings, no long-term statistics) |
| `sensor.heating_energy_mode` | the energy mode (see "Energy modes"); `active_heating` = compressor running for heating |
| `sensor.heating_circuit_return_temp_valid` | `ehp/HcReturnTemp`, masked during hot water and 5 min after (a package margin: the unit's return shows no tail, device VWS-12) |
| `sensor.heating_compressor_starts_daily` | daily delta of `ehp/CompStartsHc` (heating only) |
| `sensor.hot_water_compressor_starts_daily` | daily delta of `ehp/CompStartsHwc` (hot water only) |
| `select.heating_electricity_by_mode`, `sensor.heating_electricity_by_mode_<mode>` | Shelly energy per mode, daily (per-mode meter, five modes) |
| `select.heating_yield_by_mode`, `sensor.heating_yield_by_mode_<mode>` | `YieldTotal` per mode, daily (per-mode meter: `space_heating`, `water_heating`, `cooling`, `off`) |
| `sensor.space_heating_efficiency_today`, `sensor.hot_water_efficiency_today` | per-mode efficiency |
| `sensor.{heating,space_heating,hot_water}_efficiency_30d` | rolling 30-day efficiency (see "Energy modes") |
| `sensor.{heating,space_heating,hot_water}_{yield,electricity}_30d` | `sql:` 30-day kWh sums from long-term statistics |
| `binary_sensor.heating_slab_mode_wanted` | the decision |
| `sensor.heating_wanted_operating_mode` | Phase 2 wanted mode: `on` / `off` / `none` (unknown season: write nothing); reads no actual register |
| `input_number.heating_comfort_temp` | the comfort knob (no `initial:`; set in the UI) |
| `sensor.heating_target_temp` | Phase 2 wanted `mc/TempDesired` (comfort out of season, comfort + 1 in season, comfort + 1 + offset while boosting; boost only in `active_heating`) |
| `automation.heating_comfort_control` | the only writer: `ebusd/mc/OperatingMode/set`, `ebusd/mc/TempDesired/set` |
| `input_boolean.heating_comfort_control_enabled` | master switch of the writer (no `initial:`; off = no write at all) |
| `input_datetime.heating_mode_last_written` | when HA last wrote the mode: start of the 30 min hold |
| `input_datetime.heating_temp_desired_last_written` | when HA last published the setpoint: 5 min re-send guard |
| `sensor.ebusd_heating_ebusd_scan_status`, `binary_sensor.ebusd_heating_ebusd_running` | `ebusd/global/scan`, `/running` |

## Decisions in force

- **Mode law (Phase 2, `automation.heating_comfort_control`):** HA writes only `on` or `off`,
  never `auto`/`low` (the geoTHERM time program is ignored; Loxone owns the schedule). Heating
  season (`active_heating`, `neutral`): Loxone warm enough → `off`, otherwise → `on`; unknown,
  unavailable or a 24 h silent Loxone heats. A slab boost overrides to `on`, in `active_heating`
  only. Cooling season → `off` (cooling unaffected). Unknown season indicator → no write. At most
  one mode change per 30 min; setpoint changes are not held. Full table: design HPB-1. Below
  3 °C outdoor `off` still heats to `TempDesiredLow` (device VWS-6).
- **Hold = `input_datetime.heating_mode_last_written`**, never the mode sensor's `last_changed`
  (that restarts the hold on every HA restart); a hand change at the wall does not touch it. A
  fresh helper (no `initial:`) reads today 00:00 local (CONFIRMED, `input_datetime/entity.py` at
  2026.11.1): on a fresh helper the first mode write is held only before 00:30.
- **Compressor cycling: no `CompHysteresis` change for now** (owner, 2026-11-21). Targets: < 8–10
  heating starts a day, runs ≥ 20–30 min. Met in mild weather at hysteresis 7 K and start integral
  −180 °min (2026-11-14…20: ≈ 5 heating + 2 hot-water starts a day, daily mean run 22–30 min;
  baseline before: 9–11 heating starts). OBSERVED, confounded: the heating curve and `TempDesired`
  changed in the same window, and so did `CompHysteresis` (likely 6 → 7 K; dated in the
  `plans/heating-curve-tuning.md` change log). Lifetime average heating run ≈ 60 min (13277 h ÷ 13385 starts, owner
  read), so short runs are a mild-weather effect.
- **Tuning levers, in order** (if runs shorten again; one change at a time, ≥ 3 nights of similar
  weather each): (1) the heating-circuit pump speed would be the main lever but has no software
  path on SW 0383 (device VWS-23); (2) a deeper `CompIntegral` (only with `BackupModeHc` =
  `no_backup`): longer runs and pauses; (3) `CompHysteresis`, only where flow reaches the stop line
  first. Basis: runs start at `CompIntegral` and end at integral ≈ 0 or on the stop line,
  whichever comes first (device VWS-2, VWS-3, VWS-4, VWS-5).
- **Cold weather:** `CompHysteresis` is one fixed value, no weather dependency described
  (device VWS-37);
  setpoint + hysteresis can exceed `FlowTempMax` (e.g. 28 + 9 = 37 °C) while floor protection sits
  at FlowTempMax + hysteresis + 2 K (46 °C at 9 K). Rule: raise the hysteresis only moderately (8–9 K) and on the first cold days
  step it back 1 K if run-end flow temperatures approach 35 °C;
  `sensor.heating_compressor_stop_temp` plots that stop point on the "Why runs end" graph.
- **Counting compressor cycling** (owner): starts = `sensor.heating_compressor_starts_daily` +
  `sensor.hot_water_compressor_starts_daily`; runtime, 24 h duty cycle and last run read `ehp/Comp`
  in every mode; average run = runtime ÷ both starts; `sensor.heating_efficiency_today` includes
  hot water. A baseline = 3 consecutive full days of comparable weather, each day's mean outdoor
  temperature noted. Mode flips count only changes between real modes, never into/out of
  `unavailable`/`unknown` (restarts). The settings sensors have no long-term statistics: log
  `CompHysteresis`/`CompIntegral` changes (date, time, old, new) and read every number within the
  recorder's raw history (`purge_keep_days`, `configuration.yaml`).

## Energy modes

`sensor.heating_energy_mode` is owner-defined, first match wins: table in design HPB-2 (tested as
a case table in `test_energy_mode`).

- `active_heating` is NOT a run: a run rolling heating → hot water → heating gives two
  `active_heating` segments but one machine start, counted in heating (device VWS-11). Run
  statistics therefore read `ehp/Comp`, starts the machine counters.
- The electricity meter keeps all five modes (Shelly Wh about every 60 s keeps the passive
  cycle's circulation-pump draw visible); the yield meter has one `space_heating` bucket (owner).
  Misbooking at active → hot water, hot water → passive and → off is accepted (owner).
- The combined `sensor.heating_efficiency_today` (includes hot water) stays next to the per-mode
  ones (owner); all daily efficiencies render `unknown`, not 0, below 1 kWh electricity (owner).
- **Rolling 30 days** (owner): `space_heating_yield_30d` also sums the pre-merge statistics
  `sensor.heating_yield_by_mode_active_heating`/`_passive_heating`. Do not delete them from
  long-term statistics until 30 days after #164 is deployed, or the window shrinks.

## Known biases / open issues

- Keep the dual name/number parsing of enums (incl. raw `1` → `cooling`): the catalog generation
  is the current one (device VWS-32), but some enums arrive as numbers (device VWS-44).
- `automation.heating_slab_charge_decision_changed` still says "Phase 1 — observation only,
  nothing was written" (message and `description:`), but with both switches on the decision IS
  written (Invariants "Two switches"). Fixing it changes the automation's output: do it with a
  test of the message.

## Tests

Package-specific test facts: `doc/heating_pv_boost/tests.md` (loads with the test files).

## Related

- `doc/heating_pv_boost/design.md` (control law, energy modes); the unit:
  `doc/devices/vaillant-vws-83-2/`.
- `plans/ebusd-pv-heating-optimization.md` (rollout),
  `plans/heating-baseline-and-phase2-prerequisites.md` (raw-history retention).
- Victron surplus inputs: `doc/victron/notes.md`.
