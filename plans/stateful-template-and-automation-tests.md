# Plan: Stateful Jinja2 + Automation Test in CI

## Status

| Step | Status |
|---|---|
| 1.1 — Create `tests/state_defaults.yaml` | done |
| 1.2 — Add `.github/scripts/seed_state.py` | done |
| 1.3 — Add `--strict` to `validate_templates.py` | done |
| 1.4 — Split state vs runtime templates in `extract_templates.py` | done |
| 1.5 — Update `validate_templates` job in `ha_check_frenk.yaml` | done |
| 1.6 — Remove defensive guards from `packages/pergola.yaml` (follow-up) | blocked — awaiting CI green |
| 2.1 — Define `tests/scenarios.yaml` | done |
| 2.2 — Add `.github/scripts/run_automations.py` | done |
| 2.3 — Refactor seeding into `.github/scripts/_ha_state.py` | done |
| 2.4 — Add `execute_automations` job in `ha_check_frenk.yaml` | done |

---

## Context

Today the `validate_templates` job in [.github/workflows/ha_check_frenk.yaml](.github/workflows/ha_check_frenk.yaml) boots a Home Assistant Docker container with an **empty** `/config` and validates templates via `POST /api/template`. Because no entities exist, the validator must skip every error containing `"is undefined"` ([validate_templates.py:20-22](.github/scripts/validate_templates.py#L20-L22)). This means the templates in [packages/pergola.yaml](packages/pergola.yaml) are only checked for raw Jinja2 syntax — never against actual entity values — so each template carries defensive guards like `states('sensor.x') not in ['unavailable', 'unknown']` and fallbacks like `| float(0)` to keep production safe.

**Goal:** boot HA with the **real** repo config, seed every input helper and every external dependency entity with a known good value, then re-run the template tests strictly (no skips for unknown/None/undefined). Once the test passes, the `| float(<default>)` / `| int(<default>)` dead-code fallbacks inside template sensor `state:` blocks (where the same entity is already guarded by the sensor's own `availability:` check) can be removed with confidence. The `availability:` checks themselves stay — they remain the semantic guard for when the sensor is valid. Phase 2: trigger every automation under multiple scenarios and assert no error trace.

---

## Architecture

```
GitHub Actions  ──►  HA Docker (full repo as /config)
                          │
                          │  (1) onboarding → token
                          │  (2) seed_state.py applies defaults
                          │      ├─ input helpers → service calls
                          │      └─ external sensors → POST /api/states
                          │  (3) extract_templates.py  (state vs runtime split)
                          │  (4) validate_templates.py --strict
                          │  (5) run_automations.py: scenarios × automations + trace check
                          ▼
                    pass / fail / PR comment
```

External entities the repo references but does **not** define in YAML (must be stubbed via `POST /api/states`):
- `sensor.solar_yield_watts` *(MQTT — broker unreachable in CI)*
- `sensor.wheatherstation_outdoor_temperature`, `_solar_radiation`, `_uv_index`, `_hourly_rain`, `_rain_rate`
- `sensor.dach_links_priority_lock_originator`, `_timer`
- `sensor.dach_rechts_priority_lock_originator`, `_timer`
- `cover.dach_links`, `cover.dach_rechts` *(Somfy — UI integration, missing in CI)*
- `sun.sun` *(state override of elevation/azimuth attributes)*

Inputs the repo defines and that need explicit defaults applied (so the test starts from a known scenario rather than relying on `initial:`):
- `input_boolean.pergola_automatic_enabled`, `pergola_heating`, `pergola_cooling_optimized`
- `input_select.pergola_automation_state`
- `input_number.pergola_*` (10 helpers — see [packages/pergola.yaml:78-242](packages/pergola.yaml#L78-L242))

---

## Files to add / modify

| File | Action | Purpose |
|---|---|---|
| `tests/state_defaults.yaml` | **new** | Single source of truth: defaults for every input helper + stub state/attributes for every external dependency |
| `tests/scenarios.yaml` | **new** *(Phase 2)* | Declarative list of named **state overlays** layered on top of `state_defaults.yaml`. The Phase 2 runner applies each scenario, then triggers every automation under that state |
| `.github/scripts/_ha_state.py` | **new** | Shared module: `apply_inputs(token, url, mapping)` and `apply_states(token, url, mapping)`. Imported by both `seed_state.py` and `run_automations.py` |
| `.github/scripts/seed_state.py` | **new** | Reads `tests/state_defaults.yaml`, applies inputs via service calls, applies stub states via `POST /api/states/{entity_id}` |
| `.github/scripts/run_automations.py` | **new** *(Phase 2)* | **Generic** runner: discovers all automations via `/api/states` (domain == `automation`), iterates scenarios, triggers each, walks `/api/automation/trace/<id>` for errors. Knows nothing about specific automations |
| `.github/scripts/validate_templates.py` | **modify** | Add `--strict` flag: in strict mode, treat undefined errors AND results equal to `unknown` / `unavailable` / `None` / empty as failures |
| `.github/scripts/extract_templates.py` | **modify (small)** | Skip templates that obviously reference runtime-only vars (`trigger`, `value`, `wait`, `repeat`, `this`). Output two lists in JSON: `state_templates` (validated strictly) and `runtime_templates` (parsed for syntax, undefined still skipped) |
| `.github/workflows/ha_check_frenk.yaml` | **modify** | The `validate_templates` job mounts the repo as `/config`, waits for full startup, runs `seed_state.py`, then validates strictly. Add a second job `execute_automations` for Phase 2. Leave the existing `home-assistant` (frenck) job untouched |
| `secrets.yaml` (root, gitignored) / `fakesecrets.yaml` | confirm | Make sure no `!secret` lookups blow up startup. `fakesecrets.yaml` is already present — if any `!secret` keys appear in YAML, add fakes there |

The stale workflow `ha-config-check.yml` is **out of scope** — leave as-is.

---

## `tests/state_defaults.yaml` — proposed shape

```yaml
# Applied to running HA via seed_state.py before any test runs.
# Keep this file in sync with every external entity referenced in templates/automations.

# Input helpers — applied via input_*.set_value / turn_on / turn_off / select_option
inputs:
  input_boolean.pergola_automatic_enabled: "on"
  input_boolean.pergola_heating: "off"
  input_boolean.pergola_cooling_optimized: "on"
  input_select.pergola_automation_state: "sun_automatik_cooling"
  input_number.pergola_pv_conversion_factor: 3.2
  input_number.pergola_shading_sensitivity: 0.9
  input_number.pergola_min_sun_elevation: 10
  input_number.pergola_deadband_angle: 5
  input_number.pergola_rain_recovery_step: 0
  input_number.pergola_max_tilt_angle: 122
  input_number.pergola_wall_azimuth: 204
  input_number.pergola_slat_width: 22
  input_number.pergola_slat_pivot_spacing: 20
  input_number.pergola_slat_thickness: 3

# Stubbed entity states — applied via POST /api/states/{entity_id}
# Stand-ins for integrations not present in CI (MQTT, Somfy, weather station).
states:
  sun.sun:
    state: "above_horizon"
    attributes:
      elevation: 45
      azimuth: 180

  sensor.solar_yield_watts:
    state: "1500"
    attributes: { unit_of_measurement: "W", device_class: "power" }

  sensor.wheatherstation_outdoor_temperature:
    state: "18.5"
    attributes: { unit_of_measurement: "°C", device_class: "temperature" }
  sensor.wheatherstation_solar_radiation:
    state: "650"
    attributes: { unit_of_measurement: "W/m²" }
  sensor.wheatherstation_uv_index:
    state: "5"
  sensor.wheatherstation_hourly_rain:
    state: "0"
    attributes: { unit_of_measurement: "mm" }
  sensor.wheatherstation_rain_rate:
    state: "0"
    attributes: { unit_of_measurement: "mm/h" }

  sensor.dach_links_priority_lock_originator:  { state: "none" }
  sensor.dach_rechts_priority_lock_originator: { state: "none" }
  sensor.dach_links_priority_lock_timer:       { state: "0" }
  sensor.dach_rechts_priority_lock_timer:      { state: "0" }

  cover.dach_links:
    state: "open"
    attributes: { current_tilt_position: 50 }
  cover.dach_rechts:
    state: "open"
    attributes: { current_tilt_position: 50 }
```

---

## Step-by-step implementation

### Phase 1 — stateful template validation

**Step 1.1 — Create `tests/state_defaults.yaml`**
Author the file using the shape above. Source the input defaults from the existing `initial:` keys in [packages/pergola.yaml:78-242](packages/pergola.yaml#L78-L242). Source the stub keys by enumerating every external `states('sensor.*')` / `state_attr('cover.*'/'sun.sun')` reference under [packages/](packages/) and [automations.yaml](automations.yaml). After writing, grep the repo for any external entity that is not yet covered.

**Step 1.2 — Add `.github/scripts/seed_state.py`**
- Argparse: `--defaults <path>`, `--ha-url`, optional `--retries`.
- Reads `HA_TOKEN` from env (consistent with `validate_templates.py`).
- For `inputs:` block, dispatch by domain prefix:
  - `input_boolean` → `services/input_boolean/turn_on|turn_off`.
  - `input_number` → `services/input_number/set_value`.
  - `input_select` → `services/input_select/select_option`.
  - `input_text`, `input_datetime` → equivalents (future-proof).
- For `states:` block, `POST /api/states/{entity_id}` with `{state, attributes}`. Read back to verify.
- On failure, print which entity and exit 1.

**Step 1.3 — Modify [.github/scripts/validate_templates.py](.github/scripts/validate_templates.py)**
- Add `--strict` flag (default off — keeps current behavior usable).
- In strict mode:
  - `is undefined` no longer auto-skips — it becomes a failure (state has been seeded).
  - A `200 OK` response whose body equals `"unknown"`, `"unavailable"`, `"None"`, or empty string is a failure.
  - Continue to skip templates that reference runtime-only vars (the upstream filter in step 1.4 ensures those don't reach strict mode).

**Step 1.4 — Modify [.github/scripts/extract_templates.py](.github/scripts/extract_templates.py)**
Add a filter: skip strings that reference `trigger`, `wait`, `value`, `repeat`, `this`, `iif`, `context.id`, etc. Output two lists in the JSON: `state_templates` (validated strictly) and `runtime_templates` (still parsed for syntax, but allowed to skip on undefined). Validator iterates both lists with the right strictness.

**Step 1.5 — Modify [.github/workflows/ha_check_frenk.yaml](.github/workflows/ha_check_frenk.yaml)**
In the `validate_templates` job:
- Replace the `mkdir /tmp/ha-ci-config` empty-config setup with `-v ${{ github.workspace }}:/config` so the real repo is the HA config dir.
- Pre-step: ensure `themes/` exists and `secrets.yaml` exists (HA needs both at startup; `fakesecrets.yaml` already covers any `!secret` lookups but the runtime expects `secrets.yaml`).
- Pin the HA image tag to the contents of `.HA_VERSION` so the live container matches the deployed version.
- Extend the readiness wait: after onboarding `user` step, also wait for `GET /api/` to return `{"message":"API running."}` so seeding doesn't race startup.
- Insert new step `Seed test state` that runs `seed_state.py --defaults tests/state_defaults.yaml`.
- Run validator with `--strict`.

The existing `home-assistant` job in this same workflow (frenck static `check_config`) stays unchanged — belt-and-braces.

**Step 1.6 — Remove dead-code float fallbacks from template sensor state blocks (follow-up commit, after CI is green)**
The `availability:` checks on each template sensor stay — they are the semantic guard that tells HA when a sensor is valid to compute. What is dead code is the `| float(<default>)` (and `| int(<default>)`) inside the `state:` block for entities that are **already covered by that sensor's own `availability:` check**: when availability is false the state is never evaluated, so the fallback can never be reached.

Do NOT remove defaults in automations/scripts, or where the `availability:` uses an OR condition (binary_sensor.pergola_sun_shining — either source may be unavailable while the other is available).

Entities to remove explicit defaults from (only where directly guarded in the same sensor's `availability:` block):

| Sensor | Entity reference in state | Default to remove |
|---|---|---|
| `pergola_pv_power` | `states('sensor.solar_yield_watts')` | `\| float(0)` → `\| float` |
| `pergola_effective_sun_angle` | `state_attr('sun.sun', 'elevation')` | `\| float(0)` → `\| float` |
| `pergola_effective_sun_angle` | `state_attr('sun.sun', 'azimuth')` | `\| float(0)` → `\| float` |
| `pergola_effective_sun_angle` | `states('input_number.pergola_wall_azimuth')` | `\| float(204)` → `\| float` |
| `pergola_slat_angle` | `states('sensor.pergola_max_open_east_morning_cooling_angle')` | `\| float(90)` → `\| float` |
| `pergola_max_open_east_morning_cooling_angle` | `pergola_effective_sun_angle`, `slat_width`, `slat_pivot_spacing`, `slat_thickness` | all `\| float(<n>)` → `\| float` |
| `pergola_max_open_west_cooling_angle` | same 4 entities | all `\| float(<n>)` → `\| float` |
| `pergola_min_heating_slat_angle` | `slat_width`, `slat_pivot_spacing`, `slat_thickness` | all `\| float(<n>)` → `\| float` |
| `pergola_tilt_position` | `pergola_slat_angle`, `pergola_max_tilt_angle` | `\| float(90)` → `\| float`, `\| float(122)` → `\| float` |
| `pergola_rain_recovery_step` | `pergola_rain_recovery_step` (input_number) | `\| int(0)` → `\| int` |
| `pergola_sun_shining` | `state_attr('sun.sun', 'elevation')` | `\| float(0)` → `\| float` (elevation is not none is guarded; solar_radiation/pv_power NOT removable due to OR) |
| `pergola_cooling_lower_bound` | `pergola_max_tilt_angle`, `slat_width`, `slat_pivot_spacing`, `slat_thickness` | all `\| float(<n>)` → `\| float` |

Tracked here for visibility; committed separately so the diff stays small.

### Phase 2 — automation execution check (scenario-driven, fully generic)

The runner must work without knowing any automation IDs, file names, or branch structure, so adding/removing/refactoring automations does not require touching test code. Branch coverage comes from declarative **scenarios**, not from test-code logic.

**Step 2.1 — Define `tests/scenarios.yaml`**
A scenario is a named overlay that may change **any** lever — input booleans, input selects, input numbers, and stubbed entity states — on top of the baseline `state_defaults.yaml`. The boolean flags (`pergola_automatic_enabled`, `pergola_heating`, `pergola_cooling_optimized`) and the state-machine select (`pergola_automation_state`) gate most `choose:` branches in [packages/pergola.yaml](packages/pergola.yaml), so they must be flipped explicitly in scenarios — sensor states alone won't reach those branches.

Coverage is the union of (boolean combinations) × (state-machine option) × (sensor situation). Not every combination is meaningful; the scenario list is curated to one entry per branch. Initial set:

```yaml
scenarios:
  # Baseline — heating off, cooling optimized on, auto enabled, sunny midday.
  - name: baseline_cooling_optimized
    overrides: {}

  # Cooling un-optimized branch in pergola_slat_angle / state manager.
  - name: cooling_unoptimized
    overrides:
      inputs:
        input_boolean.pergola_cooling_optimized: "off"

  # Heating branch — slat_angle uses pergola_min_heating_slat_angle.
  - name: heating_mode
    overrides:
      inputs:
        input_boolean.pergola_heating: "on"
        input_boolean.pergola_cooling_optimized: "off"
        input_select.pergola_automation_state: "sun_automatik_heating"

  # Automation kill-switch off — every automation should early-return cleanly.
  - name: automation_disabled
    overrides:
      inputs:
        input_boolean.pergola_automatic_enabled: "off"

  # State: not_enough_sun (low elevation + low PV).
  - name: not_enough_sun
    overrides:
      inputs:
        input_select.pergola_automation_state: "not_enough_sun"
      states:
        sun.sun: { state: "above_horizon", attributes: { elevation: 6, azimuth: 180 } }
        sensor.solar_yield_watts: { state: "30" }
        sensor.wheatherstation_solar_radiation: { state: "40" }
        sensor.wheatherstation_uv_index: { state: "0.5" }

  # State: no_sun_behind_house (sun azimuth past wall).
  - name: no_sun_behind_house
    overrides:
      inputs:
        input_select.pergola_automation_state: "no_sun_behind_house"
      states:
        sun.sun: { state: "above_horizon", attributes: { elevation: 25, azimuth: 350 } }

  # Frost guard — pergola_state_manager should switch to 'frost'.
  - name: frost
    overrides:
      states:
        sensor.wheatherstation_outdoor_temperature: { state: "-1.5" }

  # Frost recovery — temp climbs back above 3.0°C with state=='frost'.
  - name: frost_recovery
    overrides:
      inputs:
        input_select.pergola_automation_state: "frost"
      states:
        sensor.wheatherstation_outdoor_temperature: { state: "5.0" }

  # Rain starts.
  - name: rain_starts
    overrides:
      states:
        sensor.wheatherstation_rain_rate: { state: "2.5" }

  # Rain stops → recovery branch (input_number drives recovery step).
  - name: post_rain_recovery
    overrides:
      inputs:
        input_select.pergola_automation_state: "rain_stopped"
        input_number.pergola_rain_recovery_step: 1
      states:
        sensor.wheatherstation_rain_rate: { state: "0" }

  # User override on left cover (priority_lock_originator != none).
  - name: user_override_left
    overrides:
      states:
        sensor.dach_links_priority_lock_originator: { state: "user" }
        sensor.dach_links_priority_lock_timer: { state: "300" }

  # Rain-originated lock from cover hardware.
  - name: rain_lock_from_cover
    overrides:
      states:
        sensor.dach_links_priority_lock_originator: { state: "rain" }
        sensor.dach_rechts_priority_lock_originator: { state: "rain" }
  # …add more as new branches are introduced…
```

Authoring rule: when a new `choose:` branch or guard is added, append a scenario that selects it. The runner code does not change.

**Step 2.2 — Add `.github/scripts/run_automations.py`** *(automation-agnostic)*
- `GET /api/states` → keep entries where `entity_id` starts with `automation.` → list of all automations (auto-discovers new ones, ignores deleted ones).
- For each scenario in `tests/scenarios.yaml`:
  1. Re-apply baseline `state_defaults.yaml` (clean slate).
  2. Apply the scenario overlay using `_ha_state.apply_inputs` / `apply_states`.
  3. For each discovered automation: `POST /api/services/automation/trigger` with `skip_condition: false` first; the **scenario** is what makes a given branch reachable. If a trigger does not produce a trace because the automation has no triggers reachable from a forced trigger call, fall back to `skip_condition: true`.
  4. Poll `GET /api/config/automation/trace/<config_id>` (HA exposes traces per automation config ID); assert no trace node carries a non-empty `error`.
  5. Snapshot `GET /api/error/all` before scenario, diff after — fail on any new ERROR-level line.
- Aggregate failures across scenarios, fail at the end with a per-scenario / per-automation summary.

**Step 2.3 — Refactor seeding into a shared module**
Extract the apply-defaults logic into `.github/scripts/_ha_state.py` with `apply_inputs(token, url, mapping)` and `apply_states(token, url, mapping)`. `seed_state.py` becomes a thin CLI wrapper; `run_automations.py` imports the same functions for overlay application.

**Step 2.4 — New job `execute_automations` in [.github/workflows/ha_check_frenk.yaml](.github/workflows/ha_check_frenk.yaml)**
Reuse the same Docker boot + onboarding token + initial seed steps. Add a step that runs `run_automations.py --defaults tests/state_defaults.yaml --scenarios tests/scenarios.yaml`. Same PR-comment-on-failure pattern as the template job.

---

## Critical files to read before implementing

- [.github/workflows/ha_check_frenk.yaml](.github/workflows/ha_check_frenk.yaml) — the only active CI workflow; extend the `validate_templates` job and add a new `execute_automations` job alongside it
- [.github/scripts/validate_templates.py](.github/scripts/validate_templates.py) — strictness logic lives here
- [.github/scripts/extract_templates.py](.github/scripts/extract_templates.py) — runtime-var filter
- [packages/pergola.yaml](packages/pergola.yaml) — every templated sensor + every entity reference
- [configuration.yaml](configuration.yaml) — confirm `default_config:` is loaded so the API + states endpoint work
- [packages/victron.yaml](packages/victron.yaml) — MQTT integration that won't connect in CI (sensor will be `unknown` until seeded)

---

## Verification

1. **Local dry run of the seed script** against a temporary HA Docker container:
   ```bash
   docker run -d --name ha-local -p 8123:8123 -v "$PWD:/config" ghcr.io/home-assistant/home-assistant:$(cat .HA_VERSION)
   # …onboarding to get a token…
   HA_TOKEN=<token> python .github/scripts/seed_state.py --defaults tests/state_defaults.yaml --ha-url http://localhost:8123
   # Spot-check via GET /api/states/sensor.pergola_pv_power, sensor.pergola_slat_angle etc. — values should be numeric, not 'unknown'.
   ```
2. **Strict template validation locally**:
   ```bash
   HA_TOKEN=<token> python .github/scripts/validate_templates.py --templates /tmp/templates.json --strict
   # Expect: 0 invalid, 0 skipped (state) — all should evaluate to a real value.
   ```
3. **CI run on a feature branch** — push and watch both jobs. The PR comment path should still trigger on failure.
4. **Phase 2 verification**: confirm each automation produces a clean trace via `GET /api/config/automation/trace/<id>` after `run_automations.py` runs across every scenario.

---

## Decisions (confirmed with user)

1. **Strict mode** fails on Jinja2 errors **and** on results equal to `unknown` / `unavailable` / `None` / empty. This is what enables removing the defensive guards in [packages/pergola.yaml](packages/pergola.yaml).
2. **Single defaults file**: `tests/state_defaults.yaml` with `inputs:` and `states:` sections.
3. **Phase 2 is generic** — the runner discovers automations from `/api/states` and never references specific automation IDs or files. Branch coverage is declarative via `tests/scenarios.yaml`; new automations and refactors require no test-code changes. Scenarios MUST flip `input_boolean.pergola_heating`, `pergola_cooling_optimized`, and `pergola_automatic_enabled` — sensor states alone don't reach those branches.
4. **Keep** the existing frenck static `check_config` job (the `home-assistant` job in `ha_check_frenk.yaml`) alongside the new live test. The stale `ha-config-check.yml` workflow is out of scope.
