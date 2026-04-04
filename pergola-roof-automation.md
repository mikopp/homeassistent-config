# Pergola Roof Automation — Implementation Plan

## Context
The two Somfy bioclimatic pergola covers (`cover.dach_links`, `cover.dach_rechts`) on the
terrasse currently have no automatic tilt control. They are controlled from Loxone and synced
back to HA via existing automations. The goal is to add fully automatic sun-following /
sun-blocking logic with frost safety, post-rain recovery, and seasonal heating/cooling modes.
Both covers always move together as one unit.

**Tilt scale:** 0 = horizontal/closed (maximum shade / rain protection), 71 ≈ vertical (90°),
100 = 125° open. Full angular range = 125°.
Formula: `slat_angle_degrees = tilt_position × 1.25`  →  `tilt_position = slat_angle_degrees / 1.25`

---

## Entity Reference

### Covers
| Entity | Description |
|---|---|
| `cover.dach_links` | Left pergola cover (tilt 0–100) |
| `cover.dach_rechts` | Right pergola cover (tilt 0–100) |
| `sensor.dach_links_priority_lock_originator` | What locked the cover (wind, rain, manual…) |
| `sensor.dach_rechts_priority_lock_originator` | Same for right |

### Sun
| Entity | Description |
|---|---|
| `sun.sun` | State: `above_horizon` / `below_horizon` |
| `state_attr('sun.sun', 'elevation')` | Degrees above horizon |
| `state_attr('sun.sun', 'azimuth')` | Compass bearing 0–360° |

### Weather Station (Ecowitt — entity prefix: `sensor.wheatherstation_`)
| Entity | Unit | Description |
|---|---|---|
| `sensor.wheatherstation_outdoor_temperature` | °C | Outdoor temp — used for frost safety |
| `sensor.wheatherstation_indoor_temperature` | °C | Indoor/room temp — used in heating season |
| `sensor.wheatherstation_rain_rate` | mm/h | > 0 = currently raining |
| `sensor.wheatherstation_hourly_rain` | mm | Rain in last 60 min |
| `sensor.wheatherstation_solar_radiation` | W/m² | Actual solar irradiance (goes into shadow in the afternoon) |
| `sensor.wheatherstation_uv_index` | UV index | Additional sun indicator |

### PV & Derived Sun Sensor
| Entity | Unit | Description |
|---|---|---|
| `sensor.pergola_pv_power` | W | Template sensor wrapping `sensor.victronsolarcharger_yield_power226` — stable alias used throughout the package |
| `sensor.victronsolarcharger_yield_power226` | W | Raw Victron solarcharger aggregate DC PV power (device model 226; per-tracker breakdown not available on this unit) |
| `binary_sensor.pergola_sun_shining` | on/off | Derived: true when PV+radiation exceed elevation-adjusted clear-sky threshold |

### Helpers to Create (in `configuration.yaml`)
| Helper | Purpose |
|---|---|
| `input_boolean.pergola_automatic_enabled` | Master on/off switch for all automation |
| `input_boolean.pergola_frost_hold` | Set by frost monitor; blocks automation |
| `input_boolean.pergola_post_rain_active` | Set during post-rain sequence; blocks automation |
| `input_number.pergola_frost_off_threshold` | Temp below which frost hold activates (default: 2.5°C) |
| `input_number.pergola_frost_on_threshold` | Temp above which frost hold clears (default: 3.0°C) |
| `input_number.pergola_pv_conversion_factor` | PV W → W/m² divisor for sun detection (default: 3.2; tune until PV proxy ≈ weather station on a clear morning when both are in sun) |

### Future Entities (not yet in HA)
| Entity | Description |
|---|---|
| `sensor.loxone_heating_season` | Boolean/flag from Loxone: 1 = heating season, 0 = cooling |
| Room temperature target | Threshold for capping heating-season sun-in mode (value TBD) |

---

## Tilt Calculation Logic

### Cooling season — block sun
Slats perpendicular to sun rays to maximise shade:
```
slat_angle = 90 − sun_elevation
tilt_position = (90 − sun_elevation) / 1.25    clamped to [0, 100]
```
Examples: elevation 90° → tilt 0 (flat, overhead sun fully blocked)  
elevation 30° → tilt 48  /  elevation 10° → tilt 64

### Heating season — let sun in
Slats parallel to sun rays so sunlight passes through:
```
tilt_position = sun_elevation / 1.25    clamped to [0, 100]
```
Suspended once `sensor.wheatherstation_indoor_temperature` reaches the room target
threshold (value TBD — fill in once decided).

### "Not enough sun" → open fully (tilt = 100)
Skip sun-tracking and go to full open when `binary_sensor.pergola_sun_shining` = `off`.

The binary sensor implements a clearness-index approach derived from the Loxone Wetter sheet:
```
effective_radiation = max(
  sensor.wheatherstation_solar_radiation,        # W/m² — weather station (shaded in afternoon)
  sensor.pergola_pv_power / pergola_pv_conversion_factor  # W/m² proxy — PV in sun longer
)
threshold = 1000 × sin(sun_elevation_rad) × 0.9  # 90% of theoretical clear-sky radiation
sun_shining = (effective_radiation > threshold) AND (elevation > 10°)
```

**Why two sources:** The weather station sensor goes into shadow in the afternoon. The
6 × 440 W Axitec AXIbiperfect panels (228° azimuth, 5–10° tilt) remain in sun longer and
produce more than the STC factor (2.64) predicts due to bifacial gain (~20%) and favourable
afternoon geometry — hence the tunable `input_number.pergola_pv_conversion_factor` (start 3.2).

**Calibration:** On a clear morning when both sources are in sun, adjust `pergola_pv_conversion_factor`
until `sensor.pergola_pv_power / factor ≈ sensor.wheatherstation_solar_radiation`.
Fine-tune the 0.9 clearness factor if the on/off boundary is too aggressive or lenient.

### Sun behind house → suspend automation
Terrasse faces **204°** (SSW). Sun is on the terrasse side when azimuth is **114°–294°**.
```
suspend when: sun.azimuth < 114  OR  sun.azimuth > 294
```
> **TBD:** Confirm or adjust this window after a few days of observation.

---

## Automation Master Block Conditions

All automatic cover movement is suspended when **any** of these are true:

| # | Condition | Reason |
|---|---|---|
| 1 | `input_boolean.pergola_automatic_enabled` = `off` | Manual override |
| 2 | `input_boolean.pergola_frost_hold` = `on` | Frost safety |
| 3 | `input_boolean.pergola_post_rain_active` = `on` | Post-rain sequence running |
| 4 | `sun.sun` = `below_horizon` | No sun |
| 4b | `binary_sensor.pergola_sun_shining` = `off` | Overcast / insufficient radiation → open fully instead |
| 5 | `sun.azimuth` outside 114°–294° | Sun behind house |
| 6 | `sensor.dach_links_priority_lock_originator` ≠ `unknown` | Active Loxone lock (wind, manual…) |

---

## Post-Rain Recovery Sequence

**Rain detection:** `sensor.wheatherstation_rain_rate > 0` = active rain.  
**Rain stopped trigger:** `sensor.wheatherstation_rain_rate` transitions to `0`.

**Script: `script.pergola_post_rain_recovery`**
1. Set `input_boolean.pergola_post_rain_active = on`
2. Set tilt → **25%** (slight opening to drain pooled water)
3. Wait **5 min**
4. Set tilt → **50%**
5. Wait **10 min**
6. Check `sensor.wheatherstation_hourly_rain`:
   - If `== 0` (no rain in last 60 min) → proceed to step 8
   - If `> 0` → wait **60 more min**, then proceed to step 8
7. *(waiting branch — handled by the delay in step 6)*
8. Set `input_boolean.pergola_post_rain_active = off` → automatic tilt resumes

> **TBD:** Tilt values of 25% and 50% are provisional. Adjust after first real test.

---

## Frost Safety

Hysteresis to prevent oscillation at the threshold:
- Outdoor temp falls **below `input_number.pergola_frost_off_threshold`** (2.5°C):
  → `input_boolean.pergola_frost_hold = on` — all automatic movement stops.
- Outdoor temp rises **above `input_number.pergola_frost_on_threshold`** (3.0°C):
  → `input_boolean.pergola_frost_hold = off` — automatic movement resumes.

Sensor: `sensor.wheatherstation_outdoor_temperature`

---

## Step-by-Step Implementation

Each step is independently deployable and testable via `git pull` on the HA host.

---

### Step 1 — Helpers & Sun Sensor
**File:** `packages/pergola.yaml`  
All pergola-specific YAML lives here. The global `configuration.yaml` loads it via
`homeassistant: packages: !include_dir_named packages`.

Add `input_boolean:`, `input_number:`, and `template:` sections.

```yaml
input_boolean:
  pergola_automatic_enabled:
    name: Pergola Automatic Enabled
    icon: mdi:sun-clock
  pergola_frost_hold:
    name: Pergola Frost Hold
    icon: mdi:snowflake-alert
  pergola_post_rain_active:
    name: Pergola Post-Rain Sequence Active
    icon: mdi:weather-rainy

input_number:
  pergola_frost_off_threshold:
    name: Pergola Frost OFF threshold
    min: -10
    max: 5
    step: 0.5
    initial: 2.5
    unit_of_measurement: "°C"
    icon: mdi:thermometer-low
  pergola_frost_on_threshold:
    name: Pergola Frost ON threshold
    min: -10
    max: 5
    step: 0.5
    initial: 3.0
    unit_of_measurement: "°C"
    icon: mdi:thermometer
```

Also add `input_number.pergola_pv_conversion_factor` (min 1, max 6, step 0.1, initial 3.2)
and the `template:` block containing `binary_sensor.pergola_sun_shining`.

**Verify:** All helpers visible in HA → Developer Tools → States.
Evaluate the template binary sensor manually via Developer Tools → Template using current
solar radiation and PV power values and confirm the result matches visual sky conditions.

---

### Step 2 — Main Tilt Control (cooling season only)
**File:** `packages/pergola.yaml` — add under the `automation:` key  
Add automation `pergola_main_tilt_control`. At this stage implements cooling-season
logic only; heating season is a later step.

Triggers:
- Time pattern: every 5 minutes
- `sun.sun` attribute change (elevation or azimuth)
- Any `input_boolean.pergola_*` state change

Conditions: all six master block conditions clear (see table above).

Action: if `binary_sensor.pergola_sun_shining` = `off` → tilt = 100 (full open); else compute
cooling formula and call `cover.set_cover_tilt_position` on both covers.

**Verify:**
- Enable `input_boolean.pergola_automatic_enabled` and confirm covers move to expected
  tilt within 5 min.
- Disable the boolean and confirm covers stop being controlled.
- Check sun-behind-house condition fires correctly (use Developer Tools → Template to
  evaluate azimuth condition).

---

### Step 3 — Frost Safety
**File:** `packages/pergola.yaml` — add under the `automation:` key  
Add automation `pergola_frost_monitor`.

Trigger: `sensor.wheatherstation_outdoor_temperature` state change.  
Action (two branches via choose):
- If temp < `input_number.pergola_frost_off_threshold` AND frost_hold is off
  → set `input_boolean.pergola_frost_hold = on`
- If temp > `input_number.pergola_frost_on_threshold` AND frost_hold is on
  → set `input_boolean.pergola_frost_hold = off`

**Verify:**
- Temporarily lower `pergola_frost_off_threshold` to current outdoor temp via the UI
  and confirm `pergola_frost_hold` turns on and covers stop responding.
- Raise threshold back and confirm hold clears.

---

### Step 4 — Post-Rain Recovery
**File:** `packages/pergola.yaml` — add under `automation:` and `script:` keys

**`automation:`** Add `pergola_post_rain_trigger`.
- Trigger: `sensor.wheatherstation_rain_rate` changes to `0` (from > 0)
- Condition: `input_boolean.pergola_post_rain_active` is off (no double-trigger)
- Action: call `script.pergola_post_rain_recovery`

**`script:`** Add `pergola_post_rain_recovery`.
- Stepped opening sequence as described above (steps 1–8).
- Use `delay` actions for the wait periods.
- Use `wait_template` for the conditional hourly-rain check at step 6.

**Verify:**
- Manually trigger the script from Developer Tools and watch cover positions over ~20 min.
- Confirm `input_boolean.pergola_post_rain_active` clears at the end.
- Confirm that once the flag clears, the main tilt control resumes automatically on next
  trigger cycle.

> **TBD:** During the next real rain event, note the value of
> `sensor.dach_links_priority_lock_originator` while it rains — this confirms whether
> the Overkiz/Loxone lock also needs to be respected in the trigger condition.

---

### Step 5 — Heating Season Logic
**File:** `packages/pergola.yaml` (update `pergola_main_tilt_control` under `automation:`)

Prerequisites:
- `sensor.loxone_heating_season` entity exists and carries `1` / `0` (or `on` / `off`)
- Room temperature target threshold decided (currently TBD — fill in below)

> **TBD:** Room temperature target = **___°C** (the indoor temp above which we stop
> trying to let sun in, even in heating season).

Update the main tilt control action to check `sensor.loxone_heating_season`:
- Heating season AND `sensor.wheatherstation_indoor_temperature` < target
  → use heating formula (`tilt = elevation / 1.25`)
- Heating season AND indoor temp ≥ target
  → use cooling formula (don't let more heat in)
- Cooling season
  → use cooling formula

**Verify:**
- With heating season flag active and indoor temp below target, confirm covers use the
  heating formula.
- Simulate indoor temp above target (via a template override) and confirm it switches
  to cooling formula.

---

### Step 6 — Field Testing & Threshold Tuning

Work through these after real-world observation:

| Item | Action |
|---|---|
| PV conversion factor | On a clear morning, adjust `input_number.pergola_pv_conversion_factor` until `sensor.pergola_pv_power / factor ≈ sensor.wheatherstation_solar_radiation` |
| Clearness factor (0.9) | On a partly cloudy afternoon, check if `binary_sensor.pergola_sun_shining` on/off boundary feels right; tune via the template sensor |
| Sun azimuth window | Observe shadows on terrasse; adjust 114°/294° bounds if needed |
| Post-rain tilt values | Confirm 25% / 50% drain adequately; adjust if water remains |
| Rain lock originator | Log value of `sensor.dach_links_priority_lock_originator` during rain; update Step 4 trigger if needed |
| Seasonality formula | If simple solar-radiation threshold isn't enough, add a seasonal correction factor here |

---

## Remaining TBD Items

| # | Item | Where to fill in |
|---|---|---|
| 1 | ~~Solar radiation "enough sun" threshold~~ | **Resolved** — `binary_sensor.pergola_sun_shining` (dynamic clearness-index formula) |
| 1b | ~~`sensor.pergola_pv_power` entity ID~~ | **Resolved** — template sensor wrapping `sensor.victronsolarcharger_yield_power226` (Victron solarcharger, model 226) |
| 1c | PV conversion factor (default 3.2) | Calibrate on a clear morning; adjust via `input_number.pergola_pv_conversion_factor` |
| 2 | Sun azimuth window confirmation | Step 2 / "Sun behind house" section above |
| 3 | Loxone heating season entity ID | Step 5 prerequisites |
| 4 | Room temperature target (°C) | Step 5 section above |
| 5 | Post-rain tilt values (25%, 50%) | Post-Rain sequence section above |
| 6 | Rain lock originator string | Step 4 verify note |
