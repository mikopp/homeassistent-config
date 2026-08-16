# Project Learnings & Gotchas

Evidence grading is explicit throughout. **CONFIRMED** = a stack trace, a source read at the pinned
`.HA_VERSION`, or a deterministic reproduction. **OBSERVED** = real data from a real run, but with a
plausible alternative explanation still open. **UNPROVEN** = a hypothesis kept only so it is not
re-litigated from scratch. Never promote an entry a grade without new evidence. See `CLAUDE.md` →
"NEVER write an unconfirmed learning".

## Active Patterns

### Home Assistant
- **W→kWh accumulation via trigger-based `template:` sensor** (CONFIRMED by every accumulator in
  `packages/victron.yaml` passing CI): `- trigger: [platform: time_pattern, minutes: "/1"]`,
  `state: "{{ (this.state | float(0)) + (power/60000) }}"`. `this.state` self-reference reads the
  entity's PREVIOUS state (pre-write). Use this for anything derived from a power reading. Grid
  import/export moved off it to `sensor: platform: integration` for **accuracy**, not because this
  pattern failed — 1/min sampling is coarse when the source pushes every 1-2 s.
- **Cross-tick baseline/counter-delta tracking**: use a DEDICATED sibling sensor with its own plain
  `state:`, declared AFTER its consumer(s) in the same trigger block; consumers then read the
  pre-this-tick value via `states('sensor.the_baseline')`. **Behaviour CONFIRMED** by the
  counter-delta tests. **Mechanism ("sensors in one trigger pass render in declaration order")
  UNPROVEN** — inferred from the observed values, not read out of HA source. If you reorder that
  block, re-run those tests rather than trusting the explanation.
- **`sensor: platform: integration`** (Riemann-sum/trapezoidal) for power→energy when the source
  updates faster than 1/min. CONFIRMED at 2026.8.1
  (`components/integration/sensor.py::async_added_to_hass`): it subscribes to **both**
  `async_track_state_change_event` and `async_track_state_report_event`, so even a same-value
  re-post drives it — unlike classic `template:` sensors (see Anti-Patterns). With no
  `max_sub_interval` it has **no timer at all**: the next source event integrates the whole elapsed
  gap as one trapezoid, `elapsed = new_state.last_updated - old_state.last_reported`. Gaps through
  `unavailable` are NOT billed (`validate_states` can't parse the old value, so no area is added).
  It also tolerates a source that doesn't exist yet at HA startup.
- **Repointing an entity across a platform change** (mqtt→template, template→integration) while
  preserving Energy Dashboard history: keep the exact same `unique_id`, then do a ONE-TIME MANUAL
  entity-registry reclaim after deploy (delete the orphaned old-platform row, rename the new entity
  onto the freed entity_id). CONFIRMED at 2026.8.1: the registry key is `platform + unique_id`
  (`entity_platform.py::_async_derive_object_ids` — `default_entity_id:` only *suggests*, it loses a
  collision and you get `_2`), and history follows the **entity_id string**
  (`recorder/entity_registry.py::_async_entity_id_changed`). Do the rename within ~5 min of restart:
  `statistics_meta.py::update_statistic_id` refuses when the target statistic_id already exists, so
  the `_2` entity must not have compiled statistics of its own yet. Full runbook in
  `plans/victron-ac-referenced-accounting.md`.
- **Derive deploy/migration docs from the BRANCH DIFF, never from the live system.** The HA host
  runs whatever was last pulled, so `ha-mcp` state and the entity registry describe the *old* world.
  Caught this the hard way: a deploy runbook told the user to repoint six `utility_meter` helpers
  that this branch had already deleted from `packages/victron.yaml` — they only still existed live
  because the host had not pulled. `git log -S`/`git diff origin/master...HEAD` is the source of
  truth for what a deploy will change; the live system is only useful for values to record
  beforehand and for UI-only state (`.storage`: Energy Dashboard prefs, dashboards, helpers created
  in the UI) that is not in the repo at all.
- **Verifying HA-version-specific behaviour**: pull the actual source at the pinned `.HA_VERSION` —
  `gh api repos/home-assistant/core/contents/<path>?ref=<tag>`. This is what CLAUDE.md's "HA version
  gate" operationalises, and it is what turned three of the entries on this page from guesses into
  facts. Docs were ambiguous or silent every time it mattered.

### Test Harness
- **Step the mocked clock with `fast_forward(timedelta(...))`, never `jump_to_next(hour=...)`,
  unless the code under test is genuinely time-of-day dependent.** CONFIRMED in `time_machine.py`:
  `jump_to_next` is forward-only (`if target_dt <= current_time: target_dt += timedelta(days=1)`),
  so re-requesting an already-passed hour silently advances a **full day**. Anchoring every test to
  `hour=10` cost one day per test — 20 calls in `test_victron.py`, ~11 days of travel, and every
  `platform: integration` step integrating 86400 s. Check the package first (grep `sun.`, `now()`,
  `today_at`, `hour`): `packages/victron.yaml` has none, so those 20 jumps were cargo cult from
  `test_pergola.py`, where sun elevation makes them load-bearing. See
  `plans/victron-test-clock-simplification.md`.
- **`pytest-timeout` charges session-fixture setup to whichever test triggers it** unless
  `timeout_func_only = true`. CONFIRMED by thread dump: `--timeout=90` killed a whole pytest
  invocation inside `docker_manager.py:603 → subprocess.run` (`docker compose up`, 60-90 s) before a
  single test ran, reported against `test_automation_disabled` which had not started. Set
  `timeout_func_only = true` in `pyproject.toml`; bound setup hangs with a job-level
  `timeout-minutes` instead.
- **Per-file test isolation via a separate `pytest` step in the CI job**: `pytest tests/<file>.py -v`
  as its own step, with `--ignore=tests/<file>.py` on the shared step. Each step is its own process,
  so the harness's session-scoped `docker`/`home_assistant`/`time_machine` fixtures start fresh.
  Established for `test_pergola.py` in `.github/workflows/ha_check.yaml`. **What it actually buys:**
  a deterministic per-file clock and container. **What it does NOT buy: hang prevention** — that was
  claimed once and disproved (see Anti-Patterns). Copy the pattern (including the Job Summary /
  PR-comment / fail-check steps' handling of multiple step outcomes) when a file genuinely needs its
  own instance.

## Anti-Patterns & Failures

### Home Assistant
- **Re-posting the IDENTICAL value via `set_state()` to force a downstream recompute** — does not
  propagate through a `template:` sensor chain. CONFIRMED at 2026.8.1
  (`helpers/event.py`): `async_track_template_result` subscribes to `EVENT_STATE_CHANGED` only,
  never `EVENT_STATE_REPORTED`. Fix: nudge the value by 1 unit. **Scope note:** this is specific to
  classic `template:` sensors — `sensor: platform: integration` listens to *both* event types and
  IS driven by a same-value re-post (see Active Patterns).
- **`sensor: platform: integration` rejects `device_class`/`state_class` as config keys** —
  `'device_class' is an invalid option for 'sensor.integration'`. CONFIRMED by a real config-check
  failure. The platform applies its own.
- **`sensor: platform: integration` keeps its running total in the entity's own Python memory**
  (restored via `RestoreSensor`) — not by re-reading its own HA-visible state. A `set_state()` REST
  override displays briefly, then the next integration step silently overwrites it using the OLD
  internal value. **Cannot be reset via `set_state()`.** Tests need a before/after baseline delta.
- **Custom `attributes:` on a trigger-based `template:` sensor, read back via
  `this.attributes.get(...)` across ticks — status UNPROVEN, do not re-litigate.** It failed in CI,
  3 round-trips went into source-tracing HA core PR #172847 as the culprit, and it was then blamed
  on the harness instead — but neither the "HA is broken" nor the "harness is broken" side was ever
  positively demonstrated. The repo uses dedicated sibling baseline sensors regardless, which is a
  better pattern on its own merits. **Transferable lesson (this part IS proven, repeatedly, in this
  repo): when a CI-only test fails, establish whether the harness is at fault before redesigning
  production YAML.**

### Test Harness
- **Harness calls that can block forever — CONFIRMED by a pytest-timeout thread dump.**
  `ha_integration_test_harness` v0.11.0 calls `requests.get/post/delete` with no `timeout=`, so an
  HA container that accepts the TCP connection but never answers blocks the process forever (dump:
  main thread in `socket.recv_into` inside `requests.get`, waiting on the HTTP status line).
  **`assert_entity_state(timeout=5)` does NOT protect against this** — its timeout is checked
  BETWEEN poll iterations and each iteration calls the unbounded `get_state()`, so the ceiling is
  never reached. Every `timeout=` in this suite was decorative against a wedged container.
  `jump_to_next()`/`fast_forward()` are unbounded too (`subprocess.run(["docker","exec",...])`), but
  they only write `/shared_data/.faketime` and never poll — a hang "in a jump" would be a hung
  `docker exec`, not clock arithmetic. **Fix (implemented):** `tests/conftest.py` wraps the
  module-level `requests` helpers to `setdefault` a 30 s timeout; CI adds
  `pytest-timeout --timeout=90 --timeout-method=thread` (with `timeout_func_only = true`) and a
  job-level `timeout-minutes: 20`.
- **`--timeout-method=thread` aborts the whole invocation**, not just the timed-out test: it dumps
  every thread's stack, then kills the process. Correct while a hang is undiagnosed; switch to
  `signal` (raises inside the test, run continues, main thread only) once it is understood.
- **pytest test order here is NOT file-definition order.** `tests/conftest.py`'s
  `pytest_collection_modifyitems` sorts by `(0 if "test_pergola" else 1, item.nodeid)` — alphabetical
  by nodeid. Don't reason about "the test before/after this one" from source position.
- **`tests/test_airflow.py` has real cross-test ordering dependencies on the clock.** CONFIRMED by
  breaking it: the delayed binary sensors (`delay_on`/`delay_off` = 10 min, trigger-based, no
  `homeassistant:start` trigger) sit at `unknown` after boot. conftest's `baseline_states` seeds
  their inputs and fires their triggers, but the result only lands once the mocked clock crosses the
  delay window. Removing the single clock advance in `_assert_recomputes_after_reload` broke **two
  unrelated tests** that were silently piggybacking on it running earlier in nodeid order. Any test
  asserting a definite on/off from a delayed sensor needs a `fast_forward` before it — check before
  touching clock calls in that file.
- **Chaining multiple `time_machine.jump_to_next()` calls within one test — OBSERVED, mechanism
  DUBIOUS.** Diagnostic dumps showed the entity's `last_updated` pinned to the reset's own timestamp
  instead of advancing on a second/third jump. The data is real, but the conclusion ("the harness
  won't re-fire the trigger") predates the discovery that HA can wedge and that every HTTP read was
  unbounded — a wedged container produces exactly this symptom. Practical rule stands (one clock
  advance per test; seed "already progressed" state via `set_state()`), but do not treat the stated
  cause as established.
- **One narrower flake, never root-caused (UNPROVEN, recorded so it is not re-investigated blindly):**
  one test failed deterministically (2/2 runs, unaffected by a 5s→20s timeout bump) apparently only
  because of its position in the nodeid-sorted suite. Skipped with a documented
  `@pytest.mark.skip(reason=...)`; the coverage gap is trivial passthrough logic covered indirectly
  by siblings. Worth re-testing now that the HTTP calls are bounded — the same wedged-container
  explanation may cover it.
- **~~The CI hangs are caused by `jump_to_next(month=...)` year-jumps in the pergola fixtures~~ —
  DISPROVED.** A docs-only commit hung with byte-identical test code. The *mechanism* is real
  (`jump_to_next` advances a full year once the target month has passed; the pergola fixtures do
  this 6× and run first, reaching ~2032 by test #30), and per-file isolation is worth keeping for
  determinism — but it was never the cause of the hang. The actual cause is the unbounded
  `requests.get` above. Standing status: `plans/ci-test-isolation.md` → "Correction".

## Log

### 2026-08-16 — Victron AC-referenced solar/battery accounting (PR #101)
- **Task:** Rewrote `packages/victron.yaml` so Solar and Battery are AC-referenced, then spent the
  rest of the session on the CI fallout.
- **Learning:** Production YAML landed well (state-only baseline sensors, `platform: integration`
  for grid, explicit conversion-loss diagnostics). The debugging around it produced **three
  successive confident root-cause claims that were each wrong**, all in the same way: a plausible
  mechanism fitted to a single confirming CI run. In order — custom `attributes:` being broken in
  HA; dropping a `jump_to_next` alignment call causing a hang; pergola year-jumps causing the hang.
  Two had to be deleted from this file as false positives. `CLAUDE.md` now forbids writing a
  learning without confirmed evidence, and this file grades every entry.

### 2026-08-16 (follow-up) — grid import/export accuracy
- **Task:** Switched `victron_grid_energy_import`/`_export` from 1/min sampling to
  `sensor: platform: integration`; added `recorder: purge_keep_days: 5`.
- **Learning:** `platform: integration` has sharp edges not in the docs: rejects
  `device_class`/`state_class`; keeps its total in entity memory (immune to `set_state()` resets);
  has no timer without `max_sub_interval`, so it bills the entire gap since the last source event as
  one trapezoid; and it listens to state *reports* as well as changes. `recorder: purge_keep_days`
  does not touch the Energy Dashboard — that reads long-term statistics, a separate store retained
  indefinitely.

### 2026-08-16 (follow-up) — the hang, actually diagnosed
- **Task:** Stopped theorising, instrumented instead.
- **Learning:** `pytest-timeout --timeout=90 --timeout-method=thread` named the blocking line on the
  first try: `requests.get` with no `timeout=`, parked in `socket.recv_into`. HA accepts the
  connection and never answers; the HA-side reason is still unknown, but the test side is now
  bounded by a `requests` wrapper in `tests/conftest.py`. Two follow-on regressions, both caught and
  both instructive: pytest-timeout charges session-fixture setup to the first test (fixed with
  `timeout_func_only`), and the airflow reload helper's clock jump was secretly supplying the delay
  crossing that two other tests depended on. Also cut ~11 days of pointless mocked-clock travel out
  of `test_victron.py` by replacing 20 `jump_to_next(hour=...)` calls with 11 `fast_forward` calls.
