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
| | `mc/Params` | fields `tempdesired;tempdesiredlow;curve;mctype;shutdowntemp;pumpidleperiod;flowtempmin;flowtempmax;maxpreheating` [T53] | `tempdesired` is whole degrees: 21 while `TempDesired` is 21.5, so never read the room setpoint here (trap) [T53]; field 6 is `flowtempmin` (15), not a second shutdown value [T53] | r | [T13] [T53] |

## Setpoints, modes and settings

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| VWS-33 | `uih/FlowTempDesired` | system flow setpoint handed to the heat pump, `b509 0d0500`, `D2C` (1/16 K) | whole °C in practice: floor of `mc/FlowTempDesired` (26.00 at 26.5; 27.0 at 27.5 in every read for 26 min); 0 during hot water [T47] | r | [CAT] [T13] [T18] [T47] |
| | `mc/FlowTempDesired` | circuit flow setpoint (curve output), `b509 0d4600`, also passive update `2946`, `D1C` (0.5 K) | 0 during hot water | r | [CAT] [T13] [T47] |
| | `mc/TempDesired` | room setpoint, `0e3200`, `D1C` (0.5 K) | answers only with `cfgheatsinktype=1` (true here); writes one decimal (VWS-25) | rw | [CAT] [T36] |
| | `mc/TempDesiredLow` | setback room setpoint = frost floor (VWS-6) | 20.0 at the last read [T53] | rw | [CAT] [IA p.46] [T53] |
| | `mc/HeatingCurve` | curve slope, `0e3500`, `UIN` ÷ 100 (payload e.g. `0.14`) | step 0.01; same `cfgheatsinktype=1` condition, answers here | rw | [CAT] [T15] |
| | `mc/OperatingMode` | heating only ("Betriebsmodus Heizen") | `0=disabled 1=on 2=off 3=auto 4=eco 5=low`, arrives as the name (`low`, VWS-44); no cooling value | rw | [CAT] [T7] [T42] |
| | `mc/CfgHeatSinkType` | circuit type | `mixer` (raw 1) here, a misleading label: the panel's C2 "Art" shows Brennerkreis for it (direct circuit) | r | [T3] [T12] |
| | `Broadcast/Outsidetemp` | outdoor broadcast, `fe b516 01`, `D2B` °C (payload e.g. `3.750`) | passive only (VWS-40) | broadcast | [CAT] [T14] |
| | `mc/FlowTempMax`, `mc/FloorProtectionLimit` | flow cap, floor-protection limit, °C (VWS-7, VWS-8) | `behaviour.md` Settings | r | [CAT] [T4] |
| | `uih/FrostOverRideTime` | "Frostschutzverzögerung", hours, installer write (VWS-6) | 0–12 h [IA0 p.59]; 3 at the last read [T53] | rw | [CAT] [T53] |
| | `uih/EhpHeatBufferAvailable` | buffer configured | `off` here | r | [CAT] [T37] |
| | `rcc/RoomTempOffset` | `1f00`, "Raumisttemp. Korrekturwert": calibrates the VR 90's own room sensor; not `mc/RoomTempOffset` | 0.50 here, with `RoomTempOffsetSelfWarming` −2.00 | r | [CAT] [T3] |
| | `rcc/HolidayPeriod`, `rcc/RoomTempHoliday` | holiday settings | 2015 dates here (never set) | r | [T3] |

## EHP sync messages (sent unasked)

Not in the published catalog; decodes from [CATB], loaded here [T60]. The UIH polls each circuit
about every 30 s; broadcasts are passive only (VWS-40). One chain: the circuit asks (`Status31`),
the heat pump decides (`SystemMode`), the circuit is served (`Status32`); on Raumaufschaltung off
they followed 6, 8 and 15 s after the VR 90's write, `ehp/Status` hcmode after 42 s [T58].

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| | `mc/Status31` | heat/cool **demand** of the circuit | `off`, `heat`, `cool`; stays `heat` during hot water [T57]; `off` when the Raumaufschaltung Thermostat cancels heating [T58]; `cool` once, in summer [T59]. Not `mc/OperatingMode`: `heat` with it `off` [T56] | r (UIH poll; forced read answers) | [CATB] [T56] [T57] [T58] [T59] |
| | `mc/Status32` (also `cc`, `hwc`) | `state;tot24hhc2`: `state` = circuit **served** now, `tot24hhc2` °C | `state`: `off` (idle or hot water), `heat` (also with the compressor off), `cool` [T57] [T58] [T59]. Only `mc` carries it: `cc` and `hwc` are `off` always, `hwc` also during hot water (trap: the hot-water circuit does not report hot water) [T57]. `tot24hhc2` = `mc/Tot24hHc2` [T56] | r (UIH polls all three, VR 90 polls `mc`) | [CATB] [T56] [T57] |
| | `Broadcast/SystemMode` | what the heat pump is doing now | `off` (idle), `heat`, `cool`, `water`; follows `ehp/Status` hcmode within seconds, `heat` also with the compressor off [T56] [T57] [T58] [T59] | broadcast | [CATB] [T56] [T57] [T58] [T59] |
| | `Broadcast/Tot24h`, `mc/Status33` | °C; the broadcast every 60 s | the 24 h outdoor average, equal to `mc/Tot24hHc2` and `Status32` `tot24hhc2`; not the live `Broadcast/Outsidetemp` [T56] | broadcast; r | [CATB] [T56] |
| | `mc/RcRoomTemp` | written by the VR 90 cyclically, °C | the VR 90's room temperature; once equal to `rcc/RoomTemp` + `RoomTempOffset` + `RoomTempOffsetSelfWarming` (23.75 + 0.50 − 2.00 = 22.25), so probably the corrected value [T61] | passive write (VR 90 → `mc`), catalog type `uw`: cached read only, no `read -f`, no poll; missing while the CSV had `w` [T63] | [CATB] [T61] [T63] |

## Cooling

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| | `mc/CoolingOperatingModeHc2` | cooling **setting** | on through the summer, arriving as `1` (VWS-44); `off` at the last read [T62] | rw | [CAT] [T42] [T62] |
| | `mc/SetCoolingOperatingModeHc2` | the VR 90's write of the cooling setting, same values as `mc/CoolingOperatingModeHc2` | `on`, `off`, `auto`, all seen; one write per value shown while scrolling, the last of a burst is the setting (trap) [T62]; heating mode goes as `mc/SetMode` instead [T62]. Not in the loaded CSVs yet (T60) | passive write (VR 90 → `mc`) | [CATB] [T62] |
| | `uih/CoolingDemand` | raw cooling need | — | r | [CAT] |
| | `mc/CoolingRequestHc2` | gated, actually triggered request ("abhängig von der Kühlungsbetriebsart, Zeitfenstern und Effizienzfunktionen") | arrives as `0` (VWS-44) | r | [CAT] [T42] |
| | `uih/CoolingActive` | UIH "Kühlung aktiv" flag | — | r | [CAT] |
| | `mc/OtShutdownLimit` + `mc/CoolingStartOffsetHc2` | C2 "AT-Abschaltgrenze" + cooling start offset, °C (VWS-16, VWS-17) | 15 [T13] and 2 [T4] at the last reads | rw | [CAT] [IA p.58] |
| | `mc/EfficiencyHysteresisHc2Min` | flow-to-room delta for releasing cooling, not a heating-band constraint | 1.0 here | r | [CAT] [T4] |
| | `DWMOffToCoolingDelayHc2`, `DWMOffToHeatingDelayHc2` | heating/cooling changeover delays, h | 6 each here | r | [CAT] [T4] |
