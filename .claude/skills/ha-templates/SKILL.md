---
name: ha-templates
description: "Runtime semantics of HA template sensors/automations at the pinned version: trigger vs state-based, this.state self-reference, re-render/propagation, variables, automation.trigger conditions. Use when designing or debugging template:/automation logic; not for YAML style (see yaml)."
---

# HA template & automation runtime semantics

Grades: **CONFIRMED** = source read at the pinned version (`.github/ha-versions/ha/Dockerfile` `FROM`),
stack trace, or deterministic repro. **OBSERVED** = real data, alternative explanation open.
**UNPROVEN** = hypothesis, kept so it is not re-litigated. Never promote a grade without new evidence.

## Trigger-based template sensors
- **W→kWh accumulator** (CONFIRMED, every accumulator in `packages/victron.yaml` passes CI):
  `trigger: [platform: time_pattern, minutes: "/1"]`, `state: "{{ (this.state | float(0)) + (power/60000) }}"`.
  - Why: `this.state` reads the entity's PREVIOUS (pre-write) state, so it accumulates cleanly.
  - Limit: 1/min sampling is coarse for sources pushing every 1-2 s; use `platform: integration` there (see `ha-energy-metering`).
- **Cross-tick baseline / counter delta**: dedicated sibling sensor with its own plain `state:`, declared
  AFTER its consumers in the same trigger block; consumers read `states('sensor.the_baseline')`.
  - Why: consumers see the pre-this-tick value. Behaviour CONFIRMED by the counter-delta tests.
  - Mechanism ("sensors in one trigger pass render in declaration order") UNPROVEN. If you reorder the block, re-run those tests.
- **Custom `attributes:` read back via `this.attributes.get(...)` across ticks** — UNPROVEN, do not re-litigate.
  - Why: failed in CI; neither "HA is broken" nor "harness is broken" was ever shown. Use sibling baseline sensors instead (better on its own merits).

## Re-render and propagation
- **Re-posting the IDENTICAL value via `set_state()` does not propagate through a `template:` chain** (CONFIRMED 2026.8.1, `helpers/event.py`).
  - Why: `async_track_template_result` subscribes to `EVENT_STATE_CHANGED` only, never `EVENT_STATE_REPORTED`. Nudge the value by 1 unit instead.
  - Scope: `sensor: platform: integration` listens to both and IS driven by a same-value re-post.
- **A template reading `this` re-renders on its OWN state change**, up to `len(_template_attrs)` times in a row
  before the "Template loop detected" guard (CONFIRMED 2026.10.1, `components/template/template_entity.py::_handle_results`).
  - Why it matters: an externally set state does not stick; each re-render recomputes from real inputs, so a hysteresis ladder walks one step per render toward the inputs. Test consequence: see `ha-test-harness`.

## Decision design
- **One decision sensor, consumers read only it** (CONFIRMED 2026.10.1): compute the decision once in a
  state-based template sensor (state = reason, attributes = outputs); every automation/display reads only that.
  - Why: wiring indicators into each consumer separately lets them disagree.
  - Inputs must never include the outputs. Why: feedback loop.
- **State-based entity `variables:` render ONCE at setup** (CONFIRMED, `template_entity.py::_async_template_startup`).
  - Why it matters: they cannot carry live state. For one evaluation shared by state and attributes, put the logic in a
    `custom_templates/*.jinja` macro returning `"a|b|c"` and import it in each template.

## Automations
- **`automation.trigger` skips conditions by default** — `skip_condition` defaults to `True` (CONFIRMED 2026.10.1, `components/automation/__init__.py`).
  - Production consequence: never rely on `conditions:` alone to keep a `choose` `default:` from running on bad data. Why: a manual "Run actions" also skips them. Name every acted-on case explicitly.
