# heating_pv_boost: ebusd register decodes

Reference for `packages/heating_pv_boost.yaml`; not auto-loaded, read or grep when adding or
parsing a register. Package facts and rules: `doc/heating_pv_boost/notes.md`.
Source: the live catalog `https://ebus.github.io/de/vaillant/*.csv` (never the `archived/` CSVs),
checked against a full `ebusctl` dump of this bus.

## Multi-field messages (positional, `;`-separated)

| Register | Fields |
|---|---|
| `ehp/Status` | `HcFlowTemp;HcPress;SourcePress;hcmode;hex` (flow T6 °C, bar, bar, enum, raw hex). Confirmed by exact value match against the standalone registers (`25.19;1.266;1.682;off;00`). `hcmode`: `0=off 1=cooling 3=heat 4=water` (an older config generation names it `hcmode2` and lacks `1`: raw `1` = cooling) |
| `ehp/HcReturnTemp` | register `0A00`, internal sensor T5: `temp;sensor`, sensor = `ok\|circuit\|cutoff` |
| `mc/Status0a` | `flowtemp;mixer;pump;onoff;flowtempdesired` (field 4 = current flow setpoint, integer °C) |
| `mc/Status` | `flowtempdesired;onoff;flowtemp;tempdesired`: no modulation field; field 3 is a second setpoint, not a percentage |
| `hwc/Status` | `desired;onoff;actual;desired` (field 1 = generic unnamed `onoff`, the DHW circuit state) |

`ehp/FlowTemp` (VF2, `temp;sensor`) is the external flow sensor the controller regulates on
(energy integral, floor protection; Installationsanleitung 0020045204_01 p. 46, p. 59), a different
register from `ehp/Status` field 0 (internal T6). Read as `sensor.geotherm_heating_flow_temp_vf2`.

## Enums

- `mc/OperatingMode` (heating only, "Betriebsmodus Heizen"): `0=disabled 1=on 2=off 3=auto 4=eco 5=low`.
- `ehp/Status` `hcmode`: see above.

## Unusable or not answered on this unit

- `mc/Mode` field 5 decodes `pool` while `mc/CfgHeatSinkType` and `mc/Params` say `mixer`: do
  not use `mc/Mode` at all. `mixer` (raw 1) is a misleading catalog label: the panel's menu C2
  "Art" shows Brennerkreis for this value (owner, 2026-11-21), a direct circuit without mixer.
- `ehp/Status02` returns placeholder data (`disabled;0;100.0;0;100.0`).
- `ehp/Status01` is fully defined (`temp` flow, `temp_1` **return**, `temp_2` outside, `temp_3`
  hot water, `temp_4` storage, `pumpstate`) but this unit answers `ERR: read timeout`. Worth an
  occasional re-check: if it ever answers, `temp_1` is an independent return-temperature reading.
- `mc/RoomTempOffset` (`b505 2d`, "Raumaufschaltung"): write-only (only a `w` entry, no `r`),
  plain signed `D2C` °C, no enum or mode flag. Visible on MQTT only because ebusd passively
  decodes the VR 90 writing it. No declared max magnitude; observed live values small (0.00).
- `rcc/RoomTempOffset` (`1f00`, "Raumisttemp. Korrekturwert"): a different register, calibrates
  the VR 90's own sensor (live 0.50, alongside `RoomTempOffsetSelfWarming` −2.00).
- `mc/Party` ("Quick - Party", `b505 05`, write-only) exists on `mc`, `hwc` and `cc`, but the VR 90
  has no Party button, so nothing triggers it on this hardware.
- `rcc/HolidayPeriod`, `rcc/RoomTempHoliday` exist; the live dump shows 2015 dates (never set).

## Compressor tuning registers

From `08.ehp.csv` and `50.ehp.mc.csv`. All answer a forced read on this unit.

| Register | Meaning |
|---|---|
| `ehp/Integral` | running energy integral, Σ(flow VF2 − flow desired) per minute, °min (`SIN`; VF2 per p. 59). The setpoint is the whole-degree one, `uih/FlowTempDesired`, not the 0.5 K `mc` value: CONFIRMED 2026-11-22 by a controlled test (`TempDesired` 22.0 → 22.5 for 30 min: `mc` 27.5, `uih` 27.0 in every forced read, integral rate −1.01/min = VF2 − 27, not VF2 − 27.5 = −1.5), plus ≈ 13 matching phases |
| `ehp/CompIntegral` | "Komp. Start in": integral at which the compressor starts (installer setting) |
| `ehp/CompHysteresis` | forced start below setpoint − hyst, forced **stop** above setpoint + hyst (no buffer = hydraulic plan 6 on the exclusiv; *Installationsanleitung* 0020045204_01 p. 63, p. 69) |
| `ehp/BackupIntegral` | backup heater starts at BackupIntegral + CompIntegral (e.g. −600 + −60 = −660); not read |
| `ehp/CompDemand` | regulation wants the compressor (0=no 1=yes) |
| `uih/FlowTempDesired` | the system flow setpoint handed to the generator (`D2C`, `b509 0d0500`; whole °C in practice): read as `sensor.geotherm_heating_circuit_flow_temp_desired`. Replaces `mc/Status0a` field 4 (same value, own poll lag). **0 during hot water**, as is `mc/FlowTempDesired` (OBSERVED 2026-11-22 17:01, one run; Status0a field 4 did the same) |
| `mc/FlowTempDesired` | the same setpoint, `D1C` (0.5 K; `b509 0d4600`, also passive update `2946`); `uih/FlowTempDesired` (`D2C`, 1/16 K) passes on floor of it (26.00 at 26.5; 27.0 at 27.5 for 26 min of forced reads, CONFIRMED 2026-11-22) |
| `ehp/CompStartsHc`, `ehp/CompHoursHc`, `ehp/YieldTotal` | lifetime heating starts, heating hours, total heat kWh (heating + hot water, whole kWh) |
| `ehp/CompStartsHwc` | lifetime hot-water starts ("Compressor_Commutations_DHW"); owner `ebusctl` read 9419 |
| `ehp/Comp` | compressor on/off now ("Status Kompressor: AN/AUS") |
| `mc/HeatingCurve` | weather-curve slope, `UIN` ÷ 100 (payload e.g. `0.14`); same `cfgheatsinktype=1` condition as `TempDesired`, answers on this unit |
| `Broadcast/Outsidetemp` | outdoor temperature broadcast (`u`, `fe b516 01`, `D2B` °C, payload e.g. `3.750`), from `broadcast.csv`; passive only, not pollable. Same value as `ehp/OutsideTemp` (`b509 0d0600`, temp + sensor status; owner), so that register is not read |
| `ehp/Hc1Pump` | heating-circuit pump on/off now ("Status Heizkreispumpe: AN/AUS"), the signal the owner's Loxone logic uses |

`ehp/YieldTotal` is the only yield register: there is no per-mode (heating / hot water) yield.
Also in the catalog, not read: `NumberCompStarts` (max starts/h, sets
`TimeBetweenTwoCompStartsMin`),
`ehp/CompHoursHwc` (DHW hours, whole hours only), `ehp/Backup*` (backup heater, never used
here), `HwcLaggingTime` ("WP Nachlaufzeit WW", owner read 3 min: pump run-on after a hot-water charge).

Heating-circuit pump registers live in **`50.ehp.mc.csv` (circuit `mc`), not `08.ehp.csv`**, and
need unit software ≥ 407: `HcPumpStatus` (0 = speed-controlled HEP ok, ≥ 2 = no HEP), `HcPumpPWM`
(actual %, 7 % = off), `Hc1PumpSpeedControlDirectCircuit` (setpoint while the compressor runs,
writable, installer), `Hc1PumpSpeedControlDirectCircuitWhileO` (SW ≥ 414, while off). This unit
runs SW 0383, so it does not have them (see the note, "Hardware").

## Cooling registers

| Register | Meaning |
|---|---|
| `mc/CoolingOperatingModeHc2` | writable cooling **setting** (reads `On` through summer) |
| `uih/CoolingDemand` | raw cooling need |
| `mc/CoolingRequestHc2` | gated, actually-triggered request ("abhängig von der Kühlungsbetriebsart, Zeitfenstern und Effizienzfunktionen") |
| `uih/CoolingActive` | UIH "Kühlung aktiv" flag |
| `mc/OtShutdownLimit` + `mc/CoolingStartOffsetHc2` | 15 + 2 = 17 °C **outdoor** cooling release (catalog). `OtShutdownLimit` is the C2 "AT-Abschaltgrenze", set seasonally: above it no heating, below it no cooling (owner); the /2 manuals describe it for heating only and cooling as a manual function |
| `mc/EfficiencyHysteresisHc2Min` | 1.0: flow-to-room delta for releasing cooling, not a heating-band constraint |
| `DWMOffToCoolingDelayHc2` / `DWMOffToHeatingDelayHc2` | both 6 h |
