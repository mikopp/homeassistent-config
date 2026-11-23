# Vaillant geoTHERM exclusiv VWS 83/2: registers of the generator (`ehp`)

Covers the register definitions of circuit `ehp` (`08.ehp.csv`) and the compressor-timing
entries of `50.ehp.mc.csv` listed with them; indexed by `interface.md`. What the unit does with them: `behaviour.md`
and its parts. No entity ids. Decodes from the published catalog [CAT], checked against a full
`ebusctl` dump of this bus [T2] [T3]; all answer a forced read here unless listed in
`interface.md` `## Unusable on this unit` [T8].

## Status and temperatures

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| VWS-32 | `ehp/Status` | fields `temp;press;press_1;hcmode;hex` [T51]: flow T6 °C, bar, bar = the values of `ehp/HcFlowTemp`, `HcPress`, `SourcePress` [T2]; enum; raw hex | `hcmode` `0=off 1=cooling 3=heat 4=water` here [T51], name or number (VWS-44); the archived catalog names it `hcmode2` without `1` [CAT] | r | [CAT] [T2] [T51] |
| | `ehp/HcReturnTemp` | register `0A00`, internal sensor T5: `temp;sensor` | sensor `ok\|circuit\|cutoff`; reads the hot-water circuit during a hot-water charge (VWS-12) | r | [CAT] [T32] |
| | `ehp/FlowTemp` | VF2, external flow sensor: `temp;sensor`; a different register from the `ehp/Status` flow field (T6) | the controller's flow input (VWS-18) | r | [CAT] [T13] |
| | `ehp/OutsideTemp` | `b509 0d0600`: outdoor temp + sensor status | same value as `Broadcast/Outsidetemp` | r | [CAT] [T14] |
| | `ehp/OutsideTempOffset` | outdoor calibration: read `b509 0dc300`, write `0ec300` (installer), `D2C` (1/16 K) | `uih` and `mc` have no offset register; non-integer writes untested (VWS-36) | rw | [CAT] [T14] |
| | `ehp/ReturnTempMax` | return limit, °C (VWS-9) | 46 here (`behaviour.md` Settings) | r | [CAT] [T4] |
| | `ehp/PowerCut` | `b509 0d1100`, `UCH`: EVU block ("Stromunterbrechung", vrDIALOG status [IA p.68]) | `0=no 1=yes`; not SW-gated in the catalog; answers forced reads on this unit, `no` at the last read [T53] | r | [CAT] [T53] |

## Compressor, energy balance and counters

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| VWS-34 | `ehp/Integral` | running energy integral, Σ(VF2 − W) per minute, °min, `SIN`; W = `uih/FlowTempDesired` (VWS-3) | signed, not clamped (VWS-5) | r | [CAT] [T18] [T19] |
| | `ehp/CompIntegral` | "Komp. Start in": integral at which the compressor starts (installer), °min | negative | rw | [CAT] |
| | `ehp/CompHysteresis` | compressor hysteresis, K (VWS-4) | — | rw | [CAT] |
| | `ehp/BackupIntegral`, `ehp/BackupType`, `ehp/BackupModeHc` | backup heater start offset (VWS-20), type, heating use | `behaviour.md` Settings | r | [CAT] [T4] |
| | `ehp/CompDemand` | regulation wants the compressor | `0=no 1=yes` | r | [CAT] |
| | `ehp/Comp` | compressor now ("Status Kompressor: AN/AUS") | on/off | r | [CAT] |
| | `ehp/Hc1Pump` | heating-circuit pump now ("Status Heizkreispumpe: AN/AUS") | on/off, arrives as `0`/`1` (VWS-44) | r | [CAT] [T42] |
| | `ehp/CompStartsHc`, `ehp/CompStartsHwc` | lifetime heating / hot-water starts ("Compressor_Commutations_DHW") | they add up to the compressor starts (VWS-11) | r | [CAT] [T9] [T30] |
| | `ehp/CompHoursHc`, `ehp/CompHoursHwc` | lifetime heating / hot-water hours | whole hours | r | [CAT] [T8] |
| VWS-29 | `ehp/YieldTotal` | lifetime heat, heating + hot water, kWh | whole kWh; the only yield register: no per-mode yield. No electrical-power or modulation register exists: `ehp/Comp` is on/off, `ehp/ActualEnvironmentPower` is thermal display data | r | [CAT] |
| | `NumberCompStarts` | max starts per hour; sets `TimeBetweenTwoCompStartsMin` | 3–5 [IA p.69] | rw | [CAT] |
| | `TimeBetweenTwoCompStartsMin`, `TimeCompOffMin`, `TimeCompOnMin` | compressor timing, s | `behaviour.md` Settings | r | [CAT] [T4] |
| | `HwcLaggingTime` | "WP Nachlaufzeit WW": run-on after a hot-water charge, min (VWS-13) | 3 here | r | [CAT] [T9] |
