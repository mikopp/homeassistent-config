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
- [ ] 1. Add `custom_templates/airflow_decision.jinja` + rewrite `sensor.airflow_cooling_state`
       (state + `profile` / `ventilation` attributes, availability, icon).
- [ ] 2. Controller Section 1: replace Blocks 1–5 with one "apply `profile` attribute" step + notify.
- [ ] 3. Controller Section 2: key every branch on the `ventilation` attribute.
- [ ] 4. Drying boost automation: trigger/conditions on `ventilation == boost`.
- [ ] 5. Climate `hvac_action_template`: read `cooling_state` instead of the indicators.
- [ ] 6. Tests (`tests/test_airflow.py`): rewrite `cooling_state` tests to seed indicators (not
       hvac_action); add decision-table cases incl. the 2026-10-23 scenario (active_heating + free
       ON → `heating`, warm, auto); adapt controller/boost tests to the new inputs; run locally.
- [ ] 7. Update `packages/notes/airflow_cooling.md`, `plans/airflow-cooling-architecture.md`,
       `.claude/learnings.md`; dashboard unchanged (already shows `cooling_state`).
