# Airflow — `sensor.airflow_cooling_state` as the single decision

## Context
On 2026-10-23 the dashboard showed `free_cooling` with `heating_cooling_indicator = active_heating`,
room 21.7 °C (target 22.0). Two defects were fixed directly on `claude/friendly-meitner-m9kv9h`:
1. Block 1B (active heating → warm) required free cooling OFF, so `cool` was held in heating season.
2. Section 2 raised the preset to medium on raw `free_cooling_available`, ignoring the season.

Root cause behind both: **there is no single decision.** Today the indicators are wired straight into
every consumer, and `sensor.airflow_cooling_state` is only a *label derived from the outputs*:

| Consumer | Reads today |
|---|---|
| Controller Section 1 (profile, Blocks 1–5) | `heating_cooling_indicator`, `free_cooling_available`, `flush_needed`, indoor dew vs `dew_point_min/max`, **current profile** |
| Controller Section 2 (preset / auto_mode) | `drying_needed`, `ventilation_low_needed`, `flush_needed`, `cooling_state` (after fix 2) |
| Drying boost automation | `drying_needed` |
| `climate.airflow_climate` hvac_action | profile, `free_cooling_available`, `drying_needed`, `flush_needed` |
| `sensor.airflow_cooling_state` | `climate` hvac_action (= profile), free, moisture/heat low, boost switch |

So each consumer re-implements its own season/priority rules, they can disagree (the bug), and the
status sensor reports what the device *is doing*, not what the automation *decided*.

## Goal
```
indicators ──► sensor.airflow_cooling_state ──► controller (profile + preset/auto) ──► ComfoConnect
                 (state = reason,                 drying boost automation
                  attr profile, ventilation)      climate hvac_action (display)
```
- `sensor.airflow_cooling_state` is computed **only from indicators** (free cooling, flush, drying,
  moisture low, heat low, `heating_cooling_indicator`, indoor dew vs `dew_point_min`, auto enabled).
  It never reads the profile, preset, climate or boost switch.
- Every automation that changes the device reads **only** `sensor.airflow_cooling_state`
  (plus hardware/user guards listed below), never the indicators directly.

## Decision table (one template, first match wins)

Profile (independent of protections — they only change the rate):
| # | Condition | profile |
|---|---|---|
| P1 | `flush_needed` (⊇ `drying_needed`) | cool |
| P2 | season = `active_heating` | warm |
| P3 | indoor dew < `dew_point_min` − 0.1 (stay while < `dew_point_min`) and season not cooling | warm |
| P4 | `free_cooling_available` | cool |
| P5 | otherwise | comfort |

Ventilation:
| # | Condition | ventilation |
|---|---|---|
| V1 | `drying_needed` | boost |
| V2 | `flush_needed` | medium |
| V3 | moisture low or heat low | low |
| V4 | profile chosen by P4 (free cooling) | medium |
| V5 | otherwise | auto |

State (reason label, shown on the dashboard):
`off` (auto disabled) → `moisture_flush_boost` (V1) → `moisture_flush_cooling` (V2) →
`heat_protection` (heat low, not moist) → `moisture_protection` (V3) → `free_cooling` (P4) →
`moisture_retention` (P3, or P2 with dry indoor) → `heating` (P2) → `comfort`.
`cooling` (manual cool without free cooling) disappears: manual modes turn auto off → `off`.

This reproduces today's Blocks 1–5 and Section 2 statelessly, with the fixes 1 + 2 built in:
- Blocks 3/4/5 (comfort + stuck-cool / stuck-warm recovery) collapse into P5 — no "keep current
  profile" path exists any more, so the stuck traps cannot occur.
- Block 1A's −0.1 °C anti-chatter epsilon becomes P3's hysteresis (memory = previous `profile`
  attribute).
- Behaviour change to confirm: humid indoor in **neutral** season with profile `warm` today stays
  `warm` (no block matches); under P5 it becomes `comfort`.

## Implementation: one template, no duplicated logic
State-based template entities cannot share variables between state and attributes at 2026.10.1
(entity `variables` are rendered once at setup, `template_entity.py::_async_template_startup`), and
trigger-based is ruled out for slow-binary-derived sensors (`notes/airflow_cooling.md`, restore-stale).
So the decision lives in **one Jinja macro**, `custom_templates/airflow_decision.jinja`, returning
`"<state>|<profile>|<ventilation>"`; the sensor's state and its `profile` / `ventilation` attributes
each import it and pick their field. All three render from the same inputs in the same update.

> **Recommended (needs your OK):** the macro is the only file outside `packages/`. Alternative:
> inline the ~15-line decision three times in the sensor with a "keep in sync" comment and a test
> asserting the three agree. I recommend the macro.

## Consumers after the change
| Consumer | Reads | Keeps (guards, not decisions) |
|---|---|---|
| Controller Section 1 | `cooling_state.profile` → write profile if different | auto enabled, idempotency on current profile |
| Controller Section 2 | `cooling_state.ventilation`: boost → auto on, no preset; low → auto off + low; medium → bump from auto-schedule low (existing route-to-auto); auto → restore auto | Away, running boost switch (never cancel a manual boost), preset/auto idempotency |
| Drying boost automation | `cooling_state.ventilation == boost` on/off instead of `drying_needed` | auto enabled, Away, countdown re-arm |
| Climate hvac_action | `drying` when state is a flush state, else from the **actual** profile (display of device) | — |
| Controller triggers | `sensor.airflow_cooling_state` (state + attributes) + boost/auto/preset/Away hardware triggers | — |

Indicators keep their own logic (debounce, Schmitt, mutual exclusivity); only their consumers change.

## Steps & status
- [x] 1. `custom_templates/airflow_decision.jinja` + `sensor.airflow_cooling_state` rewritten (state +
       `profile` / `ventilation` attributes; availability requires every indicator). Disabled
       automation → profile/ventilation `off` (not `none`: the strict template test treats `none` as
       a sentinel).
- [x] 2. Controller Section 1: Blocks 1–5 replaced by "write `profile` if different" + notify.
       New trigger: the device reporting a profile on its own (reconnect / manual change) re-asserts
       the decision; indicator triggers replaced by one trigger on the decision.
- [x] 3. Controller Section 2: every branch keyed on `ventilation`; boost-switch guard, Away and
       idempotency guards kept.
- [x] 4. Drying boost: attribute triggers on `ventilation` (to/from `boost`); stop only on a real
       non-boost decision (an unavailable decision never stops a boost).
- [x] 5. Climate `hvac_action_template` reads the decision.
- [x] 6. Tests: decision-table tests (`test_decision_*`) incl. the 2026-10-23 scenario; controller,
       boost and hvac tests re-pointed at the decision; Block 1–5 tests removed. conftest seeds
       `free_cooling_available` and `moisture_ventilation_low_needed`. Local run with the pinned image
       2026.10.1: full non-pergola suite 172 passed / 1 skipped (baseline before the change: 190 / 1);
       HA `check_config` clean; yamllint clean (pre-existing warnings only).
- [x] 7. Notes, architecture doc (§3, §6, §7, §8, §10, §11), learnings, CLAUDE.MD updated.

## Deploy notes
- `git pull`, then **restart** HA (a YAML reload does not load a new `custom_templates/` file;
  `homeassistant.reload_custom_templates` + template reload also works).
- After a reload the trigger-based indicators can sit `unknown` until their self-trigger / next input
  change; the decision is `unavailable` meanwhile and the automations do nothing (by design).
