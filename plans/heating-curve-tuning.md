# Heating — tune the heating curve and `TempDesired` for stable room temperatures

## Overview

Goal: stable room temperatures from the geoTHERM's own weather compensation alone, that is the
heating curve (slope) and `mc/TempDesired` (parallel shift), plus hydraulic balancing of the
floor loops where rooms differ. Loxone's `warm_enough` is ignored for now (owner, 2026-11-21: its
publishing does not update, a separate issue not fixed here); the comfort control stays off and
the target is not adapted dynamically. A later sunny-day exception is out of scope until
`warm_enough` works again.

Room targets (owner):

| Room | Target | Floor (HA floor registry) | HA sensor (Ecowitt channel) |
|---|---|---|---|
| Living room | 22–23 °C | ground floor | `sensor.wheatherstation_indoor_temperature` (base station) |
| Bathroom | 22 °C | upper floor | `sensor.wheatherstation_temperature_5` |
| Office | 22 °C | upper floor | `sensor.wheatherstation_temperature_3` |
| Bedroom | 21.5 °C | upper floor | `sensor.wheatherstation_temperature_1` |
| Kids' room (Kilian) | 21.5–22 °C | upper floor | `sensor.wheatherstation_temperature_2` |

Owner facts (2026-11-21): the bedroom and Kilian's room warm up at night with people sleeping in
them (expected, not a fault). The bedroom sensor sat close to the sleepers and has been moved to a
more neutral spot, so bedroom readings before the move overstate it. Last year the owner
balanced the manifold so the upper floor gets more flow; without it the ground floor was always
warmer.

Outdoor: `sensor.wheatherstation_outdoor_temperature` (HA has no geoTHERM outdoor sensor; see
"Curve relation"). The geoTHERM's own outdoor sensor (VRC DCF) sits on the north side of the
house and gets no sun (owner, 2026-11-21). Sun: `sensor.wheatherstation_solar_radiation`, PV `sensor.victron_solar_yield_total_kwh`.

Machine: geoTHERM exclusiv **VWS 83/2** (art. `0010002787`, matches the bus scan in the note
"Bus participants"). The heating curves are the manufacturer's diagram, see "References" and A.3.

The curve is a panel setting. `TempDesired` is set by hand, at the panel or with
`number.geotherm_heating_temp_desired` (added on this plan's branch). HA writes nothing
automatically: the comfort control stays off.

## Design approach

- **Design IDs touched:** HPB-1 (`doc/heating_pv_boost/design.md`): the comfort knob is the
  only knob only while the writer is armed. With it off, `number.geotherm_heating_temp_desired`
  writes `mc/TempDesired` on a change by hand (one line added to HPB-1 and the note "Invariants").
  The control law itself is unchanged. If the writer is armed later, `mc/TempDesired` =
  `input_number.heating_comfort_temp` + 1 (rows 4–7) and a hand value is overwritten. The curve is
  read by `sensor.geotherm_heating_curve` (`mc/HeatingCurve`, `?9`).
- **Which lever does what:**
  - **Curve slope** (panel) sets the balance between cold and mild weather. Too warm in mild
    weather and right in cold weather: slope too steep. Right in mild weather, too cold in cold
    weather: slope too flat.
  - **`TempDesired`** (panel, later the comfort knob) shifts the whole curve in parallel. All rooms
    too warm or too cold by the same amount, whatever the weather: change `TempDesired`.
  - **Room-to-room differences** (bathroom, office and Kilian colder than the living room,
    bedroom warmer than its target) are hydraulics or room losses. Neither lever fixes them (see
    Phase 3).
  - **`warm_enough`** is ignored for now (see Overview). Later, sunny days only, never to
    correct a curve that is too high.
- **Settle time:** the slab lags by a day or more. Change one setting, then wait at least 4 full
  days, judging only days with comparable outdoor temperature and little sun. Log every change in the
  change log below with the date, time, old and new value.
- **Interactions:** compressor cycling (run model in `doc/heating_pv_boost/notes.md`: a higher flow
  setpoint gives more headroom up to setpoint + hysteresis and longer runs), and frost protection
  (`off` below 3 °C still heats to `TempDesiredLow` 20 °C, note "Frost protection").
- Invariants checked: no automatic write and no change to the control law. The new register
  `mc/HeatingCurve` needs its two bridge lines (note "Invariants"); the hand setter uses the
  existing `mc/TempDesired` and `/set` lines.

## Change log (owner settings)

| When (local) | Setting | Old → new | Evidence |
|---|---|---|---|
| 2026-11-14 ≈ 20:20 | Heating curve | 0.15 → 0.13 | OBSERVED, estimated from the data: the flow setpoint stepped 27 → 26 °C while it got colder outside (2.6 → 1.8 °C). No other input changed. Owner: "after the heat spike" |
| 2026-11-14 23:05 – 11-15 00:45 | `TempDesired` | 22 → 21 → 19 (briefly) → 22 | OBSERVED: the HA target followed the comfort knob (21, 18), so these were writes by the armed Phase 2 writer |
| 2026-11-15 ≈ 08:30 – 11-16 00:07 | `mc/OperatingMode` | `on` → `off` → `on` | HYPOTHESIS: the setpoint ran ≈ 2 K below the 0.13 relation all day (frost protection at `TempDesiredLow` 20); `heating_mode_last_written` = 11-16 00:07:52, and the setpoint jumped 25 → 27 at 00:08 |
| 2026-11-20 evening (read back 22:14) | Heating curve | 0.13 → 0.14 | Owner: read back at 22:14 and shown on the wall unit |
| 2026-11-20 22:01:44 | `TempDesired` | 22 → 22.5 | Owner: written by HA (the writer was armed for ≈ 3 s; switched off at 22:01:47) |
| 2026-11-20 22:01:47 | Comfort control | on → off | Owner: `warm_enough` does not update; stays off, `warm_enough` ignored |
| 2026-11-21 or shortly before | Bedroom sensor | moved away from the bed to a neutral spot | Owner. Bedroom data before the move are not comparable |
| unchanged | `CompHysteresis` 7 K, `CompIntegral` −180, `TempDesiredLow` 20 (owner-stated) | — | read live 2026-11-21 (the first two) |

## Part A — baseline and current state (ha-mcp, long-term statistics, 2026-11-21)

Data come from the recorder's long-term statistics (hourly or 5 min means). The read-only tools give
no state history for non-numeric entities, so the mode and `warm_enough` history cannot be counted
(see A.4).

### A.1 Did the changes take effect?

- **`TempDesired` = 22.5: CONFIRMED** (read-back `sensor.geotherm_heating_temp_desired` 22.5 since
  2026-11-20 22:01:44; the owner confirms HA wrote it).
- **Curve 0.14: CONFIRMED by the owner** (read back at 22:14, shown on the wall unit). The data
  agree: the only setpoint step on 11-20 that the weather does not
  explain is 24 → 25 → 26 °C between 22:00 and 22:20, at a steady 8.9 °C outside, together with
  the `TempDesired` write. The steps at 18:05 (24 → 26) and 21:40 (26 → 24) match the usual
  24 ↔ 26 transitions of the 0.13 period at about 7–9 °C outside. Since then the setpoint has been
  26 °C at 5.4–9.7 °C outside (one hour at 25), where the 0.13/22 setting gave 24 °C at 8–11 °C
  (nights of 11-19/20). The fit (A.3) predicts ≈ 25 °C for `TempDesired` +0.5 alone and ≈ 26 °C for
  both changes, which matches "both took effect".
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
  targets on average (bathroom −0.26, bedroom +0.5), but falling: P2 days ran 21.5–21.9 in the
  bathroom and reached 21.2 in bedroom, Kilian and bathroom on the evening of 11-20.
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

### A.3 Curve relation (fit from the data)

Flow setpoint = `mc/Status0a` field 4 (whole °C; 0 during hot water, excluded). The machine uses
its own outdoor sensor on the north side, without sun (owner), not the weatherstation. The setpoint
often drops 1–2 K between 08 and 11 h without a matching weatherstation change; sun on the
machine's sensor does not explain it. HYPOTHESIS: the controller damps its outdoor value, or the
two sensors differ in the morning (a sunlit weatherstation would read warmer, not colder). The fit
uses the weatherstation and night/evening hours. Error ±1 K.

| Outdoor (weatherstation) | 0.15 / 22 (P1) | 0.13 / 22 (P2) | 0.14 / 22.5 (P3) |
|---|---|---|---|
| −2 °C | 29 (11-14 07 h, −1.8) | 27 (11-16 01–04 h) | — |
| 2–3 °C | 27 | — | — |
| 3.5–6 °C | 26 (27 below ≈ 3.5) | 26 | 26 (5.4–6.9) |
| 7–9 °C | 26 (7.6–7.9) | 24 | 26 (7.7–9.7; one hour 25) |
| 10–11 °C | 24 (daytime) | 24 | — |
| 13–15 °C | — | 23 | — |

Fit (HYPOTHESIS; an empirical shape, not a Vaillant formula): setpoint ≈ TD − 1.4 + b·(TD − T_out)
with b ≈ 0.38 K/K at 0.15, ≈ 0.28 at 0.13, so ≈ 0.33 at 0.14. A `TempDesired` step moves the
setpoint by about 1 + b (≈ 1.3 K per K), which matches 11-14 23:05 (TD −1 → −1 K) and 11-15 00:45.
This also explains why 0.13 gave 24 ↔ 26 jumps (never 25) at 7 °C in the integer setpoint.
Consequence: 0.14 / 22.5 ≈ 0.15 / 22 in mild weather (+0.4 K at 8 °C) and ≈ 0.5 K lower at 0 °C.
So P3 will probably land near the P1 room temperatures in mild weather, above target in the
bedroom and Kilian.

**Manufacturer curve.** The VWS 83/2 operating manual (Ref. 1, p. 21, menu "HK2 Parameter") shows
the "Heizkurven" diagram: flow setpoint over the outdoor temperature (+20 … −20 °C) for curves
0.2 … 4.0 at room setpoint 20 °C. A different room setpoint moves the curve in parallel along a
45° axis (Ref. 1, p. 18; the diagram marks the room-setpoint axis 15 / 20 / 22). So flow(T, RS) =
flow₂₀(T − (RS − 20)) + (RS − 20), the same form as the fit above. Floor heating: curves < 0.4
(Ref. 1, p. 21). Ref. 1 draws no curve below 0.2. The successor's installation manual (Ref. 2,
p. 66, menu C2; written for the VWS 63/3–103/3, not the 83/2) has the same diagram plus a 0.1
curve; its 0.2 and 0.4 curves match Ref. 1 to 0.1 K, so the 0.1 curve is taken from Ref. 2
(HYPOTHESIS that the /2 controller uses the same 0.1 curve). Values were read from the diagrams'
vector paths in the PDFs (not by eye, ±0.2 K). 0.13–0.15 are interpolated linearly between 0.1
and 0.2, so **those columns are an interpolation, not manufacturer values.**

| Outdoor | 0.1 | 0.2 | 0.4 | 0.13 (interp.) | 0.14 (interp.) | 0.15 (interp.) |
|---|---|---|---|---|---|---|
| +15 °C | 22.4 | 22.5 | 24.3 | 22.4 | 22.4 | 22.4 |
| +10 °C | 24.1 | 24.5 | 27.6 | 24.2 | 24.3 | 24.3 |
| +5 °C | 25.5 | 26.3 | 30.4 | 25.7 | 25.8 | 25.9 |
| 0 °C | 26.7 | 28.0 | 33.0 | 27.1 | 27.2 | 27.3 |
| −5 °C | 27.7 | 29.5 | 35.5 | 28.3 | 28.4 | 28.6 |
| −10 °C | 28.6 | 31.0 | 37.7 | 29.3 | 29.5 | 29.8 |
| −20 °C | 29.7 | 33.2 | 41.9 | 30.7 | 31.1 | 31.4 |

Shifted to our room setpoints, the diagram predicts 0.15 / 22: 28.5 °C at 5 °C, 27.6 at 8 °C;
0.13 / 22: 28.3 at 5 °C, 27.4 at 8 °C, 25.5 at 14 °C; 0.14 / 22.5: 29.0 at 5 °C, 28.2 at 8 °C.

OBSERVED discrepancy, open: the machine runs **1.5–3.5 K below** the diagram (0.13 / 22 at 8 °C:
24 observed vs 27.4), and the diagram puts 0.13 vs 0.15 only ≈ 0.2–0.4 K apart, while the data show
≈ 2 K (24 vs 26 at 7–9 °C). HYPOTHESES, none tested: (a) the machine's outdoor value (north side,
damped) reads well above the weatherstation; (b) the panel value is not on the diagram's scale
below 0.2 (the diagram draws nothing between 0.1 and 0.2); (c) `mc/Status0a` field 4 is not the
plain curve setpoint (e.g. after an internal correction). (a) is checked first, see step 0.5.
Until this is resolved, the size column of the Phase 2 table is from our data, not from the
diagram.

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
  (A.1 change log); the mode has been `on` since.
- The Energy-mode `off` meter stayed 0 every day: the heating-circuit pump never stopped.

### A.5 What can and cannot be concluded yet

- Can: `TempDesired` 22.5 is in the machine. The setpoint is now ≈ 2 K higher than under 0.13/22 at
  the same mild outdoor temperature. 0.13/22 in mild weather gave rooms 0.8–0.9 K colder than
  0.15/22 gave in colder weather (P1), and P1 itself was above the targets.
- Cannot: where 0.14/22.5 settles (needs ≥ 4 days,
  the slab lags); how it behaves in cold weather (no frost day since); how much of the 11-21
  overnight rise is the setting vs the normal night rise.

## Steps

### Phase 0 — verify and record

- [DONE] **0.1** Part A analysis (above).
- [DONE] **0.2** Curve 0.14 confirmed (owner read-back 2026-11-20 22:14, wall unit).
- [DONE] **0.3** Owner answers (2026-11-21): 22.5 written by HA; the comfort control is off
  because `warm_enough` does not update (separate issue), and `warm_enough` is ignored for now;
  bedroom sensor moved away from the sleepers (night warming by occupants is expected in the
  bedroom and Kilian's room); hydraulic balancing is part of this plan; the upper floor already
  gets more flow from last year's balancing; no dynamic target.
- [TODO] **0.4** Deploy the HA additions (steps 4.3, 4.5): add the bridge lines
  `topic ebusd/mc/HeatingCurve in 0` and `topic ebusd/mc/HeatingCurve/get out 0`, restart
  Mosquitto, check that `sensor.geotherm_heating_curve` reads 0.14 and that
  `number.geotherm_heating_temp_desired` shows 22.5.
- [TODO] **0.5** Compare the machine's outdoor value with the weatherstation (A.3 discrepancy,
  hypothesis a). `ehp/Status01` field `temp_2` (outside) times out on this unit (registers.md), so
  first look for another ebusd register with the geoTHERM outdoor temperature (read-only, no HA
  change without approval). Without one, the owner reads the outdoor value at the panel or the
  VR 90 a few times (night, 08–11 h, afternoon) and notes it with the time; compare with
  `sensor.wheatherstation_outdoor_temperature` and with the flow setpoint the diagram predicts.
  Result → "Observations".
  Depends on: nothing (can run during Phase 1).

### Phase 1 — settle the current setting (0.14 / 22.5), no changes

- [TODO] **1.1** Leave curve, `TempDesired`, the hysteresis and the integral alone until at least
  2026-11-25 (4 full days). The comfort control stays off.
  Depends on: 0.2.
- [TODO] **1.2** Evaluate the settled days: per room the daily mean minus target, min/max, the
  outdoor mean and the radiation. Judge only days with radiation mean < 25 W/m², and compare cold
  days (< 4 °C) with mild days (> 7 °C) separately. Expected (HYPOTHESIS, A.3): close to P1 in mild
  weather, so the living room ≈ 23, the bathroom ≈ 22.3–22.6, the bedroom ≈ 22.5–22.8 (over target;
less after the sensor move). Judge the bedroom and Kilian's room on daytime values: their night
rise comes from the sleepers.
  Log the result under "Observations" in this plan.
  Depends on: 1.1.

### Phase 2 — tune, one change at a time

Decision rule per evaluation (use the bathroom, the room with the largest lag, as the limiting room
for the 22 °C rooms; the bedroom has its own issue, Phase 3):

| Settled result | Change | Size |
|---|---|---|
| All rooms over target by about the same amount, mild and cold alike | `TempDesired` down | 0.5 K (≈ 0.65 K flow) |
| All rooms under target by about the same amount | `TempDesired` up | 0.5 K |
| Right on mild days, too cold on cold days | slope up | 0.01 |
| Right on cold days, too warm on mild days | slope down | 0.01 |
| Only some rooms off, others on target | no curve change: Phase 3 | — |
| A sunny day overshoots | no change: the PV exception (Phase 5) | — |

Sizes: by the manufacturer diagram (A.3), a slope step of 0.01 moves the flow only ≈ 0.1–0.2 K
around 0.13–0.15; our data showed ≈ 1 K per 0.01. Until step 0.5 explains the gap, size steps on
the data and log the flow setpoint before and after.

- [TODO] **2.1** Apply at most one change from the table (`TempDesired` with
  `number.geotherm_heating_temp_desired`, the curve at the panel), log it in the change log, then wait ≥ 4
  full days of comparable weather before the next evaluation (1.2 again).
  Depends on: 1.2.
- [TODO] **2.2** Repeat 2.1 until all rooms are within ±0.3 K of their target band on non-sunny days,
  across at least one cold spell (< 3 °C) and one mild spell. Track success with the metrics below.
  Depends on: 2.1.

Success metrics (readable in HA):
- Per room, the daily mean minus target within ±0.3 K on days with radiation mean < 25 W/m².
- Daily min/max range per room ≤ 1 K outside sunny days.
- Heating starts/day not above the P1 level (≈ 7) at comparable outdoor temperature;
  average run ≥ 20–30 min (cycling plan targets).
- Mode stays `on` all day (no correction needed from outside the curve).

### Phase 3 — room imbalance (owner)

The four upper-floor rooms (bathroom, office, Kilian, bedroom) run 0.5–1.0 K below the ground-floor
living room, and the gap grew by ≈ 0.25–0.3 K at the lower flow temperature of 0.13 (A.2). This
is the floor imbalance the owner already balanced against last year. The curve shifts every room
together, so it cannot fix it. All loops and valves are open and the pump speed cannot be set
(note "Owner-side configuration", "Bus participants"). The bedroom's apparent warmth was partly
the sensor position (moved).

- [TODO] **3.1** Hydraulic balancing (owner-approved as part of this plan). Options:
  - Note each loop's flow-meter reading first (the current, last-year state), then shift more
    flow to the upper floor: throttle the ground-floor (living room) loops a little further.
    With the pump fixed, this reduces the total flow and raises the flow-return spread (≈ 8 K
    now), which shortens compressor runs: keep the change small and check the run lengths after
    it (step 5.3).
  - Within the upper floor: the bathroom (largest lag, target 22) gets the most; the bedroom
    (target 21.5) the least.
  - Then raise the curve or `TempDesired` so the cold rooms reach target while the throttled warm
    rooms stay in their band.
  - Room-side causes to rule out: doors (the bedroom and Kilian change ≈ 1 K over a day, typical of
    ventilation or closed doors), furniture or rugs over the floor loops, a towel radiator or
    ventilation settings in the bathroom.
  - Accept the imbalance and tune for the limiting room.
  Depends on: 1.2 (a settled baseline to compare against).
- [TODO] **3.2** After any manifold change: back to Phase 1 (settle ≥ 4 days), log it in the change
  log.

### Phase 4 — optional HA additions (each needs approval; none implemented)

Implemented on branch `claude/heating-curve-tuning` (owner request, 2026-11-21): 4.3 and 4.5.
Still optional: 4.1, 4.4.

- [TODO] **4.1** Room deviation sensors: one template sensor per room = temperature − target (the
  targets as `input_number` helpers or fixed in the template), with long-term statistics, plus a
  "Room deviation" card on `dashboards/heating-dashboard.yaml` (daily mean statistics graph).
- [DROPPED] **4.2** `warm_enough` cut-in counters: `warm_enough` is ignored for now (owner).
- [DONE] **4.3** `sensor.geotherm_heating_curve` (`mc/HeatingCurve`, UIN ÷ 100, same
  `cfgheatsinktype=1` condition as `TempDesired`; `?9` poll; long-term statistics). Bridge lines in
  step 0.4.
- [TODO] **4.4** Curve relation sensor: (flow setpoint − `TempDesired`) ÷ (`TempDesired` −
  outdoor), as a statistics-backed sensor, for comparing settings across weather (A.3). Low value
  if 4.3 exists; skip it then.
- [DONE] **4.5** `number.geotherm_heating_temp_desired`: MQTT number, state from
  `ebusd/mc/TempDesired`, command to `ebusd/mc/TempDesired/set` (18–25 °C, 0.5 K steps,
  one-decimal payload). Writes only when set by hand; the comfort control overwrites it while
  armed. On the heating dashboard next to the setpoint rows.
  Depends on (4.1, 4.4): owner approval; then the package rules (`.claude/rules/ha-yaml.md`) and tests.

### Phase 5 — writer, sunny-day exception, cycling

- [DONE] **5.1** Decided (owner, 2026-11-21): the comfort control stays off; `TempDesired` is
  tuned by hand with `number.geotherm_heating_temp_desired` (or the panel), no dynamic target.
  If the writer is armed later, set `input_number.heating_comfort_temp` to `TempDesired` − 1 first.
- [TODO] **5.2** (deferred until `warm_enough` works again, separate issue) Sunny-day exception:
  with the curve right, `warm_enough` should switch `off` only on very sunny days. Note the lag:
  cutting off at the moment of overshoot does little, because the
  slab was charged the night before (A.2 spikes). A forecast-based reduction the evening before is
  a separate idea (HYPOTHESIS, not planned here). Below 3 °C, `off` still heats to `TempDesiredLow`.
  Depends on: 2.2, `warm_enough` fixed.
- [TODO] **5.3** Cycling check after each change: setpoint + hysteresis vs return + ≈ 8 K
  (cycling run model, note). A higher setpoint gives more headroom and longer runs (11-21: setpoint 26,
  return 24.5, runs ≈ 33 min); a lower one shortens them. Any `CompHysteresis` or
  `CompIntegral` change waits until Phase 2 has settled (one change at a time across both plans).

## Observations

(Log settled evaluations here: dates, outdoor and radiation mean, per-room deviation, starts/day.)

## References

1. Vaillant, *Bedienungsanleitung geoTHERM exclusiv VWS* (operating manual, DE/AT/CH),
   0020025604_00, 02/2007. Covers VWS 63/2, **83/2** (art. 0010002787) and 103/2 (p. 3).
   Heating-curve diagram ("Heizkurven", curves 0.2 … 4.0, room setpoint 20 °C) and floor-heating
   advice (< 0.4): p. 21, menu "HK2 Parameter"; room setpoint as a 45° parallel shift: p. 18.
   Download: https://kontakt.vaillant.de/documents/download/73792/
   The owner's printed manual for this unit shows the same diagram (owner photo, 2026-11-21:
   20–90 °C scale, curves 0.2 … 4.0, bold 1.5 with the dash-dot example at −15 °C; no curve below
   0.2). Spot checks against the A.3 values at −20 °C (0.2 ≈ 33, 0.6 ≈ 50, 1.0 ≈ 65) agree.
2. Vaillant, *Installationsanleitung geoTHERM exclusiv* (installation manual, DE/AT/CH),
   0020087974_00, 04/2010. Valid only for VWS 63/3, 83/3, 103/3 (§1.4), the successor; used only
   for the 0.1 curve that Ref. 1 lacks (same diagram otherwise). Diagram: p. 66, Tab. 9.6 menu C2.
   Download: https://kontakt.vaillant.de/documents/download/78824/

Neither manual gives a formula for the curves: the A.3 table is read off the diagrams.

## Knowledge homes

- `doc/heating_pv_boost/notes.md` "Owner-side configuration": the settled curve and `TempDesired`
  values with their origin, and the room targets (owner values).
- `doc/heating_pv_boost/notes.md` "Hardware": the machine is a VWS 83/2; the manufacturer curve
  (Ref. 1, A.3 table) and the outdoor sensor on the north side without sun. At Close check the
  note's citations of "VWS 82/3 installation manual 0020132514_00" ("Frost protection", "Room
  influence") against the 83/2 documents.
- `doc/heating_pv_boost/notes.md` "Hardware" or "Decisions in force": the curve relation (A.3)
  only once CONFIRMED, graded; the "TempDesired step ≈ (1 + b) K flow" rule as one line.
- Design doc: no change expected (no architecture change; K-4.1 gate). Revisit only if Phase 4
  adds a component.
- Story (the 0.13 episode, the spike analysis) → `doc/heating_pv_boost/background.md`.

## Status

- [DONE] 0.1 Part A analysis
- [DONE] 0.2 Curve 0.14 confirmed (owner read-back)
- [DONE] 0.3 Owner answers (2026-11-21)
- [TODO] 0.4 Deploy: 2 bridge lines for `mc/HeatingCurve`, restart Mosquitto, check both entities
- [TODO] 0.5 Machine outdoor value vs weatherstation (diagram discrepancy, A.3)
- [DONE] Manufacturer heating curve sourced (References, A.3); outdoor sensor location recorded
- [IN_PROGRESS] 1.1 Settle 0.14 / 22.5, no changes until ≥ 2026-11-25
- [TODO] 1.2 Evaluate settled days
- [TODO] 2.1–2.2 Tuning loop (`TempDesired` by hand, curve at the panel)
- [TODO] 3.1–3.2 Hydraulic balancing (upper floor vs ground floor)
- [DONE] 4.3 curve sensor, 4.5 hand setter (branch `claude/heating-curve-tuning`); [DROPPED] 4.2;
  [TODO] 4.1, 4.4 optional
- [DONE] 5.1 knob decided; [TODO] 5.2 deferred (`warm_enough`); [TODO] 5.3 cycling check
- [TODO] Close

## Close

- [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this
  plan (`doc/KNOWLEDGE.md#K-6`).
