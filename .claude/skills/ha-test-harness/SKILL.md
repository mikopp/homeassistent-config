---
name: ha-test-harness
description: "Gotchas for this repo's pytest + ha_integration_test_harness suite (Docker HA, mocked clock, REST set_state seeding). Use when writing, debugging or reviewing tests/*.py, conftest.py, CI test steps, flaky/hanging CI, fast_forward/jump_to_next, pytest-timeout."
---

# pytest + ha_integration_test_harness gotchas

Grades: **CONFIRMED** = source read at the pinned version (`.github/ha-versions/ha/Dockerfile` `FROM`),
stack trace / thread dump, or deterministic repro. **OBSERVED** = real data, alternative explanation open.
**UNPROVEN** = hypothesis, kept so it is not re-litigated. Never promote a grade without new evidence.
Package-specific test facts live in the package notes (`packages/notes/<package>.md`).

## First rule
- **When a CI-only test fails, establish whether the harness is at fault before redesigning production YAML.** Why: proven repeatedly here; several confident "HA is broken" root causes were wrong.

## Mocked clock
- **Step with `fast_forward(timedelta(...))`, never `jump_to_next(hour=...)`, unless the code is genuinely time-of-day dependent** (CONFIRMED, `time_machine.py`).
  - Why: `jump_to_next` is forward-only (`if target_dt <= current_time: target_dt += timedelta(days=1)`); re-requesting a passed hour silently advances a full day (and every `platform: integration` step integrates 86400 s).
  - Check the package first (grep `sun.`, `now()`, `today_at`, `hour`). `test_pergola.py` needs them (sun elevation); `test_victron.py` did not.
  - Same for `jump_to_next(month=...)`: advances a full year once the month has passed.
  - DISPROVED: month/year jumps (pergola fixtures reach ~2032) are NOT the CI hang cause; a docs-only commit hung with identical test code.
- **Delayed trigger-based sensors are `unknown` after boot until the mocked clock crosses their delay** (CONFIRMED, airflow and heating tests).
  - Why it matters: tests silently piggyback on an earlier test's clock move; a green full-suite run hides this. Run a touched test file on its own before trusting it.
- **Chaining several `jump_to_next()` calls in one test** — OBSERVED, mechanism DUBIOUS: `last_updated` stayed pinned to the reset timestamp on 2nd/3rd jumps.
  - Rule: one clock advance per test; seed "already progressed" state via `set_state()`. Why: a wedged container (below) produces the same symptom, so the "harness won't re-fire" cause is not established.

## REST `set_state()` seeding
- **Seed trigger inputs FIRST, then delayed (`delay_on/off`) trigger-based binary sensors** (CONFIRMED, deterministic repro, airflow, 2026.10.1).
  - Why: the delay has never elapsed in CI, so the sensor has no internal state; any trigger re-renders it and writes `unknown` over the seed (cascading to dependents).
- **Don't pin a self-referencing template (reads `this.state`) with `set_state()`** (CONFIRMED 2026.10.1, `template_entity.py::_handle_results`).
  - Why: it re-renders on its own state change (up to `len(_template_attrs)` times, e.g. state + availability = 2) and walks a hysteresis ladder back toward its real inputs. Drive the real input (e.g. the 48h mean) and assert the reached state; one input change moves it at most 1 + 2 steps.
- **`sensor: platform: integration` totals can't be reset via `set_state()`.** Why: the total is in entity memory. Assert a before/after delta (details: `ha-energy-metering`).
- **Same-value `set_state()` doesn't propagate through `template:` chains.** Why: listens to state *changes* only. Nudge by 1 unit (details: `ha-templates`).
- **`automation.trigger` skips conditions by default** (CONFIRMED 2026.10.1). Why: `skip_condition` defaults to `True`; a test of a condition guard must pass `skip_condition: False`.

## Hangs and timeouts
- **Harness HTTP calls can block forever** (CONFIRMED, pytest-timeout thread dump). Why: `ha_integration_test_harness` v0.11.0 calls `requests.get/post/delete` without `timeout=`; a container that accepts TCP but never answers parks in `socket.recv_into`.
  - `assert_entity_state(timeout=5)` does NOT protect: the timeout is checked between polls, each calling the unbounded `get_state()`.
  - `jump_to_next()`/`fast_forward()` are unbounded `docker exec` writes to `/shared_data/.faketime`; they never poll, so a hang "in a jump" is a hung `docker exec`, not clock arithmetic.
  - Fix in place: `tests/conftest.py` wraps `requests` helpers to `setdefault` a 30 s timeout; CI uses `pytest-timeout --timeout=90 --timeout-method=thread` and job-level `timeout-minutes: 20`. Keep them.
- **`pytest-timeout` charges session-fixture setup to whichever test triggers it unless `timeout_func_only = true`** (CONFIRMED, thread dump in `docker_manager.py → subprocess.run` / `docker compose up`, 60-90 s). Why: keep `timeout_func_only = true` in `pyproject.toml`; bound setup with job `timeout-minutes`.
- **`--timeout-method=thread` aborts the whole invocation** after dumping all stacks. Why: right while a hang is undiagnosed; switch to `signal` (raises in the test, run continues) once understood.

## Ordering and isolation
- **Test order is NOT file-definition order.** Why: `tests/conftest.py::pytest_collection_modifyitems` sorts by `(0 if "test_pergola" else 1, item.nodeid)`. Don't reason about neighbouring tests from source position.
- **Per-file isolation = separate `pytest tests/<file>.py -v` CI step, with `--ignore=tests/<file>.py` on the shared step** (used for `test_pergola.py` in `.github/workflows/ha_check.yaml`).
  - Why: each step is its own process, so session-scoped `docker`/`home_assistant`/`time_machine` fixtures start fresh → deterministic clock and container.
  - Does NOT prevent hangs (claimed once, disproved). Copy the Job Summary / PR-comment / fail-check handling of multiple step outcomes too.
- **One skipped test, never root-caused** (UNPROVEN): failed deterministically (2/2, unaffected by 5s→20s timeout) apparently only due to its nodeid-sorted position; skipped with documented `@pytest.mark.skip(reason=...)`. Why kept: worth re-testing now that HTTP calls are bounded; the wedged-container explanation may cover it.

## Docker in the cloud sandbox
- Docker works in the cloud sandbox (`dockerd`), but the harness image needs the proxy CA + libfaketime baked in. Why: `apk add` at container start fails TLS through the proxy.
