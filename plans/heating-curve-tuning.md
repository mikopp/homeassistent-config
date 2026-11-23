# Heating — tune the heating curve and `TempDesired` for stable room temperatures

Done steps are collapsed to one line. Their full analysis (baseline Part A, the curve tables, the
step 0.6 procedure, the run scans) is in git: this file at commit `4956e8a`; the 11-22 room
readings and the long 2.1 / 4.9 texts at commit `91d6f1b`.

## Overview

Goal: stable room temperatures from the geoTHERM's own weather compensation alone, that is the
heating curve (slope), `mc/TempDesired` (parallel shift) and the outdoor offset, plus hydraulic
balancing of the floor loops where rooms differ. The goal is the real room temperature measured
by the indoor Ecowitt sensors, not a particular setting (owner). Loxone's `warm_enough` is ignored
for now (its publishing does not update, a separate issue); the comfort control stays off and the
target is not adapted dynamically.

Room targets (owner):

| Room | Target | Band (target ± 0.3 K) | Floor | HA sensor (Ecowitt channel) |
|---|---|---|---|---|
| Living room | 22–23 °C | 21.7–23.3 | ground floor | `sensor.wheatherstation_indoor_temperature` (base station) |
| Bathroom | 22 °C | 21.7–22.3 | upper floor | `sensor.wheatherstation_temperature_5` |
| **Office (limiting room)** | 22 °C | 21.7–22.3 | upper floor | `sensor.wheatherstation_temperature_3` |
| Bedroom | 21.5 °C | 21.2–21.8 | upper floor | `sensor.wheatherstation_temperature_1` |
| Kids' room (Kilian) | 21.5–22 °C | 21.2–22.3 | upper floor | `sensor.wheatherstation_temperature_2` |

No YAML in this repo references the room sensors. Owner facts: the bedroom and Kilian's room warm
up at night with people sleeping in them (judge them on 08–20 h); the bedroom sensor was moved to a
neutral spot on or before 2026-11-21 (older bedroom data overstate it); last year's balancing
gives the upper floor more flow. Bathroom: a temperature spike with a humidity spike
(`sensor.wheatherstation_humidity_5`) is a shower; leave those hours out of every evaluation.
Office (owner, 2026-11-23): north-west, no sun by day; on **Mondays and Fridays** someone works
there all day (screen, notebook), which adds heat. Leave Mondays and Fridays out of every office
evaluation, and judge it only over several days, never one.

Outdoor: the weatherstation `sensor.wheatherstation_outdoor_temperature` and the machine's own
`sensor.geotherm_heating_outdoor_temp` (north side, no sun). Sun:
`sensor.wheatherstation_solar_radiation`. Machine: geoTHERM exclusiv **VWS 83/2**: device doc
`doc/devices/vaillant-vws-83-2/` (manuals in its README; heating curves: `heating-curve.md`).

**All settings go over ebus (owner, 2026-11-22).** For this automation the VR 90/3 and the unit's
own menus are manual inputs only: they write a setting only when someone changes it there, and
their whole-number entry steps do not limit the bus, so 0.5 K `TempDesired` writes are fine
(device VWS-24). What counts is the ebus register format and what the controller does with it
(decodes: device `registers-*.md`):

| Setting | Register (catalog) | Bus format | How |
|---|---|---|---|
| `TempDesired` | `mc/TempDesired` (`0e3200`) | D1C, 0.5 K | `number.geotherm_heating_temp_desired` (#186) or `ebusctl write -c mc TempDesired 21.5` |
| Curve slope | `mc/HeatingCurve` (`0e3500`) | UIN ÷ 100, 0.01 | `ebusctl write -c mc HeatingCurve 0.14` (no HA setter) |
| Outdoor offset | `ehp/OutsideTempOffset` (`0ec300`, installer level) | D2C, 1/16 K | `ebusctl write -c ehp OutsideTempOffset 0.5` |

Read back every write with `ebusctl read -f` and log it in the change log. HA writes nothing
automatically.

## Design approach

- **Design IDs touched:** HPB-1 (`doc/heating_pv_boost/design.md`) already carries the hand-setter
  line (#186). The control law is unchanged. If the writer is armed later, `mc/TempDesired` =
  `input_number.heating_comfort_temp` + 1 and a hand value is overwritten.
- **What the compressor acts on: the whole-degree setpoint** W = floor(`mc/FlowTempDesired`),
  passed on by `uih` (device VWS-3). Runs end at integral ≈ 0,
  so the mean flow ≈ W (HYPOTHESIS). A lever changes the room level only when it changes W, at
  least for part of the outdoor range. 1 K of W ≈ 0.6–0.7 K room (rough estimate, HYPOTHESIS).
- **Levers:**
  - **`TempDesired`** shifts the curve in parallel: from a `TempDesired` ending in .0 a −0.5 K
    step lowers W by 1 K and a +0.5 K step does nothing; from one ending in .5 it is the other way
    round (device VWS-25). Near a jump of the curve the half degree may also move the jump by
    ≈ 0.5 K outdoor (HYPOTHESIS, 0.7).
  - **Curve slope** sets the balance between cold and mild weather. Too warm mild and right cold:
    too steep; right mild and too cold cold: too flat. Step 0.01 ≈ 0.25 K flow mild, ≈ 0.45 K at
    −10 °C (Kühne formula; below 0.2 the formula is the only model, HYPOTHESIS).
  - **Outdoor offset** (owner: 0 now). A tuning lever (owner): the rooms are the reference, so
    which outdoor sensor is "right" does not matter. Two working HYPOTHESES, tested at the first
    offset change (0.8): (a) the curve uses the corrected value; (b) the controller keeps values
    finer than whole K (0.5 K assumed). If (a) holds, a positive offset makes the geoTHERM read
    warmer, lowers the flow and moves the curve's jumps along the outdoor axis by the offset;
    averaged ≈ 0.12 K flow per 0.5 K at slope 0.14, a trim finer than `TempDesired`. Side effects
    (accepted): frost protection ("below 3 °C"), the AT-Abschaltgrenze and the cooling release
    move with it. Log the offset with every change; re-check it before the cooling season.
  - **Room-to-room differences** are hydraulics or room losses: Phase 3, no lever above fixes them.
- **Limiting room:** steer on the **office** (22 °C). A living-room overshoot is accepted until
  Phase 3.
- **Order (owner):** office-to-living gap > 0.5 K → Phase 3 before Phase 2. One change at a time,
  each followed by the settle time.
- **Qualifying days:** daily radiation mean < 25 W/m². Cold class: daily outdoor mean < 3 °C; mild:
  > 7 °C. Comparable: same class, daily means within ±2 K. With one class only, only
  `TempDesired` or the offset may change; slope rows need both classes.
- **Settle time:** ≥ 4 full qualifying days after a change before the next evaluation.
- **Interactions:** run length is set by the integral (Observations); floor protection =
  `FlowTempMax` + `CompHysteresis` + 2 K at VF2 (device VWS-7); frost protection (`off` below
  3 °C still heats to `TempDesiredLow`, 20 °C here) (device VWS-6).
- Invariants: no automatic write, no change to the control law, every register read has its
  bridge lines and poll (note "Invariants").

## Change log (owner settings)

| When (local) | Setting | Old → new | Evidence |
|---|---|---|---|
| 2026-11-14 – 11-16 | Curve 0.15 → 0.13; `TempDesired` writer episode; mode `off` for a day (HYPOTHESIS) | — | the 0.13 episode, detail at commit `4956e8a` |
| 2026-11-20 evening (read back 22:14) | Heating curve | 0.13 → 0.14 | Owner |
| 2026-11-20 22:01:44 | `TempDesired` | 22 → 22.5 | Owner: written by HA (writer armed ≈ 3 s) |
| 2026-11-20 22:01:47 | Comfort control | on → off | Owner |
| on or before 2026-11-21 | Bedroom sensor | moved to a neutral spot | Owner |
| 2026-11-21 evening | Heating curve | 0.14 → ? → 0.14 | Owner test; the setpoint followed within minutes, compressor running |
| 2026-11-22 08:43:17 | `TempDesired` | 22.5 → 22.0 | Owner, hand setter (2.1). Fine 27.5 → 27.0, W stayed 27 |
| 2026-11-22 08:43:21 | `input_number.heating_comfort_temp` | 21.5 → 21.0 | Owner, keeps the knob 1 K below `TempDesired` (5.1) |
| 2026-11-22 10:10 – 10:40 | `TempDesired` | 22.0 → 22.5 → 22.0 | Owner, `uih` test; set back within 1 h, settle time not restarted |
| 2026-11-22 17:07:45 | `TempDesired` | 22.0 → 21.5 | Owner, hand setter (2.1), during hot water. Forced reads after it: `mc` 26.5, `uih` 26.00 (was 27.0 / 27): W −1 K |
| 2026-11-22 17:07:57 | `input_number.heating_comfort_temp` | 21.0 → 20.5 | Owner, 1 K below `TempDesired` (5.1) |
| before 2026-11-21 | `CompHysteresis` | likely 6 → 7 K | Owner, during the cycling tuning |
| unchanged | everything else | — | current values: the note's "Owner-side configuration" |

## Baseline (summary of Part A, 2026-11-21)

Room daily means: P1 = 0.15 / 22 (11-07…13, outdoor 4.6 °C), P2 = 0.13 / 22 (11-17…20, 8.9 °C).

| Room (target) | P1 | P2 | P1 / P2 vs living |
|---|---|---|---|
| Living (22–23) | 23.33 | 22.74 | — |
| Bathroom (22) | 22.65 | 21.74 | −0.68 / −1.00 |
| Office (22) | 22.76 | 21.93 | −0.57 / −0.81 |
| Bedroom (21.5) | 22.83 | 22.01 | −0.50 / −0.73 |
| Kilian (21.5–22) | 22.63 | 21.80 | −0.70 / −0.94 |

OBSERVED: P1 was 0.5–1.3 K above target except the living room; P2 near target but falling. The
upper-floor gap to the living room grew ≈ 0.25–0.3 K at the lower flow. Sun spikes (11-05, 11-14)
come on sunny days after a cold night: lowering the curve after a spike over-corrects
(HYPOTHESIS). The machine runs 0–2 K below the Kühne formula; explained partly by the
whole-degree W and the curve's jumps (f).

**Open curve hypotheses:**
- (a) The geoTHERM outdoor value is offset from the weatherstation (first night ≈ 1 K colder).
  Damping refuted (jumps fall in the same 5 min as the edge crossing). Step 0.5, informative only.
- (b) Below 0.2 the curve does not follow the formula: answered passively by 0.7.
- (f) The curve works in **steps** over outdoor temperature, flat in between (2 K and 1 K seen,
  no hysteresis so far; the 0.13 period's 24 ↔ 26 jumps were 2 K). Edges seen: the table in 0.7.
  Open: the other edges, the step sizes, whether the offset moves the edges.

## Steps

### Phase 0 — verify and record

- [DONE] **0.1–0.4, 0.6, 0.9, 0.12** Baseline, curve 0.14, owner answers, HA additions; half
  degrees of `TempDesired` move the fine setpoint; hydraulic plan 6 (device VWS-2, -4, -7, -18);
  every hot-water charge ends with a 2–4 min heating tail (device VWS-13). [DROPPED] **0.10**
  (panels are manual inputs only, device VWS-24).
- [TODO] **0.5** Machine outdoor value vs weatherstation, more nights (first night: geoTHERM
  ≈ 1 K colder 20–06 h, ≈ 0.5 K at 08:30). Informative only, no precondition for the offset. Use
  the difference to read edge positions in weatherstation terms. Result → "Observations".
  Data so far (HA hourly means, geoTHERM − weatherstation): daily −0.5 K (11-22), −1.1 K (11-23);
  by hour 11-23: −0.7 (00 h), −1.2 (04 h), −0.55 (12 h), **−2.5 (18 h**, −3.5 vs −1.0, no sun).
  The gap is not constant: largest on the evening after a sunny day (HYPOTHESIS: the north-side
  sensor cools faster).
- [TODO] **0.7** Map the setpoint jumps (hypothesis (f), device VWS-30). Passive. From the
  "Curve check" graph (5 min statistics, ≈ 10 days kept): every jump of the fine setpoint outside
  hot water, with time, size and geoTHERM outdoor value, per `TempDesired`, next to the formula.
  Questions: fixed step size? Hysteresis? Whole curve stepped? Why: with steps, a slope change of
  0.01 may do nothing or shift a whole step. Candidate causes of W 0–2 K below the formula
  (UNPROVEN): W's floor, the steps, the colder outdoor value. Enough when edges span about −5 to
  +10 °C; once CONFIRMED → device VWS-30. Edges so far (geoTHERM outdoor value):

  | `TempDesired` | Edge (outdoor) | Levels (fine) | Seen |
  |---|---|---|---|
  | 22.5 | ≈ −2.5 | 29.5 ↔ 27.5 (2 K) | 11-22 02:11 / 08:20 |
  | 22.0 | ≈ 1.9 (1.81 ↔ 2.06) | 27 ↔ 26 (1 K) | 11-22 11:10 / 16:30 |
  | 21.5 | ≈ 1.4 (1.31 ↔ 1.56) | 26.5 ↔ 25.5 (1 K) | 11-23 10:45 down, 15:40 up |
  | 21.5 | ≈ −3.5 (−3.38 ↔ −3.69) | 26.5 → 28.5 (2 K) | 11-23 18:25 up (down not yet seen) |

  HYPOTHESIS (two pairs): an edge moves along the outdoor axis by the same amount as
  `TempDesired` (mild edge −0.5 K for −0.5 K, cold edge ≈ −1 K for −1 K), and each level drops by
  the same amount, as if the curve were a stepped function of (`TempDesired` − outdoor). At 21.5
  the 26.5 level is flat over ≈ 5 K outdoor (−3.5…1.4), far wider than the formula's slope.
- [TODO] **0.8** Outdoor offset hypotheses (a) and (b). Tested when the Phase 2 table first calls
  for an offset change. Settles VWS-36 (format: device `registers-ehp.md`; no report of a
  non-integer write found, manuals cover only the panel's 1 K steps). Test, in mild weather away
  from 3 °C and the cut-off:
  1. Read `ehp OutsideTempOffset` (expect 0), `ehp OutsideTemp` (raw), `uih OutsideTemp`, the
     broadcast and `mc FlowTempDesired`.
  2. `ebusctl write -c ehp OutsideTempOffset 0.5`, read back with `-f`: 0.5 → (b) holds; 0 or 1 →
     rounded; error → rejected.
  3. Read step 1 again. Raw `ehp` unchanged while the broadcast or `uih` and the setpoint move →
     (a) holds. Nothing moves → no lever: set 0 back, drop the offset rows.
  Result → "Observations"; the step size goes into the Phase 2 table.
  Baseline for step 1 (11-23 ≈ 20:15, `read -f`): offset **0.00**; `ehp`, `uih` and broadcast
  outdoor all −4.25;ok; `mc FlowTempDesired` 28.5, `uih` 28.00, `TempDesired` 21.5, curve 0.14.
  `uih OutsideTemp` is not cached: read it with `-f`.
- [TODO] **0.11** Does a `TempDesired`-only write start or stop the compressor (device VWS-25,
  design HPB-1 Known gaps)? At the next 2.2 change, with the integral far from 0 and VF2 far
  from the stop line, log compressor state, integral, VF2, W and fine setpoint to the second,
  5 min before to 10 min after. No change while W stays → no other path; a start or stop within
  seconds → a direct path. Repeat once. Result → device VWS-25, design Known gaps.

### Phase 1 — settle the current setting

- [DONE] **1.1** Ended early 11-22: office +0.9, gap to living 0.35–0.4 K → Phase 2.
- [TODO] **1.2** Evaluate settled days: per room daily mean minus target, min/max, outdoor mean,
  radiation, per class. Bedroom and Kilian on 08–20 h. Then decide: office-to-living gap > 0.5 K →
  Phase 3 next, else Phase 2. Log under "Observations". Depends on: 1.1.

### Phase 2 — tune, one change at a time

Decision rule per evaluation, on the **office**. d = its mean daily mean minus 22 °C over the
qualifying days of the window, Mondays and Fridays left out (occupied), at least 4 such days. Target band d within ±0.3 K; swinging inside it is fine (owner). Before each change read the
fine setpoint (`sensor.geotherm_heating_circuit_flow_temp_desired_fine`) and W
(`sensor.geotherm_heating_circuit_flow_temp_desired`). After a `TempDesired` change, check within
minutes that W moved as intended; if not, the step did nothing.

| Office result | Change | Step | Expected effect (HYPOTHESIS) |
|---|---|---|---|
| d > +0.5 K (both classes, or the only one) | `TempDesired` down to the next value that **lowers W** | from x.0: −0.5 K; from x.5: −1.0 K | W −1 K ≈ room −0.6…−0.7 K |
| d < −0.5 K (both classes, or the only one) | `TempDesired` up to the next value that **raises W** | from x.5: +0.5 K; from x.0: +1.0 K | W +1 K ≈ room +0.6…+0.7 K |
| +0.3 < d ≤ +0.5 K (both classes, or the only one) | outdoor offset **up** | +0.5 K via `ebusctl` (1 K if rounded, 0.8) | ≈ −0.12 K mean flow ≈ room −0.1 K |
| −0.5 ≤ d < −0.3 K (both classes, or the only one) | outdoor offset **down** | −0.5 K (or 1 K) | mirror |
| Within ±0.3 K mild, below −0.3 K cold | slope up | 0.01 | ≈ +0.25 K flow mild, +0.45 K at −10 °C, as moved jumps |
| Within ±0.3 K cold, above +0.3 K mild | slope down | 0.01 | mirror |
| d within ±0.3 K, other rooms out of band | no curve change: Phase 3 | — | — |
| A sunny day overshoots | no change (Phase 5) | — | — |

Rules: **coarse, then fine** (`TempDesired` moves W by a whole degree; offset and slope trim in
between; when |d| is barely above 0.5, use the offset). **A step that leaves W unchanged is not a
change** (e.g. 22.5 → 22.0); do not count its settle time. **The first offset change is also a
test** (0.8): log the fine setpoint and the geoTHERM outdoor value at each jump; if the jumps do not
move, drop the offset rows. Log every offset change in the change log and the note's "Owner-side
configuration".

- [DONE] **2.1** 22.5 → 22.0 left W unchanged (did nothing); office d ≈ +0.95 → **21.5** on 11-22
  17:07 (from 21.5 one +0.5 step raises W again). Expected: W −1 K, office ≈ +0.3.
- [IN_PROGRESS] **2.2** Settle 21.5, then evaluate as 1.2. W moved 27 → 26 (forced reads, 11-22).
  Checks: run length ≥ 20 min at the lower W (≈ 180 ÷ (VF2 − W) + ramp); daily starts. Then the table again,
  one change per evaluation, until the success metrics hold across one cold-class and one
  mild-class period. Any `CompHysteresis`/`CompIntegral` change waits until 2.2 is done.
  Depends on: 2.1.
  Check 11-23 20:00 (HA + ebus): settings unchanged. First qualifying day 11-23 (cold class);
  11-22 holds the change. Earliest evaluation: the other rooms from 11-27
  (11-23…11-26); the **office from 11-29**, since 11-23 (Mon) and 11-27 (Fri) do not count for it
  (11-24, 25, 26, 28, if they qualify).
  - Cold edge: **28.5** (W 28) at ≈ −3.5 °C geoTHERM, 11-23 18:25 (was 29.5 at 22.5): −1 K, as
    expected.
  - Runs 11-23 (5 min): ≈ 35, 35, **≈ 12** (W fell 26 → 25 at the 1.4 °C edge mid-run, the stop
    line fell to 32), 25, ≥ 25 (cut by hot water), 45 min (W 28); mean ≈ 30 min. Starts 6/day.
  - Rooms 11-23: "Observations".

Success metrics, on qualifying days: office daily mean 21.7–22.3 °C, every other room in its band
(living upper bound only after Phase 3); daily min/max range per room ≤ 1 K (bedroom and Kilian
08–20 h); heating starts ≤ 8/day and mean run ≥ 20 min.

### Phase 3 — room imbalance (owner)

The upper-floor rooms run 0.5–1.0 K below the living room (Baseline). The curve shifts every room
together, the pump speed cannot be set (device VWS-23), no flow meters.

- [TODO] **3.1** Hydraulic balancing, when 1.2 shows an office-to-living gap > 0.5 K.
  - **3.1a** Rule out room causes: doors, furniture or rugs over the loops, the bathroom's towel
    radiator or ventilation.
  - **3.1b** Record every loop's valve setting (turns or marks).
  - **3.1c** Throttle the living-room loop(s) one small step (owner's choice). This lowers the
    total flow and widens the flow-return spread (≈ 8 K now), which can shorten runs: check them.
  - **3.1d** After the settle time, evaluate as 1.2: repeat 3.1c or accept the spread.
  Depends on: 1.2.
- [TODO] **3.2** After any manifold change: settle ≥ 4 qualifying days, log it, continue Phase 2.
  Depends on: 3.1.

### Phase 4 — HA additions

- [DONE] **4.3, 4.5–4.8** Curve sensor, hand setter, fine setpoint and "Curve check", geoTHERM
  outdoor sensor, VF2 (#186, #188–#190). [DROPPED] 4.2, 4.4.
- [TODO] **4.1** Optional: room deviation sensors (temperature − target, long-term statistics)
  and a "Room deviation" card. Depends on: owner approval.
- [DONE] **4.9** W from `uih/FlowTempDesired` (#191), stop line unavailable while W is 0 (hot
  water, #194). Whether the unit's stop line uses W: open, see "How runs start and end".

### Phase 5 — writer and sunny-day exception

- [DONE] **5.1** The comfort control stays off; `TempDesired` is set by hand. If the writer is
  armed later, set `input_number.heating_comfort_temp` to `TempDesired` − 1 first.
- [TODO] **5.2** Deferred until `warm_enough` works: switch `off` only on very sunny days; the
  slab is charged the night before, so a cut at the moment of overshoot does little. Below 3 °C
  `off` still heats to `TempDesiredLow`. Depends on: 2.2, `warm_enough` fixed.

### Phase 6 — geoTHERM device knowledge

- [DONE] **6.1** Device docs `doc/devices/vaillant-vws-83-2/` (#193); facts confirmed later in
  0.7, 0.8, 2.x go straight there.

## Observations

**2026-11-22, 0.14 / 22.5** (detail at commit `91d6f1b`): every room rose 0.8–1.2 K overnight;
the 6 h at 29.5 (02:11–08:20, cold edge) charged the slab (return 24.3 → 26.2 °C).

**2026-11-23 (to 20 h), `TempDesired` 21.5 / 0.14, day 1 after the change, not settled** (cold
class: outdoor mean 1.5 °C, radiation 18 W/m², sun 10–15 h; bathroom shower 06–07 h left out;
bedroom and Kilian on 08–19 h):

| Room (band) | Mean 11-23 | 08–19 h | 18 h | vs band | Trend 11-23 |
|---|---|---|---|---|---|
| Living (21.7–23.3) | 23.06 | — | 23.26 | in band, top | flat, sun bump 13–15 h |
| Bathroom (21.7–22.3) | 22.25 | — | 21.90 | in band | falling ≈ 0.04 K/h |
| **Office (21.7–22.3)** | **22.89** | 23.06 | 23.10 | **+0.6** | **rising 22.5 (07 h) → 23.3 (16 h)** |
| Bedroom (21.2–21.8) | 21.91 | 21.70 | 21.41 | in band | falling ≈ 0.07 K/h |
| Kilian (21.2–22.3) | 22.14 | 21.94 | 21.70 | in band | falling ≈ 0.05 K/h |

OBSERVED: the office is the warmest upper-floor room, 0.17 K below living (0.57–0.81 in the
baseline), and rose by day while the others fell: 11-23 was a Monday (occupied, owner), so it does
not count. 11-22 (Sunday) also rose by day, but carried the 29.5 night and noon sun. If the office
still runs warm on unoccupied days at the 11-29 evaluation, reconsider the limiting room
(candidate: the bathroom).
The three other upper-floor rooms were still falling at 20 h: the slab was still giving off the
29.5 night (11-21/22); W 28 since 18:25 recharges it tonight.

**How runs start and end** (`ehp/Integral`, 5 min statistics; `CompIntegral` −180,
`CompHysteresis` 7 K):
- Runs start just past `CompIntegral` and end on whichever comes first: the integral back at
  ≈ 0, or the flow at W + `CompHysteresis` (device VWS-2, VWS-4), although the manual limits the
  hysteresis to plans 1 and 3 and this unit runs plan 6 (device VWS-4).
- The integral counts VF2 − W (device VWS-3); not reset, not clamped, held during hot water
  (device VWS-5). After hot water the compressor once ran on into heating at −113 (11-22), not on
  11-17 or 11-20 (cause open).
- Step 0.6: the compressor stopped 1 s after the 08:43 write, with the integral ≈ 0 and VF2 at the
  stop line: whether the write triggered it is unknown.
- **Does the stop line use W?** UNPROVEN. Evidence 2026-11-23 (5 min max, OBSERVED twice): at
  W 25 / fine 25.5 two runs stopped with VF2 max **32.06** and the integral far from 0 (10:50 at
  −125, 13:15 at −35), at W + 7 = 32 and below fine + 7 = 32.5. A 1 s log of one such stop would
  make it CONFIRMED (then → device VWS-2/VWS-4 via `record-learning`).
- Runs that end on the integral end at **+4…+10**, not at 0 (VF2 then 32.4–32.7, below W + 7).

Consequences (HYPOTHESIS):
- **Mean flow ≈ W** (the integral balances to zero each cycle), so W sets the room level;
  stop-line stops leave the mean a little below W. `CompIntegral` and `CompHysteresis` change cycle
  length and ripple, not the level.
- **Run** ≈ 180 °min ÷ (VF2 − W) plus the ramp (≈ 35 min at 27, ≈ 50 min at 29); **pause** ≈ 180 ÷
  (W − VF2 while off). A lower W gives shorter runs and less headroom to the stop line.
- Run-length lever: `CompIntegral`. `CompHysteresis` matters only where the flow reaches the stop
  line first (W ≤ 24–25, mild).
- **`TempDesired` acts on the compressor only through W** (the integral uses W: device VWS-3;
  other paths: step 0.11); on the flat parts a
  0.5 K step from .5 to .0 never changes W (device VWS-26); near an edge it may move the edge by
  ≈ 0.5 K outdoor (0.7).

## References

Manuals (with pages per topic), the ebusd catalog and the Kühne formula (used below 0.2): the
References table of `doc/devices/vaillant-vws-83-2/README.md`.

## Knowledge homes

- geoTHERM device docs (`doc/devices/vaillant-vws-83-2/`, 6.1): every unit fact confirmed here, graded by origin,
  incl. what does not work; the curve-step and offset results of 0.7 and 0.8.
- `doc/heating_pv_boost/notes.md` "Owner-side configuration": the settled curve, `TempDesired`
  and offset values, the room targets and limiting room (office, without Mondays/Fridays), the
  loop valve settings after 3.1. Unit
  facts only as anchored one-liners.
- Design doc: HPB-1 already carries the hand-setter line; no further change expected (K-4.1).
- Story (the 0.13 episode, the spike analysis) → `doc/heating_pv_boost/background.md` at Close,
  from commit `4956e8a` of this file.

## Status

- [DONE] 0.1–0.4, 0.6, 0.9, 0.12; [DROPPED] 0.10; [TODO] 0.5 (informative), 0.7 (edges, before any
  slope change), 0.8 (offset test at the first offset change; baseline read 11-23), 0.11
  (`TempDesired` write vs compressor, at the next 2.2 change)
- [DONE] 1.1; [TODO] 1.2 (first run after 2.2's settle time)
- [DONE] 2.1 (22.0 did nothing); [IN_PROGRESS] 2.2 `TempDesired` 21.5 since 2026-11-22 17:07,
  (W 27 → 26 confirmed by forced read), evaluate other rooms from 2026-11-27, the office from
  11-29 (Mondays/Fridays excluded); checked 11-23 20:00: cold edge 28.5, runs ≈ 30 min, 6
  starts/day
- [TODO] 3.1–3.2 balancing
- [DONE] 4.3, 4.5–4.9; [DROPPED] 4.2, 4.4; [TODO] 4.1 optional
- [DONE] 5.1; [TODO] 5.2 deferred
- [DONE] 6.1 geoTHERM device docs (#193)
- [TODO] Close

## Close

- [TODO] Close: distil into device docs / note / design / skill, story → background, update
  pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`).
