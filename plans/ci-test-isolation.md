# CI: per-file test isolation pattern (fresh Docker instance)

**Status:** DONE — CI green (4m38s, no hang, all 4 checks pass)
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
