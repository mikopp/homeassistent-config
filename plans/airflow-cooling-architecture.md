# Airflow Cooling & Humidity — Architecture Design

**Scope:** `packages/airflow_cooling.yaml` (+ `packages/heating_cooling_indicator.yaml`)
**Hardware:** Zehnder ComfoAir Q350 ERV via the ComfoConnect integration
**Status:** Living document — reflects the dew-point + dew-difference-flush design.

> Related plans: [ventilation-profile-automation.md](ventilation-profile-automation.md),
> [airflow-threshold-inputs-humidity-fallback.md](airflow-threshold-inputs-humidity-fallback.md),
> [airflow-bypass-sensor.md](airflow-bypass-sensor.md).

---

## 1. Purpose

Drive the ERV's **temperature profile** (`warm` / `comfort` / `cool`) and **ventilation level**
(auto / low / medium / boost) automatically, to:

1. **Free-cool** the house when outdoor air is cool and dry enough (open the bypass).
2. **Flush indoor moisture** when indoor air is too humid and outdoor air is drier — even when
   the target humidity can't be reached (mould / condensation safety).
3. **Protect** against importing humid outdoor air (reduce ventilation).
4. **Retain moisture** in dry winter air (keep the heat exchanger recovering).

Every humidity decision is expressed in **dew point** (absolute moisture) rather than relative
humidity, because RH thresholds drift as indoor temperature changes. All dew thresholds are
computed at the **target temperature** via the Magnus formula.

---

## 2. Entity inventory

### Inputs — filter sensors (5-min time-weighted average, throttled)

| Entity | Source | Meaning |
|---|---|---|
| `sensor.airflow_min_indoor_dew_5min` | indoor dew aggregate | **indoor moisture** |
| `sensor.airflow_avg_indoor_temp_5min` | indoor temp aggregate | indoor temperature |
| `sensor.airflow_avg_indoor_humidity_5min` | indoor RH aggregate | indoor RH (display) |
| `sensor.airflow_outdoor_dew_5min` | ComfoConnect intake | **outdoor moisture** |
| `sensor.airflow_outdoor_temp_5min` | ComfoConnect intake | **ComfoConnect outdoor temp** |
| `sensor.airflow_wheatherstation_outdoor_temp_5min` | weather station (filtered) | **real outdoor temp, smoothed** |
| supply/extract air temp+humidity | ComfoConnect | bypass estimation |

> **Two outdoor temperatures:** the ComfoConnect intake temp (`airflow_outdoor_temp_5min`) gates
> the *cool-profile* logic; the smoothed weather-station temp (`airflow_wheatherstation_outdoor_temp_5min`,
> same 5-min filter chain) gates only the *boost*. Smoothing replaces the boost sensor's old
> `delay_on` debounce — noise spikes can no longer falsely start/stop a boost.

### Derived thresholds — dew point at target temp (Magnus)

| Entity | From helper | Used as |
|---|---|---|
| `sensor.airflow_dew_point_min` | `airflow_min_humidity` | dry-air floor (moisture retention) |
| `sensor.airflow_dew_point_target` | `airflow_target_humidity` | comfort target / free-cooling ceiling |
| `sensor.airflow_dew_point_max` | `airflow_max_humidity` | moisture-problem ceiling |

### Decision binary sensors

| Entity | Fires when | Debounce |
|---|---|---|
| `binary_sensor.airflow_free_cooling_available` | outdoor cool **and** dry enough to free-cool | `delay_on`/`delay_off` 10 min |
| `binary_sensor.airflow_humidity_flush_needed` | indoor too humid **and** outdoor drier (cool-profile flush) | `delay_on`/`delay_off` 10 min |
| `binary_sensor.airflow_moisture_ventilation_low_needed` | outdoor too humid to import | `delay_on`/`delay_off` 10 min |
| `binary_sensor.airflow_humidity_drying_needed` | flush **and** weather-gated (smoothed) **and** scheduled (boost) | `delay_off` 10 min only |

> **`drying_needed` has no `delay_on`.** Its temp input is now the smoothed
> `airflow_wheatherstation_outdoor_temp_5min`, so the 5-min filter absorbs noise that `delay_on`
> used to guard against. Dropping `delay_on` cuts boost start latency by 10 min (was flush 10 +
> drying 10 = 20 min; now ~10 min). `delay_off` kept to avoid premature boost stop.

### Actuators (ComfoConnect)

`select.comfoconnect_pro_temperature_profile` (warm/comfort/cool) ·
`switch.comfoconnect_pro_boost` + `number.comfoconnect_pro_boost_time` ·
`select.comfoconnect_pro_ventilation_preset` (low/medium) + `switch.comfoconnect_pro_auto_mode`.

### Read-only views

`climate.airflow_climate` (hvac_mode + hvac_action) · `sensor.airflow_cooling_state`
(reason-based status) · `sensor.airflow_bypass_estimation`.

---

## 3. Data flow

```mermaid
flowchart LR
    subgraph RAW["ComfoConnect / weather (raw)"]
        OAT["outdoor temp"]
        OAD["outdoor dew"]
        WS["weather-station temp"]
        IND["indoor dew / temp / RH"]
    end

    subgraph FILT["5-min filter sensors"]
        F1["outdoor_temp_5min"]
        F2["outdoor_dew_5min"]
        F3["indoor dew / temp / RH 5min"]
        F4["wheatherstation_outdoor_temp_5min"]
    end

    subgraph HELP["input_number helpers"]
        H1["target_temp"]
        H2["min / target / max humidity"]
        H3["min_dew_diff / min_temp_diff"]
    end

    subgraph THR["dew thresholds @ target_temp"]
        D1["dew_point_min"]
        D2["dew_point_target"]
        D3["dew_point_max"]
    end

    subgraph DEC["decision binary sensors (10-min debounce)"]
        FC["free_cooling_available"]
        FL["humidity_flush_needed"]
        LO["moisture_ventilation_low_needed"]
        DR["humidity_drying_needed"]
    end

    subgraph AUT["automations"]
        A1["ventilation_controller<br/>(profile + preset + auto_mode)"]
        A3["humidity_drying_boost<br/>(boost only)"]
    end

    subgraph ACT["ComfoConnect actuators"]
        P["temperature_profile"]
        BO["boost"]
        VP["ventilation preset + auto_mode"]
    end

    SEASON["sensor.heating_cooling_indicator<br/>(48h-mean season state machine)"]

    RAW --> FILT
    OAT --> F1
    OAD --> F2
    IND --> F3
    WS --> F4
    HELP --> THR
    FILT --> DEC
    THR --> DEC
    F4 --> DR
    SEASON --> A1
    FL --> DR
    LO --> DR

    FC --> A1
    FL --> A1
    SEASON --> FL
    DEC --> AUT
    A1 --> P
    A1 --> VP
    A3 --> BO
    P --> CLIM["climate.airflow_climate<br/>hvac_action"]
    BO --> CLIM
    CLIM --> CS["sensor.airflow_cooling_state"]
```

---

## 4. Season state machine — `sensor.heating_cooling_indicator`

A Schmitt-trigger state machine over the **48-hour mean** outdoor temperature
(`sensor.wheatherstation_outdoor_temperature_48h_mean`). Wide hysteresis bands prevent the
season from flapping day-to-day. This is the **season context** consumed by the profile logic.

```mermaid
stateDiagram-v2
    [*] --> neutral
    active_heating --> neutral: mean ≥ 6 °C
    neutral --> active_heating: mean ≤ 5 °C
    neutral --> passive_cooling: mean ≥ 11 °C
    passive_cooling --> neutral: mean ≤ 10 °C
    passive_cooling --> active_cooling: mean ≥ 16 °C
    active_cooling --> passive_cooling: mean ≤ 15 °C

    note right of neutral
        "cooling season" = passive_cooling OR active_cooling
    end note
```

---

## 5. Decision sensors

### 5.1 `free_cooling_available` — temperature free cooling

All four must hold (indoor-temp uses a 0.5 °C Schmitt: ON at `target`, stays on to `target − 0.5`):

```
(outdoor_dew + min_dew_diff) < indoor_dew      # outdoor drier by a margin
AND outdoor_dew ≤ dew_point_target             # importing it won't exceed target humidity
AND outdoor_temp_5min < target − min_temp_diff # ComfoConnect intake cool enough
AND indoor_temp ≥ temp_threshold               # room warm enough to want cooling
```

### 5.2 `humidity_flush_needed` — cool-profile moisture flush

Two OR branches, both requiring a real outdoor→indoor moisture **difference**
(`margin_ok = outdoor_dew + min_dew_diff − h < indoor_dew`). A `0.3 °C` `this.state` hysteresis
(`h`) relaxes every boundary while ON.

```mermaid
flowchart TD
    S(["evaluate flush_needed"]) --> M{"margin_ok?<br/>outdoor drier than indoor by min_dew_diff"}
    M -- no --> OFF["OFF"]
    M -- yes --> B1{"Branch 1 — moisture PROBLEM<br/>indoor dew above dew_max<br/>AND outdoor dew below dew_max"}
    B1 -- yes --> SEAS1{"season =<br/>active_heating?"}
    SEAS1 -->|either| ONp["ON — flush regardless of temperature"]
    B1 -- no --> SEAS2{"season =<br/>active_heating?"}
    SEAS2 -- yes --> OFF
    SEAS2 -- no --> B2{"Branch 2 — above TARGET only<br/>indoor dew above dew_target<br/>AND outdoor dew at/below dew_target"}
    B2 -- no --> OFF
    B2 -- yes --> TG{"ComfoConnect temp gate?<br/>outdoor_temp_5min below target−min_temp_diff<br/>AND indoor_temp at/above target"}
    TG -- yes --> ONt["ON — cool flush (temp-guarded)"]
    TG -- no --> OFF
```

Key asymmetry:
- **Branch 1** (indoor above max = a real problem) → flushes **regardless of temperature**.
- **Branch 2** (above target only) → flushes **only if** the ComfoConnect temp gate holds, so a
  non-urgent flush never overcools a cool room.
- In **active_heating**, only Branch 1 is allowed.

### 5.3 `moisture_ventilation_low_needed` — humid-import protection

Indoor Schmitt (`indoor_dew ≥ dew_max` ON, stays on to `dew_target`) AND
(`outdoor_dew ≥ dew_threshold` OR `outdoor_dew ≥ indoor_dew`). Broadly the inverse of free
cooling: outdoor air is too humid to bring in.

### 5.4 `humidity_drying_needed` — the noisy boost

```
flush_needed
AND NOT low_active
AND airflow_wheatherstation_outdoor_temp_5min < target_temp  # smoothed REAL outdoor, not intake
AND in_schedule                                              # workday / non-workday window
```

The cool-profile flush deliberately **ignores** the schedule and weather station; only the boost
is schedule- and weather-gated. The temp input is the **smoothed** weather-station sensor
(`| float(99)` fail-safe kept: unavailable → 99 °C → gate fails → no boost). `delay_on` removed;
`delay_off` 10 min kept (see §2 decision-sensor note).

---

## 6. Temperature profile selection — the core decision

Profile is **Section 1** of the unified `automation.airflow_ventilation_controller` (mode: queued,
see §7). Triggers: season change, `free_cooling_available`, `humidity_flush_needed`,
`moisture_ventilation_low_needed`, indoor-humidity change, HA start, plus actuator re-assert
triggers. Gated by `input_boolean.airflow_cooling_automatic_enabled`. The profile `choose:` runs
**regardless of Away** — **first matching block wins**, each block idempotent (skips if profile
already correct).

```mermaid
flowchart TD
    T(["trigger"]) --> AUTO{"automatic enabled?"}
    AUTO -- no --> NOOP["no action"]
    AUTO -- yes --> B1

    B1{"BLOCK 1 → WARM<br/>Case A: indoor dew below dew_min AND not cooling season<br/>OR Case B: active_heating AND free OFF AND flush OFF"}
    B1 -- match --> SETW["set profile = warm<br/>(retain moisture / heating season)"]
    B1 -- no --> B2

    B2{"BLOCK 2 → COOL<br/>(free_cooling AND cooling season)<br/>OR humidity_flush_needed"}
    B2 -- match --> SETC["set profile = cool<br/>(free cooling or moisture flush)"]
    B2 -- no --> B3

    B3{"BLOCK 3 → COMFORT<br/>(neutral OR (cooling season AND free OFF))<br/>AND indoor dew within [dew_min, dew_max]"}
    B3 -- match --> SETM["set profile = comfort"]
    B3 -- no --> DEF["default: no-op<br/>(recovery zone / already correct)"]
```

**Precedence note (heating-season flush):** in `active_heating` with indoor dew above max, both
Block 1 Case B (warm) and Block 2 (cool, via flush Branch 1) would match. Block 1 Case B carries a
`flush OFF` guard, so it **yields** — the moisture flush (cool) wins, because relieving a
mould/condensation risk outranks retaining warmth.

### Resulting profile transitions

```mermaid
stateDiagram-v2
    [*] --> comfort
    comfort --> warm: Block 1 (dry air / heating, no flush)
    comfort --> cool: Block 2 (free cooling or flush)
    warm --> cool: Block 2 (flush overrides — heating-season moisture problem)
    warm --> comfort: Block 3 (dew back in dead-band, cooling/neutral)
    cool --> warm: Block 1 (dry air / heating, flush cleared)
    cool --> comfort: Block 3 (free cooling ended, dew in band)

    note right of cool
        hvac_action = cooling (temperature)
                   or drying (flush / boost)
    end note
```

> Every input to these blocks is a 10-min-debounced sensor (or a wide-hysteresis season state),
> so the profile cannot change more than roughly every 10 minutes.

---

## 7. Actuator automations

Two automations drive the actuators. The **controller** owns profile + preset + auto_mode
deterministically; **boost** is isolated with its own hardware-timer mechanics.

### 7.1 `airflow_ventilation_controller` (mode: queued)

One automation computes the *complete desired* ComfoConnect state from the decision sensors and
applies it **idempotently** — no two automations fight over preset/auto_mode. `queued` (not
restart) so a rapid second trigger never aborts a partial auto-off→preset apply.

Gated at automation level by `automatic_enabled == on`. Away handled **inside**: profile runs
always, preset/auto_mode only when `away == off`.

```mermaid
flowchart TD
    T(["trigger"]) --> AUTO{"automatic enabled?"}
    AUTO -- no --> NOOP["no action"]
    AUTO -- yes --> S1["SECTION 1 — PROFILE choose<br/>(Blocks 1/2/3, runs even during Away)"]
    S1 --> AWAY{"away == off?"}
    AWAY -- no --> END["done (profile only)"]
    AWAY -- yes --> S2["SECTION 2 — PRESET / auto_mode choose"]
    S2 --> LO{"low ON?"}
    LO -- yes --> SL["auto OFF, preset low<br/>(guard: skip if already)"]
    LO -- no --> FF{"free OR flush ON?"}
    FF -- yes --> SM["auto OFF, preset medium<br/>(guard: skip if already)"]
    FF -- no --> RST{"auto == off?"}
    RST -- yes --> RA["auto ON (restore)"]
    RST -- no --> NO2["no-op (already correct)"]
```

Preset priority (first match wins): **low → (free or flush) medium → restore auto on**. Service
order in low/medium: **auto_mode off first, then preset** (schedule can't override the manual
preset mid-apply).

Preset is computed **independent of `drying`/boost**. Since `drying ⊂ flush`, whenever a boost
runs the preset rule already yields medium, set *before* the boost starts; idempotent apply means
no preset write disturbs the running boost, and medium fallback is already in place when it expires.
That's why `drying_needed` is **not** a controller trigger.

### 7.2 `airflow_humidity_drying_boost` (mode: single)

```mermaid
flowchart TD
    DRon{"drying_needed ON<br/>and boost OFF?"} -- yes --> SB["boost_time = 30 min<br/>boost = ON"]
    DRoff{"drying_needed OFF?"} -- yes --> CB["boost = OFF"]
    EXP["boost timer expired<br/>while still needed"] --> SB
```

Boost is the high-volume flush; re-arms itself if the ComfoConnect 30-min hardware timer expires
while drying still needed. Gated `automatic_enabled == on` + `away == off` — identical guards to
the controller, so combined state stays consistent. Boost never touches profile/preset/auto_mode;
controller never touches boost.

---

## 8. Reason-based status — `sensor.airflow_cooling_state`

A read-only **derived view** (the automations remain the source of truth). It reads the climate
`hvac_action` plus the boost/low/free sensors and resolves a single status by priority — first
match wins:

```mermaid
flowchart TD
    A{"automatic enabled?"} -- no --> OFF["off"]
    A -- yes --> B{"boost ON<br/>and action = drying?"}
    B -- yes --> MFB["moisture_flush_boost"]
    B -- no --> C{"low_needed ON?"}
    C -- yes --> MP["moisture_protection"]
    C -- no --> D{"action = drying?"}
    D -- yes --> MFC["moisture_flush_cooling"]
    D -- no --> E{"action = cooling?"}
    E -- yes --> F{"free cooling?"}
    F -- yes --> FCO["free_cooling"]
    F -- no --> COO["cooling"]
    E -- no --> G{"action = heating?"}
    G -- yes --> H{"indoor dew<br/>below dew_min?"}
    H -- yes --> MR["moisture_retention"]
    H -- no --> HEA["heating"]
    G -- no --> CMF["comfort"]
```

`hvac_action` itself is `drying` when a boost runs during free cooling **or** the cool profile is
flushing (`profile == cool AND flush_needed`); `cooling` for plain cool profile; `heating` for warm;
`fan` for comfort.

---

## 9. Tunable parameters

| Helper | Role |
|---|---|
| `airflow_cooling_target_temperature` | reference temp for all dew thresholds & temp gates |
| `airflow_target_humidity` | comfort dew target / free-cooling ceiling |
| `airflow_min_humidity` / `airflow_max_humidity` | dry-air floor / moisture-problem ceiling |
| `airflow_min_dew_diff` | required outdoor→indoor dew margin |
| `airflow_min_temp_diff` | required outdoor→target temp margin |
| `airflow_bypass_efficiency_max/min` | bypass-estimation calibration |
| `schedule.airflow_boost_workday` / `_non_workday` | boost time windows |

---

## 10. Anti-flip-flop mechanisms (summary)

| Mechanism | Where | Effect |
|---|---|---|
| 10-min `delay_on`/`delay_off` | free/flush/low sensors (`drying`: `delay_off` only) | caps decision rate at ~10 min |
| 5-min filter on weather temp | `wheatherstation_outdoor_temp_5min` | replaces boost `delay_on`; absorbs noise spikes |
| idempotent unified controller | preset + auto_mode | single owner, no cross-automation hand-off race |
| 0.3 °C dew hysteresis (`this.state`) | flush sensor branches | damps the flush feedback loop |
| 0.5 °C indoor-temp Schmitt | free cooling + flush temp gate | cooling can't disable its own trigger |
| dew Schmitt (target↔max) | low-vent sensor | stable humid-import boundary |
| ±0.1 °C dew epsilon | profile Blocks 1 & 2 | anti-chatter at band edges |
| wide-band 48h-mean state machine | season indicator | season changes over days, not hours |
| idempotent `choose` + dead-band | profile automation | no redundant profile writes |
| `flush OFF` guard on Block 1B | profile automation | deterministic heating-season cool-vs-warm |
