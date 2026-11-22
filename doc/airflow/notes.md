---
paths:
  - "packages/airflow_cooling.yaml"
  - "custom_templates/airflow_decision.jinja"
  - "tests/ha/test_airflow_cooling.py"
  - "dashboards/airflow-dashboard.yaml"
  - "doc/airflow/design.md"
---
# airflow_cooling package notes (`packages/airflow_cooling.yaml`)

Read before touching `packages/airflow_cooling.yaml`, `custom_templates/airflow_decision.jinja`,
its tests or its dashboard. Scope: ComfoConnect (Zehnder ComfoAir Q350 ERV) temperature profile,
ventilation level and humidity boost. Design (entities, season machine, decision table, actuator
automations, bypass estimation): `doc/airflow/design.md` (`AF-1` … `AF-12`), on demand: read it only to change the architecture or check an addition against it; for one rule, follow the `→ design.md#ID` at that line. This note holds what
you must not break.

## Invariants
### Single decision (`sensor.airflow_cooling_state`) — the rule for every consumer
Decision table: `tests/ha/test_airflow_cooling.py::test_decision_table`. Inputs, outputs, macro: design `AF-6`.
- **Indicators feed only the decision; consumers read only the decision.** The indicators
  (`free_cooling_available`, `humidity_flush_needed`, `humidity_drying_needed`, moisture/heat low,
  `heating_cooling_indicator`, indoor dew vs `dew_point_min`) are inputs of
  `sensor.airflow_cooling_state` and of nothing that writes the device. The controller, the drying
  boost and `climate.airflow_climate`'s hvac_action read its state / `profile` / `ventilation`
  attributes. Never wire an indicator straight into an automation — why: consumers that each
  re-implement the season rules disagree.

### Trigger-based vs state-based template sensors
- A derived template sensor whose inputs are **only other (slow) binary sensors** (the decision,
  `ventilation_low_needed`) MUST be **state-based** (plain `state:`, no `trigger:`). A trigger-based
  one restores its last state on HA restart and on `template.reload` and recomputes only when an
  input **changes**, so it can come back **stale** and never resync (fails silently; OBSERVED: a stale
  `ventilation_low_needed` once held the preset at medium all day). Trigger-based + restore only for
  sensors driven by continuously-drifting numeric filters (outdoor temp/dew, weather-station temp):
  drift forces a recompute within ~1 debounce, and restoring keeps the 10-min delay + `this.state`
  hysteresis. The `to: "unknown"` self-triggers do not protect against this. → design `AF-10`.

## Hardware / integration quirks
### Boost/preset hardware model
Hardware behaviour of the ComfoConnect unit, relied on by the airflow automations:
- A running **boost** is identified by `switch.comfoconnect_pro_boost` (and the stable `drying_needed`
  intent) — **never** by `preset==high`. Boost only *reports* `high` as a side effect.
- Boost delivers HIGH airflow and **coexists with `auto_mode` ON**. On boost end the preset returns to
  its pre-boost value.
- **Two actions CANCEL a running boost:** (1) writing ANY preset (`low`/`medium`) via
  `select.select_option`, and (2) turning `auto_mode` **OFF** (airflow lingers high a few minutes, then
  reverts). Turning `auto_mode` **ON** does NOT cancel boost.
- `number.comfoconnect_pro_boost_time` is a live countdown (Modbus holding register 4, seconds on
  the wire, minutes in HA); **writing it does NOT extend a running boost** (the device ignores it).
- **Re-sending boost ON (Modbus coil 6 = 1) while a boost runs RESTARTS the timer at the full
  duration** — verified on the device. This is the seamless re-arm: `switch.turn_on` on the
  already-on boost, no off→on, no notification.
- Boost start/stop rules (edge only, no restart trigger, manual off sticks, accepted re-arm risk):
  design `AF-7.2`; known gap #153 below.

### climate_template (upstream litinoveweedle/hass-template-climate, pinned in `tests/custom_components.yaml`)
- Humidity control needs `dry` in `hvac_modes`: without it the component drops `set_humidity` /
  `target_humidity_template` with only a WARNING under its own logger and the entity loads without
  TARGET_HUMIDITY. CONFIRMED: `climate.py` at 0.8.2 and `test_climate_humidity_control` (fails with
  `dry` removed). So `dry` stays listed (meaning: design `AF-8`).
- At 0.8.2 it still logs the HA 2026.11 climate temperature deprecations
  (`plans/climate-template-deprecations.md`).

## Entity map
Full inventory with roles: design `AF-2` (inputs, thresholds, indicators, actuators, views) and
`AF-9` (helpers). Season thresholds: `input_number.heating_indicator_*` (design `AF-4`).

## Decisions in force
### Ventilation controller (`automation.airflow_ventilation_controller`, Section 2) rules
- Boost ownership (first `choose` branch) = decision `ventilation == 'boost'` OR boost switch `on`
  (adopts a manual boost); never the boost/auto switches alone, which flap during boost
  expiry/re-enable races, and never `preset == high`. Branch logic: design `AF-7.1`.
- Prefer minimal, surgical controller edits over restructures; retain existing branch behaviour unless
  a change is required to fix a specific defect.

## Known biases / open issues
- `drying_needed` reads `input_number.airflow_cooling_target_temperature | float(21.5)`, a fallback
  default on a helper that the repo rule forbids (code, not fixed in a docs step). → GitHub issue #142

## Tests (`tests/ha/test_airflow_cooling.py`, in-process)
- Tables (decision, bypass, dew points; one looping test each) seed the delayed indicators: seed
  season/dew first, then the indicators (CONFIRMED: otherwise a season/dew change re-renders the
  seeded indicators to `unknown`, they have no internal state without the delay). The season is
  the REAL `sensor.heating_cooling_indicator`, driven through its seeded 48h mean.
- Clock tests drive the REAL indicators (10 min delays, `this.state` hysteresis) through the seeded
  5-min filter outputs, the real workday/schedules (clock moved to a known weekday or the next
  public holiday) and the automations on real triggers. Effects are the recorded ComfoConnect and
  phone calls; the four ComfoConnect stubs echo a write into the entity state (a device echo), else
  follow-up runs repeat their write. Only the two airflow automations are on (`airflow_ha`): the
  pergola cover response waits on timers longer than a clock move and hangs the test.
- After a real `template.reload` the trigger-based indicators come back with their previous state
  at once (#155); the `to: "unknown"` self-triggers
  still recompute. `template.reload` logs a TemplateError for `sensor.solar_yield_watts` (allowed
  by name in `test_reload_recovery`, #155).
- The 5-min filter sensors and the 48h statistics sensor get other ids on a fresh registry than
  the templates read (#146).
- CONFIRMED config bug, `test_drying_boost_unavailable_to_boost_does_not_fire` (strict xfail,
  #153): a flush input going briefly unavailable restarts a running boost (decision unavailable →
  medium → boost is a real edge, boost time and ON re-sent). So AF-7.2's "`unavailable → boost` is
  not an edge" holds only for the direct transition, not for an input flap.
- `climate_template` echoes every `hvac_mode_template` change into the `set_hvac_mode` action
  (e.g. automatic control off writes the device's current profile back, #154); effect on the
  device UNPROVEN.
- The `outdoor_dew >= indoor_dew` term of the low-needed fallback can never decide alone (a dead
  branch, comment issue, #155).

## Related
- `doc/airflow/design.md` — current design (`AF-*` IDs).
- `packages/heating_cooling_indicator.yaml` — season indicator consumed by the decision.
