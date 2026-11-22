# Vaillant geoTHERM exclusiv VWS 83/2: registers of the heating circuit and system controller

Covers the register definitions of circuits `mc` (`50.ehp.mc.csv`), `uih` (`15.uih.csv`), `hwc`,
`rcc` (VR 90/3) and the outdoor broadcast (`broadcast.csv`); indexed by `interface.md`. What the
unit does with them: `behaviour.md` and its parts. No entity ids. Decodes from the published
catalog [CAT], checked against a full `ebusctl` dump of this bus [T2] [T3].

## Multi-field messages (positional, `;`-separated, VWS-45)

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| | `mc/Status0a` | `flowtemp;mixer;pump;onoff;flowtempdesired` | field 4 = floor(`mc/FlowTempDesired`), integer °C, 0 during hot water | r | [CAT] [T25] |
| | `mc/Status` | `flowtempdesired;onoff;flowtemp;tempdesired`: no modulation field | field 3 is a second setpoint, not a percentage | r | [CAT] |
| | `hwc/Status` | `desired;onoff;actual;desired` | field 1 = generic unnamed `onoff`, the hot-water circuit state | r | [CAT] |
| | `mc/Params` | read `22;20;0.14;mixer;15;0;15;35;0` | the values match `TempDesired` 22, `TempDesiredLow` 20, `HeatingCurve` 0.14, `CfgHeatSinkType` `mixer`, `OtShutdownLimit` 15 and `FlowTempMax` 35 (field names not checked) | r | [T13] |

## Setpoints, modes and settings

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| VWS-33 | `uih/FlowTempDesired` | system flow setpoint handed to the heat pump, `b509 0d0500`, `D2C` (1/16 K) | whole °C in practice: floor of `mc/FlowTempDesired` (26.00 at 26.5; 27.0 at 27.5 in every read for 26 min) | r | [CAT] [T13] [T18] |
| | `mc/FlowTempDesired` | circuit flow setpoint (curve output), `b509 0d4600`, also passive update `2946`, `D1C` (0.5 K) | — | r | [CAT] [T13] |
| | `mc/TempDesired` | room setpoint, `0e3200`, `D1C` (0.5 K) | answers only with `cfgheatsinktype=1` (true here); writes one decimal (VWS-25) | rw | [CAT] [T36] |
| | `mc/TempDesiredLow` | setback room setpoint = frost floor (VWS-6) | — | rw | [CAT] [IA p.46] |
| | `mc/HeatingCurve` | curve slope, `0e3500`, `UIN` ÷ 100 (payload e.g. `0.14`) | step 0.01; same `cfgheatsinktype=1` condition, answers here | rw | [CAT] [T15] |
| | `mc/OperatingMode` | heating only ("Betriebsmodus Heizen") | `0=disabled 1=on 2=off 3=auto 4=eco 5=low`, arrives as the name (`low`, VWS-44); no cooling value | rw | [CAT] [T7] [T42] |
| | `mc/CfgHeatSinkType` | circuit type | `mixer` (raw 1) here, a misleading label: the panel's C2 "Art" shows Brennerkreis for it (direct circuit) | r | [T3] [T12] |
| | `Broadcast/Outsidetemp` | outdoor broadcast, `fe b516 01`, `D2B` °C (payload e.g. `3.750`) | passive only (VWS-40) | broadcast | [CAT] [T14] |
| | `mc/FlowTempMax`, `mc/FloorProtectionLimit` | flow cap, floor-protection limit, °C (VWS-7, VWS-8) | `behaviour.md` Settings | r | [CAT] [T4] |
| | `uih/FrostOverRideTime` | "Frostschutzverzögerung", hours, installer write (VWS-6) | 0–12 h [IA0 p.59] | rw | [CAT] |
| | `uih/EhpHeatBufferAvailable` | buffer configured | `off` here | r | [CAT] [T37] |
| | `rcc/RoomTempOffset` | `1f00`, "Raumisttemp. Korrekturwert": calibrates the VR 90's own room sensor; not `mc/RoomTempOffset` | 0.50 here, with `RoomTempOffsetSelfWarming` −2.00 | r | [CAT] [T3] |
| | `rcc/HolidayPeriod`, `rcc/RoomTempHoliday` | holiday settings | 2015 dates here (never set) | r | [T3] |

## Cooling

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| | `mc/CoolingOperatingModeHc2` | cooling **setting** | on through the summer, arriving as `1` (VWS-44) | rw | [CAT] [T42] |
| | `uih/CoolingDemand` | raw cooling need | — | r | [CAT] |
| | `mc/CoolingRequestHc2` | gated, actually triggered request ("abhängig von der Kühlungsbetriebsart, Zeitfenstern und Effizienzfunktionen") | arrives as `0` (VWS-44) | r | [CAT] [T42] |
| | `uih/CoolingActive` | UIH "Kühlung aktiv" flag | — | r | [CAT] |
| | `mc/OtShutdownLimit` + `mc/CoolingStartOffsetHc2` | C2 "AT-Abschaltgrenze" + cooling start offset, °C (VWS-16, VWS-17) | 15 [T13] and 2 [T4] at the last reads | rw | [CAT] [IA p.58] |
| | `mc/EfficiencyHysteresisHc2Min` | flow-to-room delta for releasing cooling, not a heating-band constraint | 1.0 here | r | [CAT] [T4] |
| | `DWMOffToCoolingDelayHc2`, `DWMOffToHeatingDelayHc2` | heating/cooling changeover delays, h | 6 each here | r | [CAT] [T4] |
