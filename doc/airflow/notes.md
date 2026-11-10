---
paths:
  - "packages/airflow_cooling.yaml"
  - "custom_templates/airflow_decision.jinja"
  - "tests/ha/test_airflow.py"
  - "dashboards/airflow-dashboard.yaml"
  - "doc/airflow/design.md"
---
# airflow_cooling package notes (`packages/airflow_cooling.yaml`)

Read before touching `packages/airflow_cooling.yaml`, `custom_templates/airflow_decision.jinja`,
its tests or its dashboard. Scope: ComfoConnect (Zehnder ComfoAir Q350 ERV) temperature profile,
ventilation level and humidity boost. Design (entities, season machine, decision table, actuator
automations, bypass estimation): `doc/airflow/design.md` (`AF-1` … `AF-12`). This note holds what
you must not break.

## Invariants
### Single decision (`sensor.airflow_cooling_state`) — the rule for every consumer
CONFIRMED by `test_decision_*` in `tests/test_airflow.py` at 2026.10.1 (since moved to
`tests/ha/test_airflow.py::test_decision_table`).
- **Indicators feed only the decision; consumers read only the decision.** The indicators
  (`free_cooling_available`, `humidity_flush_needed`, `humidity_drying_needed`, moisture/heat low,
  `heating_cooling_indicator`, indoor dew vs `dew_point_min`) are inputs of
  `sensor.airflow_cooling_state` and of nothing that writes the device. The controller, the drying
  boost and `climate.airflow_climate`'s hvac_action read its state / `profile` / `ventilation`
  attributes. Never wire an indicator straight into an automation — why: consumers that each
  re-implement the season rules disagree.
- The decision **never reads an output** (profile, preset, auto_mode, boost switch, climate), so
  applying it cannot change it. Priority/season rules live in one place:
  `custom_templates/airflow_decision.jinja`, rendered for the state and both attributes (state-based
  template entities cannot share variables between state and attributes at 2026.10.1 — entity
  `variables` render once at setup).
- It is **state-based** (derives from slow binaries; see the trigger-vs-state rule below) and
  unavailable unless every indicator has a value — the automations then no-op.

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
- **A boost-off never restarts the boost.** The drying automation has no `boost_expired` path. A boost
  is started only on an *edge into boost*: the decision's `ventilation` going from a real non-boost
  value (`medium`/`low`/`auto`/`off`) to `boost` (also adopting a running manual boost), or Away ending
  (`away_ended`) while boost is decided and the boost switch is off. A HA restart / reload / the
  decision going `unavailable -> boost` is NOT an edge and starts nothing (so it cannot reset a running
  timer). The countdown re-arms a running boost while boost is still decided. A manual off therefore
  sticks until the next edge. Away counts only when explicitly `on` (`unknown`/`unavailable` = not away).
  Edge table: design `AF-7.2`.

## Entity map
Full inventory with roles: design `AF-2` (inputs, thresholds, indicators, actuators, views) and
`AF-9` (helpers). Season thresholds: `input_number.heating_indicator_*` (design `AF-4`).

## Decisions in force
### Template sensor pattern — trigger-based vs state-based
A derived template `binary_sensor` whose inputs are **only other (slow) binary sensors** MUST be
**state-based** (plain `state:`, no `trigger:`). Trigger-based template sensors restore their last
state on HA **restart** and recompute only when an input **changes** — so a derived-from-binaries
sensor can restore **stale** and never resync.
Reserve trigger-based + restore for **primary** decision sensors driven by continuously-drifting
numeric filters (outdoor temp/dew, weather-station temp): there the drift guarantees a recompute
within ~1 debounce after restart, and restoring preserves the 10-min delay + `this.state` Schmitt
hysteresis. Note the `to: "unknown"` self-trigger covers *reload* (comes up `unknown`), **not**
*restart* (comes up with a restored value), so it does not protect against restart-stale.

### Ventilation controller (`automation.airflow_ventilation_controller`, Section 2) rules
- Gate preset/auto ownership on the **decision** (`ventilation` attribute — boost ⊂ flush intent),
  NOT the boost/auto switches, which flap during boost expiry/re-enable races.
- While a boost is intended/running: write **no preset** and only ever turn `auto_mode` **ON** (or do
  nothing). The boost-owner branch is first in the `choose` and matches on the intent, so the `choose`
  EXITS there and the Low/Medium branches (which turn auto off / write a preset) can never cancel the
  boost. Boost gives HIGH meanwhile, so the underlying preset is moot until boost ends.
- Force `preset=medium, auto=off` only when medium is decided and the schedule is holding
  `preset=low`; `auto=on, preset=medium` is the preferred state and must not be re-forced.
- Prefer minimal, surgical controller edits over restructures; retain existing branch behaviour unless
  a change is required to fix a specific defect.

## Known biases / open issues
- Boost residual risk (accepted): a single dropped re-arm lets the boost lapse; it restarts at the
  next edge.
- `drying_needed` reads `input_number.airflow_cooling_target_temperature | float(21.5)`, a fallback
  default on a helper that the repo rule forbids (code, not fixed in a docs step). → GitHub issue #142

## Tests (`tests/ha/test_airflow.py`, in-process; no Docker tests left)
- Item-2 tables (decision, bypass, dew points) seed the indicators: seed season/dew first, then the
  delayed indicators — CONFIRMED; otherwise a season/dew change re-renders the seeded indicators to
  `unknown` (no internal state without the delay).
- Item-4 tests drive the REAL indicators through the seeded 5-min filter outputs and the clock
  (10 min delays, `this.state` hysteresis), the real workday/schedules (clock moved to a known
  weekday), and the automations on real triggers; effects are the recorded ComfoConnect/phone calls.
- CONFIRMED config bug, `test_drying_boost_unavailable_to_boost_does_not_fire` (strict xfail):
  a flush input going briefly unavailable restarts a running boost (decision unavailable →
  medium → boost is a real edge). Details: `plans/test-execution.md`, item 4 results.

## Related
- `doc/airflow/design.md` — current design (`AF-*` IDs).
- `packages/heating_cooling_indicator.yaml` — season indicator consumed by the decision.
