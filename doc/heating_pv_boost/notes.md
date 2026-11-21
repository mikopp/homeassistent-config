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
  - "plans/heating-*.md"
  - "plans/ebusd-*.md"
---
# heating_pv_boost.yaml — Vaillant geoTHERM via ebusd

Current facts for `packages/heating_pv_boost.yaml` (PV slab charging; Phase 1 = read-only decision
layer, Phase 2 = comfort control, the only writer, off until armed; rollout in
`plans/ebusd-pv-heating-optimization.md`).
**Design** (on demand): `doc/heating_pv_boost/design.md`: HPB-1 control law (read it before
changing `sensor.heating_wanted_operating_mode`, `sensor.heating_target_temp` or
`automation.heating_comfort_control`), HPB-2 energy-mode table.
**Register decodes** (field lists, enums, unusable registers, tuning and cooling registers):
`doc/heating_pv_boost/registers.md`, not auto-loaded; read it before adding or parsing
a register. **Heating curves** (manufacturer diagram and table, VWS 83/2):
`doc/heating_pv_boost/heating-curve.md`; read it before reasoning about the flow setpoint.

Source of truth for ebusd definitions: the **published** catalog
`https://ebus.github.io/de/vaillant/*.csv` (what ebusd ≥ 24.1 downloads and runs), checked
against a full `ebusctl` dump of the live bus. **Never use the `archived/` CSVs** of a local
`john30/ebusd-configuration` checkout: a frozen snapshot that diverges from the served config.

## Invariants

- **Every new ebusd register needs TWO Mosquitto bridge lines** on the HA broker host:
  `topic ebusd/<circuit>/<name> in 0` and `topic ebusd/<circuit>/<name>/get out 0`; every register
  HA **writes** also needs `topic ebusd/<circuit>/<name>/set out 0` (Phase 2: `mc/OperatingMode`,
  `mc/TempDesired`). Then **restart** Mosquitto (a reload does not load bridge changes). Without
  `in` the sensor stays `unavailable`; without `/get out` the `?N` poll silently never arrives;
  without `/set out` a write fails silently. List the exact lines in the PR's post-deploy steps.
  Prove a new `/set` line with an idempotent write of the CURRENT value only.
  **Exception, broadcasts** (catalog type `u`, e.g. `Broadcast/Outsidetemp`): ebusd only decodes
  them passively, they cannot be read on request, so only the `in` line and no `?N` poll. The
  topic keeps the catalog's case (`ebusd/Broadcast/Outsidetemp`, owner MQTT view).
- **Every register HA reads gets a `?N` in `automation.heating_ebusd_poll_registration`** (and in
  the `_POLLS` literal of `tests/ha/test_heating_pv_boost_ebusd_registers.py`), or it is never
  polled (or no longer after the next ebusd restart, see "Polling").
- **Do NOT enable `--mqttjson`.** The Loxone integration consumes the same topics as plain
  `;`-separated values. Multi-field messages are parsed positionally; document the field list
  inline at every such sensor. Field *position* is stable across config generations even where
  field *names* are not.
- **Every enum read accepts both forms** (decoded name or raw number), mapping through one table;
  unmapped → `unknown`. Which form arrives is not predictable from the declared type (live:
  `mc/OperatingMode` reads `low`, `mc/CoolingRequestHc2` reads `0`). **Writes take names**
  (`on`, `off`); never echo a normalised read back on a write.
- **Never register a poll priority while `ebusd/global/scan` reads `running`** (owner-confirmed):
  the catalog may be mid-discovery. Gate on `scan != 'running'`, never on an allowlist of resting
  values: ebusd does not document which one it settles on (owner sees `finished`; the YAML also
  accepts `OK`).
- **`input_number.heating_comfort_temp` is the only comfort knob while the writer is armed.**
  Every setpoint the writer writes is derived from it. With the writer off, the owner sets
  `mc/TempDesired` by hand with `number.geotherm_heating_temp_desired`; it writes only on a
  change by hand, never on a read-back. While the writer is armed, `mc/TempDesired` or `mc/OperatingMode` set at the
  wall is overwritten when its read-back reaches HA: the mode once the 30 min hold allows (the
  hold's end re-triggers), the setpoint unless HA published one in the last 5 min (then only at
  the next input change: there is no periodic re-check). The target is always absolute, never
  "current + offset" (a relative write compounds on a retry or a restart mid-boost).
- **`mc/TempDesiredLow` gets no HA logic** (not read, derived from or written): it is the
  machine's frost floor (see "Frost protection"), set by hand at the panel. Deriving comfort from
  it would force it to comfort level and make `off` ineffective below 3 °C.
- **Two switches arm hardware writes.** `input_boolean.heating_comfort_control_enabled` arms the
  writer; with `input_boolean.heating_pv_boost_enabled` also on, a slab decision writes mode `on`
  and comfort + 1 + offset (HPB-1 row 3), so the slab boost acts through the Phase 2 writer
  without a Phase 3 automation.
- **No hysteresis or toggle faster than 20 min** (`ehp/TimeBetweenTwoCompStartsMin` = 1200 s).

## Hardware and integration quirks

### Bus participants

| Addr | Device | Circuits |
|---|---|---|
| 08 / 23 / 25 / 50 | geoTHERM `EHP00`, art. `0010002787`, `SW=0383 HW=7201` | `ehp`, `cc`, `hwc`, `mc` |
| 15 | control interface `UIH00` | `uih` |
| 75 | VR 90/3 remote control, art. `0020040079` | `rcc` |
| 05 | VR 920 internet module, art. `0020252922` | none: **dormant**, Vaillant discontinued the service |

The geoTHERM is a **geoTHERM exclusiv VWS 83/2** (art. `0010002787`). Manuals:
- *Bedienungsanleitung geoTHERM exclusiv VWS*, 0020025604_00 (02/2007), covers VWS 63/2, 83/2,
  103/2: https://kontakt.vaillant.de/documents/download/73792/ (heating curves p. 21, room setpoint
  shift p. 18; owner's printed copy matches).
- *Installationsanleitung geoTHERM exclusiv VWS*, 0020045204_01 (07/2008; VWS 83/2 in the type
  table p. 63): https://kontakt.vaillant.de/documents/download/73782/ (energy balance p. 48,
  floor protection p. 46, menus C2 p. 58, C4/C5 p. 59, calibration p. 65, compressor/FlowTempMax
  p. 69). Revision _00 (02/2007, …/73781/) still shows menu C9 (frost delay, Temp.überhöhung).
- Successor /3 manual 0020087974_00 (…/78824/): only for what the /2 ones omit (frost end 4 °C,
  0.1 curve), graded as sibling. The site refuses plain `curl`; a browser user agent works.
- Heating curves, table and formula: `doc/heating_pv_boost/heating-curve.md`.

There is **no VRC 700 and no `700` circuit**, so `Hc1RoomCircuitMode`, `Z1DayTemp` and friends do
not exist. The VR 90 writes to the bus but accepts and keeps a value HA writes, so HA is the sole
effective writer of the control registers. SW 0383 is below 407: any catalog entry gated
`[id_sw>=…]` above 383 does not apply; the heating-circuit pump speed cannot be read or set over
ebus (owner `ebusctl info`).

### Transport

ebusd publishes to its own broker; HA's broker pulls data in through a Mosquitto bridge that lists
**every topic individually** (owner-supplied live config): no `ebusd/#` wildcard in either
direction; `ebusd/global/running` and `ebusd/global/scan` are `in` only. Only topics HA needs are
bridged: keep it that way rather than widening to `ebusd/#`.

### Polling

- `?N` (N = 1-9) to `ebusd/<circuit>/<name>/get` reads now AND enables ongoing polling at
  priority N; an empty payload is a one-time read only. Priority is a relative weight ("every Nth
  poll cycle"), not seconds.
- **A runtime-set priority does not survive an ebusd restart** (owner-confirmed); the
  registration automation re-asserts every one (triggers: its YAML).
- ebusd process status is retained under `ebusd/global/*`: `running` (`true`/`false`, `false` as
  MQTT last-will), `scan` (`running` during discovery, see "Invariants"), `version`, `uptime`,
  `signal`.
- Unchanged registers are not re-reported, so the poll rate of slow registers (`TempDesired`
  etc.) cannot be read back from HA.

### Compressor and measurements

- **`hcmode` is not the compressor.** It stays `heat` while the circulation pump idles between
  runs; run statistics and the energy mode read `ehp/Comp`. The Shelly clamp
  `sensor.technikraum_heizung_heizung_power` (Pro 3EM) is the electrical view, used for the PV
  surplus: idle circulation ~83 W, standby ~9 W, heating ~1.8 kW, hot water ~3.5 kW
  (owner-confirmed / measured). Pump state is `ehp/Hc1Pump`, as in the owner's Loxone logic
  (which also uses `ehp/ActualEnvironmentPower` > 1; HA does not).
- **No electrical-power or modulation register.** `ehp/Comp` is on/off and
  `ActualEnvironmentPower` is thermal display data, so the Shelly is the only electrical
  measurement.
- **No buffer tank.** `uih/EhpHeatBufferAvailable` is `off`, both storage sensors read `cutoff`.
  The slab is the only thermal store, which is why `ehp/HcReturnTemp` reads its charge state.
- **Resistive backup exists, disabled for heating:** `ehp/BackupType` = `internalheatandwater`,
  `ehp/BackupModeHc` = `no_backup`, `ehp/BackupIntegral` −600. Never used in this house (owner),
  so HA reads no backup register and has no backup gate. It must stay `no_backup` while
  `CompIntegral` is deepened (start point = BackupIntegral + CompIntegral, registers.md).
- Compressor timing: `TimeBetweenTwoCompStartsMin` 1200 s, `TimeCompOffMin` 300 s,
  `TimeCompOnMin` 240 s.
- Limits, not tuning targets: `mc/FlowTempMax` 35 °C caps the setpoint the circuit may request;
  **floor protection** = FlowTempMax + `CompHysteresis` + 2 K (now 44 °C = `mc/FloorProtectionLimit`),
  measured at VF2: above it for > 15 min the heat pump stops with error 72 until reset
  (Installationsanleitung 0020045204_01 p. 46, p. 69). So a higher hysteresis also raises the floor
  limit. `ehp/ReturnTempMax` 46 °C blocks the compressor on return temperature (p. 69).
  `mc/OtShutdownLimit` 15 °C is most likely the C2 "AT-Abschaltgrenze" (summer cut-off, p. 58;
  name match and `mc/Params` field, UNPROVEN until read on the panel).
- **The controller regulates on VF2** (`ehp/FlowTemp`, `sensor.geotherm_heating_flow_temp_vf2`):
  the energy integral is VF2 − flow setpoint per minute (p. 59), floor protection reads VF2. The
  panel's "Vorlauftemp. IST" and `ehp/Status` field 0 are the internal T6.

### Heating and cooling are separate mode axes

`mc/OperatingMode` is heating only, so writing it cannot disturb cooling
(`mc/CoolingOperatingModeHc2`). Interlock on the cooling activity signals (`uih/CoolingDemand`,
`mc/CoolingRequestHc2`, `uih/CoolingActive`), **never on the setting**
`mc/CoolingOperatingModeHc2`: it reads `On` all summer and would disable heating permanently if
not maintained seasonally. Cooling is released on **outdoor** temperature, so writing
`mc/TempDesired` does not move the threshold. Thresholds and changeover delays: registers.md.

### Frost protection: `off` still heats below 3 °C

Below 3 °C outdoor (the geoTHERM's own sensor) with no time window active (`off`, or `eco`
outside a window), after a delay (default 1 h; register `uih/FrostOverRideTime`, catalog
`15.uih.csv` "Frostschutzverzögerung", hours, installer write; set on the unit only, HA does not
read it), the controller requests flow temperature for the room setpoint `mc/TempDesiredLow`
(Bedienungsanleitung 0020025604_00 p. 10; delay menu C9, 0–12 h, Installationsanleitung _00 p. 59).
It ends above 4 °C per the /3 manual only (0020087974_00 p. 58; no /2 statement). The panel shows
"Frostschutz Heizung" in menu 1 while active. The floor pump runs and the compressor starts (owner-verified). So with Phase 2's `off` the dashboard shows mode
`off`, hcmode `heat`, `Hc1Pump` on, energy mode `passive_heating`/`active_heating`: correct, not
a bug. HA cannot stop it; only a lower `TempDesiredLow` limits it (owner: accepted). Whether the
room temperature is ignored then is UNPROVEN (likely, with Raumaufschaltung `Keine`).

### Room influence

- **Raumaufschaltung is `Keine`** (owner-confirmed): controller menu C5 (shown only with a VR 90)
  or the VR 90; not a cataloged ebusd register. Options (Installationsanleitung 0020045204_01
  p. 59): `Keine` ignores the VR 90 room temperature for heating; `Aufschaltung` shifts the curve's
  flow setpoint by (room desired − actual), so a warm room weakens a slab boost (factor
  undocumented); `Thermostat` stops heating at room desired + 1 K (/3 manual p. 68: not for
  energy-balance control), which would block a boost. Keep `Keine`: Loxone's `warm_enough` is the only comfort input.
- `mc/RoomTempOffset` is write-only (registers.md), so unusable as a lever.

## Owner-side configuration

- Loxone does **not** write `mc/OperatingMode`; it publishes `loxone/heating/warm_enough`
  **retained**, on change and re-sent **every hour** (owner). Loxone does not control room valves.
- **All loops and valves are open, bedrooms not throttled** (owner). Low water flow
  is a pump matter, not a closed valve.
- `mc/OperatingMode` = **`on`**, set by hand until Phase 2 is armed.
- Frost protection kept small (owner-stated, set at the unit): `uih/FrostOverRideTime` 3 h,
  `mc/TempDesiredLow` 20 °C (TDL read 20 live before HA stopped reading it). The owner's reading
  "it then kicks in only every 3 h while `off`" is UNPROVEN: catalog and manual call it a delay
  and say nothing about a repeat cycle.
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
| `sensor.geotherm_heating_curve` | `mc/HeatingCurve` (slope, set at the panel) |
| `sensor.geotherm_heating_outdoor_temp` | `Broadcast/Outsidetemp` = the value of `ehp/OutsideTemp`, the geoTHERM's outdoor sensor (owner: one and the same, so `ehp/OutsideTemp` is not read separately); the sensor sits on the north side without sun (owner); read 0.65 K below the weatherstation (3.75 vs 4.4 °C; owner, 2026-11-21 evening, one reading) |
| `sensor.geotherm_heating_circuit_flow_temp_desired_fine` | `mc/FlowTempDesired` (0.5 K steps; the same setpoint `Status0a` field 4 gives in whole °C, owner forced reads) |
| `number.geotherm_heating_temp_desired` | hand setter: read `mc/TempDesired`, write `mc/TempDesired/set` |
| `binary_sensor.geotherm_heating_compressor_running` | `ehp/Comp` |
| `binary_sensor.geotherm_heating_circuit_pump` | `ehp/Hc1Pump` |
| `sensor.heating_energy_mode` | the energy mode (see "Energy modes"); `active_heating` = compressor running for heating |
| `sensor.heating_circuit_return_temp_valid` | `ehp/HcReturnTemp`, masked during hot water and 5 min after |
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
  3 °C outdoor `off` still heats to `TempDesiredLow` ("Frost protection").
- **Hold = `input_datetime.heating_mode_last_written`**, never the mode sensor's `last_changed`
  (that restarts the hold on every HA restart); a hand change at the wall does not touch it. A
  fresh helper (no `initial:`) reads today 00:00 local (CONFIRMED, `input_datetime/entity.py` at
  2026.11.1): on a fresh helper the first mode write is held only before 00:30.
- **Compressor cycling: no `CompHysteresis` change for now** (owner, 2026-11-21). Targets: < 8–10
  heating starts a day, runs ≥ 20–30 min. Met in mild weather at hysteresis 7 K and start integral
  −180 °min (2026-11-14…20: ≈ 5 heating + 2 hot-water starts a day, daily mean run 22–30 min;
  baseline before: 9–11 heating starts). OBSERVED, confounded: the heating curve and `TempDesired`
  changed in the same window. Lifetime average heating run ≈ 60 min (13277 h ÷ 13385 starts, owner
  read), so short runs are a mild-weather effect.
- **Tuning levers, in order** (if runs shorten again; one change at a time, ≥ 3 nights of similar
  weather each): (1) the heating-circuit pump speed would be the main lever but has no software
  path on SW 0383 ("Bus participants"); (2) `CompHysteresis` is the software lever for run length;
  (3) a deeper `CompIntegral` (only with `BackupModeHc` = `no_backup`) moves the start, not the
  stop. Model behind (2) and (3), HYPOTHESIS from one day of runs: at a mild setpoint the flow sits
  at return + ≈ 8 K spread, so a run ends on flow > setpoint + hysteresis before the integral is
  repaid, and the next start follows from the integral drain whatever the start threshold; a
  deeper `CompIntegral` cuts starts only once runs end on the integral (≈ 0 at the stop).
- **Cold weather:** `CompHysteresis` is one fixed value (p. 69; no weather dependency described);
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
  `active_heating` segments but one machine start, counted in heating (OBSERVED, one run). Run
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

- Which ebusd config generation this instance runs is unconfirmed; an older one sends `ehp/Status`
  field 3 as raw `1` for cooling (registers.md). Keep the dual name/number parsing (incl. raw
  `1` → `cooling`) as cheap insurance.
- The setpoint payload with one decimal (`22.0`) is UNPROVEN against ebusd: prove it with the
  idempotent write of the current value before arming.
- `mc/FlowTempMax` caps the setpoint (Installationsanleitung _01 p. 69); no compressor stop at it
  is documented, the hard stop is floor protection ("Compressor and measurements").
- `automation.heating_slab_charge_decision_changed` still says "Phase 1 — observation only,
  nothing was written" (message and `description:`), but with both switches on the decision IS
  written (Invariants "Two switches"). Fixing it changes the automation's output: do it with a
  test of the message.

## Tests

Package-specific test facts: `doc/heating_pv_boost/tests.md` (loads with the test files).

## Related

- `doc/heating_pv_boost/design.md` (control law, energy modes), `doc/heating_pv_boost/registers.md`
  (register decodes).
- `plans/ebusd-pv-heating-optimization.md` (rollout),
  `plans/heating-baseline-and-phase2-prerequisites.md`.
- Victron surplus inputs: `doc/victron/notes.md`.
