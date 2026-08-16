# Victron tests: remove the day-scale clock jumps

**Status:** IMPLEMENTED — approved and applied. Awaiting CI result.
**Target files:** `tests/test_victron.py`, `tests/test_airflow.py`, `tests/conftest.py`
**Branch:** `fix-victron-ac-dc-mixup` (PR #101)

---

## Finding: no victron sensor depends on time of day

Grepped `packages/victron.yaml` for `sun.`, `now()`, `utcnow`, `today_at`, `as_timestamp`, `hour`.
The file has exactly two time triggers and neither is time-of-day dependent:

```yaml
- platform: time_pattern
  minutes: "/1"        # the accumulator / counter-delta sensor block
- platform: time_pattern
  seconds: "/30"       # victron_keep_alive_30s automation (mqtt.publish)
```

So every victron test needs exactly one thing from the clock: **cross one minute boundary** so the
`/1` block renders once. The wall-clock hour is irrelevant. `hour=10` was almost certainly copied
from `tests/test_pergola.py`, where it is load-bearing (sun elevation) — here it is not.

## What the current pattern actually costs

22 clock operations in the file: 20 × `jump_to_next`, 2 × `fast_forward`.

```
11 ×  jump_to_next(hour=10, minute=0, second=0)
 9 ×  jump_to_next(hour=10, minute=1, second=0)
 2 ×  fast_forward(timedelta(minutes=1))
```

`jump_to_next` is forward-only (`time_machine.py`: `if target_dt <= current_time: target_dt +=
timedelta(days=1)`). Each test leaves the clock at 10:01; the next test asks for 10:00, which is
already past, so the harness **silently adds a full day**. Nobody wanted a day — they wanted a clean
minute boundary.

Consequences:

1. **≈ 11 days of mocked-clock travel** inside `test_victron.py` alone, in 11 discrete 24 h jumps.
2. **Every `sensor: platform: integration` step integrates 86400 s.** Verified in HA 2026.8.1
   (`components/integration/sensor.py::_integrate_on_state_change`):
   `elapsed_seconds = new_state.last_updated - old_state.last_reported`, no timer involved
   (`max_sub_interval` is unset). The first source event after a day-jump bills a full day as one
   trapezoid. The grid energy tests only survive this because they assert a *relative* delta off a
   captured baseline.
3. **The two grid tests carry a jump they do not use.** Their tick comes from `fast_forward`; the
   opening `jump_to_next(hour=10, minute=0)` exists purely as "alignment" superstition — their own
   docstrings say so — and contributes one of the day jumps for nothing.

## Proposed change

Drop `jump_to_next` from `tests/test_victron.py` entirely. One clock op per time-dependent test:

```python
# before  (2 clock ops, +1 day + 1 min)
time_machine.jump_to_next(hour=10, minute=0, second=0)
_reset_energy(home_assistant)
<seed>
time_machine.jump_to_next(hour=10, minute=1, second=0)
home_assistant.assert_entity_state(...)

# after   (1 clock op, +1 min)
_reset_energy(home_assistant)
<seed>
time_machine.fast_forward(timedelta(minutes=1))
home_assistant.assert_entity_state(...)
```

The opening jump's only real effect today is to fire one junk tick that `_reset_energy` immediately
wipes. Resetting first and ticking once is equivalent and one step shorter.

For the two grid tests, delete the opening `jump_to_next` and keep the existing `fast_forward`
unchanged — they already have the right shape underneath the superstition.

**Result: 22 clock ops → 11, and ~11 days of clock travel → ~11 minutes.**

## Why `fast_forward(minutes=1)` is sufficient

`fast_forward` advances by an exact relative delta from wherever the clock is. From any starting
position a 60 s step crosses exactly one `minutes: "/1"` boundary, so the trigger block renders
exactly once — which is all any of these tests need. No absolute anchor is required because no
assertion in the file references an absolute time.

## Relationship to the open CI hang — candidate fix, not a claimed one

The current hang (`plans/ci-test-isolation.md`) is HA accepting the TCP connection and never
answering, with pytest blocked in `socket.recv_into` inside `requests.get`. Cause on the HA side is
still unknown.

Removing ~11 day-scale clock jumps removes the single largest stressor applied to the container, so
this **may** fix it. It is **not** presented as the fix — that claim needs evidence, and three
earlier root-cause claims in this session were each fitted to one confirming run. Treat a green run
after this change as one data point, not proof.

Counter-consideration, now resolved: `.claude/learnings.md` used to record that dropping a
`jump_to_next` alignment call "caused" a 20+ minute hang. That entry has been **deleted as a false
positive** — the hang reproduces *with* the alignment call in place, and the confirmed cause is an
unbounded `requests.get`, not clock alignment. It was a plausible mechanism fitted to one run, which
is exactly what `CLAUDE.md`'s new "never write an unconfirmed learning" rule now forbids.

## Risks

1. **The de-chaining rationale in the docstrings becomes stale.** Several tests carry long comments
   explaining "one jump per test after the reset". Under the new scheme there is one `fast_forward`
   per test and no chaining at all, so those comments must be rewritten, not just left in place.
2. **`test_solar_yield_ac_total_captures_baseline_on_first_tick` is currently skipped** with a
   documented harness-ordering rationale. Leave it skipped in this change; re-enabling it is a
   separate decision once the hang is understood.
3. **The `seconds: "/30"` keepalive automation fires more often** under minute steps than under day
   steps (twice per test instead of once). It calls `mqtt.publish` against a broker that does not
   exist in CI. Currently harmless; worth a look in the CI log after the change in case it starts
   logging errors at a higher rate.
4. **No behaviour change is intended.** Every assertion keeps its current expected value. If any
   assertion moves, the tick semantics differ from the analysis above and that is a finding, not
   something to paper over by adjusting the expected number.

## Verification

1. All currently-passing victron assertions still pass, unchanged.
2. `grep -c "jump_to_next" tests/test_victron.py` → 0 occurrences in test bodies.
3. CI run completes; note the rest-step duration against the 1m25s green / 2m22s timeout-run
   baselines.
4. If the hang recurs, the `--timeout=90 --timeout-method=thread` instrumentation still catches it
   in 90 s with a thread dump — so this change cannot make diagnosis worse.

## Status

- [x] Confirm no victron sensor is time-of-day dependent (see Finding above)
- [x] Get approval
- [x] Replace the 20 `jump_to_next` calls with 11 `fast_forward(timedelta(minutes=1))` calls
- [x] Rewrite the now-stale docstrings/comments about chaining and alignment
- [x] Audit the other suites (see below)
- [x] Add the `requests` default-timeout shim to `tests/conftest.py`
- [x] Purge the two false-positive entries from `.claude/learnings.md`; add the confirmed ones
- [x] Add a "never write an unconfirmed learning" rule to `CLAUDE.md`
- [ ] Push, read CI result, record outcome honestly

## Audit of the other suites (done)

| File | Clock ops before | After | Note |
|---|---|---|---|
| `tests/test_victron.py` | 22 (20 jumps + 2 fast_forwards) | **11** fast_forwards | 1 per time-dependent test |
| `tests/test_airflow.py` | 2 jumps in `_assert_recomputes_after_reload` (2 tests) | **1** `fast_forward(minutes=11)` | crosses the 10-min `delay_on`/`delay_off` |
| `tests/test_shelly_pool_pump.py` | 0 | 0 | nothing to do |
| `tests/test_templates.py` | 0 | 0 | nothing to do |
| `tests/conftest.py` (pergola sun fixtures) | 2 jumps | 2 jumps — **kept** | genuinely need an absolute date (Jun 21 sun elevation), and `test_pergola.py` runs in its own isolated instance |

For airflow, checked that neither sensor under test is schedule- or time-gated by extracting the
dependency set from their template bodies in `packages/airflow_cooling.yaml`:

```
airflow_humidity_flush_needed            -> input_number.*, sensor.airflow_*, sensor.heating_cooling_indicator
airflow_moisture_ventilation_low_needed  -> binary_sensor.airflow_*, sensor.airflow_*
```

Neither reads `schedule.*`, `binary_sensor.workday`, or any time function, so dropping the 10:00
anchor cannot flip them. (`low_needed` does read `drying_needed`, which *is* schedule-gated — but
the test only asserts "some definite on/off", not which.)

## Also implemented alongside: the HTTP timeout shim

`tests/conftest.py` now wraps the module-level `requests` helpers to `setdefault` a 30s timeout.
Separate concern from the clock work, same root problem: the confirmed thread dump
(`plans/ci-test-isolation.md`) put the hang in `requests.get` with no `timeout=`. Notably
`assert_entity_state(timeout=5)` never protected against this — its timeout is checked between
poll iterations, and each iteration calls the unbounded `get_state()`.
