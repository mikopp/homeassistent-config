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

`ehp/FlowTemp` (VF2) is the system-wide flow sensor, a different register from `ehp/Status`
field 0 (heating-circuit flow T6). Not read.

## Enums

- `mc/OperatingMode` (heating only, "Betriebsmodus Heizen"): `0=disabled 1=on 2=off 3=auto 4=eco 5=low`.
- `ehp/Status` `hcmode`: see above.

## Unusable or not answered on this unit

- `mc/Mode` field 5 decodes `pool` while `mc/CfgHeatSinkType` and `mc/Params` say `mixer`: do
  not use `mc/Mode` at all.
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
- Fallback for `mc/TempDesiredLow` if it never arrives: `mc/Params` field 1 (9-field parse).

## Compressor tuning registers

From `08.ehp.csv` and `50.ehp.mc.csv`. All answer a forced read on this unit.

| Register | Meaning |
|---|---|
| `ehp/Integral` | running energy integral, Σ(flow actual − flow desired) per minute, °min (`SIN`) |
| `ehp/CompIntegral` | "Komp. Start in": integral at which the compressor starts (installer setting) |
| `ehp/CompHysteresis` | forced start below setpoint − hyst, forced **stop** above setpoint + hyst (hydraulic plans 1/3 = no buffer) |
| `ehp/BackupIntegral` | backup heater starts at BackupIntegral + CompIntegral (e.g. −600 + −60 = −660); not read |
| `ehp/CompDemand` | regulation wants the compressor (0=no 1=yes) |
| `mc/Status0a` field 4 | current flow setpoint `flowtempdesired` (integer °C) |
| `ehp/CompStartsHc`, `ehp/CompHoursHc`, `ehp/YieldTotal` | lifetime heating starts, heating hours, total heat kWh (heating + hot water, whole kWh) |
| `ehp/CompStartsHwc` | lifetime hot-water starts ("Compressor_Commutations_DHW"); owner `ebusctl` read 9419 |
| `ehp/Comp` | compressor on/off now ("Status Kompressor: AN/AUS") |
| `ehp/Hc1Pump` | heating-circuit pump on/off now ("Status Heizkreispumpe: AN/AUS"), the signal the owner's Loxone logic uses |

`ehp/YieldTotal` is the only yield register: there is no per-mode (heating / hot water) yield.
Also in the catalog, not read: `NumberCompStarts` (max starts/h, sets
`TimeBetweenTwoCompStartsMin`), `mc/HeatingCurve` (conditional on `cfgheatsinktype`),
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
| `mc/OtShutdownLimit` + `mc/CoolingStartOffsetHc2` | 15 + 2 = 17 °C **outdoor** cooling release |
| `mc/EfficiencyHysteresisHc2Min` | 1.0: flow-to-room delta for releasing cooling, not a heating-band constraint |
| `DWMOffToCoolingDelayHc2` / `DWMOffToHeatingDelayHc2` | both 6 h |
