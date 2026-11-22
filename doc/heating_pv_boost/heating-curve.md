# heating_pv_boost: geoTHERM VWS 83/2 heating curves

Reference for tuning `mc/HeatingCurve` and `mc/TempDesired` (`sensor.geotherm_heating_curve`,
`number.geotherm_heating_temp_desired`); not auto-loaded, read when reasoning about the flow
setpoint. Package facts and rules: `doc/heating_pv_boost/notes.md`.

![Heating curves, geoTHERM exclusiv VWS operating manual p. 21](heating-curve.png)

Source: Vaillant *Bedienungsanleitung geoTHERM exclusiv VWS* (DE/AT/CH), 0020025604_00, 02/2007,
which covers VWS 63/2, **83/2** (art. 0010002787, this unit) and 103/2. Diagram p. 21 (menu "HK2
Parameter"); the owner's printed manual shows the same diagram. Download:
https://kontakt.vaillant.de/documents/download/73792/

## How to read it

- Flow setpoint (Vorlauftemperatur) over the outdoor temperature (Außentemperatur), one line per
  curve value, at room setpoint 20 °C. Every curve starts at 20 °C flow at 20 °C outdoor.
- Room setpoint (`mc/TempDesired`) shifts the curve in parallel along the 45° axis (the 15 / 20 /
  22 scale at the origin; manual p. 18): flow(T, RS) = flow₂₀(T − (RS − 20)) + (RS − 20). So a
  setpoint step of +1 K raises the flow by 1 K plus the curve's slope at that point.
- Floor heating: curves < 0.4 (manual p. 21). Vaillant gives no formula: the diagram columns are
  read off the diagram, the low curves come from the formula below.

## Formula

flow = RS + 2.55 · (curve · (RS − T_out))^0.78 (RS = room setpoint, all °C; the bracket counts as 0 when T_out ≥ RS).
Reverse-engineered by André Kühne for the current Vaillant sensoCOMFORT curves (OpenEnergyMonitor
forum; form and constants as published, written T_flow − T_set = a·[curve × (T_set − T_out)]^b, at
https://protonsforbreakfast.wpcomstaging.com/2024/10/18/vaillant-heat-pump-controls-part-3-formulas-and-spreadsheet/).
Checked against the 83/2 diagram below (computed, 8 outdoor points per curve): within ±0.7 K for
0.2, 0.4, 0.6, 0.8, 1.0 and 1.5 (the line read as 1.2 deviates up to −1.7 K; label not
re-checked). It includes the 45° room-setpoint shift by construction. Not in any Vaillant
document: use it for the low curves the diagram does not draw, graded HYPOTHESIS there.

## Table (flow setpoint °C at room setpoint 20 °C)

Diagram columns: read from the 83/2 diagram's vector paths in the PDF, not by eye (±0.2 K).
Check: curve 1.5 at −15 °C gives 75.6, the manual's dash-dot example reads ≈ 76. Columns
marked ¹ are the formula above (the diagram has no curve below 0.2).

| Outdoor | 0.13 ¹ | 0.14 ¹ | 0.15 ¹ | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 | 1.2 | 1.5 |
|---|---|---|---|---|---|---|---|---|---|---|
| +20 °C | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 |
| +15 °C | 21.8 | 21.9 | 22.0 | 22.5 | 24.3 | 25.6 | 27.6 | 29.2 | 30.7 | 32.3 |
| +10 °C | 23.1 | 23.3 | 23.5 | 24.5 | 27.6 | 30.0 | 33.3 | 35.9 | 38.7 | 41.2 |
| +5 °C | 24.3 | 24.5 | 24.8 | 26.3 | 30.4 | 33.8 | 38.3 | 41.7 | 45.6 | 49.0 |
| 0 °C | 25.4 | 25.7 | 26.0 | 28.0 | 33.0 | 37.4 | 42.8 | 46.8 | 51.9 | 56.1 |
| −5 °C | 26.4 | 26.8 | 27.1 | 29.5 | 35.5 | 40.9 | 47.0 | 51.7 | 57.7 | 62.9 |
| −10 °C | 27.4 | 27.8 | 28.2 | 31.0 | 37.7 | 44.1 | 51.1 | 56.3 | 63.3 | 69.4 |
| −15 °C | 28.3 | 28.8 | 29.3 | 32.2 | 39.9 | 47.2 | 55.0 | 60.8 | 68.6 | 75.6 |
| −20 °C | 29.2 | 29.8 | 30.3 | 33.2 | 41.9 | 50.0 | 58.9 | 65.4 | 73.9 | 81.8 |

¹ Formula, not manufacturer values. Do not interpolate between 0.1 and 0.2 instead: the successor
installation manual (*Installationsanleitung geoTHERM exclusiv*, 0020087974_00, VWS 63/3–103/3,
p. 66) draws a 0.1 curve that lies 2–2.5 K above the formula while its 0.2–1.0 curves match the
83/2 diagram; interpolating from it overstated 0.13–0.15 by ≈ 1.5 K.

`mc/FlowTempMax` (35 °C) caps the setpoint whatever the curve (note "Compressor and measurements").

Outdoor sensor calibration (installer menu "Kalibrierung" → "Aussentemperatur", ±5 K in 1 K
steps; *Installationsanleitung* 0020045204_01 p. 65 (/2); ebusd `ehp/OutsideTempOffset`): 0 K (owner,
2026-11-21). The manual calls it an adjustment of the displayed temperature; that the curve uses
the corrected value, i.e. that it shifts the curve sideways (+1 K = read warmer = lower flow), is
UNPROVEN. It would also move every other outdoor threshold (frost protection, summer cut-off,
cooling release).

## Open: how closely the machine follows it

OBSERVED (Nov 2026, flow setpoint `mc/Status0a` field 4 in whole °C vs the formula, outdoor from the
weatherstation): 0.15 / 22 matches within −1.4 … +0.1 K; 0.13 / 22 and 0.14 / 22.5 run 0.8–2.1 K
below. Part of that is the whole-degree reading (up to 1 K) and possibly whole-degree room
setpoints. Investigation: `plans/heating-curve-tuning.md` (Baseline, hypothesis (f), step 0.7).
