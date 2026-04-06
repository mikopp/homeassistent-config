# Pergola Roof Automation — Implementation Plan

## Overview

Automate the tilt control of two Somfy bioclimatic pergola covers (`cover.dach_links`, `cover.dach_rechts`) on the terrasse. Both covers always move together as one unit.

**Goals:**
- Follow the sun to provide shade (cooling season) or let sun through (heating season)
- Protect covers during frost (no movement) and rain (defer to Somfy lock)
- Step-drain covers after rain stops

**Key facts:**
- Tilt scale: 0 = horizontal/flat (maximum shade / rain protection), 71 ≈ vertical (90°), 100 = 122° open (max tilt user-configurable via `input_number.pergola_max_tilt_angle`, default 122°)
- Conversion formula (slat_angle_degrees → tilt_position, with hardware-specific rounding corrections):
  ```
  tilt_position = INT(slat_angle / max_tilt_angle × 100 + correction)
  correction: +7 if slat_angle < 20°,  +5.5 if slat_angle < 69°,  +0.5 otherwise
  ```
  Reason: motor moves very little below 20°; linear range 20°–69°; slight jerk above 70°. Values > 100 are dead zone.
- Terrasse faces 204° (SSW); sun hits the terrasse when `114° ≤ azimuth ≤ 294°`
- All config lives in `packages/pergola.yaml`; deployed via `git pull` on HA host

**References:**
* Loxone config file: `C:\Users\mikop\Documents\Loxone\Loxone Config\Projects\Haus.Loxone`
* Loxone config documentation: https://www.loxone.com/enen/kb-cat/loxone-config/
* Slat angle formula analysis: [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md)
* Gemini conversation (original analysis): [gemini-conversation-slat-formulas.md](gemini-conversation-slat-formulas.md)
* Spreadsheet with sample calculations: [terrace roof titl.xlsx](terrace%20roof%20titl.xlsx)

**TBD items blocking later steps:**
- Room temperature ignored — heating/cooling mode is determined solely by the heating indicator
- Post-rain tilt values to confirm after first rain event (Step 4)

---

## Location & Orientation (Confirmed)

**GPS coordinates** (verified 2026-04-04):
- HA `zone.home`: lat 48.12789°, lon 14.23595° — matches sonnenverlauf.de (48.12789°, 14.23601°) within ~4 m. No change needed.
- Altitude: 307 m (informational only)

**Slat rotation:** tilt 0 = flat/horizontal (rain/closed). tilt 71 = 90° vertical (fully open to diffuse light). tilt 100 = 122° (max open).

**Sun azimuth window (confirmed):**
```
sun on terrasse side when: 114° ≤ sun.azimuth ≤ 294°
sun behind house when:     sun.azimuth < 114°  OR  sun.azimuth > 294°
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
| `sensor.victronsolarcharger_yield_power226` | W | Raw Victron solarcharger DC PV power |

---

## Pergola Device

All entities created by this feature will appear under a single HA virtual device named **"Pergola Dach"** (`identifier: pergola_dach`). This allows the user to find and control everything in one place via Settings → Devices.

**Implementation note:** HA's `template:` integration supports a `device:` block that groups template entities under a virtual device directly in YAML. `input_*` helpers (config values) do not support YAML device assignment — they must be manually assigned to the "Pergola Dach" device via the HA UI after creation (Settings → Devices & Services → [each helper] → Change device).

### All entities on the device

#### Config — user-changeable in HA UI
| Entity | Type | Default | Purpose |
|---|---|---|---|
| `input_boolean.pergola_automatic_enabled` | toggle | on | Master on/off — disables all cover movement when off |
| `input_boolean.pergola_heating` | toggle | off | Heating indicator: on = heating mode (let sun through), off = cooling mode (block sun). Can be flipped by user or set via HA REST API by an external system (e.g. Loxone) |
| `input_select.pergola_automation_state` | select | — | State machine; **can be set manually to break a deadlock** |
| `input_number.pergola_frost_off_threshold` | number | 2.5 °C | Temp below which frost mode activates |
| `input_number.pergola_frost_on_threshold` | number | 3.0 °C | Temp above which frost mode clears |
| `input_number.pergola_pv_conversion_factor` | number | 3.2 | PV W → W/m² divisor for sun detection (calibrate in Step 6) |
| `input_number.pergola_max_tilt_angle` | number | 122 ° | Maximum physical slat angle; drives tilt_position conversion |
| `input_boolean.pergola_cooling_optimized` | toggle | off | Cooling angle mode: off = perfect perpendicular blocking; on = optimized (safe-zone max-open) — see Step 7 |

#### Status — derived/calculated, read-only
| Entity | Unit | Description |
|---|---|---|
| `sensor.pergola_pv_power` | W | PV power — wraps raw Victron sensor |
| `sensor.pergola_slat_angle` | ° | Currently calculated target slat angle (output of sun/season formula) |
| `sensor.pergola_tilt_position` | 0–100 | Calculated tilt_position after hardware correction (what will be sent to covers) |
| `binary_sensor.pergola_sun_shining` | on/off | True when PV+radiation exceed elevation-adjusted clear-sky threshold |

> `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` reflect the *calculated setpoint* at any given moment — useful for debugging the formula without having to look at cover state.

---

## Automation State Machine

`input_select.pergola_automation_state` is the single source of truth. One automation manages transitions; a separate automation reacts to state changes to move covers.

### States

| State | Meaning | Cover behavior |
|---|---|---|
| `no_sun_behind_house` | Sun below horizon or azimuth outside 114°–294° | tilt = 71 (vertical, open) |
| `frost` | Outdoor temp below frost threshold | No movement |
| `rain` | Rain active (weather station OR cover lock = `rain`) | No movement |
| `rain_stopped` | Rain just ended, recovery in progress | Recovery script handles covers |
| `user_override` | One or both covers locked by user (`lock originator = user`) | No movement |
| `not_enough_sun` | Sun shining indicator off for ≥ 5 min (cloud/overcast) | tilt = 71 (vertical, open) |
| `sun_automatik_heating` | Sun active, heating indicator on | Heating formula |
| `sun_automatik_cooling` | Sun active, heating indicator off | Cooling formula |

### Priority Rules (highest first)

1. **frost** — temp < `pergola_frost_off_threshold` → enter `frost`. Clears when temp > `pergola_frost_on_threshold`. On exit: if `wheatherstation_hourly_rain > 0` → enter `rain_stopped` (post-rain recovery); otherwise re-evaluate remaining rules.
2. **rain** — enter when **either** indicator is active:
   - `sensor.wheatherstation_rain_rate > 0` (weather station — slower, delayed), OR
   - `sensor.dach_links_priority_lock_originator = rain` OR `sensor.dach_rechts_priority_lock_originator = rain` (cover-mounted rain sensor — fast, no delay)

   Exit rain only when **both** indicators are off:
   - `rain_rate == 0` AND both lock originators = `unknown` (not `rain`)

   Condition: state ≠ `frost`
3. **rain_stopped** — was `rain`, both indicators now off → enter `rain_stopped`. Script exits this state.
4. **user_override** — either lock originator = `user`. Clears when both = `unknown`. Cover response automation skips all movement while in this state. On exit: if `wheatherstation_hourly_rain > 0` → enter `rain_stopped` (post-rain recovery); otherwise re-evaluate remaining rules. (Same exit logic as frost.)
5. **no_sun_behind_house** — sun below horizon OR azimuth outside 114°–294° (geometric — no sun possible regardless of sensor).
6. **not_enough_sun** — `pergola_sun_shining` has been `off` for ≥ 5 continuous minutes. Exits when `pergola_sun_shining` has been `on` for ≥ 2 continuous minutes.
7. **sun_automatik_heating** — `input_boolean.pergola_heating` = on/1.
8. **sun_automatik_cooling** — default when sun is active and heating indicator is off.

---

## Tilt Calculation Logic

Tilt calculation is a two-step process: first compute the desired **slat_angle** (degrees), then convert to **tilt_position** (0–100) using the hardware correction formula.

### Step 0 — Intermediate values

Computed once per update cycle from sun position:

```
delta_phi      = azimuth - 204                          (relative azimuth to terrasse)
delta_phi_rad  = radians(delta_phi)
elevation_rad  = radians(elevation)
max_tilt       = input_number.pergola_max_tilt_angle    (default 122°)
threshold      = max_tilt - 180                         (default -58°)
```

**Perfect perpendicular angle** (the slat tilt that blocks sun head-on):
```
if elevation <= 0 OR |sin(delta_phi_rad)| < 0.001:
    perfect_angle = 0
else:
    perfect_angle = degrees(atan2(sin(delta_phi_rad), tan(elevation_rad)))
```

> Sign convention: positive = sun from west (afternoon), negative = sun from east (morning).
> Derivation and correctness analysis: see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md)

### Step 1 — Desired slat angle

#### Cooling season (`sun_automatik_cooling`) — block sun

Map `perfect_angle` to the pergola hardware range (0–122°). The hardware can only tilt in one direction, so angles that would require the opposite tilt direction need special handling:

```
if perfect_angle <= threshold:               # sun from far east, steep angle
    slat_angle = perfect_angle + 180         # block from "back side" of slat
elif perfect_angle >= 0:                     # sun from west, direct blocking
    slat_angle = perfect_angle
else:                                        # dead zone: -58° < angle < 0°
    slat_angle = 15                           # almost flat for maximum shade (imperfect) - not completely closed

clamp slat_angle to [0°, max_tilt_angle]
```

> **Why not cap at 90°:** branch 2 (west, `perfect_angle ≥ 0`) naturally stays below 90° within the azimuth window — no cap needed. Branch 1 (east, `+180°`) produces values in `[90°, 122°]`; these are exactly correct and required. Capping at 90° (vertical) would leave eastern sun unblocked because vertical slats face south, not toward the rising sun.

**Dead zone explanation:** When the sun comes from a slight-east angle (azimuth roughly 114°–170°), the ideal blocking tilt would require a small negative angle. Since the hardware only goes 0°–122°, the fallback is **15°** (not fully flat). The slats are 22 cm wide with a 3 cm thickness and 20 cm pivot spacing, so they overlap — a 15° tilt still provides full shade in practice while allowing a small amount of airflow. Flat (0°) would also block, but 15° is slightly better for ventilation without sacrificing shade.

> If `input_boolean.pergola_cooling_optimized` is `on`, a different formula is used instead (see Step 7). The dead zone fallback of 15° applies only in the default (`off`) mode.

#### Heating season (`sun_automatik_heating`) — let sun through

To let sun through, slats should be **parallel** to the sun rays (rotated 90° from the blocking angle):

```
heating_raw = perfect_angle - 90

if heating_raw <= threshold:                 # heating_raw too negative for hardware; covers ALL east,
    slat_angle = heating_raw + 180           # noon, south, and slight west (perfect_angle ≤ ~32°).
                                             # +180 uses the 180°-equivalent slat position (same light
                                             # transmission, mechanically in range)
elif heating_raw >= 0:                       # sun from west
    slat_angle = heating_raw
else:                                        # dead zone: sun from moderate west,
    tilt_position = 100                      # ideal angle mechanically impossible —
    # skip hardware correction, use max tilt directly                                     
    # no other position lets in more sun from the west

clamp slat_angle to [0°, max_tilt]          # (only applies to the non-dead-zone branches)
```

**Dead zone fallback for heating:** When perfect alignment isn't mechanically possible (sun from west at `perfect_angle` between ~32° and 90°), use `tilt_position = 100` (max tilt, 122°) directly. Tilting the slats past vertical toward the east-face-up side opens the maximum gap to incoming west sun. No other position does better.

#### Verification table

All rows are within the azimuth window (114°–294°). Outside that range the state machine is in `no_sun_behind_house` and neither formula runs — slats go to tilt 71 (vertical).

Heating branch used: **A** = +180° equivalent (`heating_raw ≤ threshold`), **B** = direct (`heating_raw ≥ 0`), **DZ** = dead zone (`tilt_pos = 100`)

| Azimuth | Elev | perfect_angle | Cooling slat | Heating slat | Heating branch | Notes |
|---|---|---|---|---|---|---|
| 115° | 20° | −70.0° | 110° (tilt≈90) | 20.0° | A | Far east, near window edge |
| 150° | 30° | −54.5° | 15° (dead zone) | 35.5° | A | Moderate east |
| 140° | 40° | −47.0° | 15° (dead zone) | 43.0° | A | East, medium elev |
| 180° | 55° | −15.9° | 15° (dead zone) | 74.1° | A | Noon (summer) |
| 180° | 40° | −25.9° | 15° (dead zone) | 64.1° | A | South, lower elev |
| 204° | 57° | 0.0° | 0° (flat) | 90.0° | A | Sun along slat axis |
| 220° | 45° | 15.4° | 15.4° | 105.4° | A | Slight west — still branch A! |
| 240° | 40° | 35.0° | 35.0° | 100 pos | DZ | West, medium (boundary ~32°) |
| 260° | 30° | 55.1° | 55.1° | 100 pos | DZ | Far west, low |

#### No sun (`no_sun_behind_house`, `not_enough_sun`)
```
slat_angle = 90°  →  tilt_position = 71
```

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
  - Cooling uses the full range: western sun branch (slat 0°–90°, tilt 0–71) and eastern sun branch (slat 90°–122°, tilt ~71–100). Both branches are valid — going past 90° is wrong only for western sun, which never reaches 90° naturally within the azimuth window.
  - Note: the formula gives tilt ≈ 74 for slat_angle = 90° (versus hardware-observed 71). This 3-unit discrepancy exists because the +0.5 correction was calibrated in the 69°–90° range. In practice, the eastern branch rarely lands exactly at 90°; the calibration error is small relative to the 4-unit deadband.
- Values > 100 are dead zone on the Somfy controller — never send them

**Why corrections are needed:**
- Below 20°: motor displacement is very small → +7 compensates
- 20°–69°: linear region → +5.5 rounds up correctly
- Above 69°: slight mechanical jerk → only +0.5 to avoid overshoot

---

### Step 3 — Movement Deadband (5° hysteresis)

Before sending any tilt command, compare the **calculated target tilt_position** (output of Step 2) against the **current reported tilt_position** from the cover. Only move if the difference corresponds to ≥ 5° of slat angle.

**Why compare tilt positions, not slat angles:**
Inverting the Step 2 formula naïvely (`slat_angle = current_tilt × max_tilt / 100`) ignores the correction offsets (+7 / +5.5 / +0.5). Those offsets introduce errors of 7–9° at low/medium angles — larger than the 5° threshold itself, making the comparison unreliable. Because both `target_tilt_position` and `current_tilt_position` are in the same corrected tilt-position space, the corrections cancel in the difference. The comparison is done entirely in tilt-position units.

**5° converted to tilt-position units:**
```
deadband_tilt = ROUND(5 / max_tilt_angle × 100) = ROUND(5 / 122 × 100) = 4
```
(4 tilt units ≈ 4.9° at the default max_tilt_angle of 122°)

**Gate condition (applied before every cover move command):**
```
current_tilt = state_attr('cover.dach_links', 'current_tilt_position') | int

if |target_tilt_position - current_tilt| >= 4:
    send move command with target_tilt_position
else:
    skip (no movement)
```

Use `cover.dach_links` as the reference — both covers always move together.

This applies to **all** move decisions: state-change transitions, the 5-minute periodic sun-tracking trigger, and the no-sun tilt-71 target. The post-rain recovery script bypasses this check — it always moves to its drain angles regardless.

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
- Temp falls below `pergola_frost_off_threshold` (2.5°C) → state = `frost`, movement stops
- Temp rises above `pergola_frost_on_threshold` (3.0°C) → exit `frost`:
  - Check `sensor.wheatherstation_hourly_rain`:
    - If `> 0` → enter `rain_stopped` (run post-rain recovery script)
    - If `== 0` → re-evaluate normally (no rain recovery needed)

---

## Master Switch

`input_boolean.pergola_automatic_enabled` — when `off`, response automation skips all cover movement. State machine continues tracking state so re-enabling acts immediately.

---

## Implementation Steps

Each step is independently deployable via `git pull` on the HA host.

---

### Phase 1 — Foundation

#### Step 1 — Helpers, Template Sensors, Virtual Device [IN_PROGRESS]
**File:** `packages/pergola.yaml`

Add `input_boolean`, `input_select`, `input_number`, and `template` sections.
The `template:` block uses a `device:` key to create the **"Pergola Dach"** virtual device and groups all template entities under it.

**Dependencies:** None — first step.

**Notes:**
- **`packages/pergola.yaml` is rewritten from scratch** — the existing file (which still contains the old `pergola_frost_hold` and `pergola_post_rain_active` booleans and lacks the device declaration) is discarded entirely. Write the complete file fresh using only the entities listed below.
- **Carry over the 4 existing automations** — these must appear in the new file's `automation:` block. The watchdog automations (ids below) are carried over **with the state-based suppression condition already present** (added before Step 1 to fix a race condition — see Step 2 notes). The lock originator responders are carried over verbatim.
  - `id: '1771360145720'` — Inactivity Watchdog: Dach Links
  - `id: '1771361016291'` — Inactivity Watchdog: Dach Rechts
  - `id: '1771748333394'` — Dach Links: Update state when lock originator changes
  - `id: '1771748414999'` — Dach Rechts: Update state when lock originator changes
  - These are critical for the rain-lock lifecycle and must not be lost during the rewrite.
- `input_select.pergola_automation_state` must list all 8 state values
- PV conversion factor (default 3.2) calibrated in Step 6
- Add `input_number.pergola_max_tilt_angle` (default 122, min 100, max 135, step 1, unit °)
- Add `input_boolean.pergola_cooling_optimized` (default off) — selects between perfect-perpendicular and safe-zone max-open cooling formula (Step 7)
- Add `input_boolean.pergola_heating` (default off) — heating indicator; when `on`, sun is let through (heating formula); when `off`, sun is blocked (cooling formula). Can be toggled by user in UI or set via HA REST API by an external system
- Add `sensor.pergola_slat_angle` (unit °, unknown until formula defined in Step 3) and `sensor.pergola_tilt_position` (0–100, unknown until Step 3) as stub template sensors returning `unknown` for now — they exist on the device from day one
- All template sensors and binary sensors (`sensor.pergola_pv_power`, `sensor.pergola_slat_angle`, `sensor.pergola_tilt_position`, `binary_sensor.pergola_sun_shining`) must share the same `template:` block that carries the `device:` declaration

**Post-deploy (one-time, manual via HA UI):**
After first `git pull` and HA restart, manually assign each `input_*` helper to the "Pergola Dach" device:
Settings → Devices & Services → Helpers → [select each helper] → change device → "Pergola Dach"
Helpers to assign: `pergola_automatic_enabled`, `pergola_heating`, `pergola_automation_state`, `pergola_frost_off_threshold`, `pergola_frost_on_threshold`, `pergola_pv_conversion_factor`, `pergola_max_tilt_angle`, `pergola_cooling_optimized`

**Verify:**
- Settings → Devices → "Pergola Dach" shows all 12 entities
- `input_select.pergola_automation_state` shows all eight options
- `binary_sensor.pergola_sun_shining` changes state plausibly with sun conditions
- `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` report `unknown` (correct at this stage)

---

#### Step 2 — State Manager Automation [TODO]
**File:** `packages/pergola.yaml` — add under `automation:`

Add `pergola_state_manager`. This is the **only automation that writes** to `input_select.pergola_automation_state`.

Triggers: outdoor temp, rain rate, both lock originator sensors (`dach_links` and `dach_rechts`), sun attributes, `pergola_sun_shining`, `input_boolean.pergola_heating`, HA start.

> Lock originator sensors must be triggers so the state manager reacts to rain-lock entry/exit (rule 2) and user-override entry/exit (rule 4) without waiting for another trigger.

Action: evaluate priority rules top-down (frost → rain → rain_stopped → **user_override** → no_sun_behind_house → not_enough_sun → heating → cooling).

**Dependencies:** Step 1 (helpers must exist).

**Notes:**
- **Lock originator triggers are watchdog-driven.** The Somfy does not push state changes proactively. `sensor.dach_links_priority_lock_originator` and `sensor.dach_rechts_priority_lock_originator` only update in HA when the inactivity watchdog (or a movement command) sends `stop_cover_tilt` and forces a Somfy state report. The state manager triggers on these sensors but cannot observe rain clearing without the watchdog first causing a report. This is not a gap — the watchdog is already in place — but it means the state manager's lock originator triggers are reactive to watchdog-driven updates, not direct Somfy pushes.
- **Watchdog suppression is explicit, not emergent.** The watchdog and the cover response automation both use `time_pattern: minutes: /5`, so they evaluate simultaneously at every 5-minute mark. Because the cover's `last_updated` is only set after the Somfy responds (not when the command is sent), the watchdog condition would pass at the same instant the cover response is about to send a movement command — causing `stop_cover_tilt` to abort the movement mid-travel. To eliminate this race, both watchdog automations carry an explicit state condition that skips them when `input_select.pergola_automation_state` is in `[sun_automatik_cooling, sun_automatik_heating, rain_stopped]`. The watchdog runs only in quiet states where no movement commands are issued (`rain`, `frost`, `user_override`, `no_sun_behind_house`, `not_enough_sun`).
- **Lock originator responders (automations 3 & 4) complement the state manager.** These automations (already in the file) trigger on lock originator changes and immediately send a second `stop_cover_tilt`. This forces a fresh Somfy state report right after each lock transition, before the state manager has acted. The state manager's second evaluation then sees the most current tilt position data. These automations should be left as-is — do not fold their logic into the state manager.
- Guard: do not overwrite `rain_stopped` mid-flight — only the recovery script exits that state. **Exceptions** (state manager may write a different state while `rain_stopped` is active):
  - **frost entry (from any state including `rain_stopped`):** temp falls below `pergola_frost_off_threshold` → call `script.turn_off` on `script.pergola_post_rain_recovery`, then set state to `frost`. Frost is the highest-priority safety rule — it must preempt an in-progress drain sequence.
  - **rain re-entry (from any state including `rain_stopped`):** either rain indicator becomes active → call `script.turn_off` on `script.pergola_post_rain_recovery`, then set state to `rain`. Rain just restarted — the covers should stay closed and the drain sequence must not continue mid-rain.
  - **frost exit:** temp rises above `pergola_frost_on_threshold` → if `wheatherstation_hourly_rain > 0`, set state to `rain_stopped` and trigger recovery script
  - **user_override exit:** both lock originators return to `unknown` → if `wheatherstation_hourly_rain > 0`, set state to `rain_stopped` and trigger recovery script
  - **HA start with state = `rain_stopped`:** do NOT clear the state; instead re-trigger `script.pergola_post_rain_recovery` so the interrupted drain sequence resumes (see restart recovery note below)
- `input_boolean.pergola_heating` may not exist yet; use a safe default (cooling season) when unavailable
- **HA start / restart recovery:**
  - On HA start the automation fires with trigger = `homeassistant` start
  - If `input_select.pergola_automation_state` is already `rain_stopped` (persisted from before restart): do NOT evaluate other rules; instead call `script.pergola_post_rain_recovery` again to resume the interrupted drain sequence. The recovery script is idempotent enough for this — it will re-run the wait + step sequence from the beginning, which is safe (covers get drained again).
  - For all other persisted states: evaluate priority rules top-down and set the correct current state
- `not_enough_sun` entry/exit requires time-delayed transitions — use separate automations with `for:` timers rather than a single choose block:
  - Entry: trigger on `pergola_sun_shining` turning `off` **for 5 min**, condition state ≠ frost/rain/rain_stopped/user_override/no_sun_behind_house
  - Exit: trigger on `pergola_sun_shining` turning `on` **for 2 min**, condition state = `not_enough_sun` → re-evaluate heating/cooling

**Verify:**
- State reflects current conditions on HA boot
- Temporarily lower frost threshold to current temp → state becomes `frost`
- Evaluate azimuth template manually → `no_sun_behind_house` fires at night

---

### Phase 2 — Cover Control

#### Step 3 — Cover Response Automation (no-sun + cooling) [TODO]
**File:** `packages/pergola.yaml` — add under `automation:`

Add `pergola_cover_response`. Triggers on `input_select.pergola_automation_state` state change and on time pattern every 5 min (to track sun position within active state).

Condition: `input_boolean.pergola_automatic_enabled = on`.

Action (`choose` on current state):
- `no_sun_behind_house`, `not_enough_sun` → set tilt 71 on both covers
- `frost`, `rain`, `rain_stopped`, `user_override` → do nothing
- `sun_automatik_cooling` → cooling formula, clamped [0, 100]
- `sun_automatik_heating` → stub: tilt 71 (replaced in Step 5)

**Dependencies:** Step 1 (helpers), Step 2 (state machine must be writing state).

**Notes:**
- Every-5-min trigger is the only way covers track a slowly moving sun within a steady state
- Cooling tilt clamp is [0, 100]: western sun branch (slat 0°–90°) stays below tilt 71 naturally; eastern sun branch (+180°, slat 90°–122°) uses tilt 71–100 to block sun from behind the slat.
- **Deadband (Tilt Calculation Logic Step 3):** before every move command compare `target_tilt_position` against `cover.dach_links.current_tilt_position`; only issue the command if `|target - current| >= 4` tilt units (≈ 5°). Comparison is in tilt-position units — not slat degrees — so the hardware correction offsets cancel and the check is accurate across all angle zones. Post-rain recovery script bypasses this.
- Fill in the stub template sensors from Step 1: `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` should reflect the current calculated values based on state + sun position (update the template body, not just the automation)

**Verify:**
- Disable `pergola_automatic_enabled` → covers stop responding
- With sun active and cooling season, covers move to formula result within 5 min; verify no movement if cover is already within 5° of target
- Manually set state to `no_sun_behind_house` → tilt goes to 71 (or stays if already within 5°)

---

#### Step 4 — Post-Rain Recovery Script [TODO]
**File:** `packages/pergola.yaml` — add under `script:`

`script.pergola_post_rain_recovery` — stepped drain sequence (8° → wait 30 s → wait 5 min → 15° → wait 5 min → check hourly rain → [wait 30 min if rain reported] → re-evaluate and set final state).

**Dependencies:** Step 2 (state manager must set `rain_stopped` to trigger this), Step 3 (cover control).

**Notes:**
- Script must call the cover service directly (not go through state machine) during drain sequence
- Final step re-evaluates by setting state explicitly (call state manager logic or set state directly)
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
- Compute `slat_angle` using the heating formula (Tilt Calculation Logic → Step 1): `heating_raw = perfect_angle - 90`, east/west branching as defined there, clamp to `[0°, max_tilt]`
- **Dead zone special case:** if in the dead zone (`threshold < heating_raw < 0`), set `tilt_position = 100` directly — skip the hardware correction formula. No other position lets in more west sun.
- For non-dead-zone branches: convert `slat_angle` to `tilt_position` using the hardware correction formula, clamp result to `[0, 100]`

Update state manager: when sun is active and `input_boolean.pergola_heating = on` → `sun_automatik_heating`; otherwise → `sun_automatik_cooling`.

**Dependencies:** Step 1 (`input_boolean.pergola_heating` created there), Step 3 (cover response stub must exist).

**Verify:**
- With `pergola_heating` on → heating formula applied
- With `pergola_heating` off → state transitions to `sun_automatik_cooling`

---

### Phase 4 — Optimized Cooling

#### Step 7 — Optimized Cooling Angle [TBD — formula to be defined]
**File:** `packages/pergola.yaml` — update `pergola_cover_response` and cooling template sensor

Gated by `input_boolean.pergola_cooling_optimized`. When `on`, replace the perfect-perpendicular cooling formula with one that uses the **safe-zone max-open angle** — the furthest the slats can tilt toward vertical while still guaranteeing 100% shade (leveraging slat overlap/thickness).

**Key concept:** Due to the slat geometry (w=22 cm, t=3 cm, d=20 cm pivot spacing, R=0.91926, phi=8.53°), the slats overlap. There is a range of angles (the "safe zone") that all provide full shade. The max-open formula targets the far edge of this zone to maximize airflow while maintaining shade. When the sun is high enough, the safe zone includes even larger angles, giving more airflow.

**TBD:** Exact formula to be derived and agreed — see [pergola-slat-formula-analysis.md](pergola-slat-formula-analysis.md) Section 3 (Gemini "max open" formula) and Section 3 (safe zone table). The dead zone handling for the optimized mode also needs to be specified (likely the "backside block" angle from Gemini formula 5).

**Dependencies:** Step 3 (cover response and cooling formula must exist), `input_boolean.pergola_cooling_optimized` added in Step 1 update.

**Verify:**
- Toggle `pergola_cooling_optimized` off → perfect perpendicular angle applied, slats track sun tightly
- Toggle `pergola_cooling_optimized` on → slats open further (more airflow) but still block sun

---

### Phase 5 — Calibration & Validation

#### Step 6 — Field Testing & Threshold Tuning [TODO]
**Dependencies:** Steps 1–4 deployed and running for at least one sunny + one rainy day.

| Item | Action |
|---|---|
| PV conversion factor | Clear morning: adjust `pergola_pv_conversion_factor` until `PV power / factor ≈ solar_radiation` |
| Clearness factor (0.9) | Partly cloudy afternoon: check `pergola_sun_shining` on/off boundary feels correct |
| Sun azimuth window | Observe shadows — fine-tune 114°/294° if needed |
| Post-rain tilt values | Confirm 25%/50% drains adequately; adjust in script if not |
| Rain lock originator | Log `sensor.dach_links_priority_lock_originator` during rain; verify covers can move after rain stops |

---

## Remaining TBD Items

| # | Item | Blocking |
|---|---|---|
| 1 | ~~Solar radiation threshold~~ | Resolved — `binary_sensor.pergola_sun_shining` dynamic formula |
| 1b | ~~`sensor.pergola_pv_power` entity ID~~ | Resolved — wraps `sensor.victronsolarcharger_yield_power226` |
| 1c | PV conversion factor (default 3.2) | Calibrate in Step 6 |
| 2 | ~~Sun azimuth window~~ | Resolved — 114°–294° (204° ± 90°) |
| 2b | ~~HA GPS coordinates~~ | Resolved — `zone.home` matches within 4 m |
| 3 | ~~Heating indicator entity~~ | Resolved — `input_boolean.pergola_heating` (local toggle, set via UI or REST API) |
| 4 | ~~Room temperature target~~ | Resolved — not used; mode driven by heating indicator only |
| 5 | Post-rain slat angles (8°, 15°) | Confirm drainage adequate after first real rain |
| 6 | ~~Rain lock originator string value~~ | Resolved — values are `unknown` (no lock), `rain` (rain lock), `user` (user override). Timer counts down from 900 s after rain stops; driven by inactivity watchdog every 5 min |
| 7 | ~~Slat angle formula (cooling + heating season)~~ | Resolved — cooling: perpendicular blocking angle; heating: parallel alignment angle (perfect_angle - 90°). See [formula analysis](pergola-slat-formula-analysis.md) |
| 8 | Optimized cooling formula (safe-zone max-open) | Step 7 — formula to be defined before implementation |
| 9 | Reconfirm which tilt the system has on a vertical 90 degree angle in real physical position to maybe adapt the algorithm |
