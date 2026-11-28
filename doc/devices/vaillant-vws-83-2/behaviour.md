# Vaillant geoTHERM exclusiv VWS 83/2: behaviour

Only the unit, never HA. Registers are named here, defined in `interface.md`. Every statement
carries an evidence tag (`.claude/rules/devices.md`). W = the whole-degree flow setpoint
(`uih/FlowTempDesired`); "fine setpoint" = `mc/FlowTempDesired` (0.5 K).

## States and sequences

Parts:
- `runs.md` — read when reasoning about when the compressor starts or stops (energy balance,
  stop line, integral, VF2), run and start counting, or hot water within a run (VWS-2…5, 11…13, 18).
- `protections.md` — read before relying on a limit that stops, caps or overrides heating (frost,
  floor protection, flow and return limits, compressor timing, backup heater, outdoor shutdown;
  VWS-6…10, 17, 20).
- `cooling.md` — read before relying on how cooling is released or what a heating write does to
  cooling (passive only, separate settings, release; VWS-14…16).
- `heating-curve.md` (indexed in `README.md`) — read when reasoning about the flow setpoint.

### Mode, hcmode and the compressor

- **VWS-1** The compressor runs on the unit's own energy balance (`runs.md` VWS-2), not on the
  mode: between runs the heating-circuit pump circulates with hcmode (`ehp/Status` field 3) still
  `heat` [T33]. Compressor state is `ehp/Comp`, pump state `ehp/Hc1Pump` [CAT]. Draw on the
  unit's supply: idle circulation ~81–83 W, standby ~9 W, heating ~1.8 kW (never above ~2 kW;
  start peaks 2.0–2.6 kW as hourly maxima), hot water ~3.1–3.5 kW [T33]; passive cooling (brine
  and heating-circuit pump) ~150 W, so each pump ≈ 70 W plus ~10 W controls [T54].
- Heating-circuit modes: `auto` switches Heizen/Absenken by the time program; `eco` switches
  Heizen/Aus by the time program (frost protection still applies); `low` (Absenken) holds the
  setback temperature `TempDesiredLow`; `on` (Heizen) holds `TempDesired` regardless of the time
  program; `off` (Aus) is off unless frost protection applies [IA p.46]. So `on` and `auto`
  differ only in the time program, and under `on` `TempDesiredLow` acts only as the frost floor
  [IA p.46].

### Outdoor value and setpoint

- **VWS-31** `Broadcast/Outsidetemp` carries the value of `ehp/OutsideTemp`, the unit's own
  outdoor sensor [T14]. It reads colder than the house weatherstation: 0.65 K (one evening), ≈ 1 K
  at night, ≈ 0.5 K in the morning [T14] [T35].
- No damping of the outdoor value visible at 5 min resolution: setpoint jumps fall in the same
  5 min as the outdoor value crossing the curve's edge [T22]. The curve uses the live value, not
  the 24 h mean `Broadcast/Tot24h`: the edges followed the live value while the mean stayed
  ≈ 1 K below the edge [T64].
- Room influence (menu C5, VWS-21): `Keine` ignores the VR 90 room temperature [IA p.59];
  `Aufschaltung` shifts the flow setpoint depending on (room desired − actual), factor
  undocumented [IA p.59]; `Thermostat` uses the VR 90 room temperature as a room thermostat
  [IA p.59], stopping heating at room desired + 1 K, not for energy-balance control [IA3 p.68].

## Settings on this unit

Fixed installer values. Owner-tuned values (curve, `TempDesired`, `CompIntegral`,
`CompHysteresis`, `OtShutdownLimit`, `TempDesiredLow`, `FrostOverRideTime`, `OutsideTempOffset`)
change; their current values are kept by the package note named in `README.md` Used by.

| ID | Setting | Value | Maker default | Evidence |
|---|---|---|---|---|
| VWS-19 | Buffer tank | none; slab is the only store; VF2 fitted; `uih/EhpHeatBufferAvailable` off, buffer sensors `cutoff` | — | [T38] [T37] |
| VWS-21 | Raumaufschaltung (menu C5, shown only with a VR 90, or at the VR 90) | `Keine` | — | [T11] |
| | Circuit type (menu C2 "Art") | Brennerkreis, direct circuit without mixer | Brennerkreis, given "bei direkten Hydrauliken" [IA p.58] | [T12] |
| | `FlowTempMax` | 35 °C | 43 °C [IA p.69] | [T4] |
| | `FloorProtectionLimit` (VWS-7) | 44 °C | 52 °C [IA p.46] | [T4] |
| | `ReturnTempMax` | 46 °C | 46 °C [IA p.69] | [T4] |
| | `TimeBetweenTwoCompStartsMin` / `TimeCompOffMin` / `TimeCompOnMin` | 1200 s / 300 s / 240 s | 3 starts/h, 5 min, 4 min [IA p.69] | [T4] |
| | `BackupType` / `BackupModeHc` / `BackupIntegral` | `internalheatandwater` / `no_backup` / −600 °min | — | [T4] |
| | `HwcLaggingTime` | 3 min | — | [T9] |

## Control

| ID | Lever (menu, register, input) | Effect | Limits | Evidence |
|---|---|---|---|---|
| VWS-25 | `mc/TempDesired` (room setpoint), bus writes in 0.5 K | shifts the curve in parallel along the 45° axis [BA p.18]; the fine setpoint moves 0.5 K per 0.5 K step on a flat part of the curve [T17] [T18]; every fine value seen so far (2026-11-21…22) is `TempDesired` + a whole number [T20], so from x.0 a −0.5 K step lowers W by 1 K and +0.5 K leaves it, from x.5 the reverse [T20]; 22.0 → 21.5 lowered W 27 → 26 [T48] | 0.5 K values (`22.0`, `22.5`) accepted and kept [T36] [T7]; the integral uses W, not the fine setpoint (VWS-3) [T18]; whether `TempDesired` acts on the compressor by any other path: Open questions | [BA p.18] [T17] [T18] [T20] [T48] |
| VWS-27 | `mc/HeatingCurve` (slope) | the flow setpoint follows within minutes, also while the compressor runs [T15] | bus step 0.01 [CAT]; floor heating curves < 0.4 [BA p.21] | [T15] |
| VWS-28 | `mc/OperatingMode` | heating mode only (`on`, `off`, `auto`, `eco`, `low`; meaning in States) [IA p.46] [CAT]; writes accepted [T7] | its own register, separate from the cooling setting (VWS-15); `off` below 3 °C still heats (VWS-6) | [CAT] [T7] |
| | `ehp/CompIntegral` ("Komp. Start in", installer; panel C2 "Komp.Start ab", given "nur bei direkter Hydraulik" [IA p.58]) | start threshold of the energy balance; deeper = longer runs and pauses [IA p.49] | backup start moves with it (VWS-20) [IA p.60] | [IA p.49] [IA p.60] |
| VWS-37 | `ehp/CompHysteresis` (installer) | stop line setpoint + hysteresis (VWS-4; W or fine setpoint: Open questions) [T28]; raises the floor-protection limit (VWS-7) [IA p.69] | one fixed value; the manual's entry (given "nur bei Hydraulikplan 1 und 3", this unit runs plan 6 [T46] and acts on it [T28]) describes no weather dependency [IA p.69] | [T28] [IA p.69] |
| VWS-36 | `ehp/OutsideTempOffset` / panel "Kalibrierung" → "Aussentemperatur" | adjusts the displayed outdoor temperature ("Manuelle Anpassung der angezeigten Temperaturen") [IA p.65] | panel ±5 K in 1 K steps, factory 0 K [IA p.65]; bus format in `registers-ehp.md`; whether the curve uses the corrected value: Open questions | [IA p.65] |
| VWS-24 | `mc/OperatingMode`, `mc/TempDesired` (the registers written so far) written over the bus | the written value stays until written again: the VR 90/3 and the unit's own menus write a setting only when someone changes it there, never on their own; the VR 90/3 otherwise sends only `mc/RoomTempOffset` [T5] [T50] | an automation can treat both panels as manual inputs only; their whole-number entry steps do not limit bus writes (VWS-25) [T50] | [T5] [T7] [T50] |

## Does not work

| ID | Lever tried | What happens instead | Evidence |
|---|---|---|---|
| VWS-26 | a 0.5 K `TempDesired` step that leaves floor(fine setpoint) unchanged, e.g. 22.5 → 22.0 | the fine setpoint moves 0.5 K, W stays (27 before and after, flat parts seen so far), so the integral sees no change | [T17] [T20] |
| VWS-23 | heating-circuit pump speed | not readable or settable over eBUS: the pump registers need SW ≥ 407 (≥ 414 for the off-time setpoint) [CAT]; this unit runs SW 0383 [T1] | [CAT] [T1] |
| VWS-22 | `mc/RoomTempOffset` ("Raumaufschaltung" correction) as a lever | write-only, only the VR 90 sends it; cannot be read back | [CAT] [T5] |
| | Raumaufschaltung setting over eBUS | no cataloged register; set only in menu C5 / at the VR 90 | [CAT] [IA p.59] |
| VWS-39 | `mc/Party` ("Quick - Party") | exists write-only on `mc`, `hwc`, `cc` [CAT], but the VR 90/3 has no Party button, so nothing sends it here [T6] | [CAT] [T6] |
| | mode `off` below 3 °C outdoor | frost protection still heats to `TempDesiredLow` (VWS-6) | [BA p.10] [T10] |

## Open questions

- What is the recurring ~50 W level seen in summer, besides 10 W and 150 W [T54]?
  `plans/heating-spf-correction.md`
- Electrical plan 3 (`README.md` Identity): is a network-operator block contact wired to terminal
  13 "EVU", when does it block, and does it explain `off` spells such as VWS-17 (`ehp/PowerCut`)?
  Menu 1 also shows "Sperrzeit Warmwasser" / "Sperrzeit Bereitschaft" [IA p.54], which the
  manual does not tie to the EVU contact:
  `plans/ebusd-pv-heating-optimization.md` step 15
- Can a `TempDesired`-only write start or stop the compressor (VWS-25)? The compressor stopped
  1 s after the 08:43 write, with the integral ≈ 0 and VF2 at the stop line [T17]:
  `plans/heating-curve-tuning.md` step 0.11
- Does the stop line (VWS-4) use W or the fine setpoint? `plans/heating-curve-tuning.md` step 4.9
- Curve steps: other edges, step sizes (2 K and 1 K seen), whether
  `TempDesired` or the outdoor offset moves the edges (VWS-30): `plans/heating-curve-tuning.md`
  step 0.7
- Outdoor offset: does the curve use the corrected value (then +1 K reads warmer, lowers the
  flow and moves the curve's edges and every outdoor threshold: frost protection, AT-Abschaltgrenze,
  cooling release), and does the controller keep values finer than 1 K (VWS-36)?
  `plans/heating-curve-tuning.md` step 0.8
- hcmode `cooling` never seen yet; the cooling release (VWS-16 [ASSUMED]); does `TempDesired`
  move it; does heating mode `off` leave cooling running (VWS-15)?
  `plans/heating-cycling-from-ehp.md` step 14
- Whether a call for heat is honoured above `OtShutdownLimit`; the `off` spell at ≈ 13 °C
  (VWS-17); whether the pump runs while hcmode is `off`; under frost protection with `off`,
  whether the room temperature is ignored and whether it repeats (VWS-6):
  `plans/ebusd-pv-heating-optimization.md` step 15
- Whether a `/set` write takes the enum name (VWS-44): `plans/ebusd-pv-heating-optimization.md`
  step 11
