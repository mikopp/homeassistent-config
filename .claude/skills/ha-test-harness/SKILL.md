---
name: ha-test-harness
description: "Writing, running (a single test or one package's tests), debugging or reviewing tests in tests/ha (in-process HA, pytest-homeassistant, real mosquitto, Clock) or tests/e2e (real HA container), their CI workflows, flaky or hanging tests, frozen-clock moves, log_guard, mutation checks, pytest-homeassistant/Python/mosquitto pins. Use before touching tests/**, tests.yaml, e2e.yaml or ci-local.sh."
---

# Tests: in-process layer (`tests/ha`) and real-HA layer (`tests/e2e`)

Grades as in `record-learning`: everything below is CONFIRMED (source read at the pinned version,
stack trace, or deterministic repro) unless marked. Package-specific test facts live in the package
notes (`doc/<pkg>/notes.md`), not here. Pins: HA = `FROM` line of `.github/ha-versions/ha/Dockerfile`.

## Where does a new test go?
1. Behaviour of the config given inputs (templates, automations, helpers, MQTT ingest, clock)? →
   `tests/ha/test_<package>[_<topic>].py` (`<package>` = a `packages/*.yaml` name; the collection guard fails
   otherwise; harness modules are listed in `tests/ha/conftest.py`). This is the default. A test that loads/drives
   another package's real entities gets `@pytest.mark.package("<other>")` so it also runs under that package
   (not for a mere seed of an entity id).
2. Only a real container can show it? → `tests/e2e/`, marked `@pytest.mark.needs_real_ha("<reason>")`
   with a reason from `REAL_HA_REASONS` in `tests/e2e/conftest.py` (`full-boot`, `check-config`,
   `restart-persistence`, `runtime-logs`); collection fails without it. Module docstring starts
   "Needs a real HA because: …". A new reason is a deliberate decision, not a way around the rule.
3. Never repeat an in-process scenario in e2e.
4. Package-specific facts a test establishes → the package note's "Tests" section.

## Run
- Development: targeted, `.github/scripts/ci-local.sh --package <pkg>` (that package's tests incl. cross-package
  ones, repeatable) or `.github/scripts/ci-local.sh -- tests/ha/test_x.py::test_y -k … -x` (anything after `--` goes to
  pytest); `--yaml` = YAML checks only. `-n` default: auto for `--package`, 0 for explicit ids (workers only add start-up; a whole package is ~3x faster with `-n auto`); a passed `-n` wins.
  A targeted run is never verification (YAML checks skipped; summary says so).
- End of task / before pushing: `.github/scripts/ci-local.sh` (no arguments; skips `tests/ha` when no path in
  `.github/test-paths` changed, `--all` forces; `--e2e` adds Docker, full only: e2e has
  no per-package split). Needs python3.14 (`.github/ha-versions/ha-python.txt`) and mosquitto at the version of
  `.github/ha-versions/mosquitto/Dockerfile`. The script does the venv/custom-component/mosquitto setup (`.venv-test`:
  `requirements_test.txt`, which pins pytest-homeassistant and with it HA); do not call raw pytest for `tests/ha`. Each layer has
  its own ini; there is no root pytest config. Usage reference: header of the script.
- `tests/e2e` alone (no script equivalent): `pytest -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e -p no:pytest_homeassistant --timeout=300 --timeout-method=thread`
  (`tests/e2e/requirements.txt`, Docker, mosquitto on the host; `E2E_IMAGE` overrides the image;
  failure logs in `tests/e2e/.artifacts/`).
- CI: `tests.yaml` and `e2e.yaml`; both skip their steps (and pass) on a PR touching none of
  `.github/test-paths`: add a path there when a test starts reading it.
  `upload-artifact` skips dot-directories: `tests/e2e/.artifacts/` needs `include-hidden-files: true`.

## Detail (read when the task needs it)
- `references/fixtures.md`: before writing, changing or debugging a `tests/ha` test (fresh HA per test, Clock and
  frozen-clock moves, mosquitto, recorder, log_guard, teardown, platform quirks) or chasing a flaky/hanging one.
- `references/e2e.md`: before writing or debugging a `tests/e2e` test or `test_zz_log_hygiene.py`.
- `references/pins.md`: before bumping HA, pytest-homeassistant, Python or mosquitto, or when `test_versions.py` fails.

## Quality rules
- **Mutation check every new or changed test**: break the YAML under test in place, see the named case fail,
  restore with `git checkout` (never commit); a test that reads its own seed passes anyway. Also run a table with its
  case order reversed (temporary module).
- **Test the real entity, never a copy of its formula.** A test that renders a Jinja copy of a YAML formula tests the
  copy (the Docker-era copies had drifted from the config). Expected values come from an independent Python port or
  literal anchors, not from the same template.
- **Stability: 20× on changed tests** (`.github/scripts/ci-local.sh -- tests/ha/test_x.py --count=20 -n 4`), the full `ci-local.sh` once at the end.
- **No retry/rerun plugins.** A flaky test is a bug: find the cause (both flakes found so far were test or fixture
  bugs), or open a GitHub issue; never "passed again" as proof.
- A confirmed config bug is pinned by a `strict` xfail test (it fails the run when the bug is fixed), with its issue number.
- When a CI-only test fails, establish whether the test environment is at fault before redesigning production YAML.
