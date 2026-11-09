# Pergola roof automation: design

Current design of `packages/pergola.yaml`. Where this doc and the YAML disagree, the YAML wins:
fix this doc. Section IDs (`PG-1` …) are stable; never renumber, mark retired IDs as gone.
Package invariants, entity map and open issues: `doc/pergola/notes.md`.

## PG-1 Overview

Tilt control of two Somfy bioclimatic pergola covers on the terrasse, `cover.dach_links` and
`cover.dach_rechts`. Both covers always move together as one unit.

Goals:
- follow the sun: block it in cooling season, let it through in heating season;
- protect the covers: no movement in frost, defer to the Somfy rain lock in rain;
- step-drain the slats after rain.

Key facts:
- Tilt scale (Somfy `tilt_position`): 0 = flat/closed (max shade, rain protection),
  74 = vertical 90° (at max tilt 122°), 100 = `input_number.pergola_max_tilt_angle` (122°).
  Values > 100 are a dead zone on the Somfy and are never sent.
- Conversion slat angle → tilt position (PG-4.6):
  `INT(slat / max_tilt × 100 + corr)`, `corr = 6` below 20°, `5.5` below 69°, else `0.5`.
- The terrasse faces `input_number.pergola_wall_azimuth` (204°, SSW). Sun can reach it only while
  `wall_azimuth − 90 ≤ azimuth ≤ wall_azimuth + 90` (114°–294°). Derived, never hardcoded.
- Heating vs cooling season comes only from `input_boolean.pergola_heating`, which
  `automation.pergola_sync_heating_from_indicator` drives from `sensor.heating_cooling_indicator`.
  Room temperature is not used.

## PG-2 State machine

`input_select.pergola_automation_state` is the single source of truth. Writers:
`automation.pergola_state_manager` (rules 1-4 inline), `script.pergola_evaluate_state`
(rules 5-9), `script.pergola_exit_to_normal`, the two `not_enough_sun` entry/exit automations,
and the user (manually, to break a deadlock). `automation.pergola_cover_response` reacts to the
state and moves the covers (PG-4.7).

### PG-2.1 States

| State | Meaning | Cover behaviour |
|---|---|---|
| `frost` | outdoor temp < 2.5 °C | no movement |
| `rain` | weather-station rain rate > 0 or a cover lock originator = `rain` | no movement |
| `rain_stopped` | rain just ended, drain sequence running | `script.pergola_post_rain_recovery` moves (PG-6.1) |
| `user_override` | a cover lock originator = `user` | no movement |
| `sun_down` | `sensor.pergola_pv_power == 0` and `sensor.wheatherstation_solar_radiation == 0` (night) | no movement (slats stay where they are) |
| `no_sun_behind_house` | sun below horizon, elevation ≤ `pergola_min_sun_elevation`, or azimuth outside the window | slat 90° (tilt 74), always sent |
| `not_enough_sun` | `binary_sensor.pergola_sun_shining` off | slat 90°, only if > 30° away (PG-5.2) |
| `sun_automatik_heating` | sun active, `pergola_heating` on | heating formula (PG-4.4) |
| `sun_automatik_cooling` | sun active, `pergola_heating` off (default) | cooling formula (PG-4.2/4.3) |

### PG-2.2 Rules (priority order, highest first)

State manager (`mode: queued, max: 3`), first matching `choose` branch wins:

0. **HA start while `rain_stopped`**: restart `script.pergola_post_rain_recovery` (drain resumes
   from the beginning; `mode: restart`). Nothing else is evaluated.
1. **Frost entry**: `outdoor_temperature | float(99) < 2.5` and state ≠ `frost` → stop the drain
   script, set `frost`. Can preempt any state, including `rain_stopped`.
   **Frost exit**: `| float(0) > 3.0` and state = `frost` → `script.pergola_exit_to_normal`.
   Both conditions are value-based, not `trigger.id`-based, so any trigger (incl. the /5 tick)
   converges even if the `numeric_state` trigger was dropped from the queue. Fail-safe on an
   unknown sensor: entry assumes warm (99), exit assumes cold (0), so frost stays until known.
2. **Rain entry**: (`rain_rate > 0` or either originator = `rain`) and neither originator =
   `user` and state not in {`frost`, `rain`} → stop the drain script, set `rain`. Can preempt
   `rain_stopped` (rain restarted mid-drain). The `!= user` guard prevents a rain ↔ user loop.
3. **Rain exit → `rain_stopped`**: state = `rain`, `rain_rate == 0`, both originators =
   `unknown` → set `rain_stopped`, start the drain script.
   **Rain → user_override**: state = `rain` and an originator = `user` → stop the drain script,
   set `user_override` (respect the user who operated the cover during rain).
4. **User override entry**: an originator = `user` and state not in {`frost`, `rain`,
   `rain_stopped`, `user_override`} → `user_override`.
   **User override exit**: state = `user_override`, both originators `unknown` →
   `script.pergola_exit_to_normal`.
- **Protected-state guard**: state in {`frost`, `rain`, `rain_stopped`, `user_override`} and no
  branch above matched → do nothing. These states leave only via their explicit exit rules.
- **Default**: `script.pergola_evaluate_state`.

`script.pergola_exit_to_normal` (shared frost/override exit): if `wheatherstation_hourly_rain > 0`
(`sensor.wheatherstation_hourly_rain`: rain in the last 60 min)
→ set `rain_stopped` and start the drain script; else `script.pergola_evaluate_state`.

`script.pergola_evaluate_state` (`mode: restart`), first match wins:

5. `sun_down`: PV power and solar radiation both read exactly 0 (`float(-1)` fail-safe: an
   unavailable sensor skips this rule).
6. `no_sun_behind_house`: `sun.sun` below horizon, or elevation ≤ `pergola_min_sun_elevation`
   (sun shines under the roof), or azimuth outside `wall_azimuth ± 90`.
7. `not_enough_sun`: `binary_sensor.pergola_sun_shining` is `off`.
8. `sun_automatik_heating`: `input_boolean.pergola_heating` is `on`.
9. `sun_automatik_cooling`: default.

Separate automations:
- `pergola_not_enough_sun_entry`: sun_shining → `off` and state not in {`frost`, `rain`,
  `rain_stopped`, `user_override`, `sun_down`, `no_sun_behind_house`} → `not_enough_sun`.
  No `for:`: the sensor's `delay_off: 5 min` already debounces.
- `pergola_not_enough_sun_exit`: sun_shining → `on` and state = `not_enough_sun` →
  heating or cooling state from `pergola_heating`. No `for:` (sensor `delay_on: 1 min`).

### PG-2.3 Triggers

State manager: `numeric_state` outdoor temp below 2.5 (`frost_entry`) and above 3.0
(`frost_exit`); state of `sensor.wheatherstation_rain_rate`, both
`sensor.dach_*_priority_lock_originator`, `binary_sensor.pergola_sun_shining`,
`input_boolean.pergola_heating`; HA start; `time_pattern` `/5`. The /5 tick replaces triggers on
`sun.sun` attributes (they change every minute); it catches the slow azimuth/elevation crossings.

### PG-2.4 Somfy lock lifecycle and forced state reports

- `sensor.dach_{links,rechts}_priority_lock_originator`: `unknown` = no lock, `rain` = the
  cover-mounted rain sensor closed and locked the cover (faster than the weather station),
  `user` = user blocked the cover (automation must not move it).
- `sensor.dach_*_priority_lock_timer`: very large while raining; after rain it counts down from
  900 s to 0 inside the Somfy, then the originator resets to `unknown`.
- The Somfy does not push timer or originator changes. HA learns them only when a command forces
  a state report. Two mechanisms:
  - **Inactivity watchdogs** (`id 1771360145720` links, `1771361016291` rechts): every 5 min and
    on HA start, send `cover.stop_cover_tilt` when none of the cover, its originator and its timer
    updated in the last 5 min. Suppressed while the state is `sun_automatik_cooling`,
    `sun_automatik_heating` or `rain_stopped`: they share the /5 tick with movement commands, and
    the cover's `last_updated` is still stale at evaluation time, so a `stop_cover_tilt` would
    abort the movement mid-travel.
  - **Lock originator responders** (`id 1771748333394`, `1771748414999`): on any originator
    change, send `stop_cover_tilt` at once for a fresh report before the state manager acts.
  - A movement command sent while locked also makes the Somfy report its lock (and not move).
- So the state manager sees a lock clear within ≤ 5 min of the timer expiring.
- Tilt reported while locked is unreliable: never use it for decisions.

## PG-3 Coordinate system & geometry

### PG-3.1 One number line for sun and slat

```
A_eff (effective sun angle):   0° East horizon ──► 90° Zenith ──► 180° West horizon
Slat angle (hardware):         0° Flat ──► 90° Vertical ──► 122° Max tilt ···► 180° unreachable
                               (closed)     (open)          (back face toward east)
```

- The motor rotates one way only: from flat through vertical to 32° past vertical. Past vertical
  the **back face** faces east and can block eastern sun.
- Heating: slat = A_eff (parallel to the rays). Cooling: slat = A_eff ± 90 (perpendicular).
- Dead zone: slat 122.1°–180° is unreachable; such results fall back to `max_tilt`.

### PG-3.2 Geometry inputs and derived constants

| Name | Source | Value at baseline |
|---|---|---|
| `w` slat width | `input_number.pergola_slat_width` | 22 cm (usable blocking width 20 cm) |
| `d` pivot spacing | `input_number.pergola_slat_pivot_spacing` | 20 cm (centre to centre) |
| `t` slat thickness | `input_number.pergola_slat_thickness` | 3 cm |
| `max_tilt` | `input_number.pergola_max_tilt_angle` | 122° |
| `R` overlap ratio | `sqrt(d² + t²) / w` | 0.91926 |
| `PHI` thickness offset | `degrees(atan(t / d))` | 8.53° |
| `SAFETY_BUFFER` | fixed 5° (standard flip guard, flip-range buffer, `COOLING_LOWER_BOUND` loop) | 5° |
| `DB` | `input_number.pergola_deadband_angle` (PG-5) | 5° |
| `AZIMUTH_MIN/MAX` | `wall_azimuth ∓ 90` | 114° / 294° |

R and PHI are computed inline in each template from the three geometry helpers; no formula
hardcodes them.

## PG-4 Tilt formulas & dispatch

Two steps: compute **slat_angle** (degrees), then convert it to **tilt_position** (PG-4.6).
`sensor.pergola_slat_angle` holds the target for the current state; it always computes, also
while the master switch is off.

### PG-4.1 Effective sun angle (`sensor.pergola_effective_sun_angle`)

```
delta_phi = azimuth − wall_azimuth
if elevation <= 0: unavailable              # availability requires elevation > 0; template also guards
if |sin(radians(delta_phi))| < 0.001:       # singularity: sun along the slat axis
    sun_height = 90
else:
    sun_height = degrees(atan(tan(radians(elevation)) / |sin(radians(delta_phi))|))
A_eff = sun_height        if azimuth <  wall_azimuth   # morning, sun east of the terrasse
      = 180 − sun_height  if azimuth >= wall_azimuth   # afternoon, sun west
```
Rounded to 0.1°. At `delta_phi = ±90°` A_eff = elevation (or 180 − elevation); at `delta_phi = 0`
both branches give 90°.

### PG-4.2 Shade-limit angles (raw sensors, no buffer)

```
MaxOpenEast (moe) = A_eff + PHI + degrees(asin(R × sin(radians(A_eff))))
    # sensor.pergola_max_open_east_morning_cooling_angle
    # MINIMUM back-face slat angle that still gives 100 % shade from eastern sun
MaxOpenWest (mow) = A_eff + PHI − degrees(asin(R × sin(radians(A_eff))))
    # sensor.pergola_max_open_west_cooling_angle; sign is +PHI (−PHI is wrong)
    # MAXIMUM front-face slat angle that still gives 100 % shade; valid for all A_eff,
    # continuous at A_eff = 90° (31.7°); exceeds 90° for A_eff > ~128°
```

`sensor.pergola_cooling_lower_bound` (`COOLING_LOWER_BOUND`, LB): the flip point `a_flip` is the
largest integer A_eff in 1…90 with `moe(a) ≤ max_tilt − 5`; `LB = round(mow(a_flip), 0)`.
Baseline: `a_flip = 57` (moe 116.0°; at 58° moe is 117.8°), `mow(57) = 15.1°` → **LB = 15°**.
Re-derives when any geometry input or max_tilt changes; no formula hardcodes 15°.

### PG-4.3 Cooling (`sun_automatik_cooling`)

`input_boolean.pergola_cooling_optimized` picks the sub-mode.

**Standard (off)**: perpendicular blocking.
```
if A_eff < 90 and moe <= max_tilt − 5:            # morning, back-face blocking is safe
    slat = A_eff + 90 if A_eff + 90 <= max_tilt else max_tilt
else:                                             # afternoon, or morning past the safe limit
    slat = max(A_eff − 90, LB)
slat = clamp(slat, LB, max_tilt)
```
- Morning dead zone (A_eff ≈ 32°–57°): A_eff + 90 > 122°, so 122° is used. Safe: moe stays
  ≤ 117° in this range, so 122° is inside the shade safe zone.
- Flip: once moe > max_tilt − 5 (A_eff ≥ 58°) back-face blocking can no longer guarantee full
  shade and the formula flips to front-face/closing. The 5° buffer makes the flip happen about two
  update cycles before shade loss would start.
- LB = mow at the flip point: the most open front-face angle that still fully shades overhead /
  high-east sun at the flip. At 15° summer noon (≈ 65° elevation) is still fully shaded.

**Optimized (on)**: safe-zone max-open. Slat overlap makes a range of angles give 100 % shade;
target the edge closest to vertical for more airflow.
```
if A_eff < 90 and moe <= max_tilt − DB:           # morning; flip guard uses the deadband helper
    slat = min(max(90, moe + DB), max_tilt)       # DB doubles as safety buffer above moe
elif A_eff <= 90:                                 # flip range
    slat = mow − 5                                # fixed 5° motor-accuracy buffer below the limit
else:                                             # afternoon
    slat = min(mow − 5, 90)                       # cap reached when mow ≥ 95°
slat = clamp(slat, 0, max_tilt)
```
- Morning: moe is the minimum shade angle; the target stays DB above it, so the sun can advance a
  full deadband before a corrective move and shade still holds. Floor 90°: a sub-vertical back
  face gives no blocking benefit. DB must not be set below the motor's positional accuracy.
- Flip range / afternoon: mow is the maximum shade angle; 5° below it stays inside the safe zone,
  and since mow grows with A_eff the slat is always below the future limit.
- The optimized morning guard (`max_tilt − DB`) equals the standard guard (`max_tilt − 5`) only
  while DB = 5°.

| Branch | Standard | Optimized |
|---|---|---|
| Morning (A_eff < 90, guard passes) | `min(A_eff + 90, max_tilt)` | `min(max(90, moe + DB), max_tilt)` |
| Flip range (A_eff ≤ 90, guard fails) | `max(A_eff − 90, LB)` | `mow − 5` |
| Afternoon (A_eff > 90) | `max(A_eff − 90, LB)` | `min(mow − 5, 90)` |

### PG-4.4 Heating (`sun_automatik_heating`)

```
min_heat = sensor.pergola_min_heating_slat_angle
         = degrees(acos(d / sqrt(w² + t²))) + degrees(atan(t / w))   # ≈ 33.5° at baseline
if A_eff > max_tilt:  slat = max_tilt                 # dead zone (moderate-to-far west) → tilt 100
else:                 slat = clamp(A_eff, min_heat, max_tilt)
```
- Slat parallel to the rays: on the shared number line slat = A_eff.
- `min_heat` is the "break-the-seal" angle: below it adjacent slats still overlap
  (gap condition `w·cosθ + t·sinθ = d`), so no direct sun gets through.
- Dead zone: past vertical with the back face toward the west sun opens the largest gap; no other
  position lets in more west sun.

### PG-4.5 Other states

`no_sun_behind_house`, `not_enough_sun` and all other states: `sensor.pergola_slat_angle` = 90
(vertical, max ventilation). The cover only moves in the states listed in PG-4.7.

### PG-4.6 Slat angle → tilt position

```
corr = 6    if slat < 20°      # motor barely moves at small angles
     = 5.5  if slat < 69°      # linear range
     = 0.5  otherwise          # slight jerk above vertical: avoid overshoot
tilt_position = clamp(INT(slat / max_tilt × 100 + corr), 0, 100)
```
- `script.pergola_set_slat_angle` is the **single authoritative** converter and the only place
  that sends `cover.set_cover_tilt_position` (to both covers). Callers pass `slat_angle`.
- `sensor.pergola_tilt_position` mirrors the formula for display and for the deadband compare;
  it never drives a cover command.
- Baseline values: 8° → 12, 15° → 18, 90° → 74, 122° → 100.

### PG-4.7 Cover response dispatch (`automation.pergola_cover_response`)

Triggers: state change of `input_select.pergola_automation_state` and `time_pattern` `/5` (the
only way to track the sun within a steady state). No conditions: the master-switch gate lives in
the script. `mode: queued, max: 3`.

| State | Action |
|---|---|
| `frost`, `rain`, `rain_stopped`, `user_override`, `sun_down` | no-op branch |
| `no_sun_behind_house` | `set_slat_angle(90)`, no deadband |
| `not_enough_sun` | `set_slat_angle(90)` if either cover is > 30° (tilt units) from target (PG-5.2) |
| `sun_automatik_cooling`, `sun_automatik_heating` | 500 ms delay, deadband (PG-5.1), `set_slat_angle(sensor.pergola_slat_angle)` |

The 500 ms delay lets the template cascade (state → A_eff → moe → slat_angle → tilt_position)
settle after a state change; without it a stale 90°/74 either moves the covers to 90° or masks the
real move.

### PG-4.8 Verification table (baseline geometry, DB = 5°, computed from the YAML logic)

| Az | Elev | A_eff | moe | mow | Std slat (tilt) | Opt slat (tilt) | Heat slat (tilt) |
|---|---|---|---|---|---|---|---|
| 115° | 20° | 20.0 | 46.9 | 10.2 | 110.0 (90) | 90.0 (74) | 33.5 (32) |
| 150° | 30° | 35.5 | 76.3 | 11.8 | 122 DZ (100) | 90.0 (74) | 35.5 (34) |
| 140° | 40° | 43.0 | 90.4 | 12.7 | 122 DZ (100) | 95.4 (78) | 43.0 (40) |
| 165° | 50° | 62.2 | 125.1 | 16.3 | 15 LB (18) | 11.3 (15) | 62.2 (56) |
| 180° | 40° | 64.1 | 128.4 | 16.8 | 15 LB (18) | 11.8 (15) | 64.1 (58) |
| 180° | 55° | 74.1 | 144.8 | 20.5 | 15 LB (18) | 15.5 (18) | 74.1 (61) |
| 204° | 57° | 90.0 | 165.3 | 31.7 | 15 LB (18) | 26.7 (27) | 90.0 (74) |
| 220° | 45° | 105.4 | 176.3 | 51.5 | 15.4 (18) | 46.5 (43) | 105.4 (86) |
| 240° | 40° | 125.0 | 182.4 | 84.7 | 35.0 (34) | 79.7 (65) | 122 DZ (100) |
| 260° | 30° | 145.1 | 185.4 | 121.9 | 55.1 (50) | 90.0 (74) | 122 DZ (100) |

All rows are inside the azimuth window; outside it the state is `no_sun_behind_house`. The test
anchor `A_eff = 67.9` gives optimized `mow − 5 = 13.0°`, standard 15.0°, heating 67.9°.

## PG-5 Deadband

### PG-5.1 Sun-tracking deadband (cooling and heating)

```
DB_tilt = round(input_number.pergola_deadband_angle / max_tilt × 100)      # 5° → 4 tilt units
target  = sensor.pergola_tilt_position
move if max(|links.current_tilt − target|, |rechts.current_tilt − target|) >= DB_tilt
     or target >= 100
```
- Compared in tilt-position units: inverting PG-4.6 to slat degrees ignores the corrections
  (errors of several degrees, larger than the threshold). In tilt space they cancel.
- Both covers are checked (max deviation), so one cover lagging still triggers a move.
- `target >= 100` always passes, so the max-tilt dead-zone target is always re-sent.
- The same helper is the optimized-morning safety buffer (PG-4.3).
- Why ~5°: motor dead zone and mechanical play are ≈ 2–3°; 5° prevents micro-moves as the sun
  creeps while still tracking meaningful changes within one or two /5 ticks.

### PG-5.2 Other states

- `not_enough_sun`: fixed 30° deadband (`round(30 / max_tilt × 100)` = 25 tilt units) against the
  90° target, max of both covers. Avoids travel when the slats are already roughly vertical.
- `no_sun_behind_house`: no deadband; always sends 90° (the Somfy is idempotent).
- Post-rain drain: no deadband; the drain must complete (PG-6.1).

## PG-6 Rain / frost / master switch

### PG-6.1 Post-rain recovery (`script.pergola_post_rain_recovery`, `mode: restart`)

Started on entry to `rain_stopped` (rain exit, frost/override exit with hourly rain > 0, HA start
while `rain_stopped`). Progress in `input_number.pergola_rain_recovery_step`, shown by
`sensor.pergola_rain_recovery_step` (0 whenever the state ≠ `rain_stopped`, so an aborted run
needs no cleanup).

1. Step 1: wait 30 s for lock and weather sensors to settle.
2. Step 2, only if `wheatherstation_hourly_rain > 0`: slat **8°**, hold 5 min. When hourly rain
   is 0 this pre-drain is skipped (counter goes 1 → 3).
3. Step 3: slat **15°**, hold 5 min.
4. Step 4: if hourly rain > 0, wait 30 more min (slats dry at 15°).
5. `script.pergola_evaluate_state` sets the new state (rules 1-4 cannot apply here). The state
   manager would not fire by itself, since no input changed.

After every delay the script aborts unless the state is still `rain_stopped`. Rain or frost entry
stops it with `script.turn_off`. A restart re-drains from the start, which is safe. No deadband;
the master switch still applies (water stays on the slats while it is off).

### PG-6.2 Frost

Enter below 2.5 °C, exit above 3.0 °C (hardcoded, 0.5 °C hysteresis), no movement while in
`frost`. Exit goes through `script.pergola_exit_to_normal` (drain if hourly rain > 0). Value-based
conditions and fail-safes: PG-2.2 rule 1.

### PG-6.3 Master switch

`input_boolean.pergola_automatic_enabled` off: `script.pergola_set_slat_angle` exits at its first
condition, so no cover moves (sun tracking and drain alike). The state machine and all template
sensors keep running, so re-enabling acts at the next trigger. Only after the gate passes does the
script record the commanded angle in `input_number.pergola_last_set_slat_angle`
(`sensor.pergola_effective_slat_angle`).

## PG-7 Entities

Grouped in `group.pergola_dach`; the same entities appear in `dashboards/elements/pergola_card.yaml`.

| Entity | Role |
|---|---|
| `cover.dach_links`, `cover.dach_rechts` | Somfy covers, tilt 0–100, move together |
| `sensor.dach_{links,rechts}_priority_lock_originator` / `_lock_timer` | Somfy lock state / countdown (PG-2.4) |
| `input_boolean.pergola_automatic_enabled` | master switch (PG-6.3) |
| `input_boolean.pergola_heating` | season: on = heating; driven by the indicator sync |
| `input_boolean.pergola_cooling_optimized` | cooling sub-mode (PG-4.3) |
| `input_select.pergola_automation_state` | state machine (PG-2) |
| `input_number.pergola_pv_conversion_factor` | PV W → W/m² divisor (PG-8) |
| `input_number.pergola_shading_sensitivity` | sun-shining threshold factor (PG-8) |
| `input_number.pergola_min_sun_elevation` | elevation floor for `no_sun_behind_house` and sun shining |
| `input_number.pergola_deadband_angle` | deadband and optimized-morning buffer (PG-5) |
| `input_number.pergola_max_tilt_angle` | hardware max slat angle |
| `input_number.pergola_wall_azimuth` | terrasse bearing; azimuth window and A_eff |
| `input_number.pergola_slat_width` / `_pivot_spacing` / `_thickness` | slat geometry (PG-3.2) |
| `input_number.pergola_last_set_slat_angle` | internal: last commanded angle (not in group) |
| `input_number.pergola_rain_recovery_step` | internal: drain step counter (not in group) |
| `sensor.pergola_pv_power` | PV wrapper (PG-8) |
| `sensor.pergola_effective_sun_angle` | A_eff (PG-4.1), primary debug value |
| `sensor.pergola_slat_angle` | target slat angle for the current state |
| `sensor.pergola_effective_slat_angle` | last commanded slat angle |
| `sensor.pergola_tilt_position` | target tilt (display / deadband) |
| `sensor.pergola_max_open_east_morning_cooling_angle` | moe (PG-4.2) |
| `sensor.pergola_max_open_west_cooling_angle` | mow (PG-4.2) |
| `sensor.pergola_cooling_lower_bound` | LB (PG-4.2), recorder-excluded |
| `sensor.pergola_min_heating_slat_angle` | heating floor (PG-4.4), recorder-excluded |
| `sensor.pergola_rain_recovery_step` | drain step 0–4, recorder-excluded |
| `binary_sensor.pergola_sun_shining` | shading needed (PG-8) |
| `script.pergola_set_slat_angle` | only cover mover + converter (PG-4.6) |
| `script.pergola_evaluate_state` | rules 5-9 |
| `script.pergola_exit_to_normal` | frost / override exit |
| `script.pergola_post_rain_recovery` | drain sequence (PG-6.1) |

## PG-8 Sun detection

`sensor.pergola_pv_power` wraps the raw Victron DC PV power `sensor.victron_solar_yield_dc_watts`
(not the AC-referenced `sensor.solar_yield_watts`: the conversion factor is calibrated on panel
output). The MPPT topic stops publishing at night and the source goes unavailable
(`expire_after: 120`); while `sensor.victron_ac_load_total_power` is still available the wrapper
reports 0 W instead of unavailable, so the `sun_down` rule (needs PV == 0) works at night.

`binary_sensor.pergola_sun_shining` (adapted from the Loxone Wetter/Sonnenschein logic):
```
effective = max(sensor.wheatherstation_solar_radiation,
                sensor.pergola_pv_power / pergola_pv_conversion_factor)
threshold = 512 × sin(radians(elevation)) × pergola_shading_sensitivity
on = elevation > pergola_min_sun_elevation and (effective > threshold or uv_index >= 3)
delay_on 1 min, delay_off 5 min
```
- `max()` of both sources: whichever sensor is still in direct sun drives the reading (the
  weather station goes into shadow in the afternoon).
- 512 W/m² × sin(elevation): Loxone-calibrated "shade needed" baseline for Central Austria
  (≈ 47°N), about half the theoretical clear-sky `1000 × sin(elevation)`.
- UV ≥ 3 (WHO "moderate") catches hazy days with low irradiance but real UV.
- PV conversion factor 3.2: 6× Axitec 440 W bifacial panels at 5–10° tilt, 228° azimuth; STC
  2640 W / 1000 W/m² = 2.64, raised for bifacial gain and near-flat tilt. Field calibration is
  open: `plans/pergola-field-calibration.md`.
