# Pergola Slat Angle Formula Analysis

> Referenced by: [pergola-roof-automation.md](pergola-roof-automation.md)
> Sources: [terrace roof titl.xlsx](terrace%20roof%20titl.xlsx), [Gemini conversation](gemini-conversation-slat-formulas.md)

---

## 1. Physical Setup

### Pergola Geometry
- **Terrasse faces:** 204° azimuth (SSW)
- **Slat rotation axis:** runs along 204°/24° (parallel to terrasse face)
- **Effective cross-section plane:** perpendicular to the slat axis, at 114°/294°
- **Sun hits terrasse when:** 114° <= azimuth <= 294°

### Slat Dimensions (from spreadsheet L7/L8)
- **Slat width (w):** 22 cm *(usable blocking width: 20 cm)*
- **Slat thickness (t):** 3 cm
- **Pivot spacing (d):** 20 cm *(center-to-center between adjacent slats)*
- **Effective diagonal (deff):** sqrt(20² + 3²) = 20.22 cm
- **Effective slat ratio (R):** deff / w = sqrt(20² + 3²) / 22 = **0.91926**
- **Thickness offset (phi):** arctan(3/20) = **8.53°**

### Unified Coordinate System

Both sun position and slat angles use the same 0°–180° number line:

**Effective Sun Angle ($A_{eff}$):**
```
0°  (East Horizon)  ──►  90°  (Zenith/Noon)  ──►  180°  (West Horizon)
```

**Slat Angle (hardware, 0°–122°):**
```
0°  (Flat/closed)  ──►  90°  (Vertical/open)  ──►  122°  (Max, back face)  ···►  180°  (unreachable)
```

- **0°** = flat / horizontal (fully closed, rain protection)
- **90°** = vertical (slats perpendicular to ground, fully open)
- **122°** = maximum tilt (32° past vertical; back face blocks eastern sun) — configurable via `input_number.pergola_max_tilt_angle`
- **Dead zone:** 122.1°–180° is mechanically unreachable

**Key insight:** In heating mode, `slat_angle = A_eff` — the slat directly tracks the sun's effective position on the shared number line. In cooling mode, `slat_angle = A_eff ± 90°` (perpendicular offset).

---

## 2. Core Formulas

All formulas use:
- **azimuth** = `state_attr('sun.sun', 'azimuth')` (compass bearing 0-360°)
- **elevation** = `state_attr('sun.sun', 'elevation')` (degrees above horizon)
- **terrasse_azimuth** = 204° (constant)
- **delta_phi** = azimuth - terrasse_azimuth (relative azimuth)

### 2.1 Effective Sun Angle ($A_{eff}$)

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

### 2.2 Blocking Angle

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

### 2.3 Mapping to Pergola Hardware

The hardware only rotates in one direction (0°–122°). The $A_{eff}$-based mapping uses a morning/afternoon split:

```
MORNING_LIMIT = 85°    # early flip to afternoon formula; gives ~2 update cycles of
                       # lead time before geometric noon crossing at A_eff = 90°
COOLING_LB    = 11°    # ventilation floor (tilt_position ≈ 16)
max_tilt      = 122°   # hardware maximum

Morning (A_eff < 85°) — back-face blocking:
  if A_eff + 90 <= max_tilt:   slat_angle = A_eff + 90    # achievable: 90°–122°
  else:                         slat_angle = max_tilt       # dead zone fallback (122°)

Afternoon (A_eff >= 85°) — direct front-face blocking:
  slat_angle = max(A_eff - 90, COOLING_LB)                 # 0°–90°, floor at 11°
```

**Morning dead zone:** When A_eff is between ~32° and 85°, `A_eff + 90` exceeds 122°. The hardware falls back to 122° (max tilt, back-face position), which geometry confirms provides complete shade for all sun elevations > 10°.

**Why 85° (not 90°):** The sun moves ~1–1.5°/5 min at the noon crossing. Switching 5° early ensures the slats move to afternoon direct-blocking before the geometric crossing at A_eff = 90°, preventing any unblocked gap during the transition.

**Spreadsheet column H** (`IF(D <= -58, D + 180, IF(D >= 0, D, -1))`) implements the equivalent logic using the old signed `blocking_angle` (column D). In the new coordinate: `blocking_angle <= -58°` ↔ `A_eff ≤ 32°` (reachable morning back-face); `blocking_angle >= 0°` ↔ `A_eff >= 90°` (afternoon direct); `-1` ↔ dead zone (32° < A_eff < 90°, back-face unreachable).

---

## 3. Cooling Mode Formula (Block Sun)

**Goal:** Block direct sunlight by tilting slats perpendicular to sun rays.

### Standard formula (no slat thickness correction)

```
MORNING_LIMIT = 85°
COOLING_LB    = 11°    # ventilation floor (tilt_position ≈ 16)

if A_eff < MORNING_LIMIT:                       # Morning — back-face blocking
    if A_eff + 90 <= max_tilt:
        slat_angle = A_eff + 90                 # back face perpendicular to east sun
    else:
        slat_angle = max_tilt                   # dead zone: best available (122°)
else:                                           # Afternoon — direct front-face blocking
    slat_angle = max(A_eff - 90, COOLING_LB)

clamp slat_angle to [COOLING_LB, max_tilt]
```

Cooling lower bound (11°): When A_eff ≈ 90° (sun nearly overhead), `A_eff − 90 ≈ 0°` (flat). The 11° floor prevents full closure for ventilation. At 11°, `e_crit ≈ 48.3°` — summer noon elevation (~65°) exceeds this, so full shade is maintained.

### Enhanced version (with slat thickness / safe zone — from Gemini conversation)

The slat thickness and overlap create a "safe zone" — a range of angles that all provide 100% shade. Instead of the exact perpendicular angle, the **maximum open angle** (edge of safe zone closest to vertical) can be used to maximise airflow while maintaining full shade.

The safe-zone formulas use `sun_height` (the unsigned projected elevation = `A_eff` for morning, `180° − A_eff` for afternoon):

**Max Open toward sun:**
```
Stoward = sun_height + phi - 180 + degrees(asin(R * sin(radians(sun_height))))
```

**Max Open away from sun ("Backside Block"):**
```
Sbackside = sun_height + phi - degrees(asin(R * sin(radians(sun_height))))
```

Where R = 0.91926, phi = 8.53°.

**Safe Zone width at various sun positions (d=20, w=22, t=3):**

| $A_{eff}$ (morning) | sun_height | Ideal slat ($A_{eff}$+90) | Sbackside | Safe Zone Width |
|---|---|---|---|---|
| 10° | 10° | 100° | +9.3° | 161.6° |
| 20° | 20° | 110° | +10.2° | 143.4° |
| 30° | 30° | 120° | +11.2° | 125.3° |
| 40° | 40° | 130° → dead zone | +12.3° | 107.6° |
| 50° | 50° | 140° → dead zone | +13.8° | 90.5° |
| 60° | 60° | 150° → dead zone | +15.8° | 74.5° |
| 70° | 70° | 160° → dead zone | +18.8° | 60.5° |

> Note: For morning rows where the ideal slat exceeds 122° (dead zone), the standard formula uses 122°. The `Sbackside` column shows the alternative west-tilt angle that still achieves full shade via slat overlap — this is the basis for the `pergola_cooling_optimized` mode (Step 7).

### Recommended Cooling Strategy

For the HA automation, use the **standard formula** above. Reasons:
1. The perpendicular angle sits safely inside the safe zone for all sun positions
2. It provides the thickest shadow (maximum margin of error)
3. It's simpler to implement and debug
4. The safe zone optimisation (minimal motor movement) is a future enhancement — the motor moves at most every 5 minutes anyway

The safe zone data is documented here for future optimisation (Step 7) if desired.

---

## 4. Heating Mode Formula (Let Sun Through)

**Goal:** Tilt slats parallel to sun rays so sunlight passes between them.

### Derivation

In the unified coordinate, $A_{eff}$ and the slat angle share the same number line. For heating, the slat should be **parallel** to the sun rays — which means the slat angle directly equals $A_{eff}$:

```
slat_angle = A_eff
```

**Why this works geometrically:** The heating slat angle is `blocking_angle − 90 = A_eff − 180`. This is always ≤ 0°, so the hardware back-face mapping (`+180`) always applies: `(A_eff − 180) + 180 = A_eff`. The old three-branch logic (threshold / direct / dead zone) collapses to a single check against `max_tilt`.

### Hardware mapping

```
if A_eff <= max_tilt (122°):
    slat_angle = A_eff              # direct — covers all east, noon, south, slight west
else:
    tilt_position = 100             # dead zone: A_eff > 122° (moderate-to-far west)
                                    # max tilt is best available; skip hardware correction

clamp slat_angle to [0°, max_tilt]
```

Dead zone explanation: When `A_eff > 122°` (sun from moderate-to-far west), slats are tilted to 122° (past vertical). The back face angles toward the incoming west sun, opening the maximum gap. No other position transmits more west light.

### Verification

| Azimuth | Elev | $A_{eff}$ | slat_angle | Physical interpretation |
|---|---|---|---|---|
| 115° | 20° | 20.0° | 20.0° (= $A_{eff}$) | Low east sun — slat near flat, light enters between open slats |
| 150° | 30° | 35.5° | 35.5° (= $A_{eff}$) | Moderate east |
| 180° | 40° | 64.1° | 64.1° (= $A_{eff}$) | South, lower elevation |
| 204° | 57° | 90.0° | 90.0° (= $A_{eff}$) | Sun along slat axis → vertical |
| 220° | 45° | 105.4° | 105.4° (= $A_{eff}$) | Slight west → past vertical, back face angled toward sun |
| 240° | 40° | 125.0° | tilt = 100 (DZ) | West — dead zone, max tilt |
| 260° | 30° | 145.1° | tilt = 100 (DZ) | Far west — dead zone, max tilt |

All values match the verification table in `pergola-roof-automation.md`.

---

## 5. Gemini Analysis — Correctness Assessment

### What Gemini got right
1. **Core sun projection formula** — the effective sun angle and perpendicular angle formulas are geometrically correct and match the spreadsheet
2. **Safe zone concept** — the idea that slat overlap creates a range of valid blocking angles is sound physics
3. **Slat thickness correction** — the deff and phi constants correctly account for 3 cm slat thickness in the safe zone calculation
4. **The reciprocal relationship** between "where is the sun" (A_EFF) and "where should the slat be" (perfect_angle) is correctly explained as complementary angles (sum = 90°)

### What Gemini got wrong or confused
1. **Coordinate system confusion** — Gemini repeatedly mixed up the coordinate system despite corrections. The conversation went through at least 4 coordinate system changes, leading to sign errors in intermediate steps
2. **Dead zone handling** — Gemini initially provided the "conservative" (closer to flat) edge of the safe zone instead of the "max open" edge, then corrected after user pushback
3. **Direction labeling** — Gemini swapped east/west directions multiple times until the user explicitly locked them down
4. **Formula 5 (backside block)** — this is mathematically correct but the initial table values were wrong (using wrong edge of safe zone). Corrected in the final summary

### What's missing from Gemini's analysis
1. **Heating mode** — the entire conversation focused on blocking sun (cooling). No formula for letting sun through was discussed
2. **Integration with HA** — no Jinja2 templates or HA-specific implementation
3. **The -58° threshold derivation** — Gemini didn't explicitly connect the dead zone to the hardware max tilt angle (122° - 180° = -58°)

---

## 6. Summary: Formulas for HA Implementation

### Step 0 — Effective Sun Angle ($A_{eff}$)
```
delta_phi     = azimuth - 204
elevation_rad = radians(elevation)
max_tilt      = 122  (from input_number.pergola_max_tilt_angle)

# Guard: sun below horizon — state machine handles this before reaching formula
if elevation <= 0: return

# Singularity guard: sun along slat axis (azimuth ≈ 204°)
if |sin(radians(delta_phi))| < 0.001:
    sun_height = 90
else:
    sun_height = degrees(atan(tan(elevation_rad) / abs(sin(radians(delta_phi)))))

A_eff = sun_height        if azimuth < 204    # morning (east sun)
      = 180 - sun_height  if azimuth >= 204   # afternoon (west sun)
```

### Step 1a — Cooling slat_angle (block sun)
```
MORNING_LIMIT = 85    # early flip before geometric noon crossing
COOLING_LB    = 11    # ventilation floor

if A_eff < MORNING_LIMIT:                          # Morning — back-face blocking
    if A_eff + 90 <= max_tilt:
        slat_angle = A_eff + 90
    else:
        slat_angle = max_tilt                      # dead zone fallback
else:                                              # Afternoon — direct blocking
    slat_angle = max(A_eff - 90, COOLING_LB)

clamp slat_angle to [COOLING_LB, max_tilt]
```

### Step 1b — Heating slat_angle (let sun through)
```
if A_eff <= max_tilt:
    slat_angle = A_eff                             # slat tracks sun directly
else:
    tilt_position = 100                            # dead zone: skip Step 2
    return

clamp slat_angle to [0, max_tilt]
```

### Step 2 — Convert slat_angle → tilt_position
```
correction = 7    if slat_angle < 20
           = 5.5  if slat_angle < 69
           = 0.5  otherwise

tilt_position = INT(slat_angle / max_tilt * 100 + correction)
clamp tilt_position to [0, 100]
```
