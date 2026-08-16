# CI: per-file test isolation pattern (fresh Docker instance)

**Status:** IMPLEMENTED, but **did NOT fix the hang** — see "Correction" at the bottom. The
isolation itself works and is worth keeping; the hang has a different cause.
**Target files:** `.github/workflows/ha_check.yaml`, `tests/conftest.py` (comment only)
**Branch:** `fix-victron-ac-dc-mixup` (PR #101)

---

## Context

While debugging PR #101's CI, found that `tests/test_pergola.py` uses two fixtures
(`midday_sun`, `low_elevation_sun` in `tests/conftest.py`) that call
`time_machine.jump_to_next(month="Jun", ...)`. Per that method's own semantics, once the mocked
clock is already past June 21 in the current mocked year (true after the first such call), every
subsequent call jumps a **full year** forward. 6 pergola tests use these fixtures (5×
`midday_sun`, 1× `low_elevation_sun`), and `conftest.py`'s `pytest_collection_modifyitems` forces
all pergola tests to run **first** in the whole 158-test session — so those year-jumps front-load
almost all of the session's eventual clock drift before any other test file even starts. A
`get_state()` diagnostic dump earlier in this debugging session already showed the mocked clock at
**2032** by roughly test #30 of 158.

`ha_integration_test_harness`'s `docker`/`home_assistant`/`time_machine` fixtures are all
`scope="session"`, hardwired in the harness's own bundled `conftest.py` (confirmed by reading the
harness source at the pinned release commit) — not overridable from this repo. `time_machine` is
also forward-only and never reset. So the mocked clock keeps drifting further from real "now" for
the rest of the 158-test session, and by the time the victron tests run (near the end,
alphabetically late), the clock is plausibly a decade or more past boot.

User observed CI runs progressively slowing down through the later part of the suite, eventually
hanging outright (20+ minutes, reproduced deterministically across reruns) at varying points late
in `test_victron.py`. Working theory: HA's own scheduling/recorder machinery gets more expensive
the further the mocked "now" drifts from real wall-clock time, eventually tipping into an outright
hang — compounded by `ha_integration_test_harness`'s `get_state()`/`assert_entity_state()` calls
having no explicit HTTP timeout (confirmed by reading the harness source), so an unresponsive
container manifests as an indefinite hang rather than a clean failure.

## Decision

Give `test_pergola.py` its own fresh Docker container / mocked clock, isolated from the rest of
the suite, rather than trying to fix the underlying year-jump behavior (which is legitimate test
design for pergola's own sun-position scenarios). Since the harness's session-scoped fixtures are
tied to the `pytest` **process**, not something a fixture-scope override can subdivide, isolation
means running `test_pergola.py` as its own separate `pytest` invocation.

Chosen approach (of two): **separate sequential `pytest` steps within the existing single CI job**,
not separate parallel GitHub Actions `jobs:`. Reuses the already-pulled/cached HA Docker image,
smallest diff to the existing workflow, and establishes a simple, copy-pasteable pattern for any
future test file/group that turns out to need its own instance — add one more
`pytest tests/<file>.py -v` step, add `--ignore=tests/<file>.py` to the shared-instance step.
Parallel jobs would run faster wall-clock but duplicate every setup step (checkout, Python, Docker
pull/cache, config check) per job and need job-level result aggregation for the existing
PR-comment-on-failure logic — more moving parts for a marginal speed win here.

## Implementation

`.github/workflows/ha_check.yaml`, step 8 ("Run pytest") splits into two:
1. **`Run pytest — pergola tests (isolated HA instance)`**: `pytest tests/test_pergola.py -v`,
   own output file (`/tmp/pytest_pergola_output.txt`), own step `id` for outcome tracking.
2. **`Run pytest — remaining tests (shared HA instance)`**: `pytest tests/ --ignore=tests/test_pergola.py -v`,
   own output file (`/tmp/pytest_rest_output.txt`), own step `id`.

Both use `continue-on-error: true` (same as the original single step) so the job summary and PR
comment steps still run on failure.

Downstream steps updated to account for two pytest runs instead of one:
- **Job Summary step**: concatenates both output files under separate headings.
- **PR comment step**: fires if *either* step's outcome is `failure`; combines both outputs
  (still truncated to the last 60000 chars) into one comment.
- **Fail if any check failed**: fails if *either* step's outcome is `failure`.

`tests/conftest.py`'s `pytest_collection_modifyitems` (the "run pergola first" sort hook) is left
functionally as-is — harmless to keep, and for the pergola-only invocation it still sorts
correctly (everything in that collection matches `test_pergola`, tiebroken alphabetically same as
before). Its original stated rationale (preventing airflow-automation event-loop bleed into
pergola sensor assertions) is now handled structurally by process isolation rather than by sort
order, so its comment is updated to note that, without changing the logic.

## Status
- [x] Investigated harness fixture scope (confirmed `scope="session"`, no override available)
- [x] Confirmed only `test_pergola.py` uses the year-jumping fixtures (repo-wide grep)
- [x] Got user's choice on sequential-steps-in-one-job vs. parallel-jobs
- [x] Split `.github/workflows/ha_check.yaml` step 8 into pergola + rest steps
- [x] Update Job Summary step for two output files
- [x] Update PR-comment-on-failure step for two step outcomes / combined output
- [x] Update "Fail if any check failed" step for two step outcomes
- [x] Update `tests/conftest.py`'s sort-hook comment (logic unchanged)
- [x] Validate workflow YAML syntax (`yaml.safe_load`) and `conftest.py` syntax (`ast.parse`)
- [x] Push and confirm CI green, with the clock-drift/hang problem resolved

---

## Correction — the pergola year-jumps were NOT the root cause

Disproved by run **31954488094** (commit `6bd86cc`, a **docs-only** commit: `.claude/learnings.md`
+ `plans/ci-test-isolation.md`, zero changes to tests, config or workflow). It hung anyway.

Evidence, from the GH Actions job logs of the two runs of identical test code:

| Run | Commit | Pergola step | Rest step | Outcome |
|---|---|---|---|---|
| 31954182745 | `8d66843` (isolation) | 1m44s ✅ | **1m25s** ✅ | green, 4m42s |
| 31954488094 | `6bd86cc` (docs only) | 1m42s ✅ | **hung ≥ 8m**, cancelled | — |

So:
- The pergola isolation step itself works (both runs: pergola completes in its own fresh container
  in <2 min, and its clock drift can no longer reach the rest of the suite).
- The hang survives that isolation, with byte-identical test code. It is **nondeterministic**.

### Where it hangs — precisely

Both hung runs stop at the same place. The last line printed in run 31954488094 was:

```
15:07:07.5620958Z tests/test_victron.py::test_power_domain_identity_holds_with_eta PASSED  [ 95%]
```

then nothing for 7 minutes until cancellation. pytest prints a test's result line only on
completion, so the hang is in the **next** test by nodeid order, which is
`test_solar_yield_ac_total_applies_delta_once_baselined` (96 % in the green run, where it took
1.59 s). This matches the earlier hang the user reported by name.

### When it started

`gh run list` for this branch — every run before commit `074c22c` finished in 2–9 minutes, pass or
fail, and none ever hung:

| Run | Commit | Duration | Result |
|---|---|---|---|
| 31950030587 | `test(victron): skip a harness-ordering flake` | 4m12s | success |
| 31950633727 | `feat(victron): switch grid import/export to continuous integration` | 1m40s | failure (config check — tests never ran) |
| 31950779359 | `fix(victron): remove invalid device_class/state_class` | 4m26s | failure (assertions — **full suite ran, no hang**) |
| 31951136882 | `074c22c fix(victron): force a real state change in grid energy tests` | **30m** | cancelled — **first hang** |
| 31952710113 | `af149ac fix(victron): restore clock alignment` | **15m** | cancelled — hang |
| 31954182745 | `8d66843 ci: pergola isolation` | 4m42s | success |
| 31954488094 | `6bd86cc docs only` | **≥8m** | cancelled — hang |

Run 31950779359 rules out `sensor: platform: integration` and `recorder: purge_keep_days: 5` (both
already present there) as sufficient causes on their own: the full suite ran to completion under
them. The hang appears with `074c22c`, which introduced `fast_forward()` into the grid tests.

### What is actually unbounded (read from the pinned harness source, v0.11.0 `ee8abdd`)

Three call sites can block forever; only one is bounded:

| Call | Bound |
|---|---|
| `assert_entity_state()` | **bounded** — `while True` with `time.sleep(1)` and an explicit `elapsed >= timeout` break |
| `get_state()` / `set_state()` | **unbounded** — `requests.get/post(...)` with no `timeout=` kwarg |
| `time_machine.jump_to_next()` / `fast_forward()` | **unbounded** — resolves to `DockerManager.write_container_file()`, which is `subprocess.run(["docker","exec",...])` with no `timeout=` |

Note `jump_to_next()` does no waiting or polling of its own — it only writes `/shared_data/.faketime`
into the container. So a hang *inside* a jump is a hung `docker exec`, not clock arithmetic.

### Also disproved: "the clock drifts a decade"

Only `test_pergola.py` had year-scale jumps. In the remaining suite the arithmetic is
`jump_to_next(hour=10, minute=0)` → target already passed → **+1 day**, and 11 victron tests chain
two such jumps. Total drift across the rest-suite is on the order of **two weeks**, not years —
too small to be a plausible cause on its own.

Chaining is also still present throughout, contrary to what `.claude/learnings.md` recorded:
`test_grid_import_energy_accumulates` has 3 jumps + 2 fast-forwards; 10 other victron tests have 2
jumps each.

### Instrumentation (implemented)

Stop guessing and make the hang self-report. Done:

- [x] Added `pytest-timeout` to `.github/workflows/requirements.txt`, with a comment explaining it
  exists to convert CI hangs into failures with thread dumps.
- [x] Both pytest steps in `.github/workflows/ha_check.yaml`
  (`run_tests_pergola` and `run_tests_rest`) now run with `--timeout=90 --timeout-method=thread`.
  On expiry pytest dumps the stack of **every** thread and fails the test, which names the exact
  blocking line — `requests` socket read vs. `subprocess.run` on `docker exec` vs. something in HA.
  The 90s bound was chosen as ~4x headroom over the slowest legitimately-passing test observed in
  the last green run (21.8s; typical tests are 0.2–1.7s), so it won't false-positive on real work
  while still surfacing a hang within ~1.5 min.
- [x] Added `timeout-minutes: 20` to the `ha-ci` job (job level, sibling of `runs-on:`) so a hang can
  never burn the default 6-hour budget again.

This is instrumentation, not a fix: it converts an unfalsifiable hang into evidence. The next hang
should produce a thread dump naming the exact blocking call — at that point the real fix follows
from what the dump shows (e.g. wrapping the harness's `requests.get/post` or
`subprocess.run(["docker","exec",...])` calls with an explicit timeout, or patching/forking the
harness).
