# Vaillant geoTHERM exclusiv VWS 83/2: compressor runs and hot water

Covers how heating runs start and end (energy balance, stop line, integral) and how hot-water
charges fit into runs; indexed by `behaviour.md`. Only the unit, never HA; registers defined in
`interface.md`. W = the whole-degree flow setpoint (`uih/FlowTempDesired`); "fine setpoint" =
`mc/FlowTempDesired` (0.5 K).

## Energy balance: how runs start and end

- **VWS-2** Energy balance: the controller sums (flow actual − flow setpoint) per minute in °min;
  the compressor starts at a set heat deficit (`CompIntegral`) and stops once the delivered heat
  equals the deficit [IA p.48] [IA p.49]. The manual gives it "nur für Hydrauliken ohne
  Pufferspeicher (Hydraulikplan 6)" [IA p.48]; this unit runs plan 6 [T46]. The flow in the sum is VF2: the menu C4 display that the manual
  gives "bei direktem Heizbetrieb (z. B. Hydraulikplan 6)" shows "Vorlauftemp. VF2" and the
  "Energie-Integral", the summed difference VF2 − "Vorlauftemp. SOLL" per minute [IA p.59]; on
  this unit the integral rate matches VF2 − W [T18] [T19]. This unit: runs start at integral
  ≈ −183 … −186, 1–3 min after it crosses `CompIntegral` −180, and end at integral ≈ 0
  (−8 … +8), 9 of 9 runs, outdoor −8 … +8 °C [T26]. A deeper (more negative) `CompIntegral`
  gives longer runs and pauses [IA p.49].
- **VWS-3** The flow setpoint in that sum is W = floor(fine setpoint), the value `uih` passes on
  to the heat pump, not the 0.5 K value [T18] [T19].
- **VWS-18** The controller regulates on VF2 (`ehp/FlowTemp`, external flow sensor): the integral
  rate is VF2 − W [T18] [T19], and menu C4 shows VF2 next to the integral (direct-heating
  display "z. B. Hydraulikplan 6"; this unit runs plan 6 [T46]) [IA p.59]. The `ehp/Status` flow field (`temp`, = `ehp/HcFlowTemp`) is the
  internal sensor T6 [CAT]; menu 1 "Vorlauftemp. IST" is the flow "im Gerät" (inside the unit)
  [IA p.54], not VF2.
- **VWS-4** Stop line: a run also ends when the flow exceeds the setpoint + `CompHysteresis`,
  whichever comes first; 4 such stops with the integral still negative, all at W 24–26 in mild
  weather [T28]. IA p.69 lists "Komp. Hysterese (nur bei Hydraulikplan 1 und 3)": forced start
  below setpoint − hysteresis, forced stop above setpoint + hysteresis [IA p.69]; this unit runs
  plan 6 [T46], yet stops on the line [T28]: the unit beats the manual's restriction. Whether the line uses W or the fine setpoint: Open questions.
- **VWS-5** The integral is not reset at a stop (+12 after a stop), not clamped (+88 seen with the
  compressor off) and holds its value during hot water [T27].
- After hot water the compressor ran on into heating at integral −113 on one day (11-22), not on
  11-17 or 11-20 [T27]; cause: Open questions.
- The flow setpoint is computed with the compressor off too: a curve jump came 2–3 min before
  the compressor started [T22].

## Hot water within runs

- **VWS-11** A run can roll heating → hot water → heating, or hot water → heating, without the
  compressor stopping; each counts as one start, in the counter of the mode the run started in:
  a run starting in heating in `CompStartsHc` [T29], a hot-water run rolling into heating in
  `CompStartsHwc` [T30]. The two start counters add up to the compressor starts [T30]. Heating
  gives way to hot water after "Max. Heizzeit" (factory 20 min) and hot water to heating after
  "Max. Ladezeit WW" (factory 40 min) when both ask [IA p.69].
- **VWS-13** End of a hot-water charge: every charge seen ends with 2–4 min of compressor at
  heating power (~1.8–1.9 kW) into the heating circuit before it stops; hcmode has already left
  `water` [T31] [T52]. The tail warms the flow (VF2 +12 K) and adds to the integral [T52]. A
  5 min power mean hides it (trap: looks like "straight to idle"). Cause unproven: the catalog's
  `HwcLaggingTime` ("WP Nachlaufzeit WW") [CAT] is 3 min here [T9] and fits.
- **VWS-12** During a hot-water charge `ehp/HcReturnTemp` and the `ehp/Status` flow field read the
  hot-water circuit (51–56 °C), back to the slab level (24.7–26 °C) within the 5 min bucket the
  charge ends, no thermal tail, 7 of 7 runs [T32]. `mc/Status0a` field 4 reads 0 during hot water
  [T25].
