# Heating — tune the heating curve and `TempDesired` for stable room temperatures

Done steps are collapsed to one line. Their full analysis (baseline Part A, the curve tables, the
step 0.6 procedure, the run scans) is in git: this file at commit `4956e8a`.

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

Outdoor: the weatherstation `sensor.wheatherstation_outdoor_temperature` and the machine's own
`sensor.geotherm_heating_outdoor_temp` (north side, no sun). Sun:
`sensor.wheatherstation_solar_radiation`. Machine: geoTHERM exclusiv **VWS 83/2** (manuals in the
note "Bus participants"); heating curves: `doc/heating_pv_boost/heating-curve.md`.

**All settings go over ebus; the panel is read-only (owner, 2026-11-22).** What counts is the
ebus register format and what the controller does with it, not the panel's display steps:

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
  passed on by `uih` (CONFIRMED, `doc/heating_pv_boost/registers.md`). Runs end at integral ≈ 0,
  so the mean flow ≈ W (HYPOTHESIS). A lever changes the room level only when it changes W, at
  least for part of the outdoor range. 1 K of W ≈ 0.6–0.7 K room (rough estimate, HYPOTHESIS).
- **Levers:**
  - **`TempDesired`** shifts the curve in parallel: the fine setpoint moves 0.5 K per 0.5 K step
    on a flat part (observed). Every fine value seen is `TempDesired` + a whole number, so from a
    `TempDesired` ending in .0 a −0.5 K step lowers W by 1 K and a +0.5 K step does nothing; from
    one ending in .5 it is the other way round. Near a jump of the curve the half degree may also
    move the jump by ≈ 0.5 K outdoor (HYPOTHESIS, 0.7).
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
  `FlowTempMax` + `CompHysteresis` + 2 K at VF2 (note "Compressor and measurements"); frost
  protection (`off` below 3 °C still heats to `TempDesiredLow` 20 °C, note "Frost protection").
- Invariants: no automatic write, no change to the control law, every register read has its
  bridge lines and poll (note "Invariants").

## Change log (owner settings)

| When (local) | Setting | Old → new | Evidence |
|---|---|---|---|
| 2026-11-14 ≈ 20:20 | Heating curve | 0.15 → 0.13 | OBSERVED from the data (setpoint 27 → 26 while it got colder) |
| 2026-11-14 23:05 – 11-15 00:45 | `TempDesired` | 22 → 21 → 19 → 22 | OBSERVED: writes by the then-armed writer |
| 2026-11-15 ≈ 08:30 – 11-16 00:07 | `mc/OperatingMode` | `on` → `off` → `on` | HYPOTHESIS (setpoint ≈ 2 K low all day, consistent with frost protection; mode history unreadable) |
| 2026-11-20 evening (read back 22:14) | Heating curve | 0.13 → 0.14 | Owner |
| 2026-11-20 22:01:44 | `TempDesired` | 22 → 22.5 | Owner: written by HA (writer armed ≈ 3 s) |
| 2026-11-20 22:01:47 | Comfort control | on → off | Owner |
| on or before 2026-11-21 | Bedroom sensor | moved to a neutral spot | Owner |
| 2026-11-21 evening | Heating curve | 0.14 → ? → 0.14 | Owner test; the setpoint followed within minutes, compressor running |
| 2026-11-22 08:43:17 | `TempDesired` | 22.5 → 22.0 | Owner, hand setter (2.1). Fine 27.5 → 27.0, W stayed 27 |
| 2026-11-22 08:43:21 | `input_number.heating_comfort_temp` | 21.5 → 21.0 | Owner, keeps the knob 1 K below `TempDesired` (5.1) |
| 2026-11-22 10:10 – 10:40 | `TempDesired` | 22.0 → 22.5 → 22.0 | Owner, `uih` test; set back within 1 h, settle time not restarted |
| 2026-11-22 17:07:45 | `TempDesired` | 22.0 → 21.5 | Owner, hand setter (2.1), during hot water. Expected fine 26.5 / W 26 below the 2 °C edge: read back after hot water |
| 2026-11-22 17:07:57 | `input_number.heating_comfort_temp` | 21.0 → 20.5 | Owner, 1 K below `TempDesired` (5.1) |
| before 2026-11-21 | `CompHysteresis` | likely 6 → 7 K | Owner, during the cycling tuning |
| unchanged | `CompHysteresis` 7 K, `CompIntegral` −180, `TempDesiredLow` 20, outdoor offset 0 K | — | read live / owner, 2026-11-21 |

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
- (f) The curve works in **2 K steps** over outdoor temperature. OBSERVED: one edge at ≈ −2.5 °C
  (geoTHERM value), 27.5 ↔ 29.5 at 0.14 / 22.5, crossed once each way on 2026-11-22 with no
  hysteresis; flat in between. Fits the 0.13 period's 24 ↔ 26 jumps (never 25). **Not always
  2 K** (OBSERVED 2026-11-22, 0.14 / 22.0): 27 ↔ 26 at geoTHERM ≈ 1.9 °C (1.81 ↔ 2.06), up 11:10,
  down 16:30, no hysteresis. Open: the other edges, the step sizes, whether `TempDesired` or the
  offset moves the edges (0.7).

## Steps

### Phase 0 — verify and record

- [DONE] **0.1–0.4** Baseline, curve 0.14 confirmed, owner answers, HA additions deployed.
- [TODO] **0.5** Machine outdoor value vs weatherstation, more nights (first night: geoTHERM
  ≈ 1 K colder 20–06 h, ≈ 0.5 K at 08:30). Informative only, no precondition for the offset. Use
  the difference to read edge positions in weatherstation terms. Result → "Observations".
- [DONE] **0.6** (e) refuted: half degrees of `TempDesired` move the fine setpoint. (b) dropped.
- [TODO] **0.7** Map the setpoint jumps (hypothesis (f)). Passive, no setting changes. From the
  "Curve check" graph (5 min statistics, ≈ 10 days kept): every jump of the fine setpoint outside
  hot water, with time, size and the geoTHERM outdoor value before and after. Group by
  `TempDesired` (22.5 until 11-22 08:43, then 22.0). Per setting: a table of edges (outdoor °C)
  and levels (flow °C) next to the formula. Questions: fixed step size? Edges fixed or moved by
  `TempDesired`? Hysteresis? Why: with a stepped curve, a slope change of 0.01 may do nothing or
  shift a whole step, and an offset may move every edge. Enough when edges are seen across about
  −5 to +10 °C. Result → "Observations"; once CONFIRMED → the device docs (6.1).
- [TODO] **0.8** Outdoor offset hypotheses (a) and (b). Tested when the Phase 2 table first calls
  for an offset change. Research: `ehp/OutsideTempOffset` is D2C (1/16 K), read `b509 0dc300`,
  write `0ec300` (installer level); no source reports a non-integer write on any model; `uih` and
  `mc` have no offset register; the manuals describe only the panel menu (±5 K, 1 K steps), which
  does not decide (b); nothing decides (a). Test, in mild weather away from 3 °C and the cut-off:
  1. Read `ehp OutsideTempOffset` (expect 0), `ehp OutsideTemp` (raw), `uih OutsideTemp`, the
     broadcast and `mc FlowTempDesired`.
  2. `ebusctl write -c ehp OutsideTempOffset 0.5`, read back with `-f`: 0.5 → (b) holds; 0 or 1 →
     rounded; error → rejected.
  3. Read step 1 again. Raw `ehp` unchanged while the broadcast or `uih` and the setpoint move →
     (a) holds. Nothing moves → no lever: set 0 back, drop the offset rows.
  Result → "Observations"; the step size goes into the Phase 2 table.

### Phase 1 — settle the current setting

- [DONE] **1.1** Ended early 2026-11-22 08:43: office +0.9 and rising, office-to-living gap
  0.35–0.4 K → Phase 2 first; only `TempDesired` may change (one class).
- [TODO] **1.2** Evaluate settled days: per room daily mean minus target, min/max, outdoor mean,
  radiation, per class. Bedroom and Kilian on 08–20 h. Then decide: office-to-living gap > 0.5 K →
  Phase 3 next, else Phase 2. Log under "Observations". Depends on: 1.1.

### Phase 2 — tune, one change at a time

Decision rule per evaluation, on the **office**. d = its daily mean minus 22 °C on qualifying
days. Target band d within ±0.3 K; swinging inside it is fine (owner). Before each change read the
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

- [DONE] **2.1** `TempDesired` 22.5 → 22.0 (11-22 08:43) left W unchanged all day (W 27, 26
  above the 2 °C edge, identical at 22.5), so it did nothing. Office mean 11-22 ≈ 22.95 (d ≈ +0.95,
  cold class, 22 W/m²; inflated by the 6 h at 29.5 overnight and noon sun), every room above its
  band → **21.5** at 17:07 (owner, a day early). 21.5 rather than 21.0: same W (fine = `TempDesired`
  + whole number), and from 21.5 one +0.5 step raises W again. Expected: W −1 K, office ≈ +0.3.
  `uih` passes floor(`mc`) and the integral uses it (CONFIRMED).
- [IN_PROGRESS] **2.2** Settle 21.5, then evaluate as 1.2 (≥ 4 qualifying days: earliest
  2026-11-27). Checks: after hot water fine 26.5 / W 26 below 2 °C (else the step did nothing;
  log the forced-read `mc FlowTempDesired`); the cold edge (was 29.5 at 22.5) now 28.5 or 29; run
  length ≥ 20 min at the lower W (≈ 180 ÷ (VF2 − W) + ramp); daily starts. Then the table again,
  one change per evaluation, until the success metrics hold across one cold-class and one
  mild-class period. Any `CompHysteresis`/`CompIntegral` change waits until 2.2 is done.
  Depends on: 2.1.

Success metrics, on qualifying days: office daily mean 21.7–22.3 °C, every other room in its band
(living upper bound only after Phase 3); daily min/max range per room ≤ 1 K (bedroom and Kilian
08–20 h); heating starts ≤ 8/day and mean run ≥ 20 min.

### Phase 3 — room imbalance (owner)

The upper-floor rooms run 0.5–1.0 K below the living room (Baseline). The curve shifts every room
together, the pump speed cannot be set (note "Bus participants"), no flow meters.

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
- [DONE] **4.9** W from `uih/FlowTempDesired` (#191), deployed: on 11-22 17:01 the stop line
  followed W, not the fine value. `uih` reads **0 during hot water**, like `mc`
  (`registers.md`); the stop line is unavailable while W is 0 (this PR, was 0 + 7 = 7 °C). Still
  UNPROVEN: whether the stop line uses W; a stop-line stop at W + 7 rather than fine + 7 decides it
  (passive).

### Phase 5 — writer and sunny-day exception

- [DONE] **5.1** The comfort control stays off; `TempDesired` is set by hand. If the writer is
  armed later, set `input_number.heating_comfort_temp` to `TempDesired` − 1 first.
- [TODO] **5.2** Deferred until `warm_enough` works: switch `off` only on very sunny days; the
  slab is charged the night before, so a cut at the moment of overshoot does little. Below 3 °C
  `off` still heats to `TempDesiredLow`. Depends on: 2.2, `warm_enough` fixed.

### Phase 6 — geoTHERM device knowledge

- [TODO] **6.1** Build `doc/devices/` docs for the geoTHERM (VWS 83/2, SW 0383, circuits `ehp`,
  `mc`, `uih`, `hwc`) with the framework of #192: how it can and cannot be steered, every fact
  tagged by origin (manual page, test on this unit, `[ASSUMED]`), and what is known not to work
  (`mc/Mode`, a `TempDesired` step that leaves W unchanged, registers that do not answer, the
  panel as read-only). Sources: this plan, `plans/heating-cycling-from-ehp.md`,
  `doc/heating_pv_boost/registers.md`, `heating-curve.md`, and the unit facts in the note
  ("Bus participants", "Compressor and measurements", frost protection, Raumaufschaltung, outdoor
  sensor). Move them, leaving anchored one-liners `(device <ID>)` in the note; the note is at
  23.9k of its 24,000 char cap and should drop to ≈ 18k.
  **Timing (owner, 2026-11-22): right after #192 merges, alongside the tuning loop, not at the
  end.** Hypotheses still open go in as `[ASSUMED]` with the plan step that settles them; facts
  confirmed later in 0.7, 0.8, 2.x go straight into the device docs.
  Depends on: #192 merged.

## Observations

**2026-11-22 07 h, 0.14 / 22.5 after 35 h, not settled** (11-21 mild and sunny 09–14 h, daily
mean 5.6 °C / 23 W/m²; cold night to −3.2 °C weatherstation, −4.25 °C geoTHERM):

| Room (band) | 11-21 00 h | 11-22 07 h | vs band |
|---|---|---|---|
| Living (21.7–23.3) | 22.4 | 23.2 | in band, top |
| Bathroom (21.7–22.3) | 21.4 | 22.6 | +0.3 |
| **Office (21.7–22.3)** | 22.0 | 22.9 | +0.6 |
| Bedroom (21.2–21.8) | 21.8 | 22.7 | +0.9 (partly sleepers) |
| Kilian (21.2–22.3) | 21.8 | 22.8 | +0.5 |

Every room was still rising. Office daily means 22.35 (11-21), 22.74 (11-22 to 09 h); gap to
living 0.35–0.4 K. Fine setpoint 27.5, 29.5 from 02:11 to 08:20, then 27.5: the 6 h at 29.5
charged the slab (return 24.3 → 26.2 °C).

**How runs start and end** (`ehp/Integral`, 5 min statistics; `CompIntegral` −180,
`CompHysteresis` 7 K):
- Starts at integral ≈ −183 … −186, 1–3 min after it crosses `CompIntegral`.
- **A run ends on whichever comes first** (OBSERVED): the integral back at ≈ 0 (9 of 9 runs
  11-17…22, mild and cold, −8 … +8), or the flow at W + `CompHysteresis` (four stops with the
  integral clearly negative, all at `TempDesired` 22 and W 24–26 in mild weather: 11-06,
  11-14 20:23, 11-18 23:07, 11-19 22:10). The hysteresis acts on this unit although the /2 manual
  (p. 69) limits it to hydraulic plans 1 and 3. Manual p. 48–49 supports runs ending on the
  integral.
- The integral counts VF2 − W (CONFIRMED, registers.md). It is not reset at a stop, not clamped
  (+88 seen), and freezes during hot water. After hot water the compressor once ran on into
  heating at −113 (11-22), not on 11-17 or 11-20 (cause open).
- Step 0.6: the compressor stopped 1 s after the 08:43 write, with the integral ≈ 0 and VF2 at the
  stop line: whether the write triggered it is unknown.

Consequences (HYPOTHESIS):
- **Mean flow ≈ W** (the integral balances to zero each cycle), so W sets the room level;
  stop-line stops leave the mean a little below W. `CompIntegral` and `CompHysteresis` change cycle
  length and ripple, not the level.
- **Run** ≈ 180 °min ÷ (VF2 − W) plus the ramp (≈ 35 min at 27, ≈ 50 min at 29); **pause** ≈ 180 ÷
  (W − VF2 while off). A lower W gives shorter runs and less headroom to the stop line.
- Run-length lever: `CompIntegral`. `CompHysteresis` matters only where the flow reaches the stop
  line first (W ≤ 24–25, mild).
- **`TempDesired` acts on the compressor only through W.** On the flat parts a 0.5 K step from .5
  to .0 never changes W; near an edge it may move the edge by ≈ 0.5 K outdoor (0.7).

## References

1. *Bedienungsanleitung geoTHERM exclusiv VWS* 0020025604_00: heating curves p. 21, 45°
   room-setpoint shift p. 18, frost protection p. 10.
2. *Installationsanleitung geoTHERM exclusiv VWS* 0020045204_01: floor protection p. 46, energy
   balance p. 48–49, menus C2 p. 58, C4/C5 p. 59, calibration p. 65, compressor and FlowTempMax
   p. 69; revision _00 p. 59 for the frost delay.
3. Kühne formula (sensoCOMFORT, OpenEnergyMonitor forum), used below 0.2.

Links and the owner's printed copy: the note "Bus participants" and `heating-curve.md`.

## Knowledge homes

- geoTHERM device docs (`doc/devices/`, 6.1): every unit fact confirmed here, graded by origin,
  incl. what does not work; the curve-step and offset results of 0.7 and 0.8.
- `doc/heating_pv_boost/notes.md` "Owner-side configuration": the settled curve, `TempDesired`
  and offset values, the room targets and limiting room, the loop valve settings after 3.1. Unit
  facts only as anchored one-liners (no new entries before 6.1: the note is at its cap).
- Design doc: HPB-1 already carries the hand-setter line; no further change expected (K-4.1).
- Story (the 0.13 episode, the spike analysis) → `doc/heating_pv_boost/background.md` at Close,
  from commit `4956e8a` of this file.

## Status

- [DONE] 0.1–0.4, 0.6; [TODO] 0.5 (informative), 0.7 (edges, before any slope change), 0.8 (offset
  test at the first offset change)
- [DONE] 1.1; [TODO] 1.2 (first run after 2.2's settle time)
- [DONE] 2.1 (22.0 did nothing); [IN_PROGRESS] 2.2 `TempDesired` 21.5 since 2026-11-22 17:07,
  read back fine/W after hot water, evaluate from 2026-11-27
- [TODO] 3.1–3.2 balancing
- [DONE] 4.3, 4.5–4.9; [DROPPED] 4.2, 4.4; [TODO] 4.1 optional
- [DONE] 5.1; [TODO] 5.2 deferred
- [TODO] 6.1 geoTHERM device docs, right after #192 merges
- [TODO] Close

## Close

- [TODO] Close: distil into device docs / note / design / skill, story → background, update
  pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`).
