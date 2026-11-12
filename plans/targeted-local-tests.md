# Plan: targeted local test runs (one test, one package) in `ci-local.sh`

## Status
- [x] Plan and owner decisions (Step 3 wanted, package-load test runs with every package, test
      files renamed after their package, cross-package tests run under each package they cover)
- [x] Step 1 `ci-local.sh` selection flags [DONE]
- [x] Step 2 rename test files [DONE]
- [x] Step 3 package selection (`--package`) [DONE]
- [x] Step 4 skip unchanged dependency installs [DONE]
- [x] Step 5 agent guidance (CLAUDE.md, ha-test-harness skill, README) [DONE]
- [x] Efficiency check (wall time of the whole `ci-local.sh` call, 4 cores, deps unchanged):
      full run 57 s; one test 6-11 s (`-- tests/ha/test_energy_wallbox.py::test_wallbox_wrappers`
      5.8 s, `-- tests/ha/test_pergola.py::test_deadbands` 10.7 s); `--package` energy 8.5 s,
      heating_pv_boost 16 s, victron 21 s, airflow_cooling 21 s, pergola 26 s; `--yaml` 2 s.
      A fresh agent given only "confirm the wallbox tests are green while developing" chose
      `--package energy` from the guidance by itself (9 s, one command).
- [x] Step 6 recorder records only what the config's history readers need [DONE]
- [ ] Step 7 behaviour test: history read back from the recorder, in progress
- [ ] Step 8 Close (before merge, so the plan file is not part of the merge)

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
| `ci-local.sh --package pergola` | the `tests/ha` tests of package `pergola` (repeatable) |
| `ci-local.sh -- tests/ha/test_pergola.py::test_deadbands` | only that pytest selection |
| `ci-local.sh --package victron -- -k battery` | combination; anything after `--` goes to pytest verbatim (`-k`, `--count=20`, `-x`, `-n 0` …) |
| `ci-local.sh --yaml` | only the YAML / knowledge-layout checks, no tests |

Rules:
- Any selection (`--package`, `--`, `--yaml`) is a **targeted run**: the YAML checks are skipped
  (unless `--yaml`), and the summary ends with `TARGETED RUN – not a full verification; run
  ci-local.sh without arguments before pushing` instead of "All local checks passed." Exit code is
  still 0/1 so loops work.
- xdist: `-n auto` for the full run, unless the pytest args contain `-n`. Targeted runs, decided by
  timing: explicit test ids only (no `--package`) → `-n 0` (Step 1, one file: 7.3 s vs 10.0 s total,
  pytest 3.9 s vs 6.1 s; workers only add start-up). `--package` → `-n auto` (Step 3, 4 cores,
  total wall time of `ci-local.sh`): `pergola` 79 s (`-n 0`) vs 25 s (`-n auto`), `victron` 63 s vs 22 s.
- `--e2e` combined with a selection: rejected with a message (e2e has no per-package split).
- Unknown package name → fail fast listing the valid names (from `packages/*.yaml`).

### Test files named after their package (Step 2)
Convention: `tests/ha/test_<package>[_<topic>].py`; files that test no single package (the
harness) have fixed names and a list in `conftest.py`.

| Today | New | Package |
|---|---|---|
| `test_airflow.py` | `test_airflow_cooling.py` | `airflow_cooling` |
| `test_shelly_pool_pump.py` | `test_energy_pool_pump.py` | `energy` |
| `test_wallbox.py` | `test_energy_wallbox.py` | `energy` |
| `test_spike.py` | `test_packages_load.py` | harness, runs with every `--package` |
| `test_heating_cooling_indicator.py`, `test_heating_pv_boost.py`, `test_pergola.py`, `test_victron.py` | unchanged | as named |
| `test_templates.py`, `test_versions.py`, `test_broker_isolation.py` | unchanged | harness |

Rename with `git mv` (history kept). References to update: `doc/energy/notes.md`,
`doc/airflow/notes.md`, `doc/airflow/design.md`, `README.md`, `plans/energy-live-entity-ids.md`,
comments in `tests/ha/test_pergola.py` and `test_wallbox.py`. `doc/*/background.md` is history and
stays as it is (K-2).

### Package selection (Step 3)
- **Primary package from the file name**: the longest `packages/*.yaml` name that the module name
  starts with (`test_heating_pv_boost` → `heating_pv_boost`, not a shorter match).
- **Cross-package tests**: `@pytest.mark.package("victron")` (on a test, or on a `pytest.param`) adds
  packages; the test then runs under `--package` of its own file's package AND each marked one.
  Rule: mark a test when a change to package X's YAML could make it fail (it loads/drives X's real
  entities), not when it only seeds a state with an X entity id. Final marks (each has a comment):
  - `test_pergola.py`: `test_pv_power_wrapper` → `victron` (wraps the real Victron MQTT sensors);
    `test_sun_rules` → `victron` (PV-alone shining cases) and `heating_cooling_indicator`;
    `test_cover_formulas`, `test_deadbands`, `test_season_sync` and the `master_switch` parameter of
    `test_protected_states` → `heating_cooling_indicator` (season through the real indicator).
  - `test_heating_pv_boost.py`: `test_surplus_table` → `victron` (real Victron templates);
    `test_slab_mode_wanted_delays` → `victron` (surplus, SOC) and `heating_cooling_indicator`;
    `test_cooling_interlock`, `test_target_temp` → `heating_cooling_indicator`.
  - `test_airflow_cooling.py`: every test that sets the season (`test_decision_table`,
    `test_controller`, the three `test_drying_boost*`, `test_indicator`, `test_drying_needed`,
    `test_hvac_action`, `test_reload_recovery`) → `heating_cooling_indicator`. Not marked:
    `test_bypass_estimation`, `test_dew_point_thresholds`, `test_drying_boost_config_edge_only`.
  - No marks: energy (go-e seeded, pool pump self-contained), `test_victron.py`,
    `test_heating_cooling_indicator.py`. `test_reload_recovery` only tolerates a Victron log line
    (`allow_log`, #155), it does not drive Victron: not marked `victron`.
- **Harness**: `test_packages_load.py` runs with every `--package` (a package edit can break
  loading of all packages). `test_templates.py` runs with every `--package` but renders only the
  templates whose extracted `file` is a selected `packages/<name>.yaml` (the extractor already
  records the file); without `--package`, all templates as today. `test_versions.py` and
  `test_broker_isolation.py` run only in the full run.
- **Implementation**: `tests/ha/conftest.py` gets `pytest_addoption("--package", action="append")`
  and `pytest_collection_modifyitems` that deselects items outside the selection (harness lists
  `HARNESS_EVERY_PACKAGE`, `HARNESS_FULL_RUN_ONLY` as constants); the marker is registered in
  `tests/ha/pytest.ini`. `test_templates.py` reads the selection from
  `request.config.getoption("package")`; every package has templates, an empty selection fails.
- **Guard** (always active, also in full runs): a test module whose name matches no package and is
  not in the harness lists; a `package` marker naming no `packages/<name>.yaml`. It is a static
  source scan in `pytest_configure` (so it fails once with a clear message, also under xdist, where
  an error raised during collection in a worker is an INTERNALERROR); a runtime check in the
  collection hook backs it up for marker names that are not string literals.

### Faster setup (Step 4)
Every call reinstalled `.github/workflows/requirements.txt`, yamllint and `requirements_test.txt`
(pip resolves even when nothing changed). `install_once` in `ci-local.sh` keeps a stamp
`<venv>/.ci-local-<name>.sha256` = sha256 of the requirement file contents + the venv's python
version + the install command; the install is skipped on a match, the stamp is written only after a
successful install. A new venv has no stamp, so it installs. The `.venv` full-manifest install that
falls back to pyyaml+requests writes no stamp, so the next run retries the full manifest (as before).
Applied to `.venv` (manifest, yamllint), `.venv-test` (pip or uv branch) and `.venv-e2e`.

Timing, `ci-local.sh -- tests/ha/test_heating_cooling_indicator.py` (wall time):
before 7.3 s / 7.4 s; after (first run, writes stamps) 7.2 s, then 5.9 s / 5.8 s. The gain is about
1.5 s per call (below the 3 s mark), kept because the helper is small. Verified: appending
`# tmp` to `requirements_test.txt` reinstalls `.venv-test` only (6.7 s); restoring it reinstalls once
more (6.7 s), then it skips (6.1 s). The `.venv-e2e` branch is only syntax-checked (`--e2e` not run).

### Recorder filter (Step 6)
Measured (py-spy + per-thread CPU, single test `test_wallbox_wrappers`, warm): a single test is
~0.4 s script, ~1.7 s Python + HA imports, ~1 s first-boot integration imports (both once per
process), ~2.2 s HA boot per test, ~0.9 s body + teardown. The boot is all CPU; ~1.1 s of it is the
Recorder thread: PHACC's `recorder_mock` commits after every event (`commit_interval: 0`), so every
boot-time state and event is one SQLite commit, competing with the loop for the GIL (92 % of its
samples in `_process_one_event` → commit). Recording nothing: steady boot 2.2 s → 0.9 s.
Prototype (reverted): override PHACC's `recorder_config` fixture with `include.entities` = the
`entity_id` sources of every `filter` / `statistics` / `history_stats` platform in `packages/*.yaml`
(15 entities, derived at run time) plus `exclude.event_types` for events no test reads
(call_service, automation_triggered, registry updates, ...): full `tests/ha` 51 s → 35 s
(60 passed, 1 xfailed), `--package pergola` 25 → 20 s, single test 6.5 → 5.5 s.
Keeping it in sync with the config (owner requirement):
- The include list is derived from the YAML at run time, never hand-written.
- A guard test lists every `platform:` used in the config (packages, configuration.yaml) and fails
  for a platform not classified in conftest as "reads recorder history" (source key named) or
  "does not": a new platform forces a decision instead of silently missing history.
- A guard that the derived list is non-empty and contains each history platform's source.
- Mutation: drop the history_stats source from the include → `test_cycling_history_stats` fails;
  drop the statistics/filter source → the test reading it fails (or, if none does, say so).
- Event exclusion: only event types proven unread by any test; a test that needs one (e.g. a
  logbook test) removes it; documented next to the list.

Built (Step 6): `recorder_config` override, `HISTORY_PLATFORMS` / `NO_HISTORY_PLATFORMS` /
`RECORDER_IMPORTING_DOMAINS` / `RECORDER_EXCLUDED_EVENTS` and the derivation (`config_entity_platforms`,
`history_sources`; scans the top-level `<domain>: [- platform: x]` lists of `configuration.yaml` and
`packages/*.yaml`; trigger `platform:` is nested and ignored) in `tests/ha/conftest.py`; guards in the
new harness module `tests/ha/test_recorder_filter.py` (in `HARNESS_EVERY_PACKAGE`, static except one
test, 4 s): (1) every platform classified in exactly one dict, no stale entry; (2) classification vs the
installed component source (history platforms import the recorder, the others and every other top-level
domain do not, `sensor`/`recorder` listed); (3) include list non-empty, holds each history entry's
source, literal ids; (4) no test module reads the recorder database (`get_instance`, `history`,
`logbook`, ... ; the exclusion of event types is safe because nothing can read them back; only
`async_wait_recording_done` is used); (5) with `ha`: every source that has a state is in the DB, no
other entity is. Entity filter semantics (source read, `helpers/entityfilter.py` case 6,
`recorder/core.py` `_event_listener`): include entities only = exact membership; events without a
top-level `entity_id` (`call_service`, registry events, ...) bypass it, hence the event-type list.
Mutations (restored): dropping the history_stats / statistics / filter sources from the derived list
-> `test_history_sources_derived` fails each time; filter not applied -> test 5 fails; a
`- platform: trend` in victron.yaml -> test 1 fails; a test module importing `get_instance` -> test 4 fails.
Coverage gap (measured): NO existing test depends on recorded history. With
`include.entities = [sensor.nothing]` the whole suite (53 passed, 1 xfailed) stays green, so
dropping the history_stats source does NOT fail `test_cycling_history_stats`: history_stats follows
live state events and reads the DB only on its first update. The list is therefore guarded by tests
1-3 and 5, not by behaviour tests; a behaviour test needs a reload/restart that forces a DB read.
Stability: whole `tests/ha` via `ci-local.sh` 3x green (65 passed, 1 xfailed each); 20x:
heating_pv_boost 180 passed, heating_cooling_indicator 20, airflow_cooling 280 passed + 20 xfailed,
test_recorder_filter 100.
Timings (wall, `ci-local.sh`, 4 cores, before -> after): full 66.6 s (noisy: 57 s in the earlier
check) -> 45.5-46.5 s (3 runs; pytest 40 s); `--package pergola` 31.4 -> 22.5 s; single test
(`test_wallbox_wrappers`) 7.0 -> 5.5 s. (The prototype measured 51 -> 35 s on a quieter machine.)

## Steps
1. **[DONE] `ci-local.sh` flags.** Argument parsing (`--e2e`, `--yaml`, `--package NAME`, `--`),
   targeted-run summary, pytest args pass-through. The `tests/ha` setup moves into one function
   used by both modes. Header comment (usage block) updated in the K-5 style. Depends on: nothing.
   Verify: full run unchanged (same test count); `-- tests/ha/test_pergola.py::test_deadbands`
   runs 1 test; a failing selection exits 1; `--package nosuch` fails with the list.
2. **[DONE] Rename test files.** `git mv` per the table, references updated. Depends on: nothing
   (independent of step 1). Verify: full `tests/ha` same count; grep finds no old name outside
   `background.md`.
3. **[DONE] Package selection.** Option, filter, marker, guard, template filter, cross-package
   markers. Depends on: steps 1 and 2. Verify:
   - every test runs under at least one selection; union of all `--package` runs + harness = full count;
   - `--package victron` includes the marked pergola/heating tests, `--package pergola` too;
   - mutation: a module named after no package → collection fails; a marker with a bad name → fails;
     a broken pergola template → `--package pergola` fails, `--package victron` passes
     (restored with `git checkout`);
   - full suite once.
   Verified: full run 60 passed, 1 xfailed; per package (selected tests incl. 1 `test_packages_load`
   and 1 `test_templates`): airflow_cooling 17, energy 4, heating_cooling_indicator 23,
   heating_pv_boost 11, pergola 16, victron 17; the union plus `test_versions` (5) and
   `test_broker_isolation` (2) is the full 61. Mutations: module `test_nosuchpkg_x.py` and marker
   `package("nosuch")` fail with the guard message; an unclosed `{{` in pergola.yaml fails
   `--package pergola` in `test_templates` (all tests of a broken package also error at setup);
   under `--package victron` `test_templates` passes (only the two pergola tests error at setup).
4. **[DONE] Skip unchanged installs.** Hash stamps. Depends on: step 1. Verify: second call skips
   pip; editing `requirements_test.txt` (temporarily) triggers the reinstall; timing recorded.
5. **[DONE] Agent guidance.** Where agents read it:
   - `CLAUDE.md` "Local CI checks": during development use the targeted form
     (`--package <pkg>` or `-- <test id>`); the full `ci-local.sh` (no arguments) once at the end,
     before pushing, is mandatory.
   - `ha-test-harness` skill: "Run" uses the script forms instead of the raw pytest commands;
     "Where does a new test go?" gets the naming convention and the `package` marker for
     cross-package tests; the 20× stability rule becomes
     `ci-local.sh -- tests/ha/test_x.py --count=20 -n 4`.
   - `README.md` local-checks line: one sentence on the targeted options.
6. **[DONE] Recorder filter.** `recorder_config` override in `tests/ha/conftest.py` per the design,
   the classification + guards, mutation checks, stability (whole suite 3x, changed/affected
   files 20x), timings recorded here. Knowledge: `ha-test-harness` skill (fixtures section: what
   the recorder records and why, how to add a history-reading platform; Run timings if stated),
   confirmed facts via the `record-learning` skill. Depends on: steps 1-5.
7. [TODO] Behaviour test for the recorder filter (owner follow-up). Gap found in Step 6: no test
   depends on recorded history (history_stats follows live events and reads the DB only on its
   first update), so dropping a source from the include list fails only the structural guards.
   Add a test that forces a DB read of a history source, e.g. history_stats after a reload/restart
   of its entity (or a statistics/filter sensor's startup load) with state changes recorded
   BEFORE, and asserts the value computed from history. Mutation: drop that source from
   `history_sources()` → the new test fails. 20x stable. Skill/notes updated (the gap fact
   in the skill is replaced). Depends on: step 6.
8. [TODO] Close: per `doc/KNOWLEDGE.md#K-6`, BEFORE merge (owner): the plan file is deleted on
   this branch so it is not part of the merge.

## Knowledge homes updated (`doc/KNOWLEDGE.md#K-1`)
- `CLAUDE.md` (Local CI checks), `.claude/skills/ha-test-harness/SKILL.md` (Run, where a test goes,
  quality rules), `README.md`, the `ci-local.sh` header comment.
- `doc/energy/notes.md`, `doc/airflow/notes.md`, `doc/airflow/design.md`: file names only.
- No learnings expected (timing results stay in this plan until Close).

## Not in scope
- CI workflows (`tests.yaml`, `e2e.yaml`) keep running the full suites.
- Selecting tests automatically from `git diff` (could follow on top of the package mapping).
