---
paths:
  - "packages/heating_pv_boost.yaml"
  - "tests/ha/test_heating_pv_boost.py"
  - "tests/e2e/test_restart.py"
  - "dashboards/heating-dashboard.yaml"
  - "plans/heating-*.md"
  - "plans/ebusd-*.md"
---
# heating_pv_boost.yaml — Vaillant geoTHERM via ebusd

Current facts for `packages/heating_pv_boost.yaml` (PV slab charging; Phase 1 = read-only, nothing
written yet; rollout in `plans/ebusd-pv-heating-optimization.md`). No design doc yet.
**Register decodes** (field lists, enums, unusable registers, tuning and cooling registers):
`doc/heating_pv_boost/registers.md`, not auto-loaded; read it before adding or parsing
a register.

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
- **Do NOT enable `--mqttjson`.** The Loxone integration consumes the same topics as plain
  `;`-separated values. Multi-field messages are parsed positionally; document the field list
  inline at every such sensor. Field *position* is stable across config generations even where
  field *names* are not.
- **Every enum read accepts both forms** (decoded name or raw number), mapping through one table;
  unmapped → `unknown`. Which form arrives is not predictable from the declared type (live:
  `mc/OperatingMode` reads `low`, `mc/CoolingRequestHc2` reads `0`). **Writes take names**
  (`auto`, `on`); never echo a normalised read back on a write.
- **Never register a poll priority while `ebusd/global/scan` reads `running`** (owner-confirmed):
  the catalog may be mid-discovery. `automation.heating_ebusd_poll_registration` gates every
  trigger on `scan != 'running'` (not an allowlist of resting values: whether the steady state is
  `finished` or `OK` is undocumented).
- **`mc/TempDesiredLow` is the only human knob.** Every setpoint HA writes is derived from it,
  so `mc/TempDesired` set at the wall will be overwritten. The target is always absolute, never
  "current + offset".
- **Never spend PV surplus while `ehp/Backup` is on** (resistive heat ≈ ¼ the heat per kWh).
- **No hysteresis or toggle faster than 20 min** (`ehp/TimeBetweenTwoCompStartsMin` = 1200 s).

## Hardware and integration quirks

### Bus participants

| Addr | Device | Circuits |
|---|---|---|
| 08 / 23 / 25 / 50 | geoTHERM `EHP00`, art. `0010002787`, `SW=0383 HW=7201` | `ehp`, `cc`, `hwc`, `mc` |
| 15 | control interface `UIH00` | `uih` |
| 75 | VR 90/3 remote control, art. `0020040079` | `rcc` |
| 05 | VR 920 internet module, art. `0020252922` | none: **dormant**, Vaillant discontinued the service |

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
- **A runtime-set priority does not survive an ebusd restart** (owner-confirmed), so the
  registration automation re-asserts all of them on HA start, ebusd running, bus data back, and
  scan finished/OK. Every register is registered, including `ehp/Status` (it goes quiet while the
  compressor idles).
- ebusd process status is retained under `ebusd/global/*`: `running` (`true`/`false`, `false` as
  MQTT last-will), `scan` (`OK`/`running`/`finished`), `version`, `uptime`, `signal`.
- Unchanged registers are not re-reported, so the poll rate of slow registers (`TempDesiredLow`
  etc.) cannot be read back from HA.

### Compressor and measurements

- **Compressor activity comes from the Shelly clamp, not ebus.** `hcmode` stays `heat` while the
  circulation pump idles between runs. `sensor.technikraum_heizung_heizung_power` (Shelly Pro 3EM):
  idle circulation ~83 W, standby ~9 W, heating ~1.8 kW, hot water ~3.5 kW (owner-confirmed /
  measured); threshold 500 W. Loxone's own status logic additionally uses
  `ehp/ActualEnvironmentPower` (> 1 → active) and `ehp/Hc1Pump`; HA deliberately polls neither.
- **No electrical-power or modulation register.** `ehp/Comp` is on/off and
  `ActualEnvironmentPower` is thermal display data, so the Shelly is the only electrical
  measurement.
- **No buffer tank.** `uih/EhpHeatBufferAvailable` is `off`, both storage sensors read `cutoff`.
  The slab is the only thermal store, which is why `ehp/HcReturnTemp` reads its charge state.
- **Resistive backup exists:** `ehp/BackupType` = `internalheatandwater`, currently `no_backup`
  on both circuits.
- Compressor timing: `TimeBetweenTwoCompStartsMin` 1200 s, `TimeCompOffMin` 300 s,
  `TimeCompOnMin` 240 s.
- Thermal ceilings are hardware protections, not tuning targets: `mc/FlowTempMax` 35 °C,
  `mc/FloorProtectionLimit` 44 °C, `ehp/ReturnTempMax` 46 °C, `mc/OtShutdownLimit` 15 °C.

### Heating and cooling are separate mode axes

`mc/OperatingMode` is heating only ("Betriebsmodus Heizen"); cooling is
`mc/CoolingOperatingModeHc2`, so writing the heating mode cannot disturb cooling. Cooling has
three stages: the setting `mc/CoolingOperatingModeHc2` (reads `On` all summer), the raw need
`uih/CoolingDemand`, and the gated request `mc/CoolingRequestHc2`. Use the activity signals as
interlocks, **never block on the setting** (it would disable heating permanently if not
maintained seasonally). Cooling is released on **outdoor** temperature (15 + 2 = 17 °C), so
writing `mc/TempDesired` does not move the threshold. Heating/cooling changeover delays are 6 h
on the machine.

### Room influence

- `mc/RoomTempOffset` (`b505 2d`) is write-only, so unusable as a lever. Do not confuse it with
  `rcc/RoomTempOffset` (`1f00`, VR 90 sensor calibration): two registers sharing a name.
- A "Raumaufschaltung: off/thermostat" toggle exists and is ebus-communicated (owner switches it
  at the VR 90 and the geoTHERM panel), but it is **not a cataloged register**; its literal ebus
  write is unknown. Whether it only gates the VR 90 writing `mc/RoomTempOffset` is UNPROVEN.
- **Owner action (open):** set Raumaufschaltung to **off** (current value unconfirmed); this
  design does not use room trim (Loxone's `warm_enough` is the only comfort input), and in
  "thermostat" it may undercut a boost. Raising `mc/TempDesired` overcomes the additive offset by
  construction, so a boost is never blocked, only possibly less effective; no declared max
  magnitude for the offset exists.
- To settle the mechanism: watch `ebusd/mc/RoomTempOffset` (or
  `ebusctl read -f -c mc RoomTempOffset`) while toggling at the VR 90. HA driving the toggle
  would need its literal write, found only by a live capture during a toggle.
- Holiday mode and `mc/Party` are unused (no Party button on the VR 90; holiday dates are 2015).

## Owner-side configuration

- Loxone **no longer writes** `mc/OperatingMode`; it publishes `loxone/heating/warm_enough`
  (on change only, no heartbeat). Loxone does not control room valves.
- **All loops and valves are open, bedrooms not throttled** (owner). Low water flow
  is a pump matter, not a closed valve.
- `mc/OperatingMode` = **`auto`** with the Vaillant's own time program (`on` by day, `low` at night).
- Heating curve 0.15; `ehp/CompIntegral` −180 °min (was −150); `ehp/CompHysteresis` 7 K at last
  read (forced stop at setpoint + 7, e.g. 31 °C at a 24 °C setpoint; the 8–9 K cap below is
  relative to this). Check `sensor.geotherm_heating_compressor_hysteresis` before relying on it.
- **Backup heater disabled for heating:** `ehp/BackupModeHc` = `no_backup`,
  `ehp/BackupIntegral` = −600 (plain `-600`). While `no_backup`, deepening `CompIntegral` cannot
  start it (if enabled, it would start at −600 + CompIntegral, now −780).

## Entity map (key entities)

| Entity | Source |
|---|---|
| `sensor.geotherm_heating_hvac_action` | `ehp/Status` field 3 (what the generator does now) |
| `sensor.geotherm_heating_hvac_mode` | `mc/OperatingMode` (configured setting) |
| `sensor.geotherm_heating_circuit_flow_temp` | `ehp/Status` field 0; liveness reference (`force_update`) |
| `sensor.geotherm_heating_circuit_return_temp` | `ehp/HcReturnTemp`, slab saturation signal |
| `sensor.geotherm_heating_temp_desired_low` | `mc/TempDesiredLow` |
| `binary_sensor.heating_compressor_active` | Shelly > 500 W (any run) |
| `binary_sensor.heating_compressor_heating_active` | Shelly > 500 W and `hvac_action` ≠ `water` |
| `sensor.heating_compressor_starts_daily` | daily delta of `ehp/CompStartsHc` (heating only) |
| `binary_sensor.heating_slab_mode_wanted` | the decision |
| `sensor.ebusd_heating_ebusd_scan_status`, `binary_sensor.ebusd_heating_ebusd_running` | `ebusd/global/scan`, `/running` |

## Decisions in force

- **Mode law (Phase 2):** `auto` is normal operation; HA writes `on` only for Loxone "not warm
  enough" or a slab boost, then back to `auto`, never `low` (by day both give the same setpoint).
  In cooling season (`passive_cooling`/`active_cooling`) HA sets the heating mode `off` (cooling
  unaffected), `auto` again in `neutral`/`active_heating`; never `off` on an unknown indicator.
  Slab boost only in `active_heating` (shoulder season mostly overheats). See the slab plan's
  "Control law".
- **Compressor tuning (cycling plan):**
  - Lifetime average heating run ≈ 60 min (13277 h ÷ 13385 starts): short runs are a
    mild-weather effect.
  - Hysteresis headroom is small: at a 24 °C setpoint and `FlowTempMax` 35 °C the hysteresis can
    usefully grow to about 11 K, less when colder weather raises the setpoint.
  - **Cold weather** (reasoned, not measured): `CompHysteresis` is fixed, the Vaillant does not
    adapt it. Cold-weather runs most likely end by integral payback; the hysteresis mainly shapes
    mild-weather runs. Setpoint + hysteresis can exceed `FlowTempMax` (e.g. 28 + 9 = 37 °C);
    the floor stays protected by 44 °C / 46 °C. **Unknown** whether `FlowTempMax` also stops the
    compressor or only caps the setpoint. Rule: raise the hysteresis only moderately (8–9 K) and
    on the first cold days step it back 1 K if run-end flow temperatures approach 35 °C;
    `sensor.heating_compressor_stop_temp` plots that stop point on the "Why runs end" graph.
  - **Start vs stop (HYPOTHESIS, not measured):** `CompIntegral` only sets when a run starts; a
    run ends at integral payback or flow > setpoint + `CompHysteresis`. At the flat curve the
    mild-weather setpoint is only a few K above room temperature, so the fixed-output compressor
    overshoots within minutes and the hysteresis ends the run: deepening `CompIntegral` lengthens
    the pause, not the run. Confirm with the integral and flow-vs-setpoint at run end.

## Baseline method (compressor-cycling comparison)

Counting rules so two baselines are comparable (plans/heating-baseline-and-phase2-prerequisites.md):

- **First full baseline day is 2026-10-31**; 2026-10-30 is partial (meters began ~16:06), exclude it.
  A baseline is 3 consecutive full days with comparable weather; note the daily mean outdoor
  temperature next to each day.
- **Starts per day:** `sensor.heating_compressor_starts_daily` (machine counter, heating only).
  `sensor.heating_compressor_runs_today` counts Shelly runs EXCLUDING hot water
  (`binary_sensor.heating_compressor_heating_active`): should roughly agree with the machine
  counter. A heating run that rolls into hot water is cut at the mode flip. Runs/runtime/duty
  cycle/last run exclude hot water; `sensor.heating_efficiency_today` still includes it (no
  DHW-free yield register). Baselines logged before 2026-11-06 counted hot-water runs too.
- **Mode flips:** count only transitions of `sensor.geotherm_heating_hvac_mode` between two values
  in {`auto`, `on`, `low`, `off`}. Ignore transitions into/out of `unavailable`/`unknown` (HA or
  MQTT restart). Normal is 2 per day (time program); more than 2 on a restart-free day is the signal.
- **Settings:** log `CompHysteresis`, `CompIntegral`, `BackupIntegral` at the start of each baseline
  day and every change (date, time, old, new). They have no long-term statistics.
- **Retention:** raw history is kept 14 days; read every number inside that window or copy it into
  the cycling plan's Observations.
- **Compressor vs circulation:** `binary_sensor.heating_compressor_active` is the Shelly clamp
  (> 500 W). `ehp/Hc1Pump` is not read; circulation alone staying below 500 W is an inference.

## Known biases / open issues

- Which ebusd config generation this instance runs is unconfirmed. An older generation (the
  `archived/` tree) leaves `ehp/Status` field 3 unnamed (`hcmode2`) with an enum lacking
  `1=cooling`, so cooling would arrive as raw `1`; the published CSVs do not have this. Keep the
  dual name/number parsing (incl. raw `1` → `cooling`) as cheap insurance.
- `ehp/Status01` times out on this unit; re-check occasionally (second return-temp reading).
- Raumaufschaltung: see "Room influence" (owner action open, mechanism unproven).

## Tests

In-process (`tests/ha/test_heating_pv_boost.py`, real broker, ebusd/Shelly/Victron payloads):
surplus, compressor and cycling formulas, cooling interlock, derived setpoint (case tables), and
on a frozen clock the DHW mask (delay_off), the slab decision (delay_on/off, master switch,
Schmitt), the last run, the real history_stats (recorder; a `history_stats.reload` test proves the values are read back from the
recorded history) and the daily meters' midnight reset.
MQTT-fed inputs (ebusd strings by name and raw enum number, Shelly Pro 3EM JSON, Venus values) go
only over the real broker; "unavailable" is a real `expire_after`. The daily meters are the real
`utility_meter`s; the 48h mean (which drives the real season indicator) and the η accumulators'
inputs outside the clock tests are seeded. `tests/e2e/test_restart.py` checks that the
`heating_electricity_daily` meter survives a real restart. The Shelly Pro 3EM entities get their
production ids on a fresh registry; other MQTT ids may not (#146).
Ten of its MQTT entities (ebusd `OperatingMode`, `CompIntegral`, `BackupIntegral`, `CompStartsHc`,
`CompHoursHc`, `global/scan`, `Backup`, `CompDemand`, `global/running`, and `loxone/heating/warm_enough`)
are never fed a message by any test: #159.

CONFIRMED: `heating_slab_mode_wanted` (delay_off 20 min) and `heating_dhw_active` (25 min) are
`unknown` after boot until the delay elapses.

## Related

- `doc/heating_pv_boost/registers.md`: register decodes.
- `plans/ebusd-pv-heating-optimization.md` (rollout, control law), `plans/heating-compressor-cycling.md`,
  `plans/heating-baseline-and-phase2-prerequisites.md`.
- Victron surplus inputs: `doc/victron/notes.md`.
