# Heating — tune the heating curve and `TempDesired` for stable room temperatures

## Overview

Goal: stable room temperatures from the geoTHERM's own weather compensation alone, that is the
heating curve (slope) and `mc/TempDesired` (parallel shift), plus hydraulic balancing of the
floor loops where rooms differ. Loxone's `warm_enough` is ignored for now (owner, 2026-11-21: its
publishing does not update, a separate issue not fixed here); the comfort control stays off and
the target is not adapted dynamically. A later sunny-day exception is out of scope until
`warm_enough` works again.

Room targets (owner):

| Room | Target | Band (target ± 0.3 K) | Floor | HA sensor (Ecowitt channel) |
|---|---|---|---|---|
| Living room | 22–23 °C | 21.7–23.3 | ground floor | `sensor.wheatherstation_indoor_temperature` (base station) |
| Bathroom | 22 °C | 21.7–22.3 | upper floor | `sensor.wheatherstation_temperature_5` |
| **Office (limiting room)** | 22 °C | 21.7–22.3 | upper floor | `sensor.wheatherstation_temperature_3` |
| Bedroom | 21.5 °C | 21.2–21.8 | upper floor | `sensor.wheatherstation_temperature_1` |
| Kids' room (Kilian) | 21.5–22 °C | 21.2–22.3 | upper floor | `sensor.wheatherstation_temperature_2` |

The room sensor IDs come from the ha-mcp baseline (Part A); no YAML in this repo references them.

Owner facts (2026-11-21): the bedroom and Kilian's room warm up at night with people sleeping in
them (expected, not a fault). The bedroom sensor sat close to the sleepers and has been moved to a
more neutral spot, so bedroom readings before the move overstate it. Last year the owner
balanced the manifold so the upper floor gets more flow; without it the ground floor was always
warmer. Bathroom (owner, 2026-11-22): a temperature spike that comes with a humidity spike
(`sensor.wheatherstation_humidity_5`) is a shower; leave those hours out of every evaluation.

Outdoor: the weatherstation `sensor.wheatherstation_outdoor_temperature` and the machine's own
sensor `sensor.geotherm_heating_outdoor_temp` (VRC DCF, north side of the house, no sun; owner).
Sun: `sensor.wheatherstation_solar_radiation`, PV `sensor.victron_solar_yield_total_kwh`.

Machine: geoTHERM exclusiv **VWS 83/2** (art. `0010002787`; manuals in the note "Bus
participants"). Heating curves: `doc/heating_pv_boost/heating-curve.md` (manufacturer diagram,
Kühne formula).

The curve is a panel setting. `TempDesired` is set by hand, at the panel or with
`number.geotherm_heating_temp_desired` (#186). HA writes nothing automatically: the comfort
control stays off.

## Design approach

- **Design IDs touched:** HPB-1 (`doc/heating_pv_boost/design.md`) already carries the hand-setter
  line (#186): with the writer off, `number.geotherm_heating_temp_desired` writes `mc/TempDesired`
  only on a change by hand. The control law is unchanged. If the writer is armed later,
  `mc/TempDesired` = `input_number.heating_comfort_temp` + 1 (rows 4–7) and a hand value is
  overwritten.
- **Which lever does what:**
  - **Curve slope** (panel) sets the balance between cold and mild weather. Too warm in mild
    weather and right in cold weather: slope too steep. Right in mild weather, too cold in cold
    weather: slope too flat. Smallest step 0.01 (panel); by the formula ≈ 0.25 K flow in mild
    weather, ≈ 0.45 K at −10 °C.
  - **`TempDesired`** (panel or hand setter) shifts the whole curve in parallel: ≈ 1.2 K flow per K
    (formula). Whether 0.5 K steps act is open (hypothesis (e), step 0.6).
  - **Outdoor sensor offset** (menu "Kalibrierung" → "Aussentemperatur", ±5 K in 1 K steps;
    Installationsanleitung 0020045204_01 p. 65, the manual calls it an adjustment of the displayed
    temperature; ebusd `ehp/OutsideTempOffset`; owner: 0 now). If the curve uses the corrected
    value (UNPROVEN, `heating-curve.md`), +1 K would lower the flow by ≈ 0.25 K at 0.14 in mild
    weather. It would also move every other outdoor decision: frost protection below 3 °C, the
    AT-Abschaltgrenze (no heating above, no cooling below). Only for correcting a measured sensor error (step 0.5),
    never instead of `TempDesired` or the slope.
  - **Room-to-room differences** (upper floor colder than the living room) are hydraulics or room
    losses. Neither lever fixes them: Phase 3.
  - **`warm_enough`** is ignored for now (see Overview). Later, sunny days only, never to
    correct a curve that is too high.
- **Limiting room (owner, 2026-11-21):** `TempDesired` and the slope are steered on the **office**
  (22 °C). A living-room overshoot is accepted until Phase 3; the other rooms' spread relative to
  the office is Phase 3's job.
- **Order (owner):** balance first. If the office-to-living gap after 1.2 is > 0.5 K, Phase 3 runs
  before Phase 2, so the curve is not tuned twice. Across both phases: one change at a time, each
  followed by the settle time.
- **Qualifying days** (used by 1.2, 2.1, 2.2): daily radiation mean < 25 W/m². Cold class: daily
  outdoor mean < 3 °C; mild class: > 7 °C. Comparable: same class and daily means within ±2 K.
  With only one class available, only `TempDesired` may change; slope rows need both classes.
- **Settle time:** the slab lags by a day or more. After a change, wait at least 4 full qualifying
  days before the next evaluation. Log every change in the change log (date, time, old, new).
- **Interactions:** compressor cycling (HYPOTHESIS run model, note "Decisions in force": a higher
  flow setpoint gives more headroom up to setpoint + hysteresis and longer runs); floor protection
  = `FlowTempMax` + `CompHysteresis` + 2 K at VF2 (note "Compressor and measurements"); frost
  protection (`off` below 3 °C still heats to `TempDesiredLow` 20 °C, note "Frost protection").
- Invariants checked: no automatic write and no change to the control law. Every register read
  has its bridge lines and poll (note "Invariants"; step 0.4 lists them).

## Change log (owner settings)

| When (local) | Setting | Old → new | Evidence |
|---|---|---|---|
| 2026-11-14 ≈ 20:20 | Heating curve | 0.15 → 0.13 | OBSERVED, estimated from the data: the flow setpoint stepped 27 → 26 °C while it got colder outside (2.6 → 1.8 °C). No other input changed. Owner: "after the heat spike" |
| 2026-11-14 23:05 – 11-15 00:45 | `TempDesired` | 22 → 21 → 19 (briefly) → 22 | OBSERVED: the HA target followed the comfort knob (21, 18), so these were writes by the armed Phase 2 writer |
| 2026-11-15 ≈ 08:30 – 11-16 00:07 | `mc/OperatingMode` | `on` → `off` → `on` | HYPOTHESIS: the setpoint ran ≈ 2 K below the 0.13 relation all day (frost protection at `TempDesiredLow` 20); `heating_mode_last_written` = 11-16 00:07:52, and the setpoint jumped 25 → 27 at 00:08. Requires < 3 °C outdoor on 11-15 (the pump never stopped, A.4): check the weatherstation statistics for that day |
| 2026-11-20 evening (read back 22:14) | Heating curve | 0.13 → 0.14 | Owner: read back at 22:14 and shown on the wall unit |
| 2026-11-20 22:01:44 | `TempDesired` | 22 → 22.5 | Owner: written by HA (the writer was armed for ≈ 3 s; switched off at 22:01:47) |
| 2026-11-20 22:01:47 | Comfort control | on → off | Owner: `warm_enough` does not update; stays off, `warm_enough` ignored |
| 2026-11-21 or shortly before | Bedroom sensor | moved away from the bed to a neutral spot | Owner. Bedroom data before the move are not comparable |
| 2026-11-21 evening | Heating curve | 0.14 → ? → 0.14 | Owner test with the compressor running: `mc/FlowTempDesired` followed after a few minutes; set back to 0.14 (owner). Test values and times not recorded |
| 2026-11-22 08:43:17 | `TempDesired` | 22.5 → 22.0 | Owner, with `number.geotherm_heating_temp_desired`: step 0.6 (e) and kept as the first Phase 2 change (2.1). Fine flow setpoint 27.5 → 27.0 (read 08:43:32) |
| 2026-11-22 08:43:21 | `input_number.heating_comfort_temp` | 21.5 → 21.0 | Owner, by hand, to keep the knob 1 K below `TempDesired` (5.1). Writer still off |
| unchanged | `CompHysteresis` 7 K, `CompIntegral` −180, `TempDesiredLow` 20 (owner-stated) | — | read live 2026-11-21 (the first two) |
| unchanged | Outdoor sensor offset 0 K | — | Owner, 2026-11-21 |

## Part A — baseline and current state (ha-mcp, long-term statistics, 2026-11-21)

Data come from the recorder's long-term statistics (hourly or 5 min means). The read-only tools give
no state history for non-numeric entities, so the mode and `warm_enough` history cannot be counted
(see A.4).

### A.1 Did the changes take effect?

- **`TempDesired` = 22.5: CONFIRMED** (read-back `sensor.geotherm_heating_temp_desired` 22.5 since
  2026-11-20 22:01:44; the owner confirms HA wrote it).
- **Curve 0.14: CONFIRMED by the owner** (read back at 22:14, shown on the wall unit). The data
  agree: the only setpoint step on 11-20 that the weather does not explain is 24 → 25 → 26 °C
  between 22:00 and 22:20, at a steady 8.9 °C outside, together with the `TempDesired` write. The
  steps at 18:05 (24 → 26) and 21:40 (26 → 24) match the usual 24 ↔ 26 transitions of the 0.13
  period at about 7–9 °C outside. Since then the setpoint has been 26 °C at 5.4–9.7 °C outside (one
  hour at 25), where 0.13/22 gave 24 °C at 8–11 °C (nights of 11-19/20). By the formula, 0.14 / 22.5
  gives +0.9 K over 0.13 / 22 at 8 °C; observed +2 K (whole-degree readings; see A.3).
- **Phase 2 writer: disarmed** (`input_boolean.heating_comfort_control_enabled` off since 11-20
  22:01:47). `input_number.heating_comfort_temp` = 21.5, so `sensor.heating_target_temp` = 22.5
  equals the machine value: arming it now would not change `TempDesired` (rows 4–7), only the mode.
- **Mode:** `on` since 2026-11-16 00:07:52 (an HA write). `warm_enough` is `on` since 11-21
  06:20, but with the writer off it has no effect. So the machine is not being cut off now.

### A.2 Periods and room temperatures (daily means of the statistics)

Periods: **P1** = 0.15 / 22, 11-07 … 11-13 (outdoor mean 4.6 °C, low sun); **Spike** = 11-14
(sunny after a cold night, setpoint 29 °C in the morning) and 11-15 (mode probably `off`); **P2** =
0.13 / 22, mode `on`, 11-17 … 11-20 (outdoor mean 8.9 °C, a little sunnier); **P3** = 0.14 / 22.5,
since 11-20 22:00 (≈ 11 h of data).

| Room (target) | P1 mean (min–max) | Spike 11-14 mean (max) | P2 mean (min–max) | P2 − P1 | P3 11-21 00–09 h | P1 / P2 vs living room |
|---|---|---|---|---|---|---|
| Living (22–23) | 23.33 (22.4–23.9) | 24.04 (25.0) | 22.74 (21.8–24.0) | −0.59 | 22.51 (22.4–22.8) | — |
| Bathroom (22) | 22.65 (22.2–23.3) | 23.10 (23.9) | 21.74 (21.2–22.3) | −0.91 | 21.59 | −0.68 / −1.00 |
| Office (22) | 22.76 (22.4–23.5) | 23.01 (23.2) | 21.93 (21.5–22.3) | −0.83 | 22.15 | −0.57 / −0.81 |
| Bedroom (21.5) | 22.83 (22.2–23.4) | 23.30 (23.9) | 22.01 (21.2–22.6) | −0.82 | 22.28 | −0.50 / −0.73 |
| Kilian (21.5–22) | 22.63 (22.1–23.4) | 22.86 (23.0) | 21.80 (21.2–22.2) | −0.83 | 22.02 | −0.70 / −0.94 |

OBSERVED:
- P1 was 0.5–1.3 K **above** the targets in every room except the living room. P2 was close to the
  targets on average (office −0.07, bathroom −0.26, bedroom +0.5), but falling: P2 days ran
  21.5–21.9 in the bathroom and reached 21.2 in bedroom, Kilian and bathroom on the evening of 11-20.
- The other rooms' gap to the living room grew by ≈ 0.25–0.3 K at the lower flow temperature.
- Daily swing (P2 hourly): the bedroom is warmest at ≈ 06:00 and coldest at ≈ 19:00 (≈ 0.8–1 K);
  Kilian similar, ≈ 0.6 K; office warmest at midday (≈ 0.5 K); bathroom warmest in the morning.
- P3 so far: bedroom 21.2 → 22.5 (19:00 → 07:00, +1.3 K vs +0.5 K the night before), Kilian
  +1.0 K, living +0.7 K, office and bathroom +0.45 K. Part of this is the normal night rise.
- Spikes on 11-05 (living max 24.8, Kilian 24.9) and 11-14 (living 25.0) were both sunny days
  after a cold night, when the curve had charged the slab (setpoint 27–29 °C).

HYPOTHESIS: P2 means flatter the equilibrium of 0.13/22, because the slab was still giving back the
11-14 spike and P2 was mild. The real 0.13/22 level at ≈ 9 °C was probably ≈ 0.3 K below the P2
means (bathroom and office under target). The spikes are a sun-after-cold-night effect, so a
"lower the curve" reaction to a spike over-corrects (as P2 shows).

### A.3 Curve relation

**Open hypotheses** (every other section refers to these letters):
- (a) The machine's outdoor value differs from the real outdoor temperature or is damped before
  the curve. One reading (geoTHERM 3.75 °C vs weatherstation 4.4 °C, 2026-11-21 evening) points
  the wrong way (a colder reading raises the setpoint); step 0.5 tests it over ≥ 2 days, incl.
  08–11 h. No Vaillant document mentions damping (/2 manuals checked).
- (b) Below 0.2 the curve does not follow the formula (the 83/2 diagram draws nothing below 0.2;
  no /2 document gives a range or step). Step 0.6 (b).
- (c) `mc/Status0a` field 4 is not the plain curve setpoint. Weak: it equals `mc/FlowTempDesired`
  within its whole degree (A.4b).
- (d) The VR 90 room sensor offset (`rcc/RoomTempOffset` 0.5 K) moves the curve. **Ruled out:** it
  only calibrates the VR 90's own reading, Raumaufschaltung is `Keine`, and `mc/RoomTempOffset`
  (the channel that would carry room influence) reads 0.00 (owner, `ebusctl find -w`).
- (e) The controller computes with whole degrees of `TempDesired` (22.5 acts as 22). **Refuted**
  by step 0.6 (e) on 2026-11-22: 22.5 → 22.0 moved the fine setpoint 27.5 → 27.0 (Observations).
- (f) NEW, OBSERVED at two transitions: at 0.14 / 22.5 the setpoint follows the outdoor
  temperature in **2 K jumps**, with an edge at about −2.5 °C (geoTHERM value): 27.5 → 29.5 at
  02:11 (−2.38 → −2.62) and back at 08:20 (−2.62 → −2.38), 2026-11-22, with no hysteresis
  between the two directions. In between it stayed flat: 27.5 from +1.06 to −2.38 °C (20–02 h)
  while the formula goes 28.5 → 29.2; 29.5 from −2.62 to −4.25 °C (formula 29.3 → 29.6). So the
  machine sits 0–2 K below the formula, depending on where it is on a step. This matches the
  0.13 period's 24 ↔ 26 jumps (never 25), the 0–2 K deficit in the table above, and the 08–11 h
  drops (a warming geoTHERM value crossing an edge, no damping needed). It would also explain (b).
  The jump came before the compressor started, so the run does not cause it. Open: the other
  edges and step sizes (step 0.7), and whether the outdoor offset moves the edges.

Data: flow setpoint = `mc/Status0a` field 4 (whole °C; 0 during hot water, excluded), against the
weatherstation (night/evening hours), error ±1 K. The setpoint often drops 1–2 K between 08 and
11 h without a matching weatherstation change (see (a)).

| Outdoor (weatherstation) | 0.15 / 22 (P1) | 0.13 / 22 (P2) | 0.14 / 22.5 (P3) |
|---|---|---|---|
| −2 °C | 29 (11-14 07 h, −1.8) | 27 (11-16 01–04 h) | — |
| 2–3 °C | 27 | — | — |
| 3.5–6 °C | 26 (27 below ≈ 3.5) | 26 | 26 (5.4–6.9) |
| 7–9 °C | 26 (7.6–7.9) | 24 | 26 (7.7–9.7; one hour 25) |
| 10–11 °C | 24 (daytime) | 24 | — |
| 13–15 °C | — | 23 | — |

An earlier linear fit to this table (b ≈ 0.28–0.38) is superseded by the formula below; the table
stays as data.

**Manufacturer curve:** `doc/heating_pv_boost/heating-curve.md`. The Kühne formula flow = RS +
2.55 · (curve · (RS − T))^0.78 reproduces the 83/2 diagram within ±0.7 K for 0.2–1.0 and 1.5
(computed); below 0.2 it is the only model (HYPOTHESIS there). Against it:

| Setting | Outdoor | Observed | Formula | Formula if RS acts as 22 |
|---|---|---|---|---|
| 0.15 / 22 | −1.8 | 29 | 28.9 | — |
| 0.15 / 22 | 2.5 | 27 | 27.9 | — |
| 0.15 / 22 | 4.75 | 26 | 27.4 | — |
| 0.15 / 22 | 7.75 | 26 | 26.6 | — |
| 0.15 / 22 | 10.5 (day) | 24 | 25.9 | — |
| 0.13 / 22 | −2 | 27 | 28.2 | — |
| 0.13 / 22 | 4.75 | 26 | 26.8 | — |
| 0.13 / 22 | 8 | 24 | 26.1 | — |
| 0.13 / 22 | 14 | 23 | 24.6 | — |
| 0.14 / 22.5 | 6.15 | 26 | 27.4 | 26.7 |
| 0.14 / 22.5 | 8.7 | 26 | 26.8 | 26.1 |
| 0.14 / 22.5 | 3.75 (geoTHERM sensor; `mc FlowTempDesired` 26.5) | 26.5 | 27.9 | 27.3 |

OBSERVED: the machine runs 0–2 K below the formula, mostly 0.5–1.5 K; 0.15 / 22 within −1.4 …
+0.1 K. Candidates: whole-degree readings of `Status0a` field 4 (up to 1 K; truncation UNPROVEN),
(e) (with RS 22 the 0.14 rows fit within 0.2–0.8 K), (a) (daytime rows lowest), the formula
itself (0.3–0.7 K below the diagram at 0.2). Unexplained: 0.13 / 22 reads ≈ 2 K below the formula
at 8 °C, more than whole-degree readings allow; candidates (a) and (b). The new 0.5 K setpoint
sensor and the geoTHERM outdoor sensor (step 0.4) give the data to settle this.

### A.4 Machine figures per period

| Figure | P1 (11-07…13) | P2 (11-17…20) | 11-21 so far |
|---|---|---|---|
| Outdoor mean / radiation mean | 4.6 °C / 16 W/m² | 8.9 °C / 20 W/m² | 7.3 °C |
| Flow setpoint, daily mean incl. hot-water zeros | 25.0–25.6 | 23.5–23.9 | 25.9 (no hot water yet) |
| Return temperature (slab charge), daily mean | 25.9 | 24.5 | 24.5 |
| Heating starts/day (`CompStartsHc`) | 7.0 (4–9) | 4.0 (3–5) | 3 by 09 h |
| Heating hours/day (`CompHoursHc`, whole h) | 3.3 | 2.25 | — |
| Hot-water starts/day | (from 11-12) 2 | 2 | 0 |
| Yield / electricity per day (incl. hot water) | 34.4 kWh / 10.4 kWh | 24.0 / 8.1 | — |
| Yield per K (22 − outdoor) per day | 1.98 kWh/K | 1.83 kWh/K | — |
| Average run today / last run | — | — | 34 min / 32.5 min |

- `warm_enough` cut-ins and `off` hours: **not measurable** with the read-only tools (binary and
  text states have no statistics). Known: `off` most likely ran 11-15 ≈ 08:30 → 11-16 00:07
  (change log); the mode has been `on` since.
- The Energy-mode `off` meter stayed 0 every day: the heating-circuit pump never stopped.

### A.4b Setpoint and flow registers

Decodes and meanings: `doc/heating_pv_boost/registers.md`. What matters here:
- Owner reads 2026-11-21 evening: `ehp FlowTemp` (VF2) 31.94, `ehp HcFlowTemp` (T6) 32.00,
  `uih FlowTemp` 32.00; forced reads `mc FlowTempDesired` 26.5, `uih FlowTempDesired` 26.00;
  `mc Params` `22;20;0.14;mixer;15;0;15;35;0`; panel C2 "Art" = Brennerkreis (direct circuit).
- HA now reads the 0.5 K setpoint (`sensor.geotherm_heating_circuit_flow_temp_desired_fine`,
  step 4.6) next to the whole-degree one, and VF2 (`sensor.geotherm_heating_flow_temp_vf2`,
  step 4.8), the flow input the controller's energy integral and floor protection use
  (Installationsanleitung 0020045204_01 p. 46, p. 59).
- HYPOTHESIS: `uih/FlowTempDesired` passes on a whole-degree value, so the generator works on 26
  while the circuit asks 26.5. (The /2 manual's "Temp.überhöhung" adds ≥ 0 K at heat-pump level,
  so it does not explain a lower `uih` value.)
- HYPOTHESIS (owner): composite status/display messages (`mc/Status0a`, `mc/Params`, the panel)
  show whole degrees as a simplification; the dedicated registers (`mc/FlowTempDesired`,
  `mc/TempDesired`) hold the value the controller works with. Audit: of everything HA reads, only
  `mc/Status0a` field 4 was whole-degree. Tests after step 0.4, ≥ 3 days of data: (1) whole =
  floor(fine) or round(fine) at all times (note which); (2) the fine setpoint moves in 0.5 K steps
  between whole ones; (3) step 0.6 (e). Only (3) shows what the controller computes with.
- `ebusctl find` prints ebusd's cache, not a bus read: use `ebusctl read -f` for tests.
- Owner hypothesis "curve changes during a run are ignored": **DISPROVED** (owner, one test: the
  setpoint followed a curve change after a few minutes with the compressor running). "The
  setpoint is only computed while the compressor runs": UNPROVEN; against it, the /2 manual
  describes a curve setpoint and an integral summed every minute (0020045204_01 p. 48). Tested in
  step 0.6 (e).

### A.5 What can and cannot be concluded yet

- Can: `TempDesired` 22.5 is in the machine. The setpoint is now ≈ 2 K higher than under 0.13/22 at
  the same mild outdoor temperature. 0.13/22 in mild weather gave rooms 0.8–0.9 K colder than
  0.15/22 gave in colder weather (P1), and P1 itself was above the targets. The formula explains the
  0.15 period within −1.4 … +0.1 K and the others within 0–2 K.
- Cannot: where 0.14/22.5 settles (needs ≥ 4 days, the slab lags); how it behaves in cold weather
  (no frost day since); how much of the 11-21 overnight rise is the setting vs the normal night
  rise; hypotheses (a), (b), (e).

## Steps

### Phase 0 — verify and record

- [DONE] **0.1** Part A analysis (above).
- [DONE] **0.2** Curve 0.14 confirmed (owner read-back 2026-11-20 22:14, wall unit).
- [DONE] **0.3** Owner answers (2026-11-21): 22.5 written by HA; the comfort control is off
  because `warm_enough` does not update (separate issue), and `warm_enough` is ignored for now;
  bedroom sensor moved away from the sleepers (night warming by occupants is expected in the
  bedroom and Kilian's room); hydraulic balancing is part of this plan; the upper floor already
  gets more flow from last year's balancing; no dynamic target; office is the limiting room;
  balance before tuning.
- [DONE] **0.4** Deployed (owner, 2026-11-22). Checked with ha-mcp: curve 0.14, hand setter, fine
  setpoint, VF2 and the geoTHERM outdoor sensor all report. The `ebusctl read -f` comparisons
  were not run (they need the owner).
  Original step: Deploy the HA additions (steps 4.3, 4.5–4.8). Bridge lines on the HA
  broker host; the first five (`mc/HeatingCurve`, `mc/FlowTempDesired`, `Broadcast/Outsidetemp`)
  are live (owner, 2026-11-21), `ehp/FlowTemp` comes with the deploy of #190:
  ```
  topic ebusd/mc/HeatingCurve in 0
  topic ebusd/mc/HeatingCurve/get out 0
  topic ebusd/mc/FlowTempDesired in 0
  topic ebusd/mc/FlowTempDesired/get out 0
  topic ebusd/ehp/FlowTemp in 0
  topic ebusd/ehp/FlowTemp/get out 0
  topic ebusd/Broadcast/Outsidetemp in 0
  ```
  (the broadcast has no `/get` line: it cannot be polled). Restart Mosquitto (a reload does not
  load bridge changes), then check: `sensor.geotherm_heating_curve` 0.14,
  `number.geotherm_heating_temp_desired` 22.5, `sensor.geotherm_heating_circuit_flow_temp_desired_fine`
  = `ebusctl read -f -c mc FlowTempDesired`, `sensor.geotherm_heating_flow_temp_vf2` ≈
  `ebusctl read -f -c ehp FlowTemp`, `sensor.geotherm_heating_outdoor_temp` shows a value, the
  "Curve check" and "Why runs end" graphs fill.
- [TODO] **0.5** First night (11-21/22): geoTHERM ≈ 1 K colder than the weatherstation from 20 to
  06 h (20 h 0.38 vs 1.57; 22 h −1.17 vs −0.07; 06 h −4.01 vs −3.06), ≈ 0.5 K at 08:30. More
  nights needed (owner rule).
  Machine outdoor value vs weatherstation (hypothesis (a)). After ≥ 2 days of data:
  compare `sensor.geotherm_heating_outdoor_temp` with the weatherstation by hour (night, 08–11 h,
  afternoon), and the fine setpoint with the formula evaluated at the geoTHERM value; a setpoint
  that lags the geoTHERM value by hours = damping. Correct with the outdoor offset only for a
  roughly constant night-time difference over clearly more than 2 nights (owner; weatherstation as
  reference). The offset moves in 1 K steps, so a constant difference well below 1 K stays as it
  is. Result → "Observations".
  Depends on: 0.4.
- [IN_PROGRESS] **0.6** (e) DONE 2026-11-22: half degrees count (Observations). Item 5's
  set-back only covered the case where 0.5 K steps might not act. They do act, so 22.0 stays as
  the first Phase 2 change. `TempDesired` is a lever, not a goal: the goal is the room
  temperatures (owner). (b) still TODO; (f) sharpens it: let the 0.20 test start and end on the
  same side of an edge.
  Controller resolution tests (owner; background A.3 (e), (b)). Each test changes
  ONE setting, at a steady outdoor temperature (`sensor.geotherm_heating_outdoor_temp` within
  ±0.5 K during the test), not during hot water (`binary_sensor.geotherm_heating_hwc_active` off).
  Read with `ebusctl read -f` (not `find`). Log every value with its time under "Observations" and
  in the change log. A test change set back within 1 h does not restart Phase 1's settle time and
  is not a Phase 2 step.
  - **(e) Does `TempDesired` act in 0.5 K steps?** Run it with
    `binary_sensor.geotherm_heating_compressor_running` **off** (this also tests "computed only
    while running", A.4b).
    1. Force-read `mc FlowTempDesired`, `mc TempDesired` (expect 22.5), `mc HeatingCurve`.
    2. Set `number.geotherm_heating_temp_desired` to **22.0**. Curve unchanged.
    3. Force-read `mc FlowTempDesired` every 2–3 min for ≥ 15 min.
    4. Result: 0.5 K drop → half degrees count. ≥ 1.0 K drop → ambiguous (22.5 may round to 23):
       repeat 22.0 → 21.5; a drop there confirms half degrees. Unchanged → 22.5 acts as 22,
       (e) confirmed.
    5. If (e) is confirmed: **keep 22.0** (owner decision) and use whole-degree `TempDesired`
       steps from then on; otherwise set 22.5 back. Log it.
  - **(b) Does the curve below 0.2 follow the formula?** On a different day from (e), so the two
    set-backs cannot overlap.
    1. Force-read `mc FlowTempDesired` and the geoTHERM outdoor value.
    2. Set the curve **0.14 → 0.20** at the panel (`TempDesired` unchanged).
    3. Force-read `mc FlowTempDesired` every 2–3 min for ≥ 15 min.
    4. Compute the formula prediction from the outdoor value of step 1 and the current
       `TempDesired` (example: +1.7 K at 3.75 °C / 22.5). A rise < 3 K supports the formula; ≈ 6 K
       supports the old data.
    5. Set **0.14** back at the panel; log both changes.
  Depends on: 0.4.
- [TODO] **0.7** Map the setpoint jumps (hypothesis (f)). Passive: no setting changes, only data
  as the weather moves through them. From the "Curve check" graph (5 min statistics, kept ≈ 10
  days): note every jump of the fine setpoint outside hot water, with its time, size and the
  geoTHERM outdoor value before and after. Group the jumps by `TempDesired` (22.5 until 11-22
  08:43, then 22.0). Per setting, the result is a table of edges (outdoor °C) and levels (flow
  °C), next to the formula. Questions:
  - Fixed step size (2 K at every edge)?
  - Do the edges sit on fixed outdoor values, or does `TempDesired` move them? (So far 22.0 moved
    the level by 0.5 K. Whether it moved the edge is unknown.)
  - Hysteresis between rising and falling outdoor values? (Not at −2.5 °C on 11-22.)
  Why: if the curve works in steps, a slope change of 0.01 may do nothing or shift a whole step,
  and an outdoor offset of 1 K may move every edge. Neither can be predicted from the formula.
  Enough when edges are seen across the outdoor range of the season so far, about −5 to +10 °C.
  Result → "Observations"; once CONFIRMED, → `doc/heating_pv_boost/heating-curve.md` at Close.
  Depends on: 0.4.

### Phase 1 — settle the current setting (0.14 / 22.5), no changes

- [DONE] **1.1** Ended early on 2026-11-22 08:43 (owner: too warm everywhere). After 35 h the
  office (the limiting room) was at 22.9 (+0.9) and every room was still rising
  (Observations). The office-to-living gap was 0.35–0.4 K (≤ 0.5), so by the Order rule Phase 2
  comes first. Evaluated early, without 4 qualifying days: 11-21 was sunny and fit no class;
  11-22 is cold class. So only `TempDesired` may change (Design approach).
  Depends on: 0.2.
- [TODO] **1.2** Evaluate the settled days: per room the daily mean minus target, min/max, the
  outdoor mean and the radiation, on qualifying days per class (Design approach). Judge the
  bedroom and Kilian's room on 08–20 h values: their night rise comes from the sleepers. Expected
  (HYPOTHESIS): close to P1 in mild weather, so the living room ≈ 23, the office ≈ 22.4–22.7, the
  bedroom ≈ 22.5–22.8 (less after the sensor move). Then decide the order: office-to-living gap
  > 0.5 K → Phase 3 next, else Phase 2. Log the result under "Observations".
  Depends on: 1.1.

### Phase 2 — tune, one change at a time

Decision rule per evaluation, on the **office** (limiting room), using its daily mean minus 22 °C
on qualifying days:

| Office result | Change | Size |
|---|---|---|
| Above +0.3 K in both classes (or in the only class available) | `TempDesired` down | 0.5 K, or 1 K if (e) is confirmed |
| Below −0.3 K in both classes (or in the only class available) | `TempDesired` up | 0.5 K, or 1 K if (e) is confirmed |
| Within ±0.3 K on mild days, below −0.3 K on cold days | slope up | 0.01 |
| Within ±0.3 K on cold days, above +0.3 K on mild days | slope down | 0.01 |
| Within ±0.3 K, other rooms out of their band | no curve change: Phase 3 (living overshoot accepted until then) | — |
| A sunny day overshoots | no change: the PV exception (Phase 5) | — |
| Step 0.5 found a constant night-time outdoor error (owner rule, step 0.5) | outdoor offset (correct the sensor) | the measured error, whole K |

- [IN_PROGRESS] **2.1** First change made: `TempDesired` 22.5 → 22.0 on 2026-11-22 08:43 (row 1,
  0.5 K since (e) is refuted). Curve stays 0.14. Settle for ≥ 4 qualifying days, then evaluate
  as 1.2. The write cut one run short (Observations); judge the cycling on full days only.
  Apply at most one change from the table (`TempDesired` with
  `number.geotherm_heating_temp_desired`, the curve at the panel). Log it in the change log with the
  forced-read `mc FlowTempDesired` before and after. Check the cycling after it: daily starts and
  mean run against the note targets ("Decisions in force"). Then wait the settle time and
  evaluate again (as 1.2).
  Depends on: 1.2, 0.6 (e); Phase 3 first if 1.2 says so. The slope and outdoor-offset rows
  also depend on 0.7 (and the slope rows on 0.6 (b)); the `TempDesired` rows do not.
- [TODO] **2.2** Repeat 2.1 until the success metrics hold across at least one cold-class and one
  mild-class period. Any `CompHysteresis`/`CompIntegral` change (note "Decisions in force") waits
  until 2.2 is done.
  Depends on: 2.1.

Success metrics (readable in HA), on qualifying days:
- Office daily mean within 21.7–22.3 °C; every other room within its band (Overview), the living
  room's upper bound only after Phase 3.
- Daily min/max range per room ≤ 1 K; bedroom and Kilian 08–20 h only.
- Heating starts ≤ 8/day and daily mean run ≥ 20 min (note "Decisions in force").

### Phase 3 — room imbalance (owner)

The four upper-floor rooms run 0.5–1.0 K below the ground-floor living room, and the gap grew by
≈ 0.25–0.3 K at the lower flow temperature of 0.13 (A.2). The curve shifts every room together, so
it cannot fix it. The pump speed cannot be set (note "Bus participants"). The ground-floor loops
are already throttled a bit from last year's balancing; no flow-meter readings are available
(owner, 2026-11-21).

- [TODO] **3.1** Hydraulic balancing (owner-approved as part of this plan). Start when 1.2 shows an
  office-to-living gap > 0.5 K.
  - **3.1a** Rule out room-side causes: doors (the bedroom and Kilian change ≈ 1 K over a day,
    typical of ventilation or closed doors), furniture or rugs over the floor loops, a towel
    radiator or ventilation settings in the bathroom.
  - **3.1b** Record every loop's valve setting (turns or marks; no flow-meter readings), the
    current state.
  - **3.1c** Throttle the living-room loop(s) one small step further (owner's choice of step), one
    change. With the pump fixed this lowers the total flow and widens the flow-return spread
    (≈ 8 K now), which can shorten compressor runs: check the run lengths after it.
  - **3.1d** After the settle time, evaluate as 1.2: repeat 3.1c, or accept the remaining spread.
  Depends on: 1.2.
- [TODO] **3.2** After any manifold change: settle ≥ 4 qualifying days, log it in the change log,
  then continue with Phase 2.
  Depends on: 3.1.

### Phase 4 — optional HA additions

- [TODO] **4.1** Room deviation sensors: one template sensor per room = temperature − target (the
  targets as `input_number` helpers or fixed in the template), with long-term statistics, plus a
  "Room deviation" card on `dashboards/heating-dashboard.yaml` (daily mean statistics graph).
  Depends on: owner approval; then the package rules (`.claude/rules/ha-yaml.md`) and tests.
- [DROPPED] **4.2** `warm_enough` cut-in counters: `warm_enough` is ignored for now (owner).
- [DONE] **4.3** `sensor.geotherm_heating_curve` (`mc/HeatingCurve`, UIN ÷ 100; `?9` poll; long-term
  statistics) (#186).
- [DROPPED] **4.4** Curve relation sensor: built on the superseded linear fit; the formula and
  4.6 replace it.
- [DONE] **4.5** `number.geotherm_heating_temp_desired`: MQTT number, state from
  `ebusd/mc/TempDesired`, command to `ebusd/mc/TempDesired/set` (18–25 °C, 0.5 K steps). Writes only
  when set by hand; the comfort control overwrites it while armed (#186).
- [DONE] **4.6** `sensor.geotherm_heating_circuit_flow_temp_desired_fine` (`mc/FlowTempDesired`,
  0.5 K, `?5`) and the "Curve check" graph (#188); `sensor.heating_compressor_stop_temp` and "Why
  runs end" use it (#189).
- [DONE] **4.7** `sensor.geotherm_heating_outdoor_temp` (`Broadcast/Outsidetemp`, no poll) (#188).
- [DONE] **4.8** `sensor.geotherm_heating_flow_temp_vf2` (`ehp/FlowTemp`, `?3`), on the
  Temperatures card and the "Why runs end" graph against the stop line (owner, 2026-11-21).
- [TODO] **4.9** Remove the whole-degree `sensor.geotherm_heating_circuit_flow_temp_desired`
  (`mc/Status0a`: sensor, `?5` poll, group entry, tests, baseline, its 2 bridge lines) once A.4b
  test (1) is done; its long-term statistics stay in the database.
  Depends on: A.4b test (1).

### Phase 5 — writer and sunny-day exception

- [DONE] **5.1** Decided (owner, 2026-11-21): the comfort control stays off; `TempDesired` is
  tuned by hand with `number.geotherm_heating_temp_desired` (or the panel), no dynamic target.
  If the writer is armed later, set `input_number.heating_comfort_temp` to `TempDesired` − 1 first.
- [TODO] **5.2** (deferred until `warm_enough` works again, separate issue) Sunny-day exception:
  with the curve right, `warm_enough` should switch `off` only on very sunny days. Cutting off at
  the moment of overshoot does little, because the slab was charged the night before (A.2 spikes).
  A forecast-based reduction the evening before is a separate idea (HYPOTHESIS, not planned
  here). Below 3 °C, `off` still heats to `TempDesiredLow`.
  Depends on: 2.2, `warm_enough` fixed.

## Observations

(Log settled evaluations and test results here: dates, outdoor and radiation mean, per-room
deviation, starts/day; step 0.5, 0.6 and A.4b results.)

**2026-11-22 08:30: 0.14 / 22.5 after 35 h, not settled** (ha-mcp hourly statistics). 11-21:
mild (5.5–7.8 °C by day, weatherstation), sunny 09–14 h (≈ 90–110 W/m²), daily mean 5.6 °C /
23 W/m². Then a cold night: weatherstation 5 °C at 18 h → −3.2 °C at 06 h; geoTHERM minimum
−4.25 °C.

| Room (band) | 11-21 00 h | 11-21 16 h | 11-22 07 h | 11-22 07 h vs band |
|---|---|---|---|---|
| Living (21.7–23.3) | 22.4 | 22.8 | 23.2 | in band, top |
| Bathroom (21.7–22.3) | 21.4 | 22.1 | 22.6 | +0.3 |
| **Office (21.7–22.3)** | 22.0 | 22.5 | 22.9 | +0.6 |
| Bedroom (21.2–21.8) | 21.8 | 22.2 | 22.7 | +0.9 (partly sleepers) |
| Kilian (21.2–22.3) | 21.8 | 22.1 | 22.8 | +0.5 |

OBSERVED:
- Bathroom showers on 11-21 at 08–09 h (humidity 54 → 76 %) and 20–22 h (53 → 74 %), left out.
  Outside those hours the bathroom rose by itself: 21.4 → 22.1 by day and 22.4 → 22.6 from 02 to
  07 h, while the humidity fell (57 → 53 %).
- The office rose steadily and was still rising at 07 h, like every other room.
- Fine setpoint: 27.5 until 02:11, 29.5 until 08:20, then 27.5 again (hypothesis (f)). Return
  24.3 → 26.2 °C overnight: the 6 h at 29.5 charged the slab.
- Daily means: office 22.35 (11-21), 22.74 (11-22 to 09 h); living 22.70, 23.14. The gap is
  0.35–0.4 K (P1: 0.57).

**Step 0.6 (e), 2026-11-22 08:43** (owner; read from HA, not `ebusctl read -f`):
- Conditions: geoTHERM outdoor −2.12 → −1.88 °C (within ±0.5 K); no hot water; curve 0.14.
  **Deviation:** the compressor was running, not off. The question "computed only while
  running" is answered by (f) instead: the 02:11 jump came with the compressor off.
- Result: `mc/TempDesired` 22.5 → 22.0 at 08:43:17. The fine setpoint went 27.5 → 27.0 (read
  08:43:32), the whole-degree one stayed 27. So half degrees count, and (e) is refuted. The
  formula predicts −0.6 K; −0.5 K is observed, which fits at 0.5 K resolution.
- Side effect: the compressor stopped at 08:43:18.7, 1 s after the write. VF2 was at 34.0 °C.
  The stop line fell from 34.5 to 34.0 (fine setpoint + 7 K), so the run ended at once. That run
  lasted 31.6 min; it would otherwise have gone on until VF2 reached 34.5. This supports
  HYPOTHESIS: a run ends when VF2 ≥ fine setpoint + `CompHysteresis`, and lowering
  `TempDesired` mid-run ends the run early. Not every run ends there: the 06:30–06:55 run ended
  at VF2 33.7 against a stop line of 36.5.
- A.4b test (1), first data: whole-degree = floor(fine) in three cases (29.5 → 29, 27.5 → 27,
  27.0 → 27).

## References

1. *Bedienungsanleitung geoTHERM exclusiv VWS* 0020025604_00 (VWS 63/2–103/2): heating curves p. 21,
   45° room-setpoint shift p. 18, frost protection p. 10.
2. *Installationsanleitung geoTHERM exclusiv VWS* 0020045204_01 (/2): floor protection p. 46,
   energy balance p. 48, menus C2 p. 58, C4/C5 p. 59, calibration p. 65, compressor and
   FlowTempMax p. 69; revision _00 p. 59 for the frost delay.
3. Kühne formula (sensoCOMFORT, OpenEnergyMonitor forum), used for curves below 0.2.

Links, the /3 successor manual and the owner's printed copy: the note "Bus participants" and
`doc/heating_pv_boost/heating-curve.md`.

## Knowledge homes

- `doc/heating_pv_boost/notes.md` "Owner-side configuration": the settled curve and `TempDesired`
  values with their origin, the room targets and limiting room, and the loop valve settings
  after 3.1.
- `doc/heating_pv_boost/heating-curve.md` "Open": the outcome of A.3 / (a), (b), (e) once
  CONFIRMED, graded (not the note: it is at 23.6 KB of its 24 KB limit).
- `doc/heating_pv_boost/registers.md`: the `mc/Params` field list and the A.4b test (1) result.
- Design doc: HPB-1 already carries the hand-setter line (#186); no further change expected
  (K-4.1 gate).
- Story (the 0.13 episode, the spike analysis, the interpolation error and its correction) →
  `doc/heating_pv_boost/background.md` at Close.

## Status

- [DONE] 0.1 Part A analysis
- [DONE] 0.2 Curve 0.14 confirmed (owner read-back)
- [DONE] 0.3 Owner answers (2026-11-21)
- [DONE] 0.4 Deployed; all new entities report (ebusctl comparisons not run)
- [TODO] 0.5 Machine outdoor value vs weatherstation (first night: geoTHERM ≈ 1 K colder)
- [IN_PROGRESS] 0.6 (e) done: half degrees count; (b) TODO; new hypothesis (f) 2 K setpoint steps
- [TODO] 0.7 Map the setpoint jumps (passive); needed before any slope or offset change
- [DONE] 1.1 Ended early 2026-11-22: office +0.9 and rising; gap to living ≤ 0.5 → Phase 2 first
- [TODO] 1.2 Evaluate settled days (after 2.1's change)
- [IN_PROGRESS] 2.1 `TempDesired` 22.5 → 22.0 (2026-11-22 08:43); settle ≥ 4 qualifying days
- [TODO] 2.2 Tuning loop on the office
- [TODO] 3.1–3.2 Hydraulic balancing
- [DONE] 4.3, 4.5, 4.6, 4.7, 4.8; [DROPPED] 4.2, 4.4; [TODO] 4.1 optional, 4.9 after A.4b test (1)
- [DONE] 5.1; [TODO] 5.2 deferred (`warm_enough`)
- [TODO] Close

## Close

- [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
  plan (`doc/KNOWLEDGE.md#K-6`).
