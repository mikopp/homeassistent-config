# Deadband Move Optimization — Implementation Plan

## Status

| Step | Description | Status |
|------|-------------|--------|
| 1 | Add `input_number.pergola_deadband_angle` helper | DONE |
| 2 | Update `sensor.pergola_cooling_lower_bound` — read deadband from input_number | N/A (see revised plan) |
| 3 | Update `sensor.pergola_slat_angle` — replace all hardcoded `5` with deadband variable | N/A (see revised plan) |
| 4 | Morning: tie safety buffer to DB, add snap-to-max_tilt. Afternoon snap removed (causes sun leak). | DONE |
| 5 | Update `pergola_cover_response` — read deadband from input_number | DONE |
| 6 | Add new entity to `group.pergola_dach` | DONE |

See `plans/Deadband-move-optimization.md` (superseded) and the approved revised plan for the final scope.

---

## Overview

The pergola automation suppresses micro-movements via a **deadband**: when the computed target slat angle is within DB degrees of the current slat angle, the covers don't move. Currently DB is hardcoded as 5° in three places:

| Location | Line | Current hardcode |
|----------|------|-----------------|
| `sensor.pergola_slat_angle` — optimized morning guard & buffer | 353, 357 | `moe <= mt - 5`, `moe + 5` |
| `sensor.pergola_slat_angle` — standard cooling morning guard | 370 | `moe <= mt - 5` |
| `sensor.pergola_cooling_lower_bound` — flip-point iteration | 616 | `{% set SAFETY = 5 %}` |
| `pergola_cover_response` — sun tracking deadband condition | 1166 | `(5 / mt * 100)` |

This plan makes DB a user-configurable `input_number`, ties the formula safety buffer to the same value, and adds two snap-to-boundary rules that prevent the deadband from blocking the covers from ever reaching the physical limits (max_tilt and 90°).

---

## Design Rationale

### Safety buffer = deadband

The optimized cooling formula (and standard cooling) uses a SAFETY_BUFFER when deciding whether to use the back-face (morning) strategy:

```
if A < 90 and moe <= mt - SAFETY_BUFFER:
    slat = max(90, moe + SAFETY_BUFFER)   # stay SAFETY_BUFFER ahead of MaxOpenEast
```

The buffer ensures the slat is always far enough from the shade boundary that a full deadband cycle cannot cause light leakage. If `SAFETY_BUFFER < DB`, the covers could theoretically be positioned where a sun tick crosses the shade boundary but the deadband suppresses the correction move. Setting `SAFETY_BUFFER = DB` closes this gap exactly.

The same SAFETY value is used in `sensor.pergola_cooling_lower_bound` when finding the flip point (the largest A_eff where the back-face strategy is still viable). Using the deadband here ensures the flip point is consistent with the formula in `sensor.pergola_slat_angle`.

### Snap-to-boundary logic

Two boundary positions are important:
- **max_tilt** (morning optimized) — maximum ventilation via the back-face. If the formula computes `slat = mt - ε` where `ε < DB/2`, the deadband comparison in the cover response automation converts both values to tilt_position integers which may be equal, so the motor never actually reaches max_tilt. Snap to max_tilt when within `DB/2`.
- **90°** (afternoon optimized) — fully vertical/maximum ventilation. Same issue: when `mow` is close to 90° the integer rounding in the deadband check may suppress the final move. Snap to 90° when within `DB/2`.

The `/2` threshold is conservative: if we are within half the deadband, we are guaranteed to be close enough that snapping is visually and mechanically indistinguishable from the formula value, and the motor will actually reach the boundary.

### Morning guard `moe <= mt - DB` — verification

The morning guard condition determines when the back-face strategy is safe:

```
Guard: moe <= mt - DB  (was: moe <= mt - 5)
```

When the guard is false (MaxOpenEast is within DB of max_tilt), two things happen:
1. The formula would need to command `slat ≥ mt`, which is already clamped to `mt`.
2. But the *next tick* may need to command a position *above* mt (shade has advanced), which cannot be expressed — the back-face strategy has run out of range.

By tying the guard threshold to DB, we ensure the flip occurs at least one full deadband cycle before the back-face runs out of room. This is correct for any DB value.

---

## Step-by-Step Implementation

### Step 1 — Add `input_number.pergola_deadband_angle`

**Location:** `packages/pergola.yaml`, `input_number:` section, after `pergola_min_sun_elevation` (line ~124).

**New entity:**

```yaml
  pergola_deadband_angle:
    name: Pergola Deadband Angle
    # Minimum slat angle change (in degrees) required to trigger a motor movement.
    # Used in three places:
    #   1. pergola_cover_response — suppresses sun-tracking moves smaller than this.
    #   2. sensor.pergola_slat_angle — safety buffer in cooling formulas equals this
    #      value so shade is guaranteed within one deadband cycle.
    #   3. sensor.pergola_cooling_lower_bound — flip-point iteration uses this as the
    #      margin below max_tilt at which the back-face strategy is declared unsafe.
    # Default 5°. Lower values → more frequent movement; higher values → less churn
    # but coarser sun tracking.
    min: 1
    max: 20
    step: 0.5
    unit_of_measurement: "°"
    mode: box
    icon: mdi:arrow-expand-horizontal
    category: Pergola
```

**No other changes in this step.**

---

### Step 2 — Update `sensor.pergola_cooling_lower_bound`

**Location:** `packages/pergola.yaml`, line 616 (inside `sensor.pergola_cooling_lower_bound` state template).

**Current:**
```jinja
{% set SAFETY = 5 %}
```

**Replace with:**
```jinja
{# SAFETY: margin below max_tilt at which back-face strategy is declared unsafe.    #}
{# Tied to the deadband so the flip point stays consistent with the slat formula.   #}
{% set SAFETY = states('input_number.pergola_deadband_angle') | float(5) %}
```

**Also update the availability template** to include the new input_number:
```yaml
availability: >
  {{ states('input_number.pergola_max_tilt_angle') not in ['unavailable', 'unknown']
     and states('input_number.pergola_slat_width') not in ['unavailable', 'unknown']
     and states('input_number.pergola_slat_pivot_spacing') not in ['unavailable', 'unknown']
     and states('input_number.pergola_slat_thickness') not in ['unavailable', 'unknown']
     and states('input_number.pergola_deadband_angle') not in ['unavailable', 'unknown'] }}
```

**Update the inline comment** on line 621 (`{# We record the LAST …`) to reference SAFETY dynamically instead of the hardcoded `5`.

---

### Step 3 — Update `sensor.pergola_slat_angle` (standard cooling branch)

**Location:** `packages/pergola.yaml`, sun_automatik_cooling block, standard (non-optimized) branch. Currently lines 368–379.

Add a variable read at the top of the cooling block (alongside `LB`, `A`, `moe`):

```jinja
{% set DB  = states('input_number.pergola_deadband_angle') | float(5) %}
```

Replace the two hardcoded `5` references:

| Current | Replace with |
|---------|-------------|
| `{% if A < 90 and moe <= mt - 5 %}` (line 370) | `{% if A < 90 and moe <= mt - DB %}` |

No other change needed in the standard cooling branch (it does not use `moe + 5`; the morning formula there is `A + 90` which doesn't involve the buffer directly).

---

### Step 4 — Update `sensor.pergola_slat_angle` (optimized cooling branch) and add snap logic

**Location:** `packages/pergola.yaml`, optimized cooling block. Currently lines 348–367.

**4a. Read DB variable** alongside existing `moe`/`mow` reads:

```jinja
{% set DB  = states('input_number.pergola_deadband_angle') | float(5) %}
```

**4b. Replace hardcoded `5` in morning guard and buffer** (lines 353, 357):

| Current | Replace with |
|---------|-------------|
| `{% if A < 90 and moe <= mt - 5 %}` | `{% if A < 90 and moe <= mt - DB %}` |
| `{% set slat = [[90, moe + 5] \| max, mt] \| min %}` | `{% set slat = [[90, moe + DB] \| max, mt] \| min %}` |

**4c. Add snap-to-max_tilt for morning branch** — after computing `slat` in the morning branch, before the final clamp line (`{{ [[slat, 0] | max, mt] | min | round(1) }}`):

```jinja
{# Snap to max_tilt if within DB/2: the deadband would otherwise prevent the covers  #}
{# from ever reaching the physical maximum-open position (full back-face ventilation). #}
{% if mt - slat < DB / 2 %}
  {% set slat = mt %}
{% endif %}
```

**4d. Add snap-to-90° for afternoon branch** — after the afternoon assignment `{% set slat = [mow, 90] | min %}`:

```jinja
{# Snap to 90° if within DB/2: prevents deadband from blocking the fully vertical    #}
{# (maximum ventilation) position when mow is just under 90°.                        #}
{% if 90 - slat < DB / 2 %}
  {% set slat = 90 %}
{% endif %}
```

**Note:** The flip-range branch (`elif A <= 90: slat = mow`) does not need a snap — its raw value is always ≤ 31.7° and never approaches 90° or max_tilt.

**Full revised optimized cooling block (for reference):**

```jinja
{% if optimized %}
  {# ── Optimised cooling: safe-zone max-open formula ──────────────────────────── #}
  {% set DB  = states('input_number.pergola_deadband_angle') | float(5) %}
  {% set mow = states('sensor.pergola_max_open_west_cooling_angle') | float(15.3) %}
  {% if A < 90 and moe <= mt - DB %}
    {# Morning back-face: max(90°, MaxOpenEast + DB), ≤ max_tilt.                  #}
    {# DB equals the deadband so the slat is always a full deadband cycle ahead of  #}
    {# MaxOpenEast — shade is guaranteed even if the motor skips one tick.          #}
    {# Floor at 90° — sub-vertical back-face provides no blocking benefit.          #}
    {% set slat = [[90, moe + DB] | max, mt] | min %}
    {# Snap to max_tilt if within DB/2: the deadband would otherwise prevent the   #}
    {# covers from ever reaching the physical maximum-open position.                #}
    {% if mt - slat < DB / 2 %}
      {% set slat = mt %}
    {% endif %}
  {% elif A <= 90 %}
    {# Flip range (A ≤ 90, morning guard failed): MaxOpenWest morning, raw.         #}
    {# Raw value ≤ 31.7° here — no snap needed.                                     #}
    {% set slat = mow %}
  {% else %}
    {# Afternoon (A > 90): min(90°, raw sensor).                                    #}
    {% set slat = [mow, 90] | min %}
    {# Snap to 90° if within DB/2: prevents deadband from blocking the fully        #}
    {# vertical position when mow is marginally below 90°.                          #}
    {% if 90 - slat < DB / 2 %}
      {% set slat = 90 %}
    {% endif %}
  {% endif %}
  {{ [[slat, 0] | max, mt] | min | round(1) }}
```

---

### Step 5 — Update `pergola_cover_response` deadband condition

**Location:** `packages/pergola.yaml`, `pergola_cover_response` automation, sun tracking branch condition, line 1166.

**Current:**
```jinja
{% set DB      = (5 / mt * 100) | round(0) | int %}
```

**Replace with:**
```jinja
{# DB: deadband in tilt_position units (0–100 scale), derived from the configurable  #}
{# pergola_deadband_angle (degrees) divided by max_tilt_angle. This matches the same #}
{# deadband used in the slat formula safety buffer.                                  #}
{% set DB      = (states('input_number.pergola_deadband_angle') | float(5) / mt * 100) | round(0) | int %}
```

No other changes in this automation.

---

### Step 6 — Add to `group.pergola_dach`

**Location:** `packages/pergola.yaml`, `group.pergola_dach` entities list (~line 1493), in the "User-configurable parameters" section.

Add after `input_number.pergola_min_sun_elevation`:

```yaml
      - input_number.pergola_deadband_angle
```

---

## Edge Cases and Invariants

| Scenario | Expected behaviour after change |
|----------|--------------------------------|
| DB = 5 (default) | Identical to current behaviour — all hardcoded `5` replaced by DB |
| DB increased to 10 | Flip point moves earlier (larger SAFETY margin); morning buffer is 10°; cover response fires less often |
| DB decreased to 2 | Flip point moves later; covers move more often; snap threshold is 1° |
| Optimized morning, `moe + DB` computes to `mt - 0.3°` (within DB/2 = 2.5°) | Snaps to `mt`; covers reach full back-face open |
| Optimized afternoon, `mow = 89.1°` with DB=5 | `90 - 89.1 = 0.9 < 2.5` → snaps to 90°; covers reach fully vertical |
| Standard cooling afternoon (not optimized) | No snap logic — formula already uses `[A-90, LB] | max` which moves monotonically; 90° is never a target |

## Files Changed

- `packages/pergola.yaml` only — all changes in one file

## Non-changes (intentional)

- `not_enough_sun` branch deadband (30°) in `pergola_cover_response` lines 1137–1144: this is a separate "coarse" threshold for a different purpose (avoid moving from an already-vertical slat) and is intentionally not tied to the motion deadband.
- `pergola_rain_recovery_step` 30° deadband: also intentionally fixed, not related to sun tracking.
