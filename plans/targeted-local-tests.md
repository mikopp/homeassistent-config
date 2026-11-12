# Plan: targeted local test runs (one test, one package) in `ci-local.sh`

## Status
- [ ] Step 1 `ci-local.sh` selection flags, awaiting approval
- [ ] Step 2 package markers in `tests/ha` + `--package` filter, awaiting approval
- [ ] Step 3 skip unchanged dependency installs, awaiting approval
- [ ] Step 4 agent guidance (CLAUDE.md, ha-test-harness skill, README)
- [ ] Step 5 Close

## Overview
`.github/scripts/ci-local.sh` always runs every YAML check and the whole `tests/ha` suite (~60 s of
tests plus pip/venv/mosquitto setup on each call). While developing a package an agent only needs
the tests of that package, or a single test. Today the only way is to copy the raw pytest command
from the `ha-test-harness` skill, which skips the setup (venv, custom component, pinned mosquitto
on PATH) and so fails or behaves differently in a fresh session.

Goal: one entry point that does the same setup and runs a chosen subset; the full run stays the
default and remains the required final check before pushing.

## Design
Same script, new options (no second script: the venv/mosquitto setup must not be duplicated):

| Call | Runs |
|---|---|
| `ci-local.sh` | everything, unchanged (YAML checks + all of `tests/ha`) |
| `ci-local.sh --e2e` | as today, plus `tests/e2e` |
| `ci-local.sh --package pergola` | only `tests/ha` tests of package `pergola` (repeatable) |
| `ci-local.sh -- tests/ha/test_pergola.py::test_deadbands` | only that pytest selection |
| `ci-local.sh --package victron -- -k battery` | combination; anything after `--` goes to pytest verbatim (`-k`, `--count=20`, `-x`, `-n 0` …) |
| `ci-local.sh --yaml` | only the YAML / knowledge-layout checks, no tests |

Rules:
- Any selection (`--package`, `--`, `--yaml`) is a **targeted run**: the YAML checks are skipped
  (unless `--yaml`), and the summary ends with `TARGETED RUN – not a full verification; run
  ci-local.sh without arguments before pushing` instead of "All local checks passed." Exit code is
  still 0/1 so loops work.
- `-n auto` stays only for the full run; a targeted run uses `-n auto` too unless the pytest args
  contain `-n` (a single test with xdist only adds worker start-up; decide at implementation by
  timing, note the result here).
- `--e2e` combined with a selection: rejected with a message (e2e has no per-package split; YAGNI).
- Unknown package name → fail fast listing the valid names (from `packages/*.yaml`).

### Package → tests mapping (Step 2)
Test file names do not match package names (`test_airflow.py` → `airflow_cooling`,
`test_victron.py`/`test_shelly_pool_pump.py`/`test_wallbox.py` → `energy`/`victron`?). So the
mapping is declared, not derived:
- Each `tests/ha/test_*.py` gets `pytestmark = pytest.mark.package("<name>", …)` (several names
  allowed). Harness files (`test_versions`, `test_broker_isolation`, `test_spike`) get
  `package("harness")`.
- `tests/ha/conftest.py`: `pytest_addoption("--package")` (repeatable) and
  `pytest_collection_modifyitems` deselecting items without a matching marker.
- Guard: collection fails if a test module has no `package` marker or names a package that has no
  `packages/<name>.yaml` (except `harness`), so the mapping cannot rot.
- `test_every_template_renders` covers all packages in one boot: with `--package` it renders only
  the templates whose extracted `file` is `packages/<name>.yaml` (the extractor already records
  the file). Without `--package` it renders all, as today.
- Open question for the owner: should `--package X` also run `harness` + `test_spike`
  (package-load / no `_2` ids, ~seconds)? Proposal: yes for `test_spike` (a package edit can
  break loading of all packages), no for `test_versions`/`test_broker_isolation`.

### Faster setup (Step 3)
Every call reinstalls `.github/workflows/requirements.txt`, yamllint and `requirements_test.txt`
(pip resolves even when nothing changed). Store a hash of each requirements file in the venv
(`.venv-test/.req-hash`) and skip the install when it matches. Measure before/after; drop the step
if the gain is < a few seconds.

## Steps
1. **[TODO] `ci-local.sh` flags.** Argument parsing (`--e2e`, `--yaml`, `--package NAME`, `--`),
   targeted-run summary, pytest args pass-through. Factor the `tests/ha` setup into a function so
   both modes share it. Header comment updated (usage block). Depends on: nothing. Verify: full run
   unchanged (same test count), `-- tests/ha/test_pergola.py::test_deadbands` runs 1 test, a
   failing selection exits 1.
2. **[TODO] Package markers + `--package`.** Markers in all 11 test modules, the option and filter
   in `conftest.py`, marker registered in `tests/ha/pytest.ini`, the guard, the template filter.
   Depends on: step 1 (the script passes `--package` through to pytest). Verify: per-package counts
   add up to the full count (harness included); mutation: remove a marker → collection fails; break
   a pergola template → `--package pergola` fails, `--package victron` passes. Full suite once.
   The mapping (which test file covers which package) is confirmed with the owner before coding.
3. **[TODO] Skip unchanged installs.** Hash stamps as above. Verify: second call skips pip, editing
   `requirements_test.txt` triggers reinstall; timing recorded here.
4. **[TODO] Agent guidance.** State the workflow where agents read it:
   - `CLAUDE.md` "Local CI checks": during development run the targeted form
     (`--package <pkg>` or `-- <test id>`); the full `ci-local.sh` (no arguments) once at the end,
     before pushing, is mandatory.
   - `ha-test-harness` skill "Run" section: replace the raw pytest commands with the script forms;
     the 20× stability rule becomes `ci-local.sh -- tests/ha/test_x.py --count=20 -n 4`.
   - `README.md` line on local checks: one sentence on the targeted options.
5. [TODO] Close: per `doc/KNOWLEDGE.md#K-6`.

## Knowledge homes updated (`doc/KNOWLEDGE.md#K-1`)
- `CLAUDE.md` (Local CI checks), `.claude/skills/ha-test-harness/SKILL.md` (Run, Quality rules),
  `README.md`; the script header comment in `ci-local.sh`.
- No package note changes; no learnings expected (timing results stay in this plan until Close).

## Not in scope
- CI workflows (`tests.yaml`, `e2e.yaml`) keep running the full suites.
- Selecting tests automatically from `git diff` (could follow later on top of the markers).
