---
name: ha-test-harness
description: "Writing, running (a single test or one package's tests), debugging or reviewing tests in tests/ha (in-process HA, PHACC, real mosquitto, Clock) or tests/e2e (real HA container), their CI workflows, flaky or hanging tests, frozen-clock moves, log_guard, mutation checks, PHACC/Python/mosquitto pins. Use before touching tests/**, tests.yaml, e2e.yaml or ci-local.sh."
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
- End of task / before pushing: `.github/scripts/ci-local.sh` (no arguments; `--e2e` adds Docker, full only: e2e has
  no per-package split). Needs python3.14 (`.github/ha-versions/ha-python.txt`) and mosquitto at the version of
  `.github/ha-versions/mosquitto/Dockerfile`. The script does the venv/custom-component/mosquitto setup (`.venv-test`:
  `requirements_test.txt`, which pins PHACC and with it HA); do not call raw pytest for `tests/ha`. Each layer has
  its own ini; there is no root pytest config. Usage reference: header of the script.
- `tests/e2e` alone (no script equivalent): `pytest -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e -p no:homeassistant --timeout=300 --timeout-method=thread`
  (`tests/e2e/requirements.txt`, Docker, mosquitto on the host; `E2E_IMAGE` overrides the image;
  failure logs in `tests/e2e/.artifacts/`).
- CI: `tests.yaml` and `e2e.yaml`; both skip their steps (and pass) on a PR touching none of
  `.github/test-paths`: add a path there when a test starts reading it.
  `upload-artifact` skips dot-directories: `tests/e2e/.artifacts/` needs `include-hidden-files: true`.

## Pins and guards (`tests/ha/test_versions.py`)
- PHACC's HA year.month must equal the Dockerfile `FROM` year.month; `holidays`/`cronsim` equal HA's
  manifest pins (PHACC does not install them).
- `ha-python.txt` must equal the minor HA requires (not the 3.15 of the YAML tooling; Dependabot must not bump it).
- The first `mosquitto` on PATH must be the version the pinned HA Mosquitto app ships (FAILS, never skips; the
  message names the fix). Bump: Dependabot raises the `FROM` line, you add the `# mosquitto-in-app:` mapping line.
  Install: `.github/scripts/install-mosquitto.sh` (copies the binary out of the app image).
- Bump PHACC and the Dockerfile together, in one PR.

## `tests/ha` fixtures and their gotchas (`tests/ha/conftest.py`)
- **Fresh HA per test (function scope).** Why: totals, `this.state` hysteresis, pending timers,
  `last_triggered`, recorder history and retained MQTT cannot be reset. A module-scoped `hass` was built and
  rejected (PHACC's fixtures are function-scoped, the per-test leak checks no longer see the shared HA).
- **Tables are one looping test**, not parametrize: one fresh HA, a case list, inputs reset (and the
  reset CHECKED) before each case, failures collected, one assert naming every failing case.
- `ha`: the repo's package domains on PHACC's `hass`, real sun integration, real `workday` entry
  (AT), `weather.get_forecasts` stubbed, MQTT on the real broker; HA is set up `not_running` and then started
  (else templates render before `input_*` exist and `homeassistant: start` never fires). Config entries load
  AFTER the package domains (else `sun` hides the YAML `sensor` platforms).
- `seed(hass, states)` / `apply_baseline(hass, mqtt=…, skip=…)`: for entities with no real source
  (Somfy, ComfoConnect, weather station, go-e). Data in `tests/baseline.py`. MQTT-fed inputs go over
  the broker only: `mqtt=False` skips registry-`mqtt` states (a seed over an MQTT entity hides the next same-value message).
- Seed trigger inputs BEFORE delayed (`delay_on/off`) trigger-based sensors: a later seed re-renders them to
  `unknown` (they have no internal state; `apply_baseline` does a second restoring pass).
- An action in `_STUBBED_ACTIONS` is stubbed only if its domain is not loaded. A config entity of that domain
  loads the real one (utility_meter tariffs create `select` entities, so `select.select_option` is real): then
  `_record_external_calls` wraps it and records only calls to `_EXTERNAL_PREFIXES` entities (deterministic repro:
  without it every airflow test failed with `KeyError: 'select.select_option'`).
- Stubbed actions (`hass.data["service_calls"][action]`) record calls; attribute a call to an automation by the
  context of its `automation_triggered` event. A device echo (write sets the entity state) is needed for follow-up
  runs to behave as in production. Assert through real triggers, not `automation.trigger` (skips conditions by default).
- **Never pin a self-referencing template (`this.state`) with a seed** unless the inputs hold that state: it
  re-renders on its own change and logs "Template loop detected" (caught by `log_guard`). Drive the real input
  (e.g. the 48h mean), then assert.
- `Clock` (`clock` fixture; request it AFTER `ha`): `advance`, `move_to`, `hold(seconds, refresh)` (steps ≤ 60 s,
  republishing live inputs before each: Victron/Shelly `expire_after` 120 s), `align()`, `local_at`/`next_day`.
  - Freezing makes `loop.time()` the frozen wall clock, so every boot-time timer is overdue; the fixture fires them
    (`advance(0)`). "unknown until the delay passes after boot" cannot be observed in-process.
  - `align()` before counting `time_pattern` minute ticks: it moves to half past the minute. A tick scheduled in
    the first second of a move is skipped (`_TrackUTCTimeChange` reschedules from now + 1 s): 1 in about 60 ticks.
  - Background tasks are not awaited by default (`background=True` opts in): MQTT's re-subscribe task waits on a
    monotonic cooldown that freezer stops → hang until the timeout.
  - A move of ≥ 60 s sends a PINGREQ and a second move before the PINGRESP drops the connection: `Clock` waits for it;
    the test client connects with `keepalive=0`. A script `delay` that never comes due on a frozen clock hangs
    `async_block_till_done` (pergola's 500 ms settle: see the package note).
  - freezegun also freezes `time.monotonic`: real-I/O waits use `freezegun.api.real_monotonic` looked up at call time
    (an alias gets frozen too) and executor sleeps.
  - Expectations come from HA's own timestamps or a state read after freezing, never from the wall clock.
- Real MQTT: a mosquitto per test (restart, SIGKILL, `persistence false`, `set_tcp_nodelay true`), on a free port;
  broker fixture first so it is torn down after HA. `publish` is pipelined; `mqtt_sync` proves every earlier message
  was handled (needed before a clock move and before a seed); `wait_subscribed` before a non-retained publish.
  Isolation proof: `test_broker_isolation.py`.
- **Test recorder** (`recorder_config` in `conftest.py`): PHACC's `recorder_mock` commits per event, so recording a boot
  cost ~1.1 s CPU per test (~2.2 s boot → ~0.9 s without). The override records only the source entities of the
  config's `filter` / `statistics` / `history_stats` entries (`HISTORY_PLATFORMS`: platform → source key; derived from
  `packages/*.yaml` and `configuration.yaml` at run time) and drops event types no test reads (`RECORDER_EXCLUDED_EVENTS`;
  `call_service` etc. carry no top-level `entity_id`, so the entity filter alone would keep them). Only the sources need
  recording: those platforms read their source's state history (source read at the pin); `integration`, `utility_meter`,
  `template`, `mqtt`, `climate_template` import no recorder. New platform in the YAML: classify it in `HISTORY_PLATFORMS` or
  `NO_HISTORY_PLATFORMS` (with the reason), else `test_recorder_filter.py` fails (it also checks the classification
  against the installed component source). A test that needs a recorded entity or event outside this set must extend
  `recorder_config`; `test_recorder_filter.py` fails on a test module that queries the recorder database (only
  `async_wait_recording_done` is allowed). `test_heating_pv_boost.py::test_history_stats_read_back_from_recorder` pins
  the history read-back: history_stats follows live events and queries the recorder only on its first update, so the
  test records two runs, commits them, calls `history_stats.reload` (`async_setup_reload_service`: new entities, empty
  cache) and asserts literal values (2 runs, 0.5 h) that only the database holds; dropping the history_stats source
  from `history_sources()` makes it fail (0 / 0.0 / 0.0). The statistics and filter sources have no such test.
- Teardown order in `ha`: automations off, then the config entries are unloaded WHILE the recorder runs (else
  unloading MQTT flips entities to unavailable and a `history_stats` source queries the stopped recorder: "cannot
  schedule new futures after shutdown"; automations reacting would wait 10 s on the gone MQTT client). A test must not end
  with a long-running script on the frozen clock (hangs HA's shutdown).
- PHACC's plugin runs `logging.basicConfig(level=INFO)` and sets `sqlalchemy.engine` to INFO at import (`plugins.py` l.157-158): every recorder SQL statement hits stderr (~3300 lines/run). `conftest.py` resets that logger to WARNING; `-p no:logging` does not silence it and is not needed.
- `log_guard` (autouse): fails setup, call or teardown on WARNING+ from `homeassistant.helpers.frame`, any
  `homeassistant.*` "deprecated" message, or a template error. Opt out per test with
  `@pytest.mark.allow_log(regex, reason=…)`; `_KNOWN_CONFIG_LOGS` lists config defects tolerated everywhere
  (an entry is an open defect, issue number in its comment). `expected_lingering_timers` is True on purpose.
- Entity ids: look up by unique_id (`entity_id()`); a fresh registry derives other ids than production for
  MQTT/filter/statistics sensors (#146); `load_repo_config` pre-registers the Victron ones.
- The template test (`test_templates.py`) renders every extracted state/runtime template in one HA, blueprints
  included (`!input` yields the input name, so their templates render leniently as runtime); a YAML parse error
  fails the extraction, naming the file. 15 of the 56 MQTT entities are never fed a message by any test, so their
  `value_template` only gets that syntax check (#159).
- Pre-start seeding takes an explicit prefix list of the missing integrations' entities, never "whatever does not exist
  yet": a seed once took `sensor.airflow_avg_indoor_humidity_5min` before the filter platform registered it and the
  config entity became `_2` (`test_packages_load` asserts no `_2` ids).
- Do not configure `http` explicitly: HA 2026.10's pending-HTTP-config trial reverts and restarts HA once 5 min pass on
  the mocked clock. The default (0.0.0.0:8123, not listening) is left alone.
- The YAML `workday` platform is rejected by HA at the pin: workday is a config entry (`MockConfigEntry` in-process,
  the flow in e2e). `utility_meter` registers `<unique_id>_single_tariff`.

## `tests/e2e` (real container)
- ONE session container (`docker run --network host`, image from the Dockerfile `FROM`), a host mosquitto, own client
  `ha_client.py` with a timeout on every call and deadline polling, no fixed sleeps.
- Bootstrap boot (onboarding, MQTT and workday through the real config flows, production-like entity ids), then a clean
  restart: only the log after it is judged (a fresh HA logs ERROR on `homeassistant: start` MQTT publishes before the
  MQTT entry exists). `test_zz_log_hygiene.py` runs last; its `EXTERNAL_NOISE` (environment) and `KNOWN_CONFIG_BUGS`
  (issue numbers) lists are explicit: add an entry only with its cause.
- A restore test must make the value final before the restart (e.g. an integral fed absurd power, then 0 W), else the
  sum keeps moving afterwards and the assertion is weak; `wait_stable` for a value that settles after a burst.
- `.github/scripts/install_custom_components.py` is the one installer of `climate_template` (CI, `ci-local.sh`, `stage.py`).

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
