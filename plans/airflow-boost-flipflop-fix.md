# Airflow — Stop the 30-min boost flip-flop

## Context
`packages/airflow_cooling.yaml` drives a ComfoConnect ERV. `flush_needed`, `boost`,
`free_cooling` and the temperature profile flip on a ~30-min beat.

### Runtime-confirmed root cause (HA history, 24h to 2026-06-12 06:25 UTC, via ha-mcp)
- `switch.comfoconnect_pro_boost` off→on blips **exactly 31 min apart** (06:32, 07:03, 07:34,
  08:05, 08:36, 09:07, 09:38), each a 3-4 s off→on. = boost re-arm: the boost automation writes
  `number.comfoconnect_pro_boost_time = 30`; the integration counts it down to 0 and drops the
  switch; the `boost_expired` (`to: "off"`) trigger turns it straight back on.
- `sensor.airflow_cooling_state` flips `moisture_flush_cooling`↔`moisture_flush_boost` locked to
  those blips → `hvac_action_template` reads raw `boost_on`.
- `number.comfoconnect_pro_boost_time` is a **live countdown** (read 5.08 mid-run), so it gives a
  clean re-arm signal and an in-place write should extend the running boost with no switch drop.
- `select...temperature_profile` also chatters cool↔comfort (6-30 min) in transition windows —
  separate environmental limit-cycle, NOT fixed by the timer change (follow-up C).

## Goal
Boost runs a 60-min period and re-arms seamlessly ~2 min before expiry while drying is still
needed (no switch drop, no `cooling_state` blip). Decouple `hvac_action` from the raw boost
switch so any residual blip never churns the status sensor. Make `drying_needed` visible in
history.

## Steps & status
- [x] 1. Boost duration 30 → 60 + description (`airflow_humidity_drying_boost`). Done.
- [x] 2. Seamless early re-arm: numeric_state trigger on `boost_time` `below: 2` (id `rearm_due`)
       + first choose branch re-writes `boost_time = 60` when drying still needed and boost on
       (no switch toggle, no notify). `boost_expired` fallback kept. Done.
- [x] 3. Fix A: `hvac_action_template` `drying` now reads `drying_needed` intent, not the raw
       boost switch. Done. (Test mirror `_hvac_action_state` updated to match.)
- [x] 4. Fix E: removed `binary_sensor.airflow_humidity_drying_needed` from `recorder.exclude`. Done.
- [x] 5. Tests added in `tests/test_airflow.py`:
       `test_drying_boost_rearm_keeps_switch_on` (re-arm never drops the switch),
       `test_hvac_action_drying_survives_boost_blip` (intent-keyed action survives the re-arm blip),
       `test_hvac_action_not_drying_when_intent_cleared`. Static checks: YAML parses, py_compile OK.
       NOT run in CI yet (no local Docker/harness).

## Follow-ups (not in this pass)
- B. `drying_needed` has no delay_on/delay_off (schedule + weatherstation-temp edges pass instantly).
- C. Profile limit-cycle (cool↔comfort chatter). 60-min boost dumps ~2× air/cycle — may widen the
  swing. Candidate: min-dwell/cooldown on flush/drying or wider hysteresis.
- D. No minimum-off between boost runs.

## Verification
- `homeassistant --script check_config` (CI), `pytest tests/test_airflow.py` (CI — no local infra).
- Device check (live HA): writing `boost_time` mid-run extends without dropping the switch.
- Post-deploy: re-read 24h history of boost switch + cooling_state — 31-min grid gone.

## Notes
- ha-mcp read-only. User deploys via `git pull` — never deploy from here.
