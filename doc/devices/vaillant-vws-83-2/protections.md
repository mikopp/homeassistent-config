# Vaillant geoTHERM exclusiv VWS 83/2: protections and limits

Covers what stops, caps or overrides heating on its own: frost protection, floor protection,
flow and return limits, compressor timing, backup heater, outdoor shutdown; indexed by
`behaviour.md`. Only the unit, never HA; registers defined in `interface.md`; this unit's limit
values in `behaviour.md` `## Settings on this unit`.

## Frost protection

- **VWS-6** Below 3 °C outdoor (the unit's own sensor) the controller sets the setback room
  setpoint `TempDesiredLow` for every heating circuit, "in allen Betriebsarten" [IA p.46]; with no
  heating window active (`off`, or `eco` outside a window) it requests flow for it [BA p.10]. It
  starts after the delay `FrostOverRideTime` (menu C9 "Frostschutzverzög", 0–12 h, factory 1 h)
  [IA0 p.59]; IA (_01) has no frost-delay menu, its C9 is Legionellenschutz [IA p.60]. Documented as a delay only: no repeat cycle
  is described [IA0 p.59]. It ends above 4 °C per the /3 manual only [IA3 p.58]. While active,
  menu 1 can show the status "Frostschutz Heizung" [IA p.54]; on this unit the floor pump runs
  and the compressor starts [T10]. Mode `off` cannot stop it; only a lower `TempDesiredLow`
  limits it [BA p.10] [T10].

## Floor protection and flow / return limits

- **VWS-7** Floor protection on VF2: flow above max. heating-circuit temperature + compressor
  hysteresis + 2 K for > 15 min stops the heat pump with error 72 until the fault is reset and
  the flow has fallen [IA p.46] [IA p.69]. The manual gives it "bei allen Hydrauliken ohne
  Pufferspeicher (bei Hydraulikplan 6)" [IA p.46]; this unit has no buffer [T38], plan number
  open (`behaviour.md` Open questions); not tested on this unit. A higher `CompHysteresis`
  therefore raises the limit [IA p.69]. Factory limit 52 °C [IA p.46].
- **VWS-8** `FlowTempMax` ("Maximaltemperatur", factory 43 °C) caps the flow setpoint the circuit
  may request; "Minimaltemperatur" (factory 15 °C) is a separate lower limit [IA p.69]. No
  compressor stop at `FlowTempMax` is documented, the hard stop is floor protection (VWS-7)
  [IA p.69].
- **VWS-9** `ReturnTempMax` ("Max. Rücklauf-Temp. HK") blocks the compressor above that return
  temperature [IA p.69].

## Compressor timing and backup heater

- **VWS-10** Compressor timing: at most `NumberCompStarts` starts per hour (factory 3, range 3–5),
  minimum run 4 min, minimum off 5 min [IA p.69] [CAT]; this unit: 20 min between starts
  (values in `behaviour.md` `## Settings on this unit`) [T4].
- **VWS-20** The backup heater starts at `BackupIntegral` + `CompIntegral` (manual example
  −600 + −120 = −720 °min) [IA p.60] [CAT]; on this unit it is fitted but disabled for heating
  (`BackupModeHc` `no_backup`) [T4].

## Outdoor shutdown

- **VWS-17** Above `OtShutdownLimit` (C2 "AT-Abschaltgrenze", "Sommerfunktion") heating does not
  run [IA p.58]; on this unit hcmode was `off` 13:52–17:00 at ≥ 15 °C on one day, and one `off`
  spell at ≈ 13 °C is unexplained [T34]; owner: above the limit no heating, below it no cooling
  [T40].
