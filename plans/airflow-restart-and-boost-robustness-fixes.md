# Airflow — restart / Away robustness of the drying boost + decision cleanups

Pinned HA: `ghcr.io/home-assistant/home-assistant:2026.10.1` (`FROM` line of `.github/ha-versions/ha/Dockerfile`).
Touches ONLY airflow files: `packages/airflow_cooling.yaml`, `custom_templates/airflow_decision.jinja`,
`packages/notes/airflow_cooling.md`, `tests/test_airflow.py`. Independent of the victron / heating plans.

## Context
A review of `automation.airflow_humidity_drying_boost` (after the single-decision refactor, #131) found
that its restart / Away behaviour does not match what its comments and the notes claim. No outage has
been reported yet; these are latent defects found by reading the code. Line numbers are from master
`0a4cab0` and were re-verified.

## Verified findings
1. **Away `unknown` at startup kills the ha_start run.** The top-level condition
   `switch.comfoconnect_pro_away_function == "off"` (l.1318-1320) is false while the ComfoConnect
   entity is still `unknown`/`unavailable` right after `homeassistant: start`, so the `ha_start` run
   is dropped. Nothing else covers it except `boost_decided` (l.1286), which only fires if the
   decision sensor itself changes to boost after the start — it may already be `boost` when HA comes
   up (restored state), so no transition happens. Net: a boost that is decided but not running after
   a restart is not started until the decision leaves boost and returns.
2. **`away_ended` (l.1307-1310) matches no branch.** It passes the conditions but the (Re)start
   branch (l.1352-1367) only accepts `boost_decided` or `ha_start`; the re-arm branch needs
   `rearm_due`; the stop branch needs `boost_not_decided`. So the trigger always hits
   `default: []`. Consequence: boost decided while Away is on is never started when Away ends.
3. **Boost timer silently reset on `unavailable -> boost`.** `boost_decided` (`to: "boost"`, l.1286-1290)
   also fires when the attribute goes `None/unavailable -> boost` (reload, restart of the template
   entity, an input briefly unavailable). The (Re)start branch has no boost-off requirement for
   `boost_decided` ("write boost ON even if a boost already runs", l.1349-1351), so it sets
   `boost_time=60` and `switch.turn_on` on a running boost, which restarts the 60-min countdown
   (notes l.16-18, verified on the device), and `boost_was_on` suppresses the notification, so it
   is invisible. The comment at l.1350-1351 ("a restart only acts when no boost runs") and the
   description at l.1272 are wrong for this trigger.
4. **Single missed re-arm lets the boost lapse (left open by decision).** `rearm_due` is `numeric_state below: 5` (l.1303-1306);
   it fires only on the crossing 5 -> <5. If that one run is dropped/blocked (queue `max: 5` full,
   Away on at that moment, decision briefly unavailable, HA restart inside the last 5 min) nothing
   re-arms; the boost ends at 0 and, per design, a boost-off never restarts it (notes l.19-21).
5. **`| float(0)` on guarded sensors** in `custom_templates/airflow_decision.jinja` l.26-27
   (`sensor.airflow_min_indoor_dew_5min`, `sensor.airflow_dew_point_min`). Both are in the sensor's
   `availability:` (`packages/airflow_cooling.yaml` l.281-282, `has_value`), so the default only
   hides errors; forbidden by CLAUDE.md. The macro is only rendered for state/attributes of that
   sensor, which is unavailable (not rendered) when either is missing — to re-confirm at step 4 by
   grepping all `airflow_decision` call sites (expected: state, `profile`, `ventilation`
   attributes of the same sensor).
6. **Stale comments** to fix: `packages/airflow_cooling.yaml` l.1349-1351 and the description l.1271-1277;
   `packages/notes/airflow_cooling.md` l.19-21 (says "only `drying_needed` off->on (re)starts"; stale
   since #131 — it is the decision's `ventilation` becoming `boost`, and after this plan also
   `away_ended` / `ha_start`).

### Optional items (see Decisions: A, B not done; C comment only)
- A. Dry retention uses `prev_profile == 'warm'` (macro l.32); `warm` is also the plain heating-season
  profile, so entering dry retention while already warm for heating uses the wider hysteresis
  (stays "dry" until `dew_min`, not `dew_min - 0.1`). Cosmetic (label `moisture_retention` vs
  `heating`), no output change because both are `warm`.
- B. The restore-auto branch of the controller cannot tell who turned `auto_mode` off (user vs
  automation) — it restores auto whenever `auto` is decided.
- C. Turning the `airflow_cooling_automatic_enabled` helper off does not stop a running boost (the
  boost automation's top-level condition just stops reacting; the hardware runs out its 60 min).

## Decisions (settled by the owner, 2026-10-30)
1. **A manual stop must stick; keep it simple.** A boost is only started on an *edge into* boost,
   never from a level. Edges that count: the decision `ventilation` going from a real non-boost value
   to `boost`, and Away ending (`away_ended`) while boost is decided and the boost switch is off.
   A Home Assistant restart is NOT an edge and starts nothing.
2. **Away must be explicit.** Only `on` means away; `unknown`/`unavailable` count as not away.
3. **No second re-arm threshold.** Too much complexity for little gain; finding 4 stays as a documented
   residual risk (a missed re-arm lets the boost lapse; it restarts on the next edge).
4. **Optional items:** only low-complexity, no-maintenance ones. Outcome: A (label-only) and B (needs
   extra memory/state) are not done. C is documented in a comment only (disabling the helper leaves a
   running boost to the hardware), no logic change. See Step 5.

### Scenario table (behaviour after this plan)
| Scenario | Today | After |
|---|---|---|
| Decision `auto/medium/low/off -> boost`, boost off | starts | starts |
| Same, a manual boost already running | restarts timer (adopts) | unchanged |
| User stops the boost by hand while still decided | stays off | stays off (no edge) |
| Away ends, boost decided, boost off | nothing (finding 2) | starts (edge) |
| Away ends, boost decided, boost already on | nothing | nothing (guard: boost off) |
| Away `unknown -> off` at HA start, boost decided and off | nothing | starts (still an Away edge; accepted, see Risks) |
| HA restart, boost decided and running | decision flap may reset the 60 min timer (finding 3) | nothing, timer untouched |
| HA restart, boost decided and not running | nothing (ha_start dropped by Away `unknown`) | nothing (by design: restart is not an edge) |
| Decision `unavailable -> boost` (reload, input outage), boost running | silently resets timer | nothing |
| Decision `unavailable -> boost`, boost not running | starts | nothing (no real edge; starts at the next real edge) |
| Away `unknown`/`unavailable` | blocks everything | not away |

## Design (per step)

### Step 1 — Away is explicit (finding 1)
Replace the top-level `condition: state away == "off"` with the template condition
`{{ not is_state('switch.comfoconnect_pro_away_function', 'on') }}`. Comment: only an explicit `on`
means away. The re-arm and stop branches pass through this too; acceptable.

### Step 2 — Start only on an edge; away_ended becomes a start edge (findings 2, 3)
1. `boost_decided` trigger gets `from: ["medium", "low", "auto", "off"]` (the same real non-boost
   values the stop branch already lists). Effect: `unavailable`/absent `-> boost` no longer fires,
   which removes the silent timer reset (finding 3) and the restart start. No template needed.
2. Remove the `ha_start` trigger and its `and` clause from the (Re)start branch.
3. (Re)start branch condition becomes: decision `ventilation == boost` AND `or`:
   - `trigger boost_decided`
   - `and`: `trigger away_ended`, `switch.comfoconnect_pro_boost == off`
4. Update the automation `description:` and branch comments: starts only on an edge into boost
   (decision change or Away end); a restart or an input flap never starts or re-arms a boost; a
   manually stopped boost stays off until the next edge.
The existing `has_value(sensor.airflow_cooling_state)` top-level condition stays.

### Step 3 — Remove `| float(0)` (finding 5)
In `custom_templates/airflow_decision.jinja` l.26-27 use `| float`. First grep all `airflow_decision`
call sites to confirm each render sits under the sensor's `availability:` (`has_value` terms at
`packages/airflow_cooling.yaml` l.281-282). Existing `test_decision_*` tests stay green unchanged.

### Step 4 — Comments and notes (finding 6)
Fix `packages/airflow_cooling.yaml` comments/description (l.1262-1277, 1349-1351) and
`packages/notes/airflow_cooling.md` l.19-21 to the real behaviour (scenario table). Do NOT add a
learning (findings are code reading, not proven; CLAUDE.md).

### Step 5 — Item C as a comment only
One comment in the automation: disabling `input_boolean.airflow_cooling_automatic_enabled` makes the
automation stop reacting, including the stop branch; a running boost runs out on the hardware.
Items A and B: no change.

## Test plan
Harness: `tests/test_airflow.py` (`home_assistant` fixture, `_decide_boost`, `_trigger_drying`,
`set_state`, `assert_entity_state`). Switch/number service calls on stubs are ignored and manual
`automation.trigger` carries no trigger id, so branch selection is trace-based; real triggers
(state changes) are observable via traces. Check how existing tests read traces first.
- Keep passing: `test_drying_boost_*` (l.282-339), `test_drying_boost_away_suppressed` (l.540).
- New: Away `unknown -> off` with boost decided and boost off -> (Re)start branch ran.
- New: Away `-> off` with boost already on -> default branch.
- New: decision `unavailable -> boost` -> the trigger does not fire.
- New: real `auto -> boost` -> start branch.
- New: Away `unknown` + real `auto -> boost` -> start branch (Away fail-open).
- New: no `ha_start` trigger remains (assert via the automation config if the harness exposes it).
- Run: pinned-image suite as in `plans/airflow-cooling-state-single-decision.md` step 6 (re-measure
  the baseline on master first), HA `check_config`, yamllint, `git ls-files --eol`.

## Risks
- Fail-open Away: if Away is `unavailable` while people are really away, a boost may run 60 min.
  Low cost (boost needs dry outdoor air).
- A boost that is decided during a restart/outage, with the decision never leaving boost, is not
  started until the next edge. Accepted by the owner (restart is not an edge).
- Away `unknown -> off` at HA start counts as an `away_ended` edge and may start a decided, stopped
  boost shortly after a restart. Accepted: rare and harmless; keeps the trigger simple.
- Finding 4 (single missed re-arm) stays open by decision: the boost lapses and restarts at the next
  edge.

## Post-deploy live verification (after `git pull`, user restarts HA)
1. With boost decided and RUNNING: restart HA; `number.comfoconnect_pro_boost_time` keeps counting
   down (not reset to 60), no notification (`ha_get_automation_traces`, read only).
2. Stop the boost by hand while decided: it stays off, also after a decision flap.
3. Boost decided while Away on: turn Away off; the boost starts via `away_ended`.
4. Watch one 60-min cycle: re-arm at <5 min, the switch never flips off.
5. `sensor.airflow_cooling_state` unchanged on a decision-table spot check.

## Status
- [x] 0. Plan reviewed, decisions answered (2026-10-30); approved to implement
- [x] 1. Away condition: only explicit `on` is away
- [x] 2. `boost_decided` with `from:` real values, drop `ha_start`, `away_ended` start edge
- [x] 3. Remove `| float(0)` in `custom_templates/airflow_decision.jinja`
- [x] 4. Fix stale comments in `packages/airflow_cooling.yaml` and `packages/notes/airflow_cooling.md`
- [x] 5. Item C comment only (A, B not done by decision)
- [~] 6. Tests added (4 harness tests + 1 static config test); run in CI only (no docker/harness locally); the two "real edge" tests create the edge via the automation master switch because seeding flush/drying makes the decision flicker unavailable in CI (None -> boost is correctly not an edge). yamllint/fix_yaml_style/resolve_ha_yaml/eol checked locally. Not testable in harness: branch selection (no trace access), away_ended with boost already on.
- [ ] 7. Deployed by user (`git pull`) and live verification above done
