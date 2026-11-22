# Vaillant geoTHERM exclusiv VWS 83/2: cooling

Covers how the unit cools and how cooling is released, separate from heating; indexed by
`behaviour.md`. Only the unit, never HA; registers defined in `interface.md`; open points in
`behaviour.md` `## Open questions`.

## Cooling

- **VWS-14** Cooling is passive only: the compressor does not run for cooling [IA p.7].
- **VWS-15** Heating and cooling are separate settings: `mc/OperatingMode` is the heating mode
  ("Betriebsmodus Heizen", no cooling value) [CAT]; cooling has its own setting
  `mc/CoolingOperatingModeHc2` [CAT]. Whether heating mode `off` leaves cooling running is not
  tested: `behaviour.md` Open questions.
- **VWS-16** Cooling release: the catalog names `OtShutdownLimit` and `CoolingStartOffsetHc2`
  and `EfficiencyHysteresisHc2Min` (flow-to-room delta for releasing cooling) [CAT]; that cooling
  is released on outdoor temperature at limit + offset (15 + 2 = 17 °C at the last reads [T13]
  [T4]) is our reading [ASSUMED], and whether `TempDesired` moves it is untested (`behaviour.md` Open
  questions); owner: below the limit no cooling [T40]. The /2 manuals describe
  cooling as a manual function run for a set number of days (0–99) [IA p.47] and the C2 limit for
  heating only ("Sommerfunktion") [IA p.58]. Changeover delays `DWMOffToCoolingDelayHc2` /
  `DWMOffToHeatingDelayHc2` 6 h each [T4].
