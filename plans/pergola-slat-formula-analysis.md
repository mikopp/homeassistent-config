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
- **Slat width (w):** 22 mm *(usable blocking width: 20 mm)*
- **Slat thickness (t):** 3 mm
- **Pivot spacing (d):** 22 mm *(center-to-center between adjacent slats)*
- **Effective diagonal (deff):** sqrt(20² + 3²) = 20.22 mm
- **Effective slat ratio (R):** deff / w = sqrt(20² + 3²) / 22 = **0.91926**
- **Thickness offset (phi):** arctan(3/20) = **8.53°**

### Pergola Coordinate System
- **0°** = flat / horizontal (fully closed, rain protection)
- **90°** = vertical (slats perpendicular to ground)
- **122°** = maximum tilt (slats tilted past vertical) — configurable via `input_number.pergola_max_tilt_angle`
- Positive angles tilt toward west (afternoon sun side)
- Negative angles would tilt toward east — but hardware only goes 0° to 122°, so negative angles are not directly achievable

---

## 2. Core Formulas

All formulas use:
- **azimuth** = `state_attr('sun.sun', 'azimuth')` (compass bearing 0-360°)
- **elevation** = `state_attr('sun.sun', 'elevation')` (degrees above horizon)
- **terrasse_azimuth** = 204° (constant)
- **delta_phi** = azimuth - terrasse_azimuth (relative azimuth)

### 2.1 Effective Sun Angle (A_EFF)

The projected height of the sun as seen from the cross-section perpendicular to the slat axis. This is the angle at which sunlight enters between the slats.

```
A_EFF = degrees(atan(tan(radians(elevation)) / sin(radians(delta_phi))))
```

- When delta_phi = 0 (sun directly along slat axis): A_EFF → 90° (sun directly overhead from slat's perspective)
- When delta_phi = ±90° (sun perpendicular to slat axis): A_EFF = elevation
- **Sign convention:** positive when sun is from the west side (afternoon), negative when from east (morning)
- **Singularity:** when sin(delta_phi) = 0, use A_EFF = 90°

**Spreadsheet column C** implements exactly this formula. Verified correct.

### 2.2 Perfect Perpendicular Angle (blocking angle)

The slat tilt that places the slat surface perpendicular to the incoming sun rays — the "perfect" blocking angle for cooling mode.

```
perfect_angle = degrees(atan(sin(radians(delta_phi)) / tan(radians(elevation))))
```

**Relationship:** perfect_angle + A_EFF = 90° (complementary angles of the same right triangle)

- **Positive values:** sun from west → tilt slats toward west to block
- **Negative values:** sun from east → tilt slats toward east to block
- When delta_phi = 0: perfect_angle = 0° (flat blocks overhead sun perfectly)
- When elevation = 0: perfect_angle → ±90° (vertical slats needed for horizon sun)

**Spreadsheet column D** implements this. Verified correct.

**Loxone formula** (user-provided): `DEG(ARCTAN(SIN(RAD(I2-I3))/TAN(RAD(I1))))` — identical, where I2-I3 = azimuth - terrasse_azimuth, I1 = elevation.

### 2.3 Mapping to Pergola Hardware (Column H)

The perfect_angle is in a symmetric coordinate system (negative = east, positive = west). The pergola hardware only supports 0° to 122° (one direction). The mapping is:

```
threshold = -(180 - max_tilt_angle) = max_tilt_angle - 180
         = 122 - 180 = -58°

if perfect_angle <= threshold (-58°):
    slat_angle = perfect_angle + 180     # flip: block from "back side" of slat
elif perfect_angle >= 0:
    slat_angle = perfect_angle           # direct blocking angle
else:
    # Dead zone: -58° < perfect_angle < 0°
    # Hardware cannot achieve this angle
    # Fallback depends on mode (see Section 3)
```

**Spreadsheet column H** implements this with: `IF(D <= -58, D + 180, IF(D >= 0, D, -1))`

The `-1` represents the dead zone — the hardware physically cannot tilt to block the sun from slight-east angles. This corresponds to early morning (azimuth ~114°-170°) when the effective sun angle is between roughly -33° and -58°.

**Why -58° is the threshold:** At perfect_angle = -58°, adding 180° gives 122° — the hardware maximum. Any more negative perfect_angle maps to a value below 122° (achievable). Values between -58° and 0° would map to 122°-180°, which is the motor's dead zone.

---

## 3. Cooling Mode Formula (Block Sun)

**Goal:** Block direct sunlight by tilting slats perpendicular to sun rays.

### Simple version (no slat thickness correction)

```
slat_angle = mapped perfect_angle (Section 2.3)
```

Dead zone fallback: **0°** (flat) — provides maximum shade even if imperfect blocking.

Clamp to: **[0°, 90°]** — never past vertical in cooling mode (past-vertical lets sun through from the other side).

### Enhanced version (with slat thickness / safe zone — from Gemini conversation)

The slat thickness and overlap create a "safe zone" — a range of angles that all provide 100% shade. Instead of the "perfect" perpendicular angle, we can use the **maximum open angle** (edge of the safe zone closest to vertical) to maximize airflow while maintaining full shade.

**Max Open toward sun (East Cutoff):**
```
Stoward = A_EFF + phi - 180 + degrees(asin(R * sin(radians(A_EFF))))
```

**Max Open away from sun (West Cutoff / "Backside Block"):**
```
Sbackside = A_EFF + phi - degrees(asin(R * sin(radians(A_EFF))))
```

Where R = 0.91926, phi = 8.53°.

The "backside block" angle is used when the "toward" angle falls in the dead zone. This is the positive (west-tilt) angle that still blocks eastern sun by leveraging slat overlap.

**Safe Zone width at various effective sun angles (for d=20, w=22, t=3):**

| A_EFF | Perfect Angle | Max East (Stoward) | Max West (Sbackside) | Safe Zone Width |
|---|---|---|---|---|
| 10° | -80.0° | -152.3° | +9.3° | 161.6° |
| 20° | -70.0° | -133.1° | +10.2° | 143.4° |
| 30° | -60.0° | -114.1° | +11.2° | 125.3° |
| 40° | -50.0° | -95.2° | +12.3° | 107.6° |
| 50° | -40.0° | -76.7° | +13.8° | 90.5° |
| 60° | -30.0° | -58.7° | +15.8° | 74.5° |
| 70° | -20.0° | -41.7° | +18.8° | 60.5° |

### Recommended Cooling Strategy

For the HA automation, use the **simple perpendicular angle** (column D mapped via column H). Reasons:
1. The perpendicular angle sits safely inside the safe zone for all sun positions
2. It provides the thickest shadow (maximum margin of error)
3. It's simpler to implement and debug
4. The safe zone optimization (minimal motor movement) is a future enhancement — the motor moves at most every 5 minutes anyway

The safe zone data is documented here for future optimization if desired.

---

## 4. Heating Mode Formula (Let Sun Through)

**Goal:** Tilt slats parallel to sun rays so sunlight passes between them.

### Derivation

To let sun through, slats should be aligned **with** the sun rays rather than perpendicular to them. This means rotating 90° from the blocking angle:

```
heating_raw = perfect_angle - 90
```

This gives the angle (in the symmetric coordinate system) where slats are parallel to sun rays.

### Mapping to pergola hardware

Same mapping logic as cooling, but applied to heating_raw:

```
threshold = max_tilt_angle - 180 = -58°

if heating_raw <= threshold (-58°):
    slat_angle = heating_raw + 180
elif heating_raw >= 0:
    slat_angle = heating_raw
else:
    # Dead zone: hardware can't achieve perfect alignment
    slat_angle = 90°  (vertical — maximizes light transmission as fallback)
```

Clamp to: **[0°, 122°]** (full hardware range available in heating mode).

### Verification with test cases

| Azimuth | Elev | perfect_angle | heating_raw | slat_angle | Physical interpretation |
|---|---|---|---|---|---|
| 220° | 45° | 15.41° | -74.59° | 105.41° | Sun from slight west, high → open past vertical to let rays through |
| 240° | 40° | 35.01° | -54.99° | 90° (dead zone) | Sun from west, medium → vertical fallback |
| 260° | 30° | 55.15° | -34.85° | 90° (dead zone) | Sun far west, low → vertical fallback |
| 102° | 31° | -58.44° | -148.44° | 31.56° | Sun from far east → tilt to 31.56° to align with rays |
| 180° | 40° | -25.86° | -115.86° | 64.14° | Sun from south → open to 64° |
| 204° | 57° | 0.00° | -90.00° | 90° | Sun along slat axis → vertical |

All values are physically sensible.

---

## 5. Gemini Analysis — Correctness Assessment

### What Gemini got right
1. **Core sun projection formula** — the effective sun angle and perpendicular angle formulas are geometrically correct and match the spreadsheet
2. **Safe zone concept** — the idea that slat overlap creates a range of valid blocking angles is sound physics
3. **Slat thickness correction** — the deff and phi constants correctly account for 3mm slat thickness in the safe zone calculation
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

### Intermediate values (computed once per update cycle)
```
delta_phi = azimuth - 204
elevation = sun elevation
max_tilt = 122  (from input_number.pergola_max_tilt_angle)
threshold = max_tilt - 180  (= -58 for default 122°)
```

### Cooling mode slat_angle (block sun)
```
if elevation <= 0 or sin(delta_phi) ≈ 0:
    perfect_angle = 0
else:
    perfect_angle = atan(sin(delta_phi) / tan(elevation))  [in degrees]

if perfect_angle <= threshold:
    slat_angle = perfect_angle + 180
elif perfect_angle >= 0:
    slat_angle = perfect_angle
else:
    slat_angle = 0  (dead zone: flat for max shade)

clamp slat_angle to [0, 90]
```

### Heating mode slat_angle (let sun through)
```
if elevation <= 0 or sin(delta_phi) ≈ 0:
    perfect_angle = 0
else:
    perfect_angle = atan(sin(delta_phi) / tan(elevation))  [in degrees]

heating_raw = perfect_angle - 90

if heating_raw <= threshold:
    slat_angle = heating_raw + 180
elif heating_raw >= 0:
    slat_angle = heating_raw
else:
    slat_angle = 90  (dead zone: vertical for max light)

clamp slat_angle to [0, max_tilt]
```

### Then convert slat_angle to tilt_position
```
correction = 7    if slat_angle < 20°
           = 5.5  if slat_angle < 69°
           = 0.5  otherwise

tilt_position = INT(slat_angle / max_tilt * 100 + correction)
clamp tilt_position to [0, 100]
```
