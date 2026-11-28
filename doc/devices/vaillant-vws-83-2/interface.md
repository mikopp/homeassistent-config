# Vaillant geoTHERM exclusiv VWS 83/2: interface

How this unit is reached and what it answers, independent of the packages using it; what the unit
does with a register is in `behaviour.md`. No entity ids. Generic ebusd and Mosquitto behaviour is
in the `EBD` and `MOSQ` References rows of `README.md`, not restated here. Addresses and circuits:
`README.md` Identity.

## Access

One path: eBUS → ebusd → ebusd's MQTT broker → Mosquitto bridge → HA's broker.

### Path and config

- ebusd decodes the bus with the **published** catalog, `https://ebus.github.io/de/vaillant/*.csv`
  (what ebusd ≥ 24.1 downloads and runs) [CAT], checked against a full `ebusctl` dump of this bus
  [T2] [T3]. ebusd 26.1 runs here and loads `vaillant/<addr>.<id>.csv` per scanned address
  (`08.ehp`, `15.uih`, `23.ehp.cc`, `25.ehp.hwc`, `50.ehp.mc`, `75.rcc`); `hcmode` with `1=cooling`
  shows the current generation (VWS-32) [T51]. Never the `archived/` CSVs of a `john30/ebusd-configuration` checkout: a frozen
  snapshot that diverges from the served config [CAT].
- Since 2026-11-27 ebusd here also has the CSVs compiled from the [CATB] branch at `2fd7044`, so
  it decodes the UIH's and VR 90's unasked messages (`registers-mc-uih.md` EHP sync messages)
  [T60].
- **VWS-45** Payloads on this setup are plain `;`-separated values, not JSON (`--mqttjson` off; the flag:
  [EBD]); multi-field messages are positional (field lists in `registers-*.md`) [T2]. Field
  positions are stable across catalog generations, field names are not (VWS-32) [CAT].
- ebusd's update check reports `vaillant/15.uih.csv: different version available`: the loaded
  `uih` file differs from the served one, which of the two is newer is unknown [T51].

### Addressing

- The heat pump answers forced reads (`ebusctl read -f`) of the registers in `registers-*.md`
  unless listed under `## Unusable on this unit` [T8] [T13]. Test a register on this unit with
  `read -f`, not `find` (cache) [EBD].
- **VWS-40** Broadcasts (catalog type `u`, e.g. `Broadcast/Outsidetemp`) are sent by the unit
  unasked; there is no read telegram for them, so they cannot be requested or polled [CAT].
  Passive writes another participant sends (catalog `uw`, e.g. `mc/RcRoomTemp` from the VR 90)
  likewise: cached reads only [T63].
- Write-only entries (only a `w` line in the catalog, e.g. `mc/RoomTempOffset`, `mc/Party`) have
  no read telegram; their values appear only when another participant writes them [CAT] [T5].
- Installer-level registers (`ehp/OutsideTempOffset`, `uih/FrostOverRideTime`,
  `Hc1PumpSpeedControlDirectCircuit`) need installer access for a write [CAT].

### Polling and limits

- `?N` on `/get` and the `ebusd/global/*` topics: [EBD].
- **VWS-42** A poll priority set at runtime is gone after an ebusd restart [T41].
- **VWS-43** `ebusd/global/scan` reads `running` while ebusd discovers the bus [T41] and settles
  on `finished` here (never seen `OK`) [T43]; ebusd documents no resting value [EBD].
- Registers whose value does not change are not re-published, so their poll rate cannot be read
  from MQTT; `ehp/HcReturnTemp` updates every 30–85 s [T45].
- `ehp/Comp` reports a compressor start or stop ≈ 1–2 min after the supply draw shows it (one
  heating run, 5 min statistics) [T39].

### Writes

- `mc/TempDesired` takes a one-decimal payload (`22.0`, `22.5`) and keeps it (VWS-25) [T36];
  `mc/OperatingMode` writes are accepted [T7].
- **VWS-44** Enum form per register on this setup: `mc/OperatingMode` arrives as a name (`low`),
  `mc/CoolingOperatingModeHc2` as `1`, `mc/CoolingRequestHc2` and `ehp/Hc1Pump` as `0`, though
  `ebusctl` decodes all to names [T42]: the form is not predictable from the declared type. Writes
  take the name (`on`, `off`) [ASSUMED]: `behaviour.md` Open questions.
- **VWS-41** Bridge wiring on this setup: every ebusd topic is bridged individually, no `ebusd/#`
  in either direction; `ebusd/global/running` and `/scan` are `in` only [T44]. Per register:
  `topic ebusd/<circuit>/<name> in 0` (read), `.../get out 0` (poll), `.../set out 0` (write);
  without `in` nothing arrives, without `/get out` a poll and without `/set out` a write never
  reaches ebusd, silently [MOSQ]. Broadcasts and passive writes get only `in` (VWS-40), topic in the catalog's case
  (`ebusd/Broadcast/Outsidetemp`) [T44]. A bridge change applies only when the bridge
  reconnects, so restart Mosquitto rather than reload [MOSQ].

## Registers

- `registers-ehp.md` — read before adding, polling or parsing a register of the generator
  (circuit `ehp`: status, temperatures, outdoor value and offset, compressor, energy balance,
  counters, backup).
- `registers-mc-uih.md` — read before adding, polling, parsing or writing a register of the
  heating circuit or system controller (circuits `mc`, `uih`, `hwc`, `rcc`, broadcast: setpoints,
  modes, curve, limits, cooling).

## Unusable on this unit

| ID | Register / path | Problem (timeout, placeholder data, write-only, wrong label) | Evidence |
|---|---|---|---|
| VWS-35 | `mc/Mode` | field 5 decodes `pool` while `mc/CfgHeatSinkType` and `mc/Params` say `mixer`: wrong data, do not use | [T3] |
| | `ehp/Status02` | placeholder data (`disabled;0;100.0;0;100.0`) | [T3] |
| | `ehp/Status01` | fully defined (`temp` flow, `temp_1` return, `temp_2` outside, `temp_3` hot water, `temp_4` storage, `pumpstate`) but answers `ERR: read timeout`; if it ever answers, `temp_1` is an independent return reading | [CAT] [T3] |
| | `mc/RoomTempOffset` | `b505 2d`, "Raumaufschaltung" correction: write-only (`w` entry only), plain signed `D2C` °C, no enum or mode flag, no declared max; seen only when the VR 90 writes it (0.00) | [CAT] [T3] [T5] |
| | `mc/Party` | "Quick - Party", `b505 05`, write-only, on `mc`, `hwc`, `cc`; nothing sends it here (VWS-39) | [CAT] [T6] |
| | `HcPumpStatus`, `HcPumpPWM`, `Hc1PumpSpeedControlDirectCircuit`, `Hc1PumpSpeedControlDirectCircuitWhileO` | heating-circuit pump registers in `50.ehp.mc.csv` (circuit `mc`, not `08.ehp.csv`): status (0 = speed-controlled HEP ok, ≥ 2 = no HEP), actual % (7 % = off), setpoint while the compressor runs (writable, installer), setpoint while off; need SW ≥ 407 (the last ≥ 414); absent on SW 0383 (VWS-23) | [CAT] [T1] |
| VWS-38 | `700` circuit (`Hc1RoomCircuitMode`, `Z1DayTemp` …) | no VRC 700 on this bus | [T1] |
| | Raumaufschaltung setting | the C5 / VR 90 option exists and is communicated on the bus [T40], but has no entry in the published catalog [CAT]; the VR 90 writes it to `mc` when changed, `mc/RoomTempSwitchOn` in [CATB] (`off` Keine, `thermostat` Thermostat); seen passively, never written by us [T58] | [CAT] [CATB] [T40] [T58] |
