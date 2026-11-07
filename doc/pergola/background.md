Background only: not design-relevant; current design is design.md.

# Pergola: background

History, derivation work and superseded designs for `packages/pergola.yaml`. Never cite this file
as current behaviour; the current design is `doc/pergola/design.md`, current package facts are in
`packages/notes/pergola.md`. IDs `PG-B<n>` are stable. Text below PG-B2 is kept as written at the
time and contains values that were later corrected (PG-B2 lists them).

## PG-B1 Sources and references

Raw material, never edited, guarded (`doc/sources/pergola/`):
- `gemini-conversation-slat-formulas.md`: the original Gemini conversation on slat formulas.
- `terrace-roof-tilt.xlsx` (was `doc/terrace roof titl.xlsx`): spreadsheet with sample
  calculations (columns C, D, H and cells L7/L8 are referenced in PG-B4).

Outside the repo (read only after asking the user):
- Loxone config file: `C:\Users\mikop\Documents\Loxone\Loxone Config\Projects\Haus.Loxone`
- Loxone config documentation: https://www.loxone.com/enen/kb-cat/loxone-config/

## PG-B2 Facts corrected when the design doc was rebuilt (2026-11-07)

The old docs (`doc/pergola-roof-automation.md`, `doc/pergola-slat-formula-analysis.md`) had
drifted from the YAML. The YAML won; the corrected facts are in design.md.

| Old doc said | YAML / design now |
|---|---|
| tilt correction +7 below 20° | 6 (`sensor.pergola_tilt_position`, `script.pergola_set_slat_angle`) |
| 8 states | 9: `sun_down` added (PV = 0 and solar radiation = 0), rule 5 before `no_sun_behind_house` |
| optimized flip range "MaxOpenWest, no buffer"; afternoon `min(90, mow)` | `mow − 5`; `min(mow − 5, 90)` |
| optimized morning `max(90, moe + SAFETY_BUFFER)`, guard `moe < max_tilt − 5` | `moe + DB` and guard `moe ≤ max_tilt − DB` (DB = `input_number.pergola_deadband_angle`) |
| fixed 5° deadband, `DEADBAND_TILT` derived constant, only `cover.dach_links` compared | helper deadband; max deviation of both covers; `target ≥ 100` always passes |
| post-rain drain "25 %/50 %" (Step 4 TBD, Step 6 table) | 8° / 15°; the 8° step only when hourly rain > 0 |
| flip point A_eff ≈ 58°, LB 15.3° | `a_flip` = 57 (largest safe integer), LB rounded to 15° |
| heating floor `input_number.pergola_min_heating_slat_angle` (16°, from tilt 20) | `sensor.pergola_min_heating_slat_angle`, gap formula, ≈ 33.5° |
| `input_number.pergola_clearness_factor` | `input_number.pergola_shading_sensitivity` |
| PV source `sensor.victron_solar_yield` | `sensor.victron_solar_yield_dc_watts` via `sensor.pergola_pv_power` |
| no-sun states both check the deadband | `no_sun_behind_house` always sends 90°; `not_enough_sun` uses a 30° deadband |
| verification-table moe values (e.g. 37.7° at A_eff 20°, A_eff 55° at az 165°/el 50°) | recomputed: 46.9°, A_eff 62.2° (design PG-4.8) |
| title "Implementation Plan" | design doc |

## PG-B3 Device linking: verified to fail

Phase 1 (PG-B6, Step 1) planned to link every template entity to the existing cover device with
`device_id:` and to add template wrappers (`template switch` / `number` / read-only `sensor`) for
each `input_*` helper so they would show on the device card. Both failed:

> **`device_id:` is NOT supported in template YAML**, and template entities also cannot be assigned
> to a device via the HA entity editor UI — both have been verified to fail.
> **No template wrappers.** `input_*` helpers (`input_boolean`, `input_number`, `input_select`)
> are used directly. Wrappers served no purpose.

The replacement is `group.pergola_dach` plus `dashboards/elements/pergola_card.yaml` (rules in the
note). The old group listing in the design doc also still held `pergola_min_heating_slat_angle`
as an `input_number`.

## PG-B4 Formula derivations (from the slat formula analysis §2-4)

### 2. Core Formulas

All formulas use:
- **azimuth** = `state_attr('sun.sun', 'azimuth')` (compass bearing 0-360°)
- **elevation** = `state_attr('sun.sun', 'elevation')` (degrees above horizon)
- **terrasse_azimuth** = 204° (constant)
- **delta_phi** = azimuth - terrasse_azimuth (relative azimuth)

#### 2.1 Effective Sun Angle ($A_{eff}$)

The sun's effective position projected onto the plane perpendicular to the slat axis, mapped to a 0°–180° east-to-west scale.

**Step 1 — Effective Sun Height** (always 0°–90°, unsigned projected elevation):
```
sun_height = degrees(atan(tan(radians(elevation)) / abs(sin(radians(delta_phi)))))
```

Guards:
- `elevation <= 0`: sun below horizon — formula should not be called (state machine handles this)
- `|sin(radians(delta_phi))| < 0.001`: singularity when sun is along slat axis (azimuth ≈ 204°) → `sun_height = 90°` (correct mathematical limit)

**Step 2 — Map to 0°–180° east-to-west:**
```
A_eff = sun_height          if azimuth < 204    (morning — sun east of terrasse)
A_eff = 180 - sun_height    if azimuth >= 204   (afternoon — sun west of terrasse)
```

Properties:
- When delta_phi = 0 (sun along slat axis): `A_eff = 90°` (zenith — from both branches)
- When delta_phi = ±90° (sun fully perpendicular to slat axis): `sun_height = elevation`, so `A_eff = elevation` (morning) or `A_eff = 180° − elevation` (afternoon)
- Range: 0° (east horizon) → 90° (zenith) → 180° (west horizon)

**Note on spreadsheet column C:** The spreadsheet implements the older signed formula `atan(tan(elev) / sin(delta_phi))`, which equals `±sun_height`. The new formula is equivalent in magnitude but always positive, with east/west disambiguation via the morning/afternoon branch instead of the sign of `sin(delta_phi)`.

#### 2.2 Blocking Angle

The slat angle that places the slat surface perpendicular to the incoming sun rays — the ideal blocking angle for cooling mode.

In the unified coordinate system this is derived directly from $A_{eff}$:

```
blocking_angle = A_eff - 90
```

Range: −90° (east horizon) → 0° (zenith) → +90° (west horizon).

- **Positive values:** sun from west (A_eff > 90°) → direct front-face blocking
- **Negative values:** sun from east (A_eff < 90°) → back-face blocking needed (hardware cannot tilt negative)
- When A_eff = 90° (sun at zenith): `blocking_angle = 0°` (flat blocks overhead sun perfectly)

**Geometric relationship:** `blocking_angle + sun_height = 90°` (complementary angles of the same right triangle — the geometry is unchanged from the original analysis, only the coordinate expression differs).

**Spreadsheet column D** computes `atan(sin(delta_phi) / tan(elevation))` which equals `blocking_angle` — the values are identical. Verified correct.

**Loxone formula** (historical reference): `DEG(ARCTAN(SIN(RAD(I2-I3))/TAN(RAD(I1))))` — computes `blocking_angle` directly, where I2-I3 = delta_phi, I1 = elevation.

#### 2.3 Mapping to Pergola Hardware

The hardware only rotates in one direction (0°–122°). The $A_{eff}$-based mapping uses a morning/afternoon split governed by `MaxOpenEastMorningCoolingAngle` (see Section 3):

```
COOLING_LB    = 15°    # ventilation floor — = MaxOpenWest at flip point (A_eff=58°) = 15.3° → 15°
max_tilt      = 122°   # hardware maximum

Morning (MaxOpenEast <= max_tilt - 5°) — back-face blocking:
  if A_eff + 90 <= max_tilt:   slat_angle = A_eff + 90    # achievable: 90°–122°
  else:                         slat_angle = max_tilt       # dead zone fallback (122°), still in safe zone

Afternoon / past safe limit — direct front-face blocking:
  slat_angle = max(A_eff - 90, COOLING_LB)                 # 0°–90°, floor at 15°
```

**Morning dead zone (A_eff ~32°–58°):** `A_eff + 90` exceeds 122° — mechanically unreachable. The hardware falls back to 122° (max tilt). This is safe because `MaxOpenEastMorningCoolingAngle` (see Section 3) remains below 117° throughout this range, confirming 122° is still inside the shade safe zone.

**Dynamic morning limit:** The flip from back-face to front-face blocking is governed by `MaxOpenEast > max_tilt - 5°`. At A_eff ≈ 58° (for max_tilt = 122°), back-face blocking can no longer guarantee full shade, and the formula flips to closing/flat (COOLING_LB = 15°).

**Spreadsheet column H** (`IF(D <= -58, D + 180, IF(D >= 0, D, -1))`) implements the equivalent logic using the old signed `blocking_angle` (column D). In the new coordinate: `blocking_angle <= -58°` ↔ `A_eff ≤ 32°` (reachable morning back-face); `blocking_angle >= 0°` ↔ `A_eff >= 90°` (afternoon direct); `-1` ↔ dead zone (32° < A_eff < 90°, back-face unreachable).

---

### 3. Cooling Mode Formula (Block Sun)

**Goal:** Block direct sunlight by tilting slats perpendicular to sun rays.

#### Standard formula (with dynamic morning limit via MaxOpenEast)

```
COOLING_LB      = 15°                           # ventilation floor — = MaxOpenWest at flip point
                                                #   MaxOpenWest(58°) = 58 + 8.53 − asin(R×sin58°) = 15.3° → 15°
SAFETY_BUFFER   = 5°                            # flip margin below max_tilt
R               = 0.91926                       # deff / w = sqrt(d² + t²) / w
                                                #   slat geometry: w=22cm, d=20cm (pivot spacing), t=3cm (thickness)
                                                #   deff = sqrt(20² + 3²) = 20.22cm → R = 20.22 / 22 = 0.91926
PHI             = 8.53°                         # arctan(t / d) = arctan(3 / 20)
                                                #   internal angle from slat thickness relative to pivot spacing

# MaxOpenEastMorningCoolingAngle: minimum back-face slat angle for 100% shade from east.
# Derivation: Sperp - W = (A_eff + 90) - (90 - PHI - asin(R × sin(A_eff)))
MaxOpenEast = A_eff + PHI + degrees(asin(R × sin(radians(A_eff))))

if A_eff < 90 and MaxOpenEast <= max_tilt - SAFETY_BUFFER:
                                                # Morning — back-face blocking (safe)
    if A_eff + 90 <= max_tilt:
        slat_angle = A_eff + 90                 # back face perpendicular to east sun
    else:
        slat_angle = max_tilt                   # dead zone: best available (122°), still in safe zone
else:                                           # Afternoon, or morning past safe limit
    slat_angle = max(A_eff - 90, COOLING_LB)

clamp slat_angle to [COOLING_LB, max_tilt]
```

**Dynamic morning limit:** The `MaxOpenEast` check ensures we only use back-face blocking while it can geometrically provide full shade. At $A_{eff}$ ≈ 58° (for max_tilt = 122°), `MaxOpenEast` exceeds 117° (= max_tilt − 5) and the formula flips to front-face/closing.

Cooling lower bound (15°): When A_eff ≈ 90° (sun nearly overhead), `A_eff − 90 ≈ 0°` (flat). The 15° floor prevents full closure for ventilation. Derived from `MaxOpenWest` at the flip point: `MaxOpenWest(58°) = 58 + PHI − asin(R·sin58°) = 15.3°` → rounded down to 15°. At 15°, `e_crit = 50.6°` — summer noon elevation (~65°) still exceeds this, so full shade is maintained.

#### Enhanced version (with slat thickness / safe zone — from Gemini conversation)

The slat thickness and overlap create a "safe zone" — a range of angles that all provide 100% shade. Instead of the exact perpendicular angle, the **maximum open angle** (edge of safe zone closest to vertical) can be used to maximise airflow while maintaining full shade.

The safe-zone formulas use `sun_height` (the unsigned projected elevation = `A_eff` for morning, `180° − A_eff` for afternoon):

**Max Open toward sun:**
```
Stoward = sun_height + phi - 180 + degrees(asin(R * sin(radians(sun_height))))
```

**Max Open away from sun ("Backside Block" = MaxOpenWestMorningCoolingAngle):**
```
Sbackside = sun_height + phi - degrees(asin(R * sin(radians(sun_height))))
```

For morning (A_eff ≤ 90, sun_height = A_eff), this is also written as:
```
# MaxOpenWestMorningCoolingAngle: maximum WEST-leaning (front-face) slat angle
# for 100% shade from east / high-noon sun (A_eff ≤ 90).
# Blocking condition (derived): sin(A_eff − θ + PHI) = R × sin(A_eff)  → solve for max θ
# NOTE: sign is +PHI (NOT −PHI).  A_eff − PHI − asin(...) is WRONG (gives negative values at flip).
MaxOpenWest = A_eff + PHI − degrees(asin(R × sin(radians(A_eff))))   [A_eff ≤ 90 only]
```

Where R = 0.91926, phi = 8.53°.

**Safe Zone width at various sun positions (d=20, w=22, t=3):**

| $A_{eff}$ (morning) | sun_height | Ideal slat ($A_{eff}$+90) | MaxOpenWest (=Sbackside) | Safe Zone Width |
|---|---|---|---|---|
| 10° | 10° | 100° | 9.3° | 161.6° |
| 20° | 20° | 110° | 10.2° | 143.4° |
| 30° | 30° | 120° | 11.2° | 125.3° |
| 40° | 40° | 130° → dead zone | 12.3° | 107.6° |
| 50° | 50° | 140° → dead zone | 13.8° | 90.5° |
| 58° | 58° | 148° → dead zone | **15.3°** (= COOLING_LB) | — |
| 60° | 60° | 150° → dead zone | 15.8° | 74.5° |
| 70° | 70° | 160° → dead zone | 18.8° | 60.5° |
| 80° | 80° | 170° → dead zone | 23.7° | — |
| 90° | 90° | 180° → dead zone | 31.7° | — |

> Note: For morning rows where the ideal slat exceeds 122° (dead zone), the standard formula uses 122° **only while `MaxOpenEast ≤ max_tilt - 5`** (A_eff up to ~58°). Beyond that, the formula flips to front-face/closing. `MaxOpenWest` is the maximum open angle that still guarantees full shade — it serves as: (1) the static COOLING_LB = 15° (evaluated at the flip point A_eff = 58°) for the standard formula; and (2) the dynamic target angle in the `pergola_cooling_optimized` mode (Step 7).

**MaxOpenEastMorningCoolingAngle** at key dead-zone boundaries:

| $A_{eff}$ | MaxOpenEast | vs max_tilt (122°) | Status |
|---|---|---|---|
| 40° | 89.5° | 32.5° margin | Safe — back-face at 122° works |
| 50° | 103.3° | 18.7° margin | Safe |
| 55° | 112.4° | 9.6° margin | Safe |
| 58° | 117.7° | 4.3° margin | **FLIP** — exceeds 117° threshold |
| 60° | 121.3° | 0.7° margin | Would fail without the fix |

#### Recommended Cooling Strategy

For the HA automation, use the **standard formula with dynamic morning limit** above. Reasons:
1. The perpendicular angle sits safely inside the safe zone for all sun positions where back-face blocking is feasible
2. The `MaxOpenEast` check dynamically detects when back-face blocking fails and flips to closing
3. It provides the thickest shadow (maximum margin of error) within the safe morning range
4. The safe zone optimisation (minimal motor movement) is a future enhancement for Step 7 — it changes the target angle within the safe zone, not the flip logic

The safe zone data is documented here for future optimisation (Step 7) if desired.

---

### 4. Heating Mode Formula (Let Sun Through)

**Goal:** Tilt slats parallel to sun rays so sunlight passes between them.

#### Derivation

In the unified coordinate, $A_{eff}$ and the slat angle share the same number line. For heating, the slat should be **parallel** to the sun rays — which means the slat angle directly equals $A_{eff}$:

```
slat_angle = A_eff
```

**Why this works geometrically:** The heating slat angle is `blocking_angle − 90 = A_eff − 180`. This is always ≤ 0°, so the hardware back-face mapping (`+180`) always applies: `(A_eff − 180) + 180 = A_eff`. The old three-branch logic (threshold / direct / dead zone) collapses to a single check against `max_tilt`.

#### Hardware mapping

```
if A_eff <= max_tilt (122°):
    slat_angle = A_eff              # direct — covers all east, noon, south, slight west
else:
    tilt_position = 100             # dead zone: A_eff > 122° (moderate-to-far west)
                                    # max tilt is best available; skip hardware correction

clamp slat_angle to [0°, max_tilt]
```

Dead zone explanation: When `A_eff > 122°` (sun from moderate-to-far west), slats are tilted to 122° (past vertical). The back face angles toward the incoming west sun, opening the maximum gap. No other position transmits more west light.

#### Verification

| Azimuth | Elev | $A_{eff}$ | slat_angle | Physical interpretation |
|---|---|---|---|---|
| 115° | 20° | 20.0° | 20.0° (= $A_{eff}$) | Low east sun — slat near flat, light enters between open slats |
| 150° | 30° | 35.5° | 35.5° (= $A_{eff}$) | Moderate east |
| 180° | 40° | 64.1° | 64.1° (= $A_{eff}$) | South, lower elevation |
| 204° | 57° | 90.0° | 90.0° (= $A_{eff}$) | Sun along slat axis → vertical |
| 220° | 45° | 105.4° | 105.4° (= $A_{eff}$) | Slight west → past vertical, back face angled toward sun |
| 240° | 40° | 125.0° | tilt = 100 (DZ) | West — dead zone, max tilt |
| 260° | 30° | 145.1° | tilt = 100 (DZ) | Far west — dead zone, max tilt |

All values matched the old verification table (PG-B6).

---

## PG-B5 Gemini analysis: correctness assessment (slat formula analysis §5)

#### What Gemini got right
1. **Core sun projection formula** — the effective sun angle and perpendicular angle formulas are geometrically correct and match the spreadsheet
2. **Safe zone concept** — the idea that slat overlap creates a range of valid blocking angles is sound physics
3. **Slat thickness correction** — the deff and phi constants correctly account for 3 cm slat thickness in the safe zone calculation
4. **The reciprocal relationship** between "where is the sun" (A_EFF) and "where should the slat be" (perfect_angle) is correctly explained as complementary angles (sum = 90°)

#### What Gemini got wrong or confused
1. **Coordinate system confusion** — Gemini repeatedly mixed up the coordinate system despite corrections. The conversation went through at least 4 coordinate system changes, leading to sign errors in intermediate steps
2. **Dead zone handling** — Gemini initially provided the "conservative" (closer to flat) edge of the safe zone instead of the "max open" edge, then corrected after user pushback
3. **Direction labeling** — Gemini swapped east/west directions multiple times until the user explicitly locked them down
4. **Formula 5 (backside block)** — this is mathematically correct but the initial table values were wrong (using wrong edge of safe zone). Corrected in the final summary

#### What's missing from Gemini's analysis
1. **Heating mode** — the entire conversation focused on blocking sun (cooling). No formula for letting sun through was discussed
2. **Integration with HA** — no Jinja2 templates or HA-specific implementation
3. **The -58° threshold derivation** — Gemini didn't explicitly connect the dead zone to the hardware max tilt angle (122° - 180° = -58°)

## PG-B6 Tilt calculation as first written (old design doc, Steps 1-3)

#### Step 1 — Desired slat angle

##### Cooling season (`sun_automatik_cooling`) — block sun

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

**Dynamic morning limit:** The transition from morning (back-face) to afternoon (front-face/closing) formula is governed by `MaxOpenEastMorningCoolingAngle` — the minimum slat angle that still provides 100% shade from eastern sun (see PG-B4 §3). When `MaxOpenEast > max_tilt - 5°` (at $A_{eff}$ ≈ 58° for max_tilt = 122°), the back-face strategy can no longer guarantee full shade, and the formula flips to the closing/flat strategy (`A_eff - 90`, floored at `COOLING_LOWER_BOUND`). The 5° buffer ensures the flip happens ~2 update cycles before shade loss would begin.

> Formula derivation and numerical anchor points: see PG-B4 §3. If `input_boolean.pergola_cooling_optimized` is `on`, a different formula is used instead (see Step 7) — the `MaxOpenEast` flip logic applies to both modes.

**Cooling lower bound:** When the formula flips at $A_{eff}$ ≈ 58° (sun nearly overhead or approaching from high east), $A_{eff}$ − 90 is still negative and the floor governs. The floor is `COOLING_LOWER_BOUND = sensor.pergola_cooling_lower_bound` — derived at runtime as `MaxOpenWest(A_eff_flip)` where `A_eff_flip` is the largest A_eff where `MaxOpenEast ≤ max_tilt − SAFETY_BUFFER` (see Derived Internal Constants above). Default ≈15.3° (w=22, d=20, t=3, max_tilt=122). At 15°, `e_crit ≈ 50.6°` — summer noon (≈65°) still gives complete shade while allowing more airflow than the former 11° floor. For the dynamic floor used in optimized cooling, see Step 7.

##### Heating season (`sun_automatik_heating`) — let sun through

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

##### Verification table

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

##### No sun (`no_sun_behind_house`, `not_enough_sun`)
```
slat_angle = 90       # vertical open position
tilt_position = INT(90 / max_tilt × 100 + 0.5)   # correction = 0.5 (90° ≥ 69°); default max_tilt=122 → 74
```
> **Implementation:** this is algorithm pseudocode only. In code, pass `slat_angle: 90` to `script.pergola_set_slat_angle` — the formula above runs inside that script, not inline.

##### Rain / Frost
No cover movement.

---

#### Step 2 — Convert slat_angle to tilt_position

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

#### Step 3 — Movement Deadband (5° hysteresis)

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

## PG-B7 Implementation step log, Phases 1-4 [all DONE]

Each step is independently deployable via `git pull` on the HA host.

---

#### Phase 1 — Foundation

##### Step 1 — Helpers, Template Sensors, Device Linking [DONE]
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

##### Step 2 — State Manager Automation [DONE]
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

#### Phase 2 — Cover Control

##### Step 3 — Cover Response Automation (no-sun + cooling) [DONE]
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

##### Step 4 — Post-Rain Recovery Script [DONE]
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

#### Phase 3 — Heating Season

##### Step 5 — Heating Season Logic [DONE]
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

#### Phase 4 — Optimized Cooling

##### Step 7 — Optimized Cooling Angle [DONE]
**File:** `packages/pergola.yaml` — add two readonly sensors; update `sensor.pergola_slat_angle` formula

Gated by `input_boolean.pergola_cooling_optimized`. When `on`, replace the perfect-perpendicular cooling formula with one that uses the **safe-zone max-open angle** — the furthest the slats can tilt toward vertical while still guaranteeing 100% shade (leveraging slat overlap/thickness).

**Key concept:** Due to the slat geometry (w=`pergola_slat_width`, t=`pergola_slat_thickness`, d=`pergola_slat_pivot_spacing`; R and PHI derived from these — see Derived Internal Constants), the slats overlap. There is a range of angles (the "safe zone") that all provide full shade. The max-open formula targets the far edge of this zone to maximize airflow. Both `MaxOpenEastMorningCoolingAngle` (morning, back-face) and `MaxOpenWestMorningCoolingAngle` (flip range, front-face) are exposed as readonly sensors and used as targets instead of the perfect-perpendicular angles.

**Formulas (see PG-B4 §3):**

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

## PG-B8 Closed TBD items

| # | Item | Blocking |
|---|---|---|
| 1c | PV conversion factor (default 3.2) | Can be refined in Step 6 field testing (Phase 5) |
| 5 | Post-rain slat angles (8°, 15°) | Confirm drainage adequate after first real rain |
| 8 | Optimized cooling formula (safe-zone max-open) | Formula defined — `MaxOpenWest` (= Sbackside, `A_eff + PHI − asin(...)`) for flip range; `MaxOpenEast` as back-face target for morning. See Step 7. |
| 9 | ~~The histeresis of actually moving the slats needs diff actual slat position with the target position~~ | ~~phase 2~~ |
| 10 | the cooling morning in optimized state needs to be max open but safe. max open is 90 deg. so this position would be max (90, max_open_east - safty) as long as its less than max titlt | phase 4 |
| 11 | the cooling lower bound needs to change to be dynamic. on the flip over we use maxopenwest which is actually a max open west morning. In the afternoon we need a max open west afternoon. That mirrors what have in the morning but for sun on the west. It should also have max open as its target, so it never opens to more than 90 | phase |
| 12 | ~~in the no sun shining state we want to only move the slats when the current slat angle is more than 30 degrees away from max open (90). this is to avoid unnecessary movement~~ | ~~phase 2~~ |
