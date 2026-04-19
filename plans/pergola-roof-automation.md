# Pergola Roof Automation — Implementation Plan

## Overview

Automate the tilt control of two Somfy bioclimatic pergola covers (`cover.dach_links`, `cover.dach_rechts`) on the terrasse. Both covers always move together as one unit.

**Goals:**
- Follow the sun to provide shade (cooling season) or let sun through (heating season)
- Protect covers during frost (no movement) and rain (defer to Somfy lock)
- Step-drain covers after rain stops

**Key facts:**
- Tilt scale: 0 = horizontal/flat (maximum shade / rain protection), ~74 = vertical (90°, derived: INT(90/max_tilt_angle×100+0.5); default 74 when max_tilt_angle=122°), 100 = max_tilt_angle open (user-configurable via `input_number.pergola_max_tilt_angle`, default 122°)
- Conversion formula (slat_angle_degrees → tilt_position, with hardware-specific rounding corrections):
  ```
  tilt_position = INT(slat_angle / max_tilt_angle × 100 + correction)
  correction: +7 if slat_angle < 20°,  +5.5 if slat_angle < 69°,  +0.5 otherwise
  ```
  Reason: motor moves very little below 20°; linear range 20°–69°; slight jerk above 70°. Values > 100 are dead zone.
- Terrasse faces 204° (SSW) — stored as `input_number.pergola_wall_azimuth`; sun hits the terrasse when `(wall_azimuth − 90)° ≤ azimuth ≤ (wall_azimuth + 90)°` (derived, never hardcoded)
- All config lives in `packages/pergola.yaml`; deployed via `git pull` on HA host

**References: Agent ONLY reads those after asking the User**
* Loxone config file: `C:\Users\mikop\Documents\Loxone\Loxone Config\Projects\Haus.Loxone`
* Loxone config documentation: https://www.loxone.com/enen/kb-cat/loxone-config/
* Slat angle formula analysis: [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md)
* Gemini conversation (original analysis): [gemini-conversation-slat-formulas.md](gemini-conversation-slat-formulas.md)
* Spreadsheet with sample calculations: [terrace roof titl.xlsx](terrace%20roof%20titl.xlsx)

**TBD items blocking later steps:**
- Room temperature ignored — heating/cooling mode is determined solely by the heating indicator

---

## Location & Orientation

**Slat rotation:** tilt 0 = flat/horizontal (rain/closed). tilt ~74 = 90° vertical (fully open to diffuse light, derived via formula from slat_angle=90° and max_tilt_angle). tilt 100 = max_tilt_angle (max open, default 122°).

**Sun azimuth window** (derived from `input_number.pergola_wall_azimuth`):
```
sun on terrasse side when: AZIMUTH_MIN ≤ sun.azimuth ≤ AZIMUTH_MAX
sun behind house when:     sun.azimuth < AZIMUTH_MIN  OR  sun.azimuth > AZIMUTH_MAX
  (AZIMUTH_MIN = wall_azimuth − 90,  AZIMUTH_MAX = wall_azimuth + 90)
```

---

## Entity Reference

### Covers
| Entity | Description |
|---|---|
| `cover.dach_links` | Left pergola cover (tilt 0–100) |
| `cover.dach_rechts` | Right pergola cover (tilt 0–100) |
| `sensor.dach_links_priority_lock_originator` | Lock state of left cover: `unknown` = no lock, `rain` = rain-locked, `user` = user override |
| `sensor.dach_rechts_priority_lock_originator` | Same for right cover |
| `sensor.dach_links_priority_lock_timer` | Countdown timer (seconds) for the active lock; 0 when no lock |
| `sensor.dach_rechts_priority_lock_timer` | Same for right cover |

> **Lock originator values:**
> - `unknown` — no active lock, cover moves freely
> - `rain` — cover-mounted rain sensor triggered; Somfy closed and locked the cover automatically (faster than weather station)
> - `user` — a user has manually blocked the cover; automation must not move it
>
> **Lock timer lifecycle (verified):** While rain is active, the lock timer is a very large value. Once rain stops, the timer counts down from 900 s to 0 independently inside the Somfy device. When it reaches 0 the lock originator resets to `unknown`. The Somfy does **not** report timer or originator changes unless forced — HA only learns the current state when we trigger a state report. We do this two ways: (1) the **inactivity watchdog** (`packages/pergola.yaml`) sends a `stop_cover_tilt` every 5 minutes when no cover or lock update has occurred, causing the Somfy to report its current state; (2) when the automation sends a movement command while unaware of the lock, the Somfy reports back the originator and timer state and, if still locked, does not actually move. Without forced state reports, the lock would appear stuck in HA indefinitely even though the countdown is progressing.
>
> **Note:** Tilt position reported while locked is unreliable — do not use for logic decisions.

### Sun
| Entity | Description |
|---|---|
| `sun.sun` | State: `above_horizon` / `below_horizon` |
| `state_attr('sun.sun', 'elevation')` | Degrees above horizon |
| `state_attr('sun.sun', 'azimuth')` | Compass bearing 0–360° |

### Weather Station (Ecowitt — prefix `sensor.wheatherstation_`)
| Entity | Unit | Description |
|---|---|---|
| `sensor.wheatherstation_outdoor_temperature` | °C | Outdoor temp — used for frost safety |
| `sensor.wheatherstation_indoor_temperature` | °C | Indoor/room temp — used in heating season |
| `sensor.wheatherstation_rain_rate` | mm/h | > 0 = currently raining |
| `sensor.wheatherstation_hourly_rain` | mm | Rain in last 60 min |
| `sensor.wheatherstation_solar_radiation` | W/m² | Actual solar irradiance |
| `sensor.wheatherstation_uv_index` | UV index | Additional sun indicator |

### PV & Derived Sun Sensor
| Entity | Unit | Description |
|---|---|---|
| `sensor.victron_solar_yield` | W | Raw Victron solarcharger DC PV power |

---

## Pergola Device

All entities created by this feature are grouped via **`group.pergola_dach`** — HA's built-in [group integration](https://www.home-assistant.io/integrations/group/). The group is defined in YAML alongside all other entities; no post-deploy UI steps are required.

> **⚠️ `device_id:` is NOT supported in template YAML**, and template entities also cannot be assigned to a device via the HA entity editor UI — both have been verified to fail.
> **No template wrappers.** `input_*` helpers (`input_boolean`, `input_number`, `input_select`) are used directly. Wrappers served no purpose.

**Rules for implementation:**
- Do **not** add `device_id:` to any `template` entity — the config validator rejects it.
- Do **not** create template wrapper entities for `input_*` helpers.
- Automations reference `input_*` entity IDs directly.
- Add every new entity to the `group.pergola_dach` entity list in `packages/pergola.yaml`.
- **Keep `dashboards/elements/pergola_card.yaml` in sync:** whenever any entity (`input_boolean`, `input_number`, `input_select`, `sensor`, `binary_sensor`, `script`) is added or removed, update the card in the same step. Place it in the appropriate section: *On/Off Toggles*, *State of Automation*, *States and Sensors*, or *Parameters*.

**Group definition** (in `packages/pergola.yaml`):
```yaml
group:
  pergola_dach:
    name: Pergola Dach
    entities:
      - input_boolean.pergola_automatic_enabled
      - input_boolean.pergola_heating
      - input_boolean.pergola_cooling_optimized
      - input_select.pergola_automation_state
      - input_number.pergola_pv_conversion_factor
      - input_number.pergola_shading_sensitivity
      - input_number.pergola_min_sun_elevation
      - input_number.pergola_max_tilt_angle
      - input_number.pergola_min_heating_slat_angle
      - input_number.pergola_wall_azimuth
      - input_number.pergola_slat_width
      - input_number.pergola_slat_pivot_spacing
      - input_number.pergola_slat_thickness
      - sensor.pergola_pv_power
      - sensor.pergola_effective_sun_angle
      - sensor.pergola_slat_angle
      - sensor.pergola_tilt_position
      - binary_sensor.pergola_sun_shining
      - sensor.pergola_cooling_lower_bound
      - sensor.pergola_max_open_east_morning_cooling_angle
      - sensor.pergola_max_open_west_cooling_angle
```

The resulting `group.pergola_dach` entity can be added directly to any Lovelace dashboard card.

### All entities on the device

#### Config — user-changeable in HA UI
| Entity | Type | Default | Purpose |
|---|---|---|---|
| `input_boolean.pergola_automatic_enabled` | toggle | on | Master on/off — disables all cover movement when off |
| `input_boolean.pergola_heating` | toggle | off | Heating indicator: on = heating mode (let sun through), off = cooling mode (block sun). Can be flipped by user or set via HA REST API by an external system (e.g. Loxone) |
| `input_select.pergola_automation_state` | select | — | State machine; **can be set manually to break a deadlock** |
| `input_number.pergola_pv_conversion_factor` | number | 3.2 | PV W → W/m² divisor for sun detection (default 3.2; can be refined in Step 6 field testing) |
| `input_number.pergola_max_tilt_angle` | number | 122 ° | Maximum physical slat angle; drives tilt_position conversion |
| `input_number.pergola_min_sun_elevation` | number | 10 ° | Elevation at or below which sun shines under the roof → `no_sun_behind_house` (must be > 0°) |
| `input_number.pergola_min_heating_slat_angle` | number | 16 ° | Floor slat angle in heating mode — prevents near-parallel slats at dawn (derived: tilt=20 → 15.86° ≈ 16°) |
| `input_boolean.pergola_cooling_optimized` | toggle | off | Cooling angle mode: off = standard ($A_{eff}$ ± 90); on = optimized (safe-zone max-open) — see Step 7 |
| `input_number.pergola_wall_azimuth` | number | 204 ° | Compass bearing of the terrasse wall (SSW). Drives the azimuth window (wall_azimuth ± 90°) and the A_eff coordinate system |
| `input_number.pergola_shading_sensitivity` | number | 0.9 | Sensitivity knob for the shading threshold (0.9 = 90% of baseline); lower → shade earlier on hazy days, higher → requires brighter sun; primary calibration knob for Step 6 |
| `input_number.pergola_slat_width` | number | 22 cm | Slat face width (w); used to derive geometry constants R and PHI |
| `input_number.pergola_slat_pivot_spacing` | number | 20 cm | Pivot-to-pivot spacing (d); used to derive geometry constants R and PHI |
| `input_number.pergola_slat_thickness` | number | 3 cm | Slat thickness (t); used to derive geometry constants R and PHI |

#### Status — derived/calculated, read-only
| Entity | Unit | Description |
|---|---|---|
| `sensor.pergola_pv_power` | W | PV power — wraps raw Victron sensor |
| `sensor.pergola_effective_sun_angle` | ° | Effective sun angle ($A_{eff}$): 0° = East Horizon → 90° = Zenith → 180° = West Horizon |
| `sensor.pergola_slat_angle` | ° | Currently calculated target slat angle (0°–122°, output of sun/season formula) |
| `sensor.pergola_tilt_position` | 0–100 | Calculated tilt_position after hardware correction (what will be sent to covers) |
| `binary_sensor.pergola_sun_shining` | on/off | True when radiation/PV exceed shading threshold OR UV ≥ 3; built-in 1 min delay_on / 5 min delay_off |

> **`binary_sensor.pergola_sun_shining` formula** (adapted from Loxone Wetter/Sonnenschein logic):
> ```
> effective_radiation = max(
>   sensor.wheatherstation_solar_radiation,      # W/m² — goes into shadow in afternoon
>   sensor.pergola_pv_power / pergola_pv_conversion_factor   # W → W/m² proxy; stays in sun longer
> )
> shading_threshold = 512 × sin(elevation_deg × π/180) × input_number.pergola_shading_sensitivity
>
> sun_is_shining = ( effective_radiation > shading_threshold
>                    OR sensor.wheatherstation_uv_index ≥ 3 )   ← UV catches hazy high-UV days
>                  AND (elevation > input_number.pergola_min_sun_elevation)
>                  # elevation guard matches state machine no_sun_behind_house threshold
> ```
> Built-in hysteresis: `delay_on: 1 min` (must be true for 1 min before activating shading),
> `delay_off: 5 min` (must be false for 5 min before deactivating). 
> - **Purpose:**Answers: "is the sun shining strongly enough that the terrasse needs shading?"
> - **Why 512 W/m²:** Loxone-calibrated "shade needed" baseline for Central Austria (≈47°N). Theoretical maximum horizontal irradiance is `1000 × sin(elevation)`, but Austrian real-world peak is significantly lower. 512 ≈ the irradiance level where shading becomes necessary. `shading_sensitivity` (default 0.9) provides fine-tuning per-installation.
> - **UV fallback:** UV index ≥ 3 (WHO "moderate") means meaningful UV exposure even when irradiance is low (e.g. thin cloud). Shading is still needed for comfort/protection.
> - `pergola_pv_conversion_factor` default 3.2 — empirically calibrated for 6× Axitec 440W bifacial panels at 5–10° tilt, 228° azimuth (bifacial back gain + near-flat tilt + afternoon facing). STC baseline (2640W / 1000 W/m² = 2.64) is adjusted upward to 3.2 for real-world geometry. Calibrate in Step 6 on a clear morning.
> - Taking `max()` of both sources solves the afternoon shadow problem: whichever sensor is still in sun drives the reading.

> **Derived Internal Constants** — computed once from `input_number` geometry/config inputs. Never hardcoded as literals; any formula that uses these must reference these derived values only.
>
> | Constant | Formula | Default | Used for |
> |---|---|---|---|
> | `R` | `sqrt(slat_pivot_spacing² + slat_thickness²) / slat_width` | 0.91926 | Overlap ratio — cooling shade geometry |
> | `PHI` | `degrees(atan(slat_thickness / slat_pivot_spacing))` | 8.53 ° | Thickness angle offset — cooling shade geometry |
> | `SAFETY_BUFFER` | fixed constant: 5 ° | 5 ° | Flip margin below max_tilt; not user-configurable |
> | `AZIMUTH_MIN` | `wall_azimuth − 90` | 114 ° | Lower bound of sun-on-terrasse azimuth window |
> | `AZIMUTH_MAX` | `wall_azimuth + 90` | 294 ° | Upper bound of sun-on-terrasse azimuth window |
> | `DEADBAND_TILT` | `(5 / max_tilt_angle * 100) \| round(0) \| int` | 4 | Movement gate: skip command if \|target − current\| < DEADBAND_TILT |
> | `COOLING_LOWER_BOUND` | MaxOpenWest at the flip point A_eff — see derivation below | ~15.3 ° | Ventilation floor for closing formula |
>
> **COOLING_LOWER_BOUND derivation:** The flip point A_eff_flip is the largest A_eff where `MaxOpenEast(A_eff) ≤ max_tilt − SAFETY_BUFFER`, found by iterating A_eff from 1°→90° in 1° steps (Jinja2 for-loop with namespace). COOLING_LOWER_BOUND = `MaxOpenWest(A_eff_flip)` = `A_eff_flip + PHI − degrees(asin(R × sin(radians(A_eff_flip))))`. Both R and PHI are live-computed from the geometry inputs, so COOLING_LOWER_BOUND automatically re-derives if any geometry input or max_tilt changes. Implemented as `sensor.pergola_cooling_lower_bound` (internal template sensor, not visible in the device UI).
>
> `sensor.pergola_effective_sun_angle` is the primary debug value — it shows the sun's effective position on the unified 0°–180° east-to-west scale. In heating mode, slat_angle = $A_{eff}$ directly; in cooling mode, slat_angle = $A_{eff}$ ± 90.
> `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` reflect the *calculated setpoint* at any given moment — useful for debugging the formula without having to look at cover state.
> These sensors compute continuously regardless of `input_boolean.pergola_automatic_enabled` — they show what the automation *would* do even when disabled, making them useful for monitoring and commissioning.

#### Scripts — internal movement helpers
| Entity | Description |
|---|---|
| `script.pergola_set_slat_angle` | **Single authoritative slat_angle→tilt_position converter.** Accepts `slat_angle` (float, degrees). First checks `input_boolean.pergola_automatic_enabled` — if `off`, exits immediately without moving covers (this gates all movement including post-rain drain). Computes `tilt_position` using the Step 2 hardware-correction formula with the live value of `input_number.pergola_max_tilt_angle`, clamps to [0, 100], and sends `cover.set_cover_tilt_position` to both covers. All cover movement commands — from the cover response automation and the post-rain recovery script — call this script. The formula is never inlined elsewhere. Does **not** apply the movement deadband; callers check the deadband before invoking where required. |

---

## Automation State Machine

`input_select.pergola_automation_state` is the single source of truth. One automation manages transitions; a separate automation reacts to state changes to move covers.

### States

| State | Meaning | Cover behavior |
|---|---|---|
| `no_sun_behind_house` | Sun below horizon, elevation ≤ `pergola_min_sun_elevation`, or azimuth outside AZIMUTH_MIN–AZIMUTH_MAX (derived: `wall_azimuth ± 90`) | slat_angle = 90° → tilt_position via formula (default 74) |
| `frost` | wheatherstation_outdoor_temperature < 2.5 °C (hardcoded) | No movement |
| `rain` | Rain active (weather station OR cover lock = `rain`) | No movement |
| `rain_stopped` | Rain just ended, recovery in progress | Recovery script handles covers |
| `user_override` | One or both covers locked by user (`lock originator = user`) | No movement |
| `not_enough_sun` | `pergola_sun_shining` off (cloud/overcast) — sensor already has 5 min delay_off built in | slat_angle = 90° → tilt_position via formula (default 74) |
| `sun_automatik_heating` | Sun active, heating indicator on | Heating formula |
| `sun_automatik_cooling` | Sun active, heating indicator off | Cooling formula |

### Priority Rules (highest first)

1. **frost** — `wheatherstation_outdoor_temperature` < 2.5 °C (hardcoded) → enter `frost`. Clears when `wheatherstation_outdoor_temperature` > 3.0 °C (hardcoded, hysteresis gap). On exit: if `wheatherstation_hourly_rain > 0` → enter `rain_stopped` (post-rain recovery); otherwise re-evaluate remaining rules.
2. **rain** — enter when **either** indicator is active:
   - `sensor.wheatherstation_rain_rate > 0` (weather station — slower, delayed), OR
   - `sensor.dach_links_priority_lock_originator = rain` OR `sensor.dach_rechts_priority_lock_originator = rain` (cover-mounted rain sensor — fast, no delay)

   Exit rain only when **both** indicators are off:
   - `rain_rate == 0` AND both lock originators = `unknown` (not `rain`)

   Condition: state ≠ `frost`
3. **rain_stopped** — was `rain`, both indicators now off → enter `rain_stopped`. Script exits this state.
4. **user_override** — either lock originator = `user`. Clears when both = `unknown`. Cover response automation skips all movement while in this state. On exit: if `wheatherstation_hourly_rain > 0` → enter `rain_stopped` (post-rain recovery); otherwise re-evaluate remaining rules. (Same exit logic as frost.)
5. **no_sun_behind_house** — sun below horizon OR `sun.sun` elevation ≤ `input_number.pergola_min_sun_elevation` (sun shines under the roof; slat geometry irrelevant) OR azimuth outside AZIMUTH_MIN–AZIMUTH_MAX (derived as `wall_azimuth ± 90`; geometric — no sun possible regardless of sensor).
6. **not_enough_sun** — `pergola_sun_shining` is `off`. No additional delay needed here — the sensor's built-in `delay_off: 5 min` already ensures it only turns off after 5 continuous minutes of no sun. Exits when `pergola_sun_shining` has been `on` for ≥ 1 continuous minute (the sensor's `delay_on: 1 min` already provides this; an extra `for:` guard on the exit trigger is optional but not required).
7. **sun_automatik_heating** — `input_boolean.pergola_heating` = on/1.
8. **sun_automatik_cooling** — default when sun is active and heating indicator is off.

---

## Unified Coordinate System

A single coordinate system is used for both sun position and slat angles.

### Effective Sun Angle ($A_{eff}$)

The sun's effective position projected onto the plane perpendicular to the slat axis:

```
  0°                90°                 180°
  East Horizon ───► Zenith/Noon ──────► West Horizon
```

### Internal Slat Angle (hardware, 0°–122°)

The physical motor only rotates in one direction — from flat (0°) through vertical (90°) and beyond to 32° past vertical (122°). Once past vertical, the **back face** of the slat faces east and can block eastern sun.

```
  0°           90°          122°          180°
  Flat ──────► Vertical ──► Max tilt ···► (unreachable)
  (closed)     (open)       (back face)   Dead Zone
```

The slat angle and $A_{eff}$ sit on the **same number line**. In heating mode the slat angle equals $A_{eff}$ directly — the slat tracks the sun's effective position. In cooling mode the slat is offset by ±90° from $A_{eff}$ to block sun perpendicularly.

**Dead zone:** Slat angles 122.1°–180° are mechanically unreachable. Any formula result in this range must fall back to `max_tilt` (122°) or `tilt_position = 100`.

---

## Tilt Calculation Logic

Tilt calculation is a two-step process: first compute the desired **slat_angle** (degrees, 0°–122°), then convert to **tilt_position** (0–100) using the hardware correction formula.

### Step 0 — Effective Sun Angle ($A_{eff}$)

Computed once per update cycle from sun position:

```
wall_azimuth   = input_number.pergola_wall_azimuth      (default 204°)
delta_phi      = azimuth - wall_azimuth                 (relative azimuth to terrasse)
elevation_rad  = radians(elevation)
max_tilt       = input_number.pergola_max_tilt_angle    (default 122°)
```

**Effective Sun Height** (the projected elevation in the slat-perpendicular plane, always 0°–90°):
```
if elevation <= 0:
    return                                              (safety guard: sun below horizon —
                                                         state machine should have already entered
                                                         no_sun_behind_house; skip formula entirely)

if |sin(radians(delta_phi))| < 0.001:                  (singularity guard: sun along slat axis,
    sun_height = 90                                      azimuth ≈ wall_azimuth → A_eff = 90° is the
                                                         correct mathematical limit)
else:
    sun_height = degrees(atan(tan(elevation_rad) / abs(sin(radians(delta_phi)))))
```

**Effective Sun Angle** ($A_{eff}$, mapped to 0°–180° east-to-west):
```
if azimuth < wall_azimuth:                              # morning — sun east of terrasse
    A_eff = sun_height
else:                                                    # afternoon — sun west of terrasse
    A_eff = 180 - sun_height
```

> At azimuth = wall_azimuth both branches converge to $A_{eff}$ = 90° (zenith).
> Derivation and correctness analysis: see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md)

### Step 1 — Desired slat angle

#### Cooling season (`sun_automatik_cooling`) — block sun

The slat must be **perpendicular** to the sun. Since $A_{eff}$ and the slat share the same number line, the blocking angle is offset by 90°. Morning sun (east) is blocked by the **back face** of the slat ($A_{eff}$ + 90); afternoon sun (west) is blocked by the **front face** ($A_{eff}$ − 90).

```
COOLING_LOWER_BOUND = sensor.pergola_cooling_lower_bound
                                            # = tilt_position ~21; ventilation floor
                                            # Derived at runtime: MaxOpenWest evaluated at the flip point A_eff.
                                            # flip point = largest A_eff where MaxOpenEast(A_eff) ≤ max_tilt − SAFETY_BUFFER
                                            #   (found by iterating A_eff from 1°→90° in 1° steps via Jinja2 for-loop)
                                            # COOLING_LOWER_BOUND = A_eff_flip + PHI − asin(R × sin(A_eff_flip))
                                            # Default (w=22, d=20, t=3, max_tilt=122): ≈15.3°
                                            # Re-derives automatically if slat geometry or max_tilt input changes.
SAFETY_BUFFER       = 5°                    # fixed named constant; flip margin below max_tilt; not user-configurable
R                   = sqrt(d² + t²) / w    # derived from slat geometry inputs:
                                            #   w = input_number.pergola_slat_width (default 22 cm)
                                            #   d = input_number.pergola_slat_pivot_spacing (default 20 cm)
                                            #   t = input_number.pergola_slat_thickness (default 3 cm)
                                            #   default: sqrt(20² + 3²) / 22 = 20.22 / 22 = 0.91926
PHI                 = degrees(atan(t / d))  # derived from slat geometry inputs (same w, d, t)
                                            #   default: degrees(atan(3 / 20)) = 8.53°

# MaxOpenEastMorningCoolingAngle: minimum back-face slat angle for
# 100% shade from eastern sun. (Condition: sin(θ − A_eff − PHI) = R × sin(A_eff))
# Derivation: Sperp - W = (A_eff + 90) - (90 - PHI - asin(R × sin(A_eff)))
MaxOpenEast = A_eff + PHI + degrees(asin(R × sin(radians(A_eff))))

# MaxOpenWestMorningCoolingAngle: maximum front-face (west-leaning) slat angle
# for 100% shade from high east / noon sun (A_eff ≤ 90 only).
# Blocking condition: sin(A_eff − θ + PHI) = R × sin(A_eff) → solve for θ.
# NOTE: sign is +PHI (not −PHI). Used as dynamic target in optimized cooling (Step 7).
# Values: 15.3° at flip point (A_eff=58°) → 31.7° at A_eff=90° (zenith).
MaxOpenWest = A_eff + PHI - degrees(asin(R × sin(radians(A_eff))))   # A_eff ≤ 90 only

if A_eff < 90 and MaxOpenEast <= max_tilt - SAFETY_BUFFER:
                                            # ── Morning (east sun, back-face blocking) ──
    if A_eff + 90 <= max_tilt:              #   back face can reach blocking angle
        slat_angle = A_eff + 90             #   perpendicular blocking
    else:                                   #   dead zone (A_eff > 32°)
        slat_angle = max_tilt               #   122° — still safe: MaxOpenEast ≤ 117°
else:                                       # ── Afternoon, or morning past safe limit ──
    slat_angle = max(A_eff - 90,            #   direct front-face / top-face blocking
                     COOLING_LOWER_BOUND)   #   15° floor (= MaxOpenWest at flip point)

clamp slat_angle to [COOLING_LOWER_BOUND, max_tilt]
```

**Morning dead zone ($A_{eff}$ ~32°–58°):** The ideal back-face angle ($A_{eff}$ + 90) exceeds 122° — mechanically unreachable. `max_tilt` (122°) is used instead. This is safe because `MaxOpenEastMorningCoolingAngle` remains well below 117° (`max_tilt - SAFETY_BUFFER`) throughout this range, confirming that 122° sits inside the shade safe zone.

**Dynamic morning limit:** The transition from morning (back-face) to afternoon (front-face/closing) formula is governed by `MaxOpenEastMorningCoolingAngle` — the minimum slat angle that still provides 100% shade from eastern sun (see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md) Section 3). When `MaxOpenEast > max_tilt - 5°` (at $A_{eff}$ ≈ 58° for max_tilt = 122°), the back-face strategy can no longer guarantee full shade, and the formula flips to the closing/flat strategy (`A_eff - 90`, floored at `COOLING_LOWER_BOUND`). The 5° buffer ensures the flip happens ~2 update cycles before shade loss would begin.

> Formula derivation and numerical anchor points: see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md) Section 3. If `input_boolean.pergola_cooling_optimized` is `on`, a different formula is used instead (see Step 7) — the `MaxOpenEast` flip logic applies to both modes.

**Cooling lower bound:** When the formula flips at $A_{eff}$ ≈ 58° (sun nearly overhead or approaching from high east), $A_{eff}$ − 90 is still negative and the floor governs. The floor is `COOLING_LOWER_BOUND = sensor.pergola_cooling_lower_bound` — derived at runtime as `MaxOpenWest(A_eff_flip)` where `A_eff_flip` is the largest A_eff where `MaxOpenEast ≤ max_tilt − SAFETY_BUFFER` (see Derived Internal Constants above). Default ≈15.3° (w=22, d=20, t=3, max_tilt=122). At 15°, `e_crit ≈ 50.6°` — summer noon (≈65°) still gives complete shade while allowing more airflow than the former 11° floor. For the dynamic floor used in optimized cooling, see Step 7.

#### Heating season (`sun_automatik_heating`) — let sun through

To let sun through, slats should be **parallel** to the sun rays. Because $A_{eff}$ and the slat angle share the same number line, the slat simply tracks $A_{eff}$:

```
MIN_HEATING_ANGLE = input_number.pergola_min_heating_slat_angle   # default 16°
                                            # Floor: prevents near-parallel slats at dawn.
                                            # Default derived from tilt-position 20:
                                            #   (20 − 7) × max_tilt_angle / 100 = 15.86° ≈ 16° at default max_tilt_angle=122°
                                            # User-configurable via input_number.

if A_eff <= max_tilt:                        # sun angle within hardware range (≤ 122°)
    slat_angle = max(A_eff, MIN_HEATING_ANGLE)
                                            # covers ALL east, noon, south, and slight west;
                                            # floor prevents near-parallel slat at dawn
else:                                        # dead zone: A_eff > 122° (moderate-to-far west)
    tilt_position = 100                      # max tilt directly — no other position lets in
    # skip hardware correction               # more sun from the west

clamp slat_angle to [MIN_HEATING_ANGLE, max_tilt]   # (only applies to non-dead-zone branch)
```

**Dead zone fallback for heating:** When $A_{eff}$ > 122° — sun from moderate-to-far west — use `tilt_position = 100` (max tilt, 122°) directly. The slats are past vertical with the back face angled toward the incoming west sun, opening the maximum gap. No other position does better.

#### Verification table

All rows are within the azimuth window (AZIMUTH_MIN–AZIMUTH_MAX, derived as `wall_azimuth ± 90`, default 114°–294°). Outside that range the state machine is in `no_sun_behind_house` and neither formula runs — slats go to slat_angle 90° (tilt_position via formula, default 74).
 
| Azimuth | Elev | $A_{eff}$ | MaxOpenEast | MaxOpenWest | Cooling slat | Cooling formula | Heating slat | Notes |
|---|---|---|---|---|---|---|---|---|
| 115° | 20° | 20.0° | 37.7° | n/a | 110° (tilt≈90) | 20+90 (morning, MOE=37.7≤117) | 20.0° (= $A_{eff}$) | Far east, near window edge |
| 150° | 30° | 35.5° | 73.8° | n/a | 122° (tilt=100) | 35.5+90=125.5 → DZ (MOE=73.8≤117) | 35.5° (= $A_{eff}$) | Moderate east — dead zone, safe |
| 140° | 40° | 43.0° | 89.5° | n/a | 122° (tilt=100) | 43+90=133 → DZ (MOE=89.5≤117) | 43.0° (= $A_{eff}$) | East, medium elev — dead zone, safe |
| 165° | 50° | 55.0° | 112.4° | n/a | 122° (tilt=100) | 55+90=145 → DZ (MOE=112.4≤117) | 55.0° (= $A_{eff}$) | High east — dead zone, 4.6° margin |
| 180° | 40° | 64.1° | 128.5° | 15.9° | **15°** (tilt≈21) | MOE=128.5>117 → **flip to closing** | 64.1° (= $A_{eff}$) | South, lower elev — back-face unsafe, floor=15° |
| 180° | 55° | 74.1° | 143.2° | 18.8° | **15°** (tilt≈21) | MOE=143.2>117 → **flip to closing** | 74.1° (= $A_{eff}$) | Noon (summer) — back-face unsafe, floor=15° |
| 204° | 57° | 90.0° | n/a | 31.7° | **15°** (tilt≈21) | 90−90=0 → LB=15 | 90.0° (= $A_{eff}$) | Sun along slat axis — lower bound |
| 220° | 45° | 105.4° | n/a | n/a (west) | 15.4° | 105.4−90 (afternoon) | 105.4° (= $A_{eff}$) | Slight west |
| 240° | 40° | 125.0° | n/a | n/a (west) | 35.0° | 125−90 (afternoon) | 100 pos (DZ: $A_{eff}$ > 122°) | West — heating dead zone |
| 260° | 30° | 145.1° | n/a | n/a (west) | 55.1° | 145.1−90 (afternoon) | 100 pos (DZ: $A_{eff}$ > 122°) | Far west — heating dead zone |

#### No sun (`no_sun_behind_house`, `not_enough_sun`)
```
slat_angle = 90       # vertical open position
tilt_position = INT(90 / max_tilt × 100 + 0.5)   # correction = 0.5 (90° ≥ 69°); default max_tilt=122 → 74
```
> **Implementation:** this is algorithm pseudocode only. In code, pass `slat_angle: 90` to `script.pergola_set_slat_angle` — the formula above runs inside that script, not inline.

#### Rain / Frost
No cover movement.

---

### Step 2 — Convert slat_angle to tilt_position

Hardware-corrected conversion (based on observed motor behaviour):
```
correction = 7    if slat_angle < 20°
           = 5.5  if slat_angle < 69°
           = 0.5  otherwise

tilt_position = INT(slat_angle / pergola_max_tilt_angle × 100 + correction)
```
- `pergola_max_tilt_angle` = `input_number.pergola_max_tilt_angle` (default 122°)
- Clamp result: both cooling and heating → [0, 100]
- Values > 100 are dead zone on the Somfy controller — never send them

**Why corrections are needed:**
- Below 20°: motor displacement is very small → +7 compensates
- 20°–69°: linear region → +5.5 rounds up correctly
- Above 69°: slight mechanical jerk → only +0.5 to avoid overshoot

> **Single authoritative implementation:** The formula above is implemented in exactly one place: `script.pergola_set_slat_angle` (defined in Implementation Step 3). All cover movement commands go through this script — the formula is never inlined in automations or other scripts. `sensor.pergola_tilt_position` also evaluates the formula for display/debug (read-only; never used to drive cover commands directly).

---

### Step 3 — Movement Deadband (5° hysteresis)

Before sending any tilt command, compare the **calculated target tilt_position** (output of Step 2) against the **current reported tilt_position** from the cover. Only move if the difference corresponds to ≥ 5° of slat angle.

**Why compare tilt positions, not slat angles:**
Inverting the Step 2 formula naïvely (`slat_angle = current_tilt × max_tilt / 100`) ignores the correction offsets (+7 / +5.5 / +0.5). Those offsets introduce errors of 7–9° at low/medium angles — larger than the 5° threshold itself, making the comparison unreliable. Because both `target_tilt_position` and `current_tilt_position` are in the same corrected tilt-position space, the corrections cancel in the difference. The comparison is done entirely in tilt-position units.

**5° converted to tilt-position units:**
```
DEADBAND_TILT = (5 / max_tilt_angle * 100) | round(0) | int    # derived; default: ROUND(5/122×100) = 4
```
(4 tilt units ≈ 4.9° at the default max_tilt_angle of 122°; re-derives if max_tilt changes)

**Gate condition (applied before every cover move command):**
```
current_tilt = state_attr('cover.dach_links', 'current_tilt_position') | int

if |target_tilt_position - current_tilt| >= DEADBAND_TILT:
    send move command with target_tilt_position
else:
    skip (no movement)
```

Use `cover.dach_links` as the reference — both covers always move together.

This applies **only to states where the formula output changes continuously with the sun** (`sun_automatik_cooling`, and `sun_automatik_heating` once the real heating formula is in place). It does **not** apply to fixed-target states (`no_sun_behind_house`, `not_enough_sun`, or the `sun_automatik_heating` stub) — those always send `slat_angle: 90` unconditionally; the Somfy is idempotent if already at the target position. The post-rain recovery script bypasses this check — it always moves to its drain angles regardless.

**Why 5°:** The motor's dead zone and mechanical play account for ≈2–3° uncertainty. A 5° threshold prevents constant micro-movements as the sun creeps while still ensuring the covers track meaningful changes (the sun moves about 1°–2° in azimuth per minute at moderate elevation, producing a slat angle change of well under 1°/min — so 5° corresponds to a 5–10 minute lag, comparable to the periodic trigger interval).

---

## Post-Rain Recovery Sequence

**Trigger:** State transitions to `rain_stopped`
**Script:** `script.pergola_post_rain_recovery`

1. Wait **30 seconds** (give system time to update all states)
2. Set slat angle → **8°** (slight opening to start drainage)
3. Wait **5 minutes** (water runs down)
4. Set slat angle → **15°** (open more for continued drainage)
5. Wait **5 minutes** (more water runs down)
6. Check `sensor.wheatherstation_hourly_rain`:
   - If `== 0` → proceed immediately to step 7
   - If `> 0` → wait **30 more minutes** (slats dry), then proceed to step 7
7. Exit `rain_stopped`: re-evaluate state machine rules → set `input_select.pergola_automation_state` to the correct current state (`no_sun_behind_house`, `not_enough_sun`, `sun_automatik_heating`, or `sun_automatik_cooling`)

> **Note:** Slat angles (8°, 15°) converted to tilt_position using the hardware correction formula before sending to covers.
> **Note:** Lock originator clears autonomously inside the Somfy via the 900 s countdown timer. HA only learns the change when the inactivity watchdog (or a movement command) forces a state report. The state machine will see `rain_stopped` → `unknown` within ≤5 minutes of the timer expiring.

---

## Frost Safety

Hysteresis to prevent oscillation:
- Temp falls below 2.5 °C (hardcoded) → state = `frost`, movement stops
- Temp rises above 3.0 °C (hardcoded, 0.5 °C hysteresis gap) → exit `frost`:
  - Check `sensor.wheatherstation_hourly_rain`:
    - If `> 0` → enter `rain_stopped` (run post-rain recovery script)
    - If `== 0` → re-evaluate normally (no rain recovery needed)

**Robustness — value-based frost conditions:** The dedicated `numeric_state` frost_entry / frost_exit triggers in `pergola_state_manager` fire on threshold crossings so we react immediately, but the branch conditions are evaluated against the *current* `wheatherstation_outdoor_temperature` value — **not** against `trigger.id`. This means any trigger (time_pattern every 5 min, sensor update, HA start) can enter or exit frost based on the live temperature, so the state converges correctly even if the threshold-crossing trigger is silently dropped from the queue (`mode: queued, max: 3`). Fail-safe defaults on unknown/unavailable sensor readings: entry uses `| float(99)` (do not trip frost), exit uses `| float(0)` (stay in frost until temp is known).

---

## Master Switch

`input_boolean.pergola_automatic_enabled` — when `off`, `script.pergola_set_slat_angle` exits immediately without moving covers. This gates all cover movement including the post-rain drain sequence. State machine continues tracking state so re-enabling acts immediately. **Template sensors (`sensor.pergola_effective_sun_angle`, `sensor.pergola_slat_angle`, `sensor.pergola_tilt_position`, `binary_sensor.pergola_sun_shining`) are NOT gated by this switch — they always reflect current computed values. Only cover movement commands are suppressed.**

---

## Implementation Steps

Each step is independently deployable via `git pull` on the HA host.

---

### Phase 1 — Foundation

#### Step 1 — Helpers, Template Sensors, Device Linking [DONE]
**File:** `packages/pergola.yaml`

Add `input_boolean`, `input_select`, `input_number`, and `template` sections. All template entities carry `device_id:` to link them to the user's existing cover device.

**Before implementing:** ask the user for their **device ID** (UUID from the device page URL) and **label name**. Substitute both throughout the file.

**Dependencies:** None — first step.

**Notes:**
- **`packages/pergola.yaml` is rewritten from scratch** — the existing file (which still contains the old `pergola_frost_hold` and `pergola_post_rain_active` booleans) is discarded entirely. Write the complete file fresh using only the entities listed below.
- **Carry over the 4 existing automations** — these must appear in the new file's `automation:` block. The watchdog automations (ids below) are carried over **with the state-based suppression condition already present** (added before Step 1 to fix a race condition — see Step 2 notes). The lock originator responders are carried over verbatim.
  - `id: '1771360145720'` — Inactivity Watchdog: Dach Links
  - `id: '1771361016291'` — Inactivity Watchdog: Dach Rechts
  - `id: '1771748333394'` — Dach Links: Update state when lock originator changes
  - `id: '1771748414999'` — Dach Rechts: Update state when lock originator changes
  - These are critical for the rain-lock lifecycle and must not be lost during the rewrite.
- **Device linking:** every `template` entity (`sensor`, `binary_sensor`, `number`, `switch`) gets `device_id: <USER_DEVICE_ID>`. Do NOT create a device — only attach to the existing one the user provides.
- **Template wrappers:** each `input_boolean` gets a `template switch`, each `input_number` gets a `template number`, and `input_select.pergola_automation_state` gets a read-only `template sensor` — all with `device_id:`. This makes them appear on the device card. Automations target the `input_*` entity IDs, not the wrappers.
- `sensor.pergola_cooling_lower_bound` carries `device_id:` and appears on the device page as a read-only value. It re-derives automatically from slat geometry inputs — no wrapper needed.
- `input_select.pergola_automation_state` must list all 8 state values
- PV conversion factor default 3.2; can be refined in Step 6 field testing (Phase 5)
- Add `input_number.pergola_max_tilt_angle` (default 122, min 100, max 135, step 1, unit °)
- Add `input_number.pergola_min_sun_elevation` (default 10, min 1, max 30, step 0.5, unit °) — elevation at or below which state = `no_sun_behind_house`
- Add `input_number.pergola_min_heating_slat_angle` (default 16, min 0, max 40, step 1, unit °) — floor slat angle in heating mode (back-calculated from tilt=20: `(20−7)×max_tilt_angle/100=15.86°≈16°` at default max_tilt_angle=122°)
- Add `input_boolean.pergola_cooling_optimized` (default off) — selects between perfect-perpendicular and safe-zone max-open cooling formula (Step 7)
- Add `input_number.pergola_wall_azimuth` (default 204, min 0, max 359, step 1, unit °) — compass bearing of terrasse wall; drives AZIMUTH_MIN/MAX and the A_eff formula
- Add `input_number.pergola_clearness_factor` (default 0.9, min 0.5, max 1.2, step 0.05) — calibration knob for sun_shining threshold (Step 6)
- Add `input_number.pergola_slat_width` (default 22, min 5, max 50, step 0.5, unit cm) — slat face width (w); used to derive R and PHI
- Add `input_number.pergola_slat_pivot_spacing` (default 20, min 5, max 40, step 0.5, unit cm) — pivot-to-pivot spacing (d); used to derive R and PHI
- Add `input_number.pergola_slat_thickness` (default 3, min 0.5, max 10, step 0.5, unit cm) — slat thickness (t); used to derive R and PHI
- Add `sensor.pergola_cooling_lower_bound` (unit °) as a read-only template sensor with `device_id:` — computed from slat geometry and max_tilt using a Jinja2 for-loop; re-derives automatically when any input changes; no other formula may hardcode a literal 15° floor
- **Derived constants computed inline or as template sensors** (never hardcode literals): AZIMUTH_MIN/MAX from wall_azimuth; R and PHI from slat geometry; DEADBAND_TILT from max_tilt; COOLING_LOWER_BOUND from sensor above. See "Derived Internal Constants" table in the device section.
- Add `input_boolean.pergola_heating` (default off) — heating indicator; when `on`, sun is let through (heating formula); when `off`, sun is blocked (cooling formula). Can be toggled by user in UI or set via HA REST API by an external system
- Add `sensor.pergola_effective_sun_angle` (unit °, unknown until formula defined in Step 3) as a stub template sensor returning `unknown` for now — exists on the device from day one for debugging
- Add `sensor.pergola_slat_angle` (unit °, unknown until formula defined in Step 3) and `sensor.pergola_tilt_position` (0–100, unknown until Step 3) as stub template sensors returning `unknown` for now

**Post-deploy (one-time, manual via HA UI):** Apply the user-defined label to all entities (both template wrappers and backend `input_*` helpers) via Settings → Entities. Template wrapper entities will already appear on the device card automatically. Backend `input_*` helpers cannot be device-linked from YAML — the label is their only grouping mechanism.

**Verify:**
- HA config check passes with no errors
- Template entities appear on the device page under Settings → Devices → [device]
- `binary_sensor.pergola_sun_shining` changes state plausibly with sun conditions
- `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` report `unknown` (correct at this stage)
- Template switch and number wrapper entities write through to the backend `input_*` entities
- `sensor.pergola_cooling_lower_bound` appears on the device card and updates automatically when geometry inputs change

---

#### Step 2 — State Manager Automation [DONE]
**File:** `packages/pergola.yaml` — add under `automation:`

Add `pergola_state_manager` and `script.pergola_evaluate_state`. Together these are the **only code that writes** to `input_select.pergola_automation_state`.

**`script.pergola_evaluate_state`** — evaluates rules 5–8 (no_sun_behind_house → not_enough_sun → heating → cooling) and sets `input_select.pergola_automation_state`. This script is the **single place** for lower-priority rule logic — called from two places to avoid duplication:
- `pergola_state_manager` default branch (when rules 1–4 do not apply)
- `script.pergola_post_rain_recovery` final step (when exiting rain_stopped — frost and rain already ruled out)

Triggers: outdoor temp (numeric_state, both entry and exit thresholds), rain rate, both lock originator sensors (`dach_links` and `dach_rechts`), `pergola_sun_shining`, `input_boolean.pergola_heating`, HA start, and `time_pattern: minutes: /5`.

> **Why `time_pattern` instead of `sun.sun` attributes:** Sun azimuth and elevation change continuously — triggering on them directly would cause an evaluation every minute. Instead, `time_pattern: /5` catches slow threshold crossings (azimuth window entry/exit, elevation guard) at a rate matched to the sun's movement speed (~1–2°/min azimuth ≙ well under 1° slat change/min, so 5 min lag is negligible). The state manager reads `sun.sun` attributes directly inside its condition templates when it runs.

> Lock originator sensors must be triggers so the state manager reacts to rain-lock entry/exit (rule 2) and user-override entry/exit (rule 4) without waiting for another trigger.

Action: `pergola_state_manager` evaluates rules 1–4 directly (frost → rain → rain_stopped → user_override) — these require preempting ongoing scripts and have asymmetric exit logic. For all other cases, it delegates to `script.pergola_evaluate_state` (rules 5–8: no_sun_behind_house → not_enough_sun → heating → cooling).

**Dependencies:** Step 1 (helpers must exist).

**Notes:**
- **Lock originator triggers are watchdog-driven.** The Somfy does not push state changes proactively. `sensor.dach_links_priority_lock_originator` and `sensor.dach_rechts_priority_lock_originator` only update in HA when the inactivity watchdog (or a movement command) sends `stop_cover_tilt` and forces a Somfy state report. The state manager triggers on these sensors but cannot observe rain clearing without the watchdog first causing a report. This is not a gap — the watchdog is already in place — but it means the state manager's lock originator triggers are reactive to watchdog-driven updates, not direct Somfy pushes.
- **Watchdog suppression is explicit, not emergent.** The watchdog and the cover response automation both use `time_pattern: minutes: /5`, so they evaluate simultaneously at every 5-minute mark. Because the cover's `last_updated` is only set after the Somfy responds (not when the command is sent), the watchdog condition would pass at the same instant the cover response is about to send a movement command — causing `stop_cover_tilt` to abort the movement mid-travel. To eliminate this race, both watchdog automations carry an explicit state condition that skips them when `input_select.pergola_automation_state` is in `[sun_automatik_cooling, sun_automatik_heating, rain_stopped]`. The watchdog runs only in quiet states where no movement commands are issued (`rain`, `frost`, `user_override`, `no_sun_behind_house`, `not_enough_sun`).
- **Lock originator responders (automations 3 & 4) complement the state manager.** These automations (already in the file) trigger on lock originator changes and immediately send a second `stop_cover_tilt`. This forces a fresh Somfy state report right after each lock transition, before the state manager has acted. The state manager's second evaluation then sees the most current tilt position data. These automations should be left as-is — do not fold their logic into the state manager.
- Guard: do not overwrite `rain_stopped` mid-flight — only the recovery script exits that state. **Exceptions** (state manager may write a different state while `rain_stopped` is active):
  - **frost entry (from any state including `rain_stopped`):** temp falls below 2.5 °C (hardcoded) → call `script.turn_off` on `script.pergola_post_rain_recovery`, then set state to `frost`. Frost is the highest-priority safety rule — it must preempt an in-progress drain sequence.
  - **rain re-entry (from any state including `rain_stopped`):** either rain indicator becomes active → call `script.turn_off` on `script.pergola_post_rain_recovery`, then set state to `rain`. Rain just restarted — the covers should stay closed and the drain sequence must not continue mid-rain.
  - **frost exit:** `wheatherstation_outdoor_temperature` rises above 3.0 °C (hardcoded) → if `wheatherstation_hourly_rain > 0`, set state to `rain_stopped` and trigger recovery script
  - **user_override exit:** both lock originators return to `unknown` → if `wheatherstation_hourly_rain > 0`, set state to `rain_stopped` and trigger recovery script
  - **HA start with state = `rain_stopped`:** do NOT clear the state; instead re-trigger `script.pergola_post_rain_recovery` so the interrupted drain sequence resumes (see restart recovery note below)
- `input_boolean.pergola_heating` may not exist yet; use a safe default (cooling season) when unavailable
- **HA start / restart recovery:**
  - On HA start the automation fires with trigger = `homeassistant` start
  - If `input_select.pergola_automation_state` is already `rain_stopped` (persisted from before restart): do NOT evaluate other rules; instead call `script.pergola_post_rain_recovery` again to resume the interrupted drain sequence. The recovery script is idempotent enough for this — it will re-run the wait + step sequence from the beginning, which is safe (covers get drained again).
  - For all other persisted states: evaluate rules 1–4 inline, then call `script.pergola_evaluate_state` for rules 5–8
- `not_enough_sun` entry/exit uses **two separate named automations** rather than a single choose block:
  - **`pergola_not_enough_sun_entry`** — trigger: `binary_sensor.pergola_sun_shining` → `off` (no `for:` — the sensor's own `delay_off: 5 min` already means it only goes `off` after 5 continuous minutes); condition: `input_select.pergola_automation_state` not in {frost, rain, rain_stopped, user_override, no_sun_behind_house}; action: set state = `not_enough_sun`
  - **`pergola_not_enough_sun_exit`** — trigger: `binary_sensor.pergola_sun_shining` → `on` (no `for:` needed — the sensor's `delay_on: 1 min` already ensures it only turns `on` after 1 continuous minute); condition: state = `not_enough_sun`; action: re-evaluate heating/cooling and set state to `sun_automatik_heating` or `sun_automatik_cooling` accordingly

**Verify:**
- Config check passes (Developer Tools → YAML → *Check Configuration*); reload automations.
- State reflects current conditions on HA boot.
- Template sanity: Developer Tools → Template, render
  `{{ states('sensor.wheatherstation_outdoor_temperature') | float(99) < 2.5 }}` and
  `{{ states('sensor.wheatherstation_outdoor_temperature') | float(0) > 3.0 }}` → match live temp.
- Frost entry: set state to `sun_automatik_cooling`, then set
  `sensor.wheatherstation_outdoor_temperature` to `2.0` via Developer Tools → States. Within ≤5 min
  (next `time_pattern` tick) state must become `frost`. Confirm the trace shows the Rule 1 Entry
  branch fired from a trigger other than `frost_entry` (proves value-based recovery works).
- Frost exit: while in `frost`, set the sensor to `4.0`. Within ≤5 min state must exit frost
  (→ `rain_stopped` if `hourly_rain > 0`, else whatever `pergola_evaluate_state` returns).
- Fail-safe on unknown sensor: while in `frost`, set the sensor to `unknown` → state must remain
  `frost`. While *not* in frost, set it to `unknown` → state must **not** enter frost.
- Evaluate azimuth template manually → `no_sun_behind_house` fires at night.
- Deploy via `git pull` on the HA host, then re-run config check and reload on the live instance.

---

### Phase 2 — Cover Control

#### Step 3 — Cover Response Automation (no-sun + cooling) [DONE]
**File:** `packages/pergola.yaml` — add under `automation:`

Add `pergola_cover_response`. Triggers on `input_select.pergola_automation_state` state change and on time pattern every 5 min (to track sun position within active state).

Also defines `script.pergola_set_slat_angle` — the single authoritative cover movement script (see entity listing and Tilt Calculation Logic Step 2). All cover movement in this step and Step 4 goes through this script.

Condition: none — the `input_boolean.pergola_automatic_enabled` gate lives inside `script.pergola_set_slat_angle`, not here. The automation always runs; the script decides whether to move covers.

Action (`choose` on current state):
- `no_sun_behind_house`, `not_enough_sun` → if deadband passes, call `script.pergola_set_slat_angle` with `slat_angle: 90`
- `frost`, `rain`, `rain_stopped`, `user_override` → do nothing
- `sun_automatik_cooling` → compute slat_angle via cooling formula; if deadband passes, call `script.pergola_set_slat_angle` with computed slat_angle
- `sun_automatik_heating` → stub: if deadband passes, call `script.pergola_set_slat_angle` with `slat_angle: 90` (replaced in Step 5)

**Dependencies:** Step 1 (helpers), Step 2 (state machine must be writing state).

**Notes:**
- Every-5-min trigger is the only way covers track a slowly moving sun within a steady state
- Cooling tilt clamp is [0, 100]: western sun branch (slat 0°–90°) stays below tilt_position(90°) naturally (default ≈74, derived via formula); eastern sun branch (+180°, slat 90°–max_tilt_angle°) uses tilt_position(90°)–100 to block sun from behind the slat.
- **Flip guard (standard cooling):** `MaxOpenEast < max_tilt − SAFETY_BUFFER` (stay in morning/back-face mode while the minimum shade angle is at least SAFETY_BUFFER below max_tilt). This is the same guard used in Step 7 optimised cooling — flip point is shared. Standard morning target: `min(A_eff + 90, max_tilt)`; optimised morning target: `min(max(90, MaxOpenEast + SAFETY_BUFFER), max_tilt)`.
- **Deadband (Tilt Calculation Logic Step 3):** the automation computes `target_tilt_position` (INT(slat_angle/max_tilt×100+correction)) and compares it against `cover.dach_links.current_tilt_position`; only calls `script.pergola_set_slat_angle` if `|target - current| >= DEADBAND_TILT`. The script itself does **not** check the deadband — this separation allows post-rain recovery to bypass it naturally by calling the script directly.
- Fill in the stub template sensors from Step 1: `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` should reflect the current calculated values based on state + sun position (update the template body, not just the automation). The template bodies for `sensor.pergola_effective_sun_angle`, `sensor.pergola_slat_angle`, and `sensor.pergola_tilt_position` must NOT check `input_boolean.pergola_automatic_enabled` — they always compute. The `automatic_enabled` gate belongs only to the `pergola_cover_response` automation condition, not to any template sensor.

**Verify:**
- Disable `pergola_automatic_enabled` → covers stop responding (script exits early, automation still evaluates state)
- With sun active and cooling season, covers move to formula result within 5 min; verify no movement if cover is already within 5° of target
- Manually set state to `no_sun_behind_house` → tilt goes to formula result for slat_angle 90° (default 74, or stays if already within 5°)

---

#### Step 4 — Post-Rain Recovery Script [DONE]
**File:** `packages/pergola.yaml` — add under `script:`

`script.pergola_post_rain_recovery` — stepped drain sequence (8° → wait 30 s → wait 5 min → 15° → wait 5 min → check hourly rain → [wait 30 min if rain reported] → re-evaluate and set final state).

**Dependencies:** Step 2 (state manager must set `rain_stopped` to trigger this), Step 3 (cover control).

**Notes:**
- Script calls `script.pergola_set_slat_angle` with `slat_angle: 8` and `slat_angle: 15` for the drain steps — the formula runs there, not inline. No deadband check; the script always moves regardless of current position (drain must complete).
- **Final step calls `script.pergola_evaluate_state`** (the shared script from Step 2) to set the correct state. No duplication — rules 5–8 live in exactly one place. The state manager won't fire on its own at script end because no sensor values changed (rain_rate and lock originators were already clear before entering rain_stopped).
- TBD: confirm 25%/50% drain adequately after first real rain

**Verify:**
- Manually trigger script from Developer Tools → confirm cover movement and timing
- State exits `rain_stopped` at end of script

---

### Phase 3 — Heating Season

#### Step 5 — Heating Season Logic [TODO]
**File:** `packages/pergola.yaml` — update `pergola_cover_response` and `pergola_state_manager`

Prerequisites:
- `input_boolean.pergola_heating` created in Step 1 (local HA toggle)

**Room temperature is NOT used** — heating/cooling mode is determined solely by `input_boolean.pergola_heating`.

Update `sun_automatik_heating` branch of `pergola_cover_response`:
- Compute `slat_angle` using the heating formula (Tilt Calculation Logic → Step 1): `slat_angle = A_eff` (slat tracks effective sun angle directly)
- **Dead zone:** if `A_eff > max_tilt` (122°), set `tilt_position = 100` directly — skip the hardware correction formula. No other position lets in more west sun.
- For non-dead-zone branch: convert `slat_angle` to `tilt_position` using the hardware correction formula, clamp result to `[0, 100]`

Update state manager: when sun is active and `input_boolean.pergola_heating = on` → `sun_automatik_heating`; otherwise → `sun_automatik_cooling`.

**Dependencies:** Step 1 (`input_boolean.pergola_heating` created there), Step 3 (cover response stub must exist).

**Verify:**
- With `pergola_heating` on → heating formula applied
- With `pergola_heating` off → state transitions to `sun_automatik_cooling`

---

### Phase 4 — Optimized Cooling

#### Step 7 — Optimized Cooling Angle
**File:** `packages/pergola.yaml` — add two readonly sensors; update `sensor.pergola_slat_angle` formula

Gated by `input_boolean.pergola_cooling_optimized`. When `on`, replace the perfect-perpendicular cooling formula with one that uses the **safe-zone max-open angle** — the furthest the slats can tilt toward vertical while still guaranteeing 100% shade (leveraging slat overlap/thickness).

**Key concept:** Due to the slat geometry (w=`pergola_slat_width`, t=`pergola_slat_thickness`, d=`pergola_slat_pivot_spacing`; R and PHI derived from these — see Derived Internal Constants), the slats overlap. There is a range of angles (the "safe zone") that all provide full shade. The max-open formula targets the far edge of this zone to maximize airflow. Both `MaxOpenEastMorningCoolingAngle` (morning, back-face) and `MaxOpenWestMorningCoolingAngle` (flip range, front-face) are exposed as readonly sensors and used as targets instead of the perfect-perpendicular angles.

**Formulas (see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md) Section 3):**

```
MaxOpenEast = A_eff + PHI + degrees(asin(R × sin(radians(A_eff))))   # min back-face angle
MaxOpenWest = A_eff + PHI − degrees(asin(R × sin(radians(A_eff))))   # max front-face angle

# MaxOpenWest is valid for ALL A_eff (0°–180°). For A_eff ≤ 90 it gives the morning flip-range
# target; for A_eff > 90 the same formula gives MaxOpenWestAfternoon (see below).

# ── Named targets applied in the slat-angle formula (NOT stored in sensors) ──

MaxOpenEastMorningCoolingAngle = max(90, sensor.pergola_max_open_east_morning_cooling_angle + SAFETY_BUFFER)
    # Morning target: MaxOpenEast is the MINIMUM angle for full shade. Adding SAFETY_BUFFER
    # keeps the slat 5° ABOVE that threshold — safely inside the shade zone, never below it.
    # Floor at 90° (vertical) — sub-vertical angles provide no sun-blocking benefit.

MaxOpenWestMorningCoolingAngle = sensor.pergola_max_open_west_cooling_angle
    # Flip-range target: dynamic front-face max-open (15.3° at flip point → 31.7° at A_eff=90°).
    # No buffer — MaxOpenWest is the permissive bound; use directly.
    # For A_eff ≤ 90° the raw value is ≤ 31.7°; the 90° cap never fires here.

MaxOpenWestAfternoon = min(90, sensor.pergola_max_open_west_cooling_angle)
    # Afternoon target: maximum front-face angle for full shade from western sun.
    # Cap applied inline (not in the sensor). No buffer needed (it is the permissive bound).
    # For A_eff > ~128°: raw sensor > 90° → capped to 90° → slat stays fully vertical, maximum airflow.
    # Continuity: at A_eff = 90° (zenith) MaxOpenWestAfternoon = MaxOpenWestMorning ≈ 31.7°.

# ── Optimized cooling decision tree (flip guard shared with standard mode) ──

if A_eff < 90 and sensor.pergola_max_open_east_morning_cooling_angle < max_tilt − SAFETY_BUFFER:
    # Morning: back-face strategy. SAFETY_BUFFER added to raw sensor value as the target.
    # Floor at 90° (vertical) is the minimum useful back-face angle.
    slat_angle = min(MaxOpenEastMorningCoolingAngle, max_tilt)

elif A_eff <= 90:
    # Flip range (A_eff < 90, morning target saturated → switch to front-face strategy).
    # MaxOpenWest morning used directly — dynamic, no fixed floor.
    slat_angle = MaxOpenWestMorningCoolingAngle

else:
    # Afternoon west sun (A_eff > 90): front-face, optimized to be as open as possible.
    # Uses MaxOpenWestAfternoon — same geometry as morning MaxOpenWest but for western sun,
    # capped at 90°. For most afternoon positions (A_eff > ~128°) this is 90° (fully open).
    slat_angle = MaxOpenWestAfternoon
```

> **MaxOpenWestAfternoon derivation:** The formula `A_eff + PHI − degrees(asin(R × sin(radians(A_eff))))` is the natural extension of morning MaxOpenWest to A_eff > 90°. Both morning and afternoon use the same algebraic formula (same sensor `pergola_max_open_west_cooling_angle`); `sin(A_eff)` for A_eff > 90° mirrors `sin(A_eff_west)` with `A_eff_west = 180° − A_eff`, encoding the symmetric western-sun geometry. The formula is continuous at A_eff = 90° (both give ≈31.7° at the zenith). The afternoon branch applies `min(90, sensor)` inline: once the sun is far enough into the west (A_eff > ~128°) the raw value exceeds 90° and gets clamped — slat holds fully vertical, maximum airflow while shade is guaranteed by slat overlap. The morning branch never needs the cap (raw value ≤ 31.7° for A_eff ≤ 90°).

**New readonly template sensors (add to `packages/pergola.yaml` template block, near `sensor.pergola_slat_angle`):**

Both sensors expose the **raw geometric values** — no safety buffer applied. The buffer is added only in the slat-angle formula (below), keeping the sensors useful as pure diagnostic values.

- `sensor.pergola_max_open_east_morning_cooling_angle`
  - Formula: `A_eff + PHI + degrees(asin(R × sin(radians(A_eff))))` (= MaxOpenEast — minimum back-face angle for full shade)
  - Meaning: pure geometric value; the slat-angle formula adds SAFETY_BUFFER on top when computing the actual target
  - Unit: `°`; icon: `mdi:angle-obtuse`
  - Availability: same as `sensor.pergola_slat_angle` (requires A_eff sensor + geometry inputs)
  - Always computed regardless of `pergola_cooling_optimized` state

- `sensor.pergola_max_open_west_cooling_angle`
  - Formula: `A_eff + PHI − degrees(asin(R × sin(radians(A_eff))))` (= MaxOpenWest — maximum front-face angle for full shade, raw/uncapped)
  - Meaning: pure geometric value; used directly as the flip-range (A_eff ≤ 90°) slat target; used with an inline `min(90, …)` cap as the afternoon (A_eff > 90°) slat target. The cap is applied in the slat-angle formula, not here, so this sensor remains a clean diagnostic value. For A_eff ≤ 90° the raw value is always ≤ 31.7° (cap would never fire anyway). For A_eff > ~128° the raw value exceeds 90°; the afternoon branch clamps it inline.
  - Continuity: raw value ≈ 31.7° at A_eff = 90° — continuous across the morning/afternoon boundary.
  - Unit: `°`; icon: `mdi:angle-acute`
  - Availability: same as `sensor.pergola_slat_angle` (requires A_eff sensor + geometry inputs)
  - Always computed regardless of `pergola_cooling_optimized` state

**Key values for sensor.pergola_max_open_west_cooling_angle (raw, no cap; defaults w=22, d=20, t=3, max_tilt=122):**
The afternoon slat-angle branch applies `min(90, sensor)` inline — values above 90° are clamped there.

| A_eff | Standard (A−90) | Raw sensor value | Afternoon slat target (after inline cap) |
|---|---|---|---|
| 90° | 0° → floor 15.3° | 31.7° | 31.7° |
| 100° | 10° | 43.6° | 43.6° |
| 110° | 20° | 58.6° | 58.6° |
| 120° | 30° | 76.0° | 76.0° |
| 128° | 38° | ≈ 90° | ≈ 90° |
| 130° | 40° | 93.8° | **90°** (capped) |
| 150° | 60° | ≫ 90° | **90°** (capped) |

**Derivation in the slat-angle formula** — read sensor values and apply adjustments inline:
```
MaxOpenEastMorningCoolingAngle = max(90, sensor.pergola_max_open_east_morning_cooling_angle + SAFETY_BUFFER)
    # SAFETY_BUFFER added here (not in the sensor) — keeps slat 5° above the geometric minimum
MaxOpenWestMorningCoolingAngle = sensor.pergola_max_open_west_cooling_angle
    # No buffer — permissive bound; used directly as flip-range target
MaxOpenWestAfternoon = min(90, sensor.pergola_max_open_west_cooling_angle)
    # No buffer — permissive bound for western sun; cap applied inline (raw sensor > 90° for A_eff > ~128°)
```

**Flip guard:** identical in both standard and optimised modes — `sensor.pergola_max_open_east_morning_cooling_angle < max_tilt − SAFETY_BUFFER` (raw sensor value compared, buffer not re-added). Flip fires when there is no longer room to stay SAFETY_BUFFER above MaxOpenEast within max_tilt. Only the target angle within each branch differs between modes:

| Branch | Standard | Optimized |
|---|---|---|
| Morning (A_eff < 90, flip guard passes) | `min(A_eff + 90, max_tilt)` | `min(MaxOpenEastMorningCoolingAngle, max_tilt)` |
| Flip range (A_eff ≤ 90, flip guard fails) | `max(A_eff − 90, COOLING_LOWER_BOUND)` | `MaxOpenWestMorningCoolingAngle` |
| Afternoon (A_eff > 90) | `max(A_eff − 90, COOLING_LOWER_BOUND)` | `MaxOpenWestAfternoon` |

**Dependencies:** Step 3 (cover response and cooling formula must exist), `input_boolean.pergola_cooling_optimized` added in Step 1 update.

**Add all two new sensors to `group.pergola_dach`** (after `sensor.pergola_cooling_lower_bound`) and to `dashboards/elements/pergola_card.yaml` (States and Sensors section).

**Verify:**
- `sensor.pergola_max_open_east_morning_cooling_angle`: raw MaxOpenEast — rises from ~28° at A_eff=0° toward max_tilt at the flip point; slat target in the formula is this value + 5° (SAFETY_BUFFER), floored at 90°
- `sensor.pergola_max_open_west_cooling_angle`: raw MaxOpenWest — ≈ 15.3° at the flip point, ≈ 31.7° at A_eff=90°, ≈ 76° at A_eff=120°, ≈ 93.8° at A_eff=130° (raw); morning branch uses it directly; afternoon branch applies `min(90, …)` inline → 90° for A_eff > ~128°
- Toggle `pergola_cooling_optimized` off → standard perpendicular formula, `sensor.pergola_slat_angle` unchanged
- Toggle on, morning A_eff = 20°: slat = max(90, ~37.7+5) = 90° (floored at vertical; standard would be 110°)
- Toggle on, flip zone A_eff = 80°: slat ≈ 23.7° (MaxOpenWestMorning = raw sensor; standard gives ~15.3°)
- Toggle on, afternoon A_eff = 100°: slat ≈ 43.6° (min(90, raw sensor) = 43.6°; standard gives 10°)
- Toggle on, afternoon A_eff = 140°: slat = 90° (min(90, raw ~110°) = 90°; standard gives 50°)

---

### Phase 5 — Calibration & Validation

#### Step 6 — Field Testing & Threshold Tuning [TODO]
**Dependencies:** Steps 1–4 deployed and running for at least one sunny + one rainy day.

| Item | Action |
|---|---|
| PV conversion factor | Clear morning: adjust `pergola_pv_conversion_factor` until `PV power / factor ≈ solar_radiation` |
| Clearness factor (0.9) | Partly cloudy afternoon: check `pergola_sun_shining` on/off boundary feels correct |
| Sun azimuth window | Observe shadows — fine-tune `input_number.pergola_wall_azimuth` if needed; AZIMUTH_MIN/MAX re-derive automatically |
| Post-rain tilt values | Confirm 25%/50% drains adequately; adjust in script if not |
| Rain lock originator | Log `sensor.dach_links_priority_lock_originator` during rain; verify covers can move after rain stops |

---

## Remaining TBD Items

| # | Item | Blocking |
|---|---|---|
| 1c | PV conversion factor (default 3.2) | Can be refined in Step 6 field testing (Phase 5) |
| 5 | Post-rain slat angles (8°, 15°) | Confirm drainage adequate after first real rain |
| 8 | Optimized cooling formula (safe-zone max-open) | Formula defined — `MaxOpenWest` (= Sbackside, `A_eff + PHI − asin(...)`) for flip range; `MaxOpenEast` as back-face target for morning. See Step 7. |
| 9 | ~~The histeresis of actually moving the slats needs diff actual slat position with the target position~~ | ~~phase 2~~ |
| 10 | the cooling morning in optimized state needs to be max open but safe. max open is 90 deg. so this position would be max (90, max_open_east - safty) as long as its less than max titlt | phase 4 |
| 11 | the cooling lower bound needs to change to be dynamic. on the flip over we use maxopenwest which is actually a max open west morning. In the afternoon we need a max open west afternoon. That mirrors what have in the morning but for sun on the west. It should also have max open as its target, so it never opens to more than 90 | phase |
| 12 | ~~in the no sun shining state we want to only move the slats when the current slat angle is more than 30 degrees away from max open (90). this is to avoid unnecessary movement~~ | ~~phase 2~~ | 
