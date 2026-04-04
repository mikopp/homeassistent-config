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

** References **
* Loxone config file: `C:\Users\mikop\Documents\Loxone\Loxone Config\Projects\Haus.Loxone`
* Loxone config documentation: https://www.loxone.com/enen/kb-cat/loxone-config/

**TBD items blocking later steps:**
- Loxone heating season entity ID (Step 5) — confirmed: Loxone sends a binary heat on/off indicator
- Room temperature ignored — heating/cooling mode is determined solely by the Loxone indicator
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

> **Lock originator values:**
> - `unknown` — no active lock, cover moves freely
> - `rain` — cover-mounted rain sensor triggered; Somfy closed and locked the cover automatically (faster than weather station)
> - `user` — a user has manually blocked the cover; automation must not move it
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

### Future Entities (not yet in HA)
| Entity | Description |
|---|---|
| `sensor.loxone_heating_season` | Boolean from Loxone: 1 = heating season, 0 = cooling |

---

## Pergola Device

All entities created by this feature will appear under a single HA virtual device named **"Pergola Dach"** (`identifier: pergola_dach`). This allows the user to find and control everything in one place via Settings → Devices.

**Implementation note:** HA's `template:` integration supports a `device:` block that groups template entities under a virtual device directly in YAML. `input_*` helpers (config values) do not support YAML device assignment — they must be manually assigned to the "Pergola Dach" device via the HA UI after creation (Settings → Devices & Services → [each helper] → Change device).

### All entities on the device

#### Config — user-changeable in HA UI
| Entity | Type | Default | Purpose |
|---|---|---|---|
| `input_boolean.pergola_automatic_enabled` | toggle | on | Master on/off — disables all cover movement when off |
| `input_select.pergola_automation_state` | select | — | State machine; **can be set manually to break a deadlock** |
| `input_number.pergola_frost_off_threshold` | number | 2.5 °C | Temp below which frost mode activates |
| `input_number.pergola_frost_on_threshold` | number | 3.0 °C | Temp above which frost mode clears |
| `input_number.pergola_pv_conversion_factor` | number | 3.2 | PV W → W/m² divisor for sun detection (calibrate in Step 6) |
| `input_number.pergola_max_tilt_angle` | number | 122 ° | Maximum physical slat angle; drives tilt_position conversion |

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
| `sun_automatik_heating` | Sun active, Loxone heating indicator on | Heating formula |
| `sun_automatik_cooling` | Sun active, Loxone heating indicator off | Cooling formula |

### Priority Rules (highest first)

1. **frost** — temp < `pergola_frost_off_threshold` → enter `frost`. Clears when temp > `pergola_frost_on_threshold`. On exit: if `wheatherstation_hourly_rain > 0` → enter `rain_stopped` (post-rain recovery); otherwise re-evaluate remaining rules.
2. **rain** — enter when **either** indicator is active:
   - `sensor.wheatherstation_rain_rate > 0` (weather station — slower, delayed), OR
   - `sensor.dach_links_priority_lock_originator = rain` OR `sensor.dach_rechts_priority_lock_originator = rain` (cover-mounted rain sensor — fast, no delay)

   Exit rain only when **both** indicators are off:
   - `rain_rate == 0` AND both lock originators = `unknown` (not `rain`)

   Condition: state ≠ `frost`
3. **rain_stopped** — was `rain`, both indicators now off → enter `rain_stopped`. Script exits this state.
4. **user_override** — either lock originator = `user`. Clears when both = `unknown`. Cover response automation skips all movement while in this state.
5. **no_sun_behind_house** — sun below horizon OR azimuth outside 114°–294° (geometric — no sun possible regardless of sensor).
6. **not_enough_sun** — `pergola_sun_shining` has been `off` for ≥ 5 continuous minutes. Exits when `pergola_sun_shining` has been `on` for ≥ 2 continuous minutes.
7. **sun_automatik_heating** — `sensor.loxone_heating_season` = on/1.
8. **sun_automatik_cooling** — default when sun is active and heating indicator is off.

---

## Tilt Calculation Logic

Tilt calculation is a two-step process: first compute the desired **slat_angle** (degrees), then convert to **tilt_position** (0–100) using the hardware correction formula.

### Step 1 — Desired slat angle

#### Cooling season (`sun_automatik_cooling`) — block sun
```
slat_angle = <TBD — to be specified>    clamped [0°, 90°]
```

#### Heating season (`sun_automatik_heating`) — let sun through
```
slat_angle = <TBD — to be specified>    clamped [0°, 122°]
```

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
- Clamp result: cooling → [0, 71]; heating → [0, 100]
- Values > 100 are dead zone on the Somfy controller — never send them

**Why corrections are needed:**
- Below 20°: motor displacement is very small → +7 compensates
- 20°–69°: linear region → +5.5 rounds up correctly
- Above 69°: slight mechanical jerk → only +0.5 to avoid overshoot

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
> **TBD:** Verify `sensor.dach_links_priority_lock_originator` clears promptly after rain.

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
- `input_select.pergola_automation_state` must list all 8 state values — **currently missing from pergola.yaml**
- PV conversion factor (default 3.2) calibrated in Step 6
- **Current pergola.yaml needs adapting:** remove `input_boolean.pergola_frost_hold` and `input_boolean.pergola_post_rain_active` (superseded by the state machine); add `input_select.pergola_automation_state` with all 8 options
- `input_boolean.pergola_automatic_enabled`, all `input_number` helpers, and both existing template sensors are already correct — keep as-is
- Add `input_number.pergola_max_tilt_angle` (default 122, min 100, max 135, step 1, unit °)
- Add `sensor.pergola_slat_angle` (unit °, unknown until formula defined in Step 3) and `sensor.pergola_tilt_position` (0–100, unknown until Step 3) as stub template sensors returning `unknown` for now — they exist on the device from day one
- All template sensors and binary sensors (`sensor.pergola_pv_power`, `sensor.pergola_slat_angle`, `sensor.pergola_tilt_position`, `binary_sensor.pergola_sun_shining`) must share the same `template:` block that carries the `device:` declaration

**Post-deploy (one-time, manual via HA UI):**
After first `git pull` and HA restart, manually assign each `input_*` helper to the "Pergola Dach" device:
Settings → Devices & Services → Helpers → [select each helper] → change device → "Pergola Dach"
Helpers to assign: `pergola_automatic_enabled`, `pergola_automation_state`, `pergola_frost_off_threshold`, `pergola_frost_on_threshold`, `pergola_pv_conversion_factor`, `pergola_max_tilt_angle`

**Verify:**
- Settings → Devices → "Pergola Dach" shows all 10 entities
- `input_select.pergola_automation_state` shows all eight options
- `binary_sensor.pergola_sun_shining` changes state plausibly with sun conditions
- `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` report `unknown` (correct at this stage)

---

#### Step 2 — State Manager Automation [TODO]
**File:** `packages/pergola.yaml` — add under `automation:`

Add `pergola_state_manager`. This is the **only automation that writes** to `input_select.pergola_automation_state`.

Triggers: outdoor temp, rain rate, sun attributes, `pergola_sun_shining`, heating season flag, HA start.

Action: evaluate priority rules top-down (frost → rain → rain_stopped → no_sun_behind_house → not_enough_sun → heating → cooling).

**Dependencies:** Step 1 (helpers must exist).

**Notes:**
- Guard: do not overwrite `rain_stopped` — only the recovery script exits that state
  - Exception: frost exit triggers a one-time check — if `wheatherstation_hourly_rain > 0`, explicitly set state to `rain_stopped` to kick off recovery
- `sensor.loxone_heating_season` may not exist yet; use a safe default (cooling season) when unavailable
- HA start trigger ensures correct state on boot/restart
- `not_enough_sun` entry/exit requires time-delayed transitions — use separate automations with `for:` timers rather than a single choose block:
  - Entry: trigger on `pergola_sun_shining` turning `off` **for 5 min**, condition state ≠ frost/rain/rain_stopped/no_sun_behind_house
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
- `sun_automatik_cooling` → cooling formula, clamped [0, 71]
- `sun_automatik_heating` → stub: tilt 71 (replaced in Step 5)

**Dependencies:** Step 1 (helpers), Step 2 (state machine must be writing state).

**Notes:**
- Every-5-min trigger is the only way covers track a slowly moving sun within a steady state
- Cooling clamp upper bound is 71, not 100 — never past vertical in cooling mode
- Fill in the stub template sensors from Step 1: `sensor.pergola_slat_angle` and `sensor.pergola_tilt_position` should reflect the current calculated values based on state + sun position (update the template body, not just the automation)

**Verify:**
- Disable `pergola_automatic_enabled` → covers stop responding
- With sun active and cooling season, covers move to formula result within 5 min
- Manually set state to `no_sun_behind_house` → tilt goes to 71

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
- `sensor.loxone_heating_season` entity exists and carries `on`/`off` (or `1`/`0`) — entity ID TBD

**Room temperature is NOT used** — heating/cooling mode is determined solely by the Loxone indicator.

Update `sun_automatik_heating` branch of `pergola_cover_response`:
- Compute `slat_angle` (heating formula — TBD), convert to `tilt_position` using hardware correction formula, clamp [0, 100]

Update state manager: when sun is active and `sensor.loxone_heating_season = on` → `sun_automatik_heating`; otherwise → `sun_automatik_cooling`.

**Dependencies:** Step 3 (cover response stub must exist), `sensor.loxone_heating_season` available in HA.

**Notes:**
- Until `sensor.loxone_heating_season` exists, state manager stays in cooling mode by default

**Verify:**
- With Loxone heating indicator on → heating formula applied
- With Loxone heating indicator off → state transitions to `sun_automatik_cooling`

---

### Phase 4 — Calibration & Validation

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
| 3 | `sensor.loxone_heating_season` entity ID | Step 5 — confirmed: Loxone sends binary heat on/off |
| 4 | ~~Room temperature target~~ | Resolved — not used; mode driven by Loxone indicator only |
| 5 | Post-rain slat angles (8°, 15°) | Confirm drainage adequate after first real rain |
| 6 | ~~Rain lock originator string value~~ | Resolved — values are `unknown` (no lock), `rain` (rain lock), `user` (user override) |
| 7 | Slat angle formula (cooling + heating season) | Step 3/5 — user to provide; tilt_position conversion formula already defined |
