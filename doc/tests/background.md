# Test framework: history of the migration to the in-process and real-HA layers

How the test suite moved from one Docker HA driven over REST (`ha_integration_test_harness`, libfaketime) to the
in-process layer `tests/ha` (PHACC, real mosquitto, frozen clock) and the real-HA layer `tests/e2e` (PR #149):
context, feasibility check, spikes and measurements, rejected options, the item-by-item migration with its
mutation tables, flakes found and fixed, the first GitHub runs, and where each finding went. This is history, not
design: the current facts are in the places below. Read it only when asked how or why the test setup came about.

Where the current facts live:
- Writing, running and debugging tests, fixtures, pins, CI: `.claude/skills/ha-test-harness/SKILL.md`
- File-type rule that loads the skill: `.claude/rules/tests.md`
- Package-specific test facts: the "Tests" section of `doc/<pkg>/notes.md`
- Confirmed config bugs found by the migration: GitHub issues #146 #147 #148 #153 #154 #155; the RFE for untested MQTT entities: #159

Grades are those of `record-learning`; "HYPOTHESIS" here was never confirmed. Sections keep the plan's wording,
so "Step N" and "item N" refer to the plan's phases.


## Context and feasibility

All 205 tests in `homeassistent-config/tests/` run against a Docker HA started by
`ha_integration_test_harness` (v0.11.0). Costs and instability seen today:
- About 140 REST round-trips of seeding per test (`baseline_inputs` + `baseline_states`), plus REST polling in `assert_entity_state`.
- The clock is libfaketime driven by `docker exec`. Only one advance per test is safe, and `jump_to_next` only moves forward.
- One container for the whole session, so state leaks between tests: two airflow tests depend on test order, one Victron test is skipped as an ordering flake, and #143 is open.
- Hangs are unexplained (`plans/ci-test-speedups.md`); the HTTP timeout shim is a workaround.
- The harness hardcodes `:stable`, so CI has to retag the pinned image.
- Pergola needs its own pytest step to get a fresh clock.
- No tests run locally, because `ci-local.sh` has no Docker.

innova_hrds solved the same problems:
- `tests/ha` runs in-process with pytest-homeassistant-custom-component (PHACC). It is the default layer, function-scoped, and takes about 1 min.
- `tests/e2e` holds only what a real HA must show, enforced by `@pytest.mark.needs_real_ha("<reason>")` with a closed list of reasons.
- `test_versions.py` keeps the PHACC version and the Docker `FROM` pin at the same year.month.
- The clock is moved with `async_fire_time_changed` and `async_block_till_done`, with no sleeps.
- A log-hygiene test runs last in e2e.
- CI has change detection, concurrency groups and a pip cache.

Goal: faster, high-quality, stable tests.
- Everything that HA's in-process test harness can show validly runs in-process.
- Only the tests that truly need a real HA run in the container.

### Feasibility: does the hrds setup fit a YAML/automation config?
The system under test differs:
- hrds tests one custom integration that talks to a Modbus simulator.
- This repo tests YAML (packages, automations, templates, helpers) that runs on core integrations.

PHACC does not care about that difference. It runs the real HA core, with its real YAML loader and real integrations, inside pytest. HA core's own tests for automation, template, utility_meter, integration and history_stats run exactly this way.

The current Docker tests do not run the real external integrations either: MQTT, go-e, Somfy and ComfoConnect are all faked with REST `set_state`. So in-process is not less real than today for these tests.

Verified against source (PHACC 0.13.375 on PyPI, HA core tag `2026.10.4`):

| Need | Finding | Status |
|---|---|---|
| Load this repo as the config dir | PHACC `hass` takes the overridable fixture `hass_config_dir`, documented for this use (`plugins.py:664-691`) | CONFIRMED |
| `!include_dir_named packages`, `!secret` | `config.async_hass_config_yaml(hass)` reads `configuration.yaml` from `hass.config.config_dir` and calls `merge_packages_config` (`config.py:205,247`) | CONFIRMED |
| `custom_templates/airflow_decision.jinja` | Bootstrap loads it through `template.async_load_custom_templates(hass)` (`bootstrap.py:490`). In tests we call this function ourselves | CONFIRMED (API exists) |
| Clock for `time_pattern`, `delay_on`/`delay_off`, integration, utility_meter | PHACC ships `freezegun`/`pytest-freezer` and `async_fire_time_changed`; HA core tests these integrations this way | CONFIRMED (deps); usage pattern from core tests |
| MQTT sensors and `mqtt.publish` | PHACC ships `paho-mqtt==2.1.0`, so the real MQTT integration can run against a real mosquitto (Step 2b). Gain: `value_template`s really run, and publishes can be asserted | Deps CONFIRMED; real broker plus freezer to be shown in the spike |
| Recorder for history_stats, statistics and filter | PHACC ships SQLAlchemy and the `recorder_mock` fixture (`plugins.py:1990`) | CONFIRMED |
| workday, utility_meter | They need `holidays==0.106` and `cronsim==2.7`, which PHACC does not install. Pin them from HA's manifests, as hrds does for pymodbus | CONFIRMED, extra requirement |
| `climate_template` (HACS) | It has no requirements, and its only dependency is `template`. It gets loaded from `<config_dir>/custom_components` with `enable_custom_integrations` | Requirements CONFIRMED; loading to be shown in the spike |
| Calls to services that do not exist in CI (notify.mobile_app, cover, switch, select, rest_command, weather.get_forecasts) | `async_mock_service` stubs them and records the calls. PHACC blocks sockets, so no request leaves the test. Gain: tests can assert what an automation did | Standard PHACC pattern |
| `trigger: homeassistant` (6 uses) | `async_test_home_assistant` takes `initial_state: CoreState` (`common.py:226`). Start as not_running, then fire the start event | API CONFIRMED; spike |
| Python | PHACC needs >=3.14 and HA 2026.10 declares `>=3.14.2` (classifier 3.14 only). `.github/ha-versions/python/Dockerfile` is 3.15, so the in-process job pins 3.14 to match HA | CONFIRMED |
| Version pin | PHACC 0.13.375 pins `homeassistant==2026.10.4`; the Docker image is 2026.10.1. year.month match, and the `test_versions.py` guard checks exactly that | CONFIRMED |

Real differences that stay real-HA only:
- `default_config`, `lovelace`/dashboards, `frontend` themes, `rest_command` with secrets: the full boot of the real `configuration.yaml`.
- The HACS install path.
- The real restart with restore_state. In-process can cover the logic with `mock_restore_cache`, but only e2e shows the real store.
- Container log hygiene.
- `check_config`.

The in-process fixture loads only the package domains, never `default_config`.

Residual risks, which the spike must close:
1. Whether all six packages load together in-process without network or missing-dependency errors.
2. Time zone and location: PHACC defaults to US/Pacific. Set Europe/Vienna and the Linz coordinates for `sun`.
3. A package-level `recorder:` key must not fight `recorder_mock`. Probably strip it from the config dict.
4. Runtime per test: a full package load each time. If it is too slow, cache the parsed config dict per session (it is pure data) and keep `hass` function-scoped.


## Spikes (Step 0)

**Step 0 results** (spike tests: `tests/ha/test_spike.py`; the fixtures are final since Step 2)
How to run it: `uv venv -p 3.14 .venv-test && VIRTUAL_ENV=.venv-test uv pip install -r requirements_test.txt`, plus a `mosquitto` binary and `custom_components/climate_template` (CI downloads it). Then:

```
.venv-test/bin/python -m pytest -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . tests/ha -n 4
```

`--count=20` runs the stability gate.

**Exit criterion met.** 7 spike tests, all in-process:
- package load;
- Shelly MQTT ingest;
- two airflow decision ports;
- Victron `time_pattern` battery accumulator, over real MQTT with `freezer`;
- Victron `integration` grid import, over real MQTT with `freezer`;
- Victron keep-alive publish (start and every 30 s).

Stability: 140/140 for 7 tests × 20 rounds, and before the last test was added, 240/240 for 6 tests × 40 rounds.

**Validity.** Each mutation of the YAML under test fails exactly the test that covers it:

| Mutation | Caught by |
|---|---|
| Shelly Wh→kWh `/1000` changed to `/100` | ingest test |
| integration `trapezoidal` changed to `left` | grid test |
| `heating_season` forced to false in `airflow_decision.jinja` | decision test |
| battery accumulator `/60000` changed to `/6000` | battery test |
| wrong keep-alive topic | publish test |

**How it works** (CONFIRMED by the runs above; the fixtures are in `tests/ha/conftest.py`):
- **Config dir**: PHACC's `hass_config_dir` fixture is overridden with a staged copy of `packages/`, `custom_templates/`, `blueprints/`, `custom_components/`, `automations.yaml`, `scripts.yaml` and the fake secrets.
- **Loading**: `async_hass_config_yaml(hass)` loads the config with packages merged. The `recorder:` key is dropped because `recorder_mock` owns the recorder.
- **Bootstrap order**: HA is set to `CoreState.not_running`, every domain is set up concurrently, then `hass.async_start()`. Without this, templates and automations render before the `input_*` helpers exist, and `homeassistant: start` triggers never fire.
- **Real MQTT**: a mosquitto per test on a free port, and `MockConfigEntry(domain="mqtt")` pointing at it. The fixture waits until `mqtt.is_connected` is true before start, so start-time publishes are not lost.
  - Before publishing, the test waits until HA has subscribed to the topic, read from mosquitto's `-v` log, so a non-retained message cannot be lost.
  - The broker fixture is set up before `hass`, so it is torn down after it.
- **Clock**: `freezer` is requested after `ha`, then `freezer.tick()` plus `async_fire_time_changed`.
  - freezegun also freezes `time.monotonic`, which stops asyncio timers. Real-I/O waits must therefore use real time (`freezegun.api.real_monotonic`, looked up at call time) and executor sleeps.
  - A plain alias `x = freezegun.api.real_monotonic` gets frozen too, because freezegun replaces every attribute that equals `time.monotonic`. That alias was the spike's first hang.
  - Freezing after start leaves timers due later unfired until a tick. The real MQTT link stayed stable through 60 s jumps (keepalive risk: not seen in 380 test runs).
- **Not available in the test HA**:
  - workday is a real `MockConfigEntry` (AT).
  - `weather.get_forecasts` is an `async_mock_service` with a deterministic 49 h forecast.
  - YAML timers that stay scheduled on the stopped HA are expected (`expected_lingering_timers`).

**Findings about the config and the current suite** (CONFIRMED by these runs; to be fixed or tracked, not in Step 0):
1. **Entity IDs depend on the old `.storage`.** Deferred to its own plan, `plans/mqtt-default-entity-id.md`. The MQTT sensors in `victron.yaml` and `energy.yaml` have no `default_entity_id`.
   - On a fresh registry they get IDs like `sensor.electrical_victron_energy_system_victron_grid_l1_power` and `sensor.pool_pool_pump_pool_pump_power`.
   - Every Victron template reads `sensor.victron_grid_l1_power`, so a rebuild or restore without `.storage` breaks the whole Victron chain.
   - The Docker suite hides this by seeding states under the production IDs. The spike pre-registers the production IDs as a stand-in.
   - Proposed fix: add `default_entity_id` to these MQTT sensors (needs approval; touches YAML).
2. **The workday fixture is invalid at the pin.** The YAML platform in `tests/custom_components.yaml` (`ha_yaml_config`) is rejected by HA ("does not support platform setup"), so CI never had a workday entity; the tests seed it.
3. **The Docker suite uses live network data.** `weather.home` is the onboarded Met.no entity, so the 48 h forecast-mean sensor depends on the internet. In-process uses a deterministic stub.
4. **Speed.** About 1.6 s of setup per test (the MQTT connect and the recorder-dependent sensors dominate) plus about 1 s of teardown.
   - Measured: 7 tests in 9.4 s with 4 workers; 140 runs in 1m53s.
   - Estimate for the 205 current tests: about 2.5–3 min with `-n 4`. That is the same order as Docker today (about 3.5 min), so the gain is in stability, coverage and local runs, not raw time.
   - Optimisations for Step 2, unmeasured: a lighter setup for modules that need no MQTT or recorder, and caching the parsed config per session.
5. **Two flakes found and fixed during the spike, both test bugs rather than harness bugs:**
   - A real minute boundary during HA start can tick a `time_pattern` accumulator before the freeze, so the baseline must be read, not assumed.
   - The 0→3000 W integration step spans real time before the freeze, so its area must come from HA's timestamps, not be rounded away.
   - Rule for Step 2: every expectation is computed from HA's own timestamps or from a state read after freezing.


## Migration results (Step 2)

### Step 2 results (first chunk: spikes, shared fixtures, migration item 1)
Run: `.venv-test/bin/python -m pytest -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . tests/ha -n 4 -q`.
13 tests (7 spike, 2 broker isolation, 1 templates, 3 version guards). Stability `--count=20 -n 4`: 260/260, 2m19s wall (Step 0: 140 runs in 1m53s).

**Module-scoped `hass` (tier 1): feasible, NOT clean; function scope kept.** Verified against PHACC 0.13.375 source (`plugins.py`, `common.py`) and a throw-away proof (one module fixture, 20 decision tests, then 100 with `--count=5`):
- Measured: module HA setup 1.4 s, teardown 1.4 s once per module, then about 40 ms per test (100 tests in 5.5 s). Function scope: about 2–2.5 s setup + 0.1–0.8 s teardown per test.
- Why not clean (each CONFIRMED in the proof or the source):
  - PHACC's `hass`, `recorder_mock`, `enable_custom_integrations`, `socket_enabled`, `freezer` are all function-scoped. A module HA must be built by hand with `async_test_home_assistant`, plus its own config-entry unload, `async_stop(force=True)` (the context manager does not stop HA; without it `INSTANCES` is left behind) and loop exception handler (the `hass` fixture's re-raise of loop exceptions is lost).
  - The recorder needs PHACC's private `plugins._async_init_recorder_component`, without the patches `async_test_recorder` applies.
  - Per test, PHACC's `reset_globals` clears the frame helper and `verify_cleanup` asserts the default time zone is UTC, so every test must re-install the frame helper and Europe/Vienna.
  - `http` (a dependency of calendar/person/mqtt) binds a socket at setup; module setup runs before the function-scoped `socket_enabled`, so sockets must be enabled by hand.
  - `verify_cleanup` checks lingering tasks/timers on the function loop, not the module loop: the per-test leak checks no longer see the shared HA. The log guard (function scope) does not see the module's boot logs.
  - xdist `load` splits a module across workers (one HA per worker per module); interleaved modules re-create it. Needs `--dist loadfile`/`loadgroup`.
- Decision: stay function-scoped. For tier-1 tables (decision, bypass, wallbox, Victron power math, indicator thresholds) use the `test_templates.py` pattern instead: ONE test on one fresh HA loops over the cases, resets the inputs it uses per case, collects failures, one assert. Same speed as module scope, no PHACC workarounds. A failing case still names itself in the assert message.

**Mosquitto clear vs restart: restart kept.** Measured in-situ (pytest, `-n 0`, 40 tests of the isolation proof):
| Variant | Cost per test |
|---|---|
| Restart, SIGTERM (Step 0 code) | 137 ms (median; graceful shutdown ≈ 110 ms) |
| Restart, SIGKILL (adopted; `persistence false`, nothing to save) | 23.5 ms |
| One broker per worker, cleared (subscribe `#`, sentinel round trip, empty retained per topic, 5 retained topics) | 23.6 ms (20 topics: 53 ms; 0 topics: 1.1 ms) |
- Clear is not faster, and it needs workarounds: PHACC's thread check fails the first test (the session paho thread appears during its setup), and `wait_subscribed` would see the previous test's subscriptions in the shared log (needs a per-test log offset).
- Isolation proof `tests/ha/test_broker_isolation.py` (A leaves retained messages and self-checks that the probe sees them; B asserts no retained message on `#`), `-n 0 --count=20 --repeat-scope=module`, both orders (A,B,… and B,A,…): restart 40/40 each; clear 40/40; control without clearing: B failed 20/20, so the proof is sensitive.
- Side finding, fixed: `Broker.stop()` called paho `loop_stop()` before `disconnect()`, so the network thread sat out its 1 s `select()` timeout: 1.0 s of every test's teardown. Teardown is now 0.1–0.8 s; the rest is unexplained (HYPOTHESIS: HA's own MQTT client shutdown).

**Shared fixtures (`tests/ha/conftest.py`).**
- `tests/baseline.py`: the baseline data (helper actions, input_number values, 99 states) moved out of `tests/conftest.py` as pure data; the Docker fixtures now loop over it. Equivalence checked by recording both fixtures' calls against a fake harness: 133 identical calls in the same order. The Docker suite still collects (203 tests).
- `seed(hass, states)`, `apply_baseline(hass)` (actions, numbers, states, then a second pass that restores entries a later seed re-rendered: the delayed airflow indicators fell back to `unknown`, the known seeding-order gotcha).
- `load_repo_config(hass, mqtt_port=…)` + `ha`: also stubs the actions of integrations the test HA lacks (`async_mock_service`, calls in `hass.data["service_calls"]`), and seeds the entities of those integrations (explicit prefix list) BEFORE start.
- `Clock` (`clock` fixture): `freezer.tick`/`move_to` + `async_fire_time_changed` + `async_block_till_done`. Background tasks are NOT awaited by default (CONFIRMED hang): MQTT's "re-subscribe and birth" task sleeps until a discovery cooldown measured on `time.monotonic`, which freezer stops, so `wait_background_tasks=True` right after start waits until the test timeout. Opt in with `background=True`.
- Autouse `log_guard`: fails setup, call or teardown on WARNING+ from `homeassistant.helpers.frame`, any `homeassistant.*` "deprecated" message, or a template error (template helper/integration loggers, or a message naming TemplateError/UndefinedError/template variable/`'template' condition`). Opt-out per test: `@pytest.mark.allow_log(regex, reason=...)`. Mutation-checked: a frame report, a template-integration error and a Shelly payload without `output` each fail; an allowed pattern and an unrelated warning pass.

**What the guard and fixtures revealed** (CONFIRMED in these runs unless marked):
1. Test-environment issues, fixed in the fixtures: the pergola watchdogs' template condition (`states.cover.dach_links.last_updated`) errored on `homeassistant: start` because the Somfy entities did not exist (now seeded before start); airflow automations then called `select.select_option` etc. (now stubbed); the Shelly ingest test payload lacked `output` (`value_json.output` warning; real devices always send it).
2. Config issue, tolerated by name in `_KNOWN_CONFIG_LOGS`, YAML fix needs approval: `sensor.victron_solar_yield_dc_baseline_kwh` / `victron_ac_pv_energy_baseline_kwh` render the string `unknown` (source and `this.state` both unknown) into a numeric energy sensor, logged as ERROR on each `time_pattern` tick before the Venus counters arrive. Proposed fix: render `none`. Production impact UNPROVEN (restored state normally covers it). Tracked in #147.
3. More registry-dependent entity ids (same class as #146), CONFIRMED on a fresh registry: filter `airflow_min_indoor_dew_5min` becomes `sensor.airflow_avg_indoor_dew_5min` (name "Avg"), filter `airflow_wheatherstation_outdoor_temp_5min` → `sensor.airflow_weatherstation_outdoor_temp_5min`, filter `wheatherstation_outdoor_temperature_15min` → `sensor.weatherstation_outdoor_temperature_15min` (so the 48h statistics sensor, which reads `sensor.wheatherstation_outdoor_temperature_15min`, has no source on a fresh install), statistics 48h mean → `sensor.weatherstation_outdoor_temperature_48h_mean`. Templates read the production ids. Added to #146 (issue comment).
4. A pre-start seed selected by "entity does not exist yet" once took `sensor.airflow_avg_indoor_humidity_5min` before the filter platform registered it (the config entity became `_2`). Hence the explicit prefix list, and `test_packages_load` now asserts no `_2` ids.
5. `http` binds `0.0.0.0:8123` (not listening) in every in-process test. Configuring it explicitly (localhost, free port) starts HA 2026.10's pending-HTTP-config trial, which reverts and restarts HA once 5 min pass on the mocked clock (seen: "Pending HTTP config was not confirmed"). Left at the default. HYPOTHESIS: a local HA on 8123 would push the test HA into the http fallback chain.
6. `extract_templates.py` scanned `.venv-test` (5 runtime templates from HA's own YAML) and took 4 s locally: hidden directories are now pruned (CI output unchanged: its checkout has none). It also silently skips the blueprints (`!input` is not a known tag, the YAMLError is swallowed), so their templates (8 lines with `{{` in two blueprints) are never checked (CONFIRMED: 0 extracted from `blueprints/`; fix later, out of this chunk). Tracked in #148.

**Migration item 1 done.** `tests/ha/test_templates.py`: one test, one HA, `apply_baseline`, then every extracted template rendered with `Template(...).async_render(parse_result=False)` like `/api/template`; strict for state templates (error, undefined variable via `log_fn`, sentinel output), lenient for runtime templates; all failures in one assert. 112 state + 97 runtime templates, about 5 s including HA boot. Mutation checks (temp copy): a state template reading a missing entity → "sentinel output: 'unknown'" naming file and template; a runtime template with an unknown filter → "TemplateAssertionError: No filter named 'bogus_filter'". The Docker `tests/test_templates.py`, the CI extraction step and `TEMPLATES_JSON` are removed.

### Step 2 results, item 2 (wallbox, heating_cooling_indicator, airflow decision/bypass/thresholds)
New: `tests/ha/test_wallbox.py`, `tests/ha/test_heating_cooling_indicator.py`, `tests/ha/test_airflow.py` (`test_decision_table`, `test_bypass_estimation`, `test_dew_point_thresholds`). Each is ONE test on one fresh HA that applies the baseline, loops over a case table, resets every input it uses before each case and CHECKS the reset (a value no case expects, so no case can pass on a leftover), collects failures and fails with one assert listing every failing case (a failed reset is listed and the case still runs).

Mapping, Docker → in-process (41 Docker tests removed, nothing dropped):
| Docker | Cases now | Notes |
|---|---|---|
| `tests/test_wallbox.py`, 7 tests | 7 | file deleted |
| `tests/test_heating_cooling_indicator.py`, 6 tests | 6 | file deleted; every case now checks both effective sensors (Docker: only the one it relied on) |
| `test_airflow.py::test_decision_*`, 20 tests | 20 | the two spike ports in `test_spike.py` removed too (same cases) |
| `test_airflow.py::test_bypass_*`, 6 tests | 6 + 2 new | new: pressure fallback, η_max read from its helper; every case now also sets the station pressure (Docker: never seeded, always the fallback) |
| `test_airflow.py::test_dew_point_*`, 2 tests | 1 + 3 new | both old tests compared the sensors with a Jinja COPY of the formula at baseline; now an independent Python Magnus with literal anchors (9.08 / 12.08 °C). New cases with distinct humidities and both target-temperature ends: at baseline max = target (55 %), so a max/target mix-up was invisible |

How inputs are driven:
- Real paths: input_number/input_boolean actions; the season of the decision is the REAL `sensor.heating_cooling_indicator`, driven through its seeded 48h mean (one mean per season, reached from neutral in at most two steps).
- Seeded (no real path without the clock, item 4): the go-e sources (MQTT discovery, not in this repo), the 48h mean (statistics over a filter, and registry-dependent id #146), the airflow delayed indicators and the 5-min filter outputs. Seeding order for the indicators as in the Docker suite (dew, season, flush, drying, low guards, free cooling).
- The indicator's previous state (`this.state`) is pinned only after the mean is set to a value that holds it, and the test checks the pin held. CONFIRMED in this run: pinning the indicator to a state its mean does not support makes the self-referencing template re-render on its own change, and more than two self-triggered renders in a row log "Template loop detected" (`template_entity.py`, limit = number of templates; the log guard caught it). The Docker airflow tests pin the indicator this way about 30 times; their logs are not checked.
- The retention "from warm" memory is checked on the macro (`Template` render, as the Docker test did over `/api/template`): a dew change re-renders the indicators to `unknown`, so the real sensor goes unavailable and drops its stored profile.

Mutation checks (temp edit, reverted with `git checkout`, never committed), each fails with the case(s) named:
| Mutation | Failing case(s) |
|---|---|
| wallbox kW `* 1000` → `* 100` | `power_kw_source_converted_to_w` |
| wallbox energy `unit == 'Wh'` → `'kWh'` | every reset (Wh path), `energy_wh_…`, `energy_kwh_…` |
| indicator heating hysteresis `heat + 1` → `heat + 0.5` | `heating_hysteresis_is_one_degree_above_the_threshold` |
| active-effective clamp `cool + 2` → `cool + 1` | `order_is_enforced_…`, `effective_thresholds_show_the_clamp` |
| decision `heat and not moist` → `heat` | `moisture_protection` |
| decision retention enter edge `dew_min - 0.1` → `dew_min` | `retention_hysteresis` |
| bypass `round(0, 'floor')` → `'common'` | `near_closed_floors_to_zero`, `efficiency_max_from_helper` |
| `dew_point_max` reads the target humidity | every reset, `distinct_humidities`, `warm_target`, `cool_target` (not `baseline`: max = target there) |

Case independence: all five tables also pass with their case order reversed (temporary module, not committed).

Stability and time: `tests/ha` 16 tests in 15 s (`-n 4`); `--count=20 -n 4`: 320/320, 3m21s wall. New tests: setup 2.3–3.0 s each (HA boot), call 0.6 s (wallbox, bypass), 0.8 s (indicator, dew points), 2.6 s (decision table, 20 cases).

Stayed in the Docker `tests/test_airflow.py` (65 tests, all collect; suite 203 → 162):
- controller, drying boost, medium preset, away, edge-only boost and controller consistency tests: automations (item 4/5, assert through real triggers instead of `automation.trigger`);
- heat protection and reload-recovery tests: delayed indicators (delay_on/off, clock: item 4);
- the dew_max gate, low-needed boundary, flush, drying and hvac_action tests: they render a COPY of a YAML formula over `/api/template`, so they test the copy, not the config (CONFIRMED drift: the drying copy reads the raw `sensor.wheatherstation_outdoor_temperature`, the real `airflow_humidity_drying_needed` reads its 5-min filter `sensor.airflow_wheatherstation_outdoor_temp_5min`). Replace them in item 4 with tests of the real sensors through their inputs and the clock, not a port of the copies.

No config bug found by these tests.

### Step 2 results, item 3 (heating_pv_boost, Victron instant power, Shelly pool pump)
New: `tests/ha/test_victron.py` (`test_instant_power_table` + the three Victron spike tests, moved unchanged), `tests/ha/test_heating_pv_boost.py` (`test_surplus_table`, `test_compressor_table`, `test_cooling_interlock`, `test_target_temp`), `tests/ha/test_shelly_pool_pump.py` (`test_pool_pump_sensors`). Same table pattern as item 2 (one test per table, reset checked per case, one assert naming every failing case); a case may have further steps without a reset (`then`), for the Docker tests that asserted a transition.

**MQTT-fed inputs go only over the real broker (Step 2b).** Venus OS `{"value": x}`, ebusd `;`-separated strings (names and raw enum numbers), Shelly Pro 3EM `em:0`/`emdata:0` and Plus Plug S `switch:0` JSON. The tests use `apply_baseline(hass, mqtt=False)` (new: skips states of registry-`mqtt` entities, since a seed over an MQTT entity hides the next same-value message) or no baseline. "Unavailable" is what production sees: a real `expire_after` (the Clock moves past it, the other inputs are republished), or an `expire_after` sensor that never got a message (starts unavailable; ebusd registers without expiry start `unknown`). Those two never-published cases run as a startup phase before the table (`multiplus_dc_power_unavailable_without_voltage`, the stop temp's missing hysteresis): the voltage's expiry is 24 h, ebusd has none.

Still seeded (no real path without the clock, item 4): the η accumulators (trigger-based minute ticks), the two `history_stats` sensors behind the average run, the 48h outdoor mean (drives the REAL indicator, as in item 2). The efficiency's daily meters are the REAL `utility_meter`s: reset per case with `utility_meter.reset`, fed by the ebusd YieldTotal and Shelly energy counters (not item 4: no cycle, no clock).

Mapping, Docker → in-process (64 Docker tests removed; Docker suite 162 → 98, collects):
| Docker | Now | Notes |
|---|---|---|
| `tests/test_victron.py`, 31 instant-power tests | 32 cases + startup phase | `pv_net_treats_unavailable_pv_as_zero_but_load_outage_as_unavailable` split in two; `multiplus_dc_power_unavailable_without_voltage` is the startup phase; new: empty / `{"value": null}` payload keeps the last value. Unavailable inputs now expire for real (Docker: REST "unavailable") |
| `test_victron.py::test_battery_discharge_energy_accumulates`, `::test_grid_import_energy_accumulates` | the spike ports (moved) | spike grid test is the stronger version (exact 60 s step) |
| spike `test_victron_keepalive_published` | moved | asserts both published keep-alive payloads |
| `tests/test_heating_pv_boost.py`, 10 surplus tests | 10 cases + 1 new | new: the heating clamp's sensor expires → unavailable. House load split in integers (MQTT rounds to W; Docker seeded load/3 floats) |
| compressor active (1, 3 asserts) | 1 case, 3 steps | clamp gone = real expiry |
| heating active (3) | 3 cases | hcmode as name and raw number (`3`, `4`) |
| average run (1, 2 steps), stop temp (1, 2 steps), efficiency (1, 2 steps) | 1 case + step; 1 case + startup phase; 2 cases | efficiency through the real meters |
| cooling interlock (1) | 1 case + 4 new | new: each ebusd signal alone, raw `1` = cooling |
| target temp (3) | 3 cases | season via the real indicator |
| `tests/test_shelly_pool_pump.py`, 10 tests (file deleted) | 9 cases + spike ingest case | every case checks all five entities. **Dropped:** `test_temperature_sensor`: `sensor.pool_pump_temperature` exists in no YAML; the Docker test read back its own seed. Spike `test_mqtt_ingest_shelly_pool_pump` = case `ingest_rounds_like_the_firmware_values` |

Stayed in Docker (item 4, they need the clock): heating DHW return mask (delay_off 25 min), master-switch decision (delay_off 20 min), the two `heating_compressor_last_run` tests (`last_changed` span); Victron η accumulator ticks (2), grid export, night no-grid, conversion loss energy, the four solar-yield counter-delta tests (one still skipped), the two battery residual tests. `tests/ha/test_spike.py` keeps only `test_packages_load`.

Mutation checks (in place, restored with `git checkout`, never committed), each fails naming the case(s):
| Mutation | Failing case(s) |
|---|---|
| victron ac_net `- ac_pv` → `+ ac_pv` | every reset (ac_net, battery, loss) and the cases reading them (98 checks) |
| victron grid L2 value_template `value / 10` | `grid_import_half_wave`, `grid_export_half_wave`, `night_solar_off_battery_discharge` |
| victron Multi current `expire_after: 600` → `6000` | `multiplus_dc_power_expired_current_reads_zero` |
| victron keep-alive payload `["suppress-republish"]` → `[]` | `test_victron_keepalive_published` (shows the published payload) |
| heating surplus PV cap removed | `…heater_leads_the_victron_load`, `surplus_never_exceeds_pv_generation` |
| heating hcmode raw `4` no longer → water | `heating_active_is_off_for_a_hot_water_run step 2` |
| energy Heizung `total_act / 1000` → `/ 100` | both efficiency cases (meter and efficiency) |
| energy Heizung power `total_act_power` → `a_act_power` | every surplus reset and most surplus cases |
| heating interlock: cooling request ignored | `cooling_interlock_cooling_request step 2` |
| heating target `tdl + 1` → `tdl + 2` | every target reset, the two in-season cases |
| energy pool pump `aenergy.total / 1000` → `/ 100` | every reset, `energy_wh_to_kwh_conversion`, `pump_running_scenario`, … |
| energy pool pump switch without `lower` | every case and reset (switch `unknown`) |

Case independence: all six tables also pass with their case order reversed (temporary module, not committed).

Stability and time: `tests/ha` 21 tests in 23 s (`-n 4`); `--count=20 -n 4`: 420/420, 5m07s wall. Call medians (20 runs): Victron table 2.6 s (33 cases), surplus 1.1 s, compressor 1.0 s, target 0.6 s, interlock 0.55 s, pool pump 0.5 s, moved Victron accumulator/keep-alive 0.1–0.3 s; setup 1.7–1.9 s each (HA boot).

Harness changes (CONFIRMED by measurement in this chunk):
- A QoS 1 publish with `wait_for_publish` took 44 ms (Nagle + delayed ACK on localhost). `set_tcp_nodelay true` in the mosquitto config and `TCP_NODELAY` on the test client: 8–10 ms; pipelining (`Broker.send`, flushed by `mqtt_sync`): ~1 ms. The Victron table went from 34 s to 3 s.
- `mqtt_sync(hass, broker)`: one fresh value on `ebusd/ehp/Integral` (subscribed, read by nothing) proves every earlier message was handled (one client, in-order delivery). Needed before a clock move (a late message would re-arm its expiry on the moved clock) and before a seed (an MQTT change can start a refresh that overwrites the seed: seen with history_stats).
- `check_states`, `near`, `at_least`, `is_state` in `tests/ha/conftest.py` for the tables.
- Seen once per run until handled: at teardown of the compressor table, history_stats queried the stopped recorder ("cannot schedule new futures after shutdown"). The test now ends with the history_stats source unavailable. HYPOTHESIS: HA's shutdown flips an MQTT input, and the refresh that follows runs after the recorder stopped.
- Registry facts used: the Shelly Pro 3EM entities get their production ids (`sensor.technikraum_heizung_heizung_power`) on a fresh registry (the surplus test asserts it); utility_meter registers `<unique_id>_single_tariff`; the pool pump sensors get `sensor.pool_pool_pump_pool_pump_*` (#146).

No config bug found by these tests.

### Step 2 results, item 4 (heating_pv_boost, Victron, airflow)
Harness changes (`tests/ha/conftest.py`), each CONFIRMED in this chunk:
- **Freezing fires every boot-time timer.** freezer replaces `time.monotonic`, which is asyncio's `loop.time()`, with the frozen wall-clock timestamp (printed in a test: loop time 1.79e9 s after the freeze vs real monotonic ~2000 s). Every timer scheduled before the freeze (a delay_on/off started at boot, time_pattern ticks, expire_after) is then overdue and fires at whatever loop iteration comes next. The `clock` fixture now fires them itself (`advance(0)`), so a test starts deterministic: e.g. `heating_dhw_active` is already `off`, not its boot `unknown`. Consequence: an "unknown until the delay passes after boot" state cannot be observed in-process (the Docker tests only worked around it).
- **MQTT keep-alive across clock moves.** paho times its keep-alive on `time.monotonic` too: a move of at least 60 s sends a PINGREQ; a second move before the PINGRESP was read (real socket I/O) counts as a ping timeout and drops the connection (seen: a move to tomorrow 10:00 right after the fixture's `advance(0)` → "Error talking to MQTT: The client is not currently connected", subscriptions lost). `Clock` now waits (real time, bounded) after every move until no ping is open.
- **history_stats after recorder stop: root cause found and fixed.** Traceback: PHACC's `hass` fixture unloads the config entries after `recorder_mock` (which depends on `hass`, so it is finalised first) stopped the recorder; unloading the MQTT entry writes `unavailable` for every MQTT entity (`entity_registry.write_unavailable_state`), the clamp → `heating_compressor_heating_active` → the history_stats coordinator queries the stopped recorder executor ("RuntimeError: cannot schedule new futures after shutdown"). The `ha` fixture now unloads the config entries itself while the recorder runs. Proof: without that unload, `test_compressor_table` (its item-3 workaround removed) and `test_slab_mode_wanted_delays` both error at teardown; with it both pass. The item-3 workaround is removed.
- **10 s teardown after clock moves, fixed.** Task dump after the unload: unloading MQTT flips its entities to unavailable, which fired "Heating: ebusd poll registration"; its `mqtt.publish` waited 10 s for the gone client (and freezer is already stopped at that point, so frozen-time timers sit far in the future). The `ha` teardown now turns every automation off before unloading. Full `tests/ha`: 56.5 s → 39.5 s.
- `Clock.hold(seconds, refresh)`: moves in ≤ 60 s steps and republishes the live inputs before each (Victron/Shelly `expire_after` 120 s), as the devices do. `local_at`/`next_day`: forward-only moves to a wall-clock time (schedules, `today_at()`, midnight). `apply_baseline(skip=…)`: leave real entities unseeded.

**heating_pv_boost** (`tests/ha/test_heating_pv_boost.py`, section 5; Docker file deleted):
| Docker | Now | Notes |
|---|---|---|
| `test_return_temp_is_masked_while_making_hot_water` | `test_dhw_mask` (8 checks) | both sources (hcmode `water`, `hwc/Status`), exact 25 min delay_off (on at 24 min, off after 25); the valid return follows. The Docker 26 min startup jump is not needed (see the clock fixture) |
| `test_decision_stays_off_while_the_master_switch_is_off` | `test_slab_mode_wanted_delays` (8 checks) | same case (switch off, surplus 3000 W → off) plus new: delay_on 15 min, Schmitt hold between 500 and 1500 W, delay_off 20 min; every gate real (season via the 48h mean, PV window schedule at 10:00, ebusd online via ehp/Status, SOC). After the first data the sensor is `unknown` for 20 min (delay_off from no state), as after a restart |
| `test_last_run_measures_the_on_to_off_transition`, `test_last_run_ignores_hot_water_runs` | `test_last_run` (6 checks) | exact spans (Docker: 6.5…8.0 for 7 min); the DHW run keeps the previous value exactly (Docker: "not ≈ 30", because of leftovers); new: heating rolling into hot water reports the heating part |
| (item 3 seeded the two history_stats) | new `test_cycling_history_stats` | REAL runs/runtime/duty-cycle history_stats with `recorder_mock` and `async_wait_recording_done`; average run from them; a hot-water run is not counted |
| — | new `test_daily_meters_reset_at_midnight` | the utility meters' `cycle: daily` at local midnight |

Mutation checks (in place, restored with `git checkout`), each fails naming the step:
| Mutation | Failing check(s) |
|---|---|
| dhw delay_off 25 → 20 min | `hcmode heat: mask still held at 24 min`, `hwc off: … 24 min` |
| dhw `hwc_active` source dropped | `hwc on masks at once`, `hwc off: … 24 min` |
| slab delay_on 15 → 10 min | `switch on: 14 min, still within delay_on` |
| slab delay_off 20 → 15 min | `switch off: 19 min, still within delay_off` |
| slab master switch ignored | `switch off, 20 min later`, `switch on: 14 min…`, `switch off: charge ends…` |
| slab Schmitt: on-state uses the start threshold | `surplus between the thresholds holds the charge`, `switch off: 19 min…` |
| last run `/ 60` → `/ 30` | every last-run check (14.0 for 7 min, …) |
| heating-only sensor ignores hcmode `water` | history: runs 3, runtime 0.75; last run: hot-water checks |
| runs_today counts `off` | `no run today` (1), runs 3, average 10.0 |
| yield meter `cycle: weekly` | `after midnight` (9), `next day` |

**Victron** (`tests/ha/test_victron.py`, section "Accumulators driven by real minute ticks"; Docker file deleted). A tick = publish every input, sync, advance 60 s (exactly one `/1` boundary); every expectation is computed from the accumulator's state read just before the tick with the template's own arithmetic (`round(x + W/60000, 3)`), so all checks are exact. Nothing is seeded.
| Docker (11) | Now (7 tests) | Notes |
|---|---|---|
| `test_eta_accumulators_keep_pace_when_ac_pv_expired` | same name | two ticks, each checked exactly (Docker ±0.001); PV never published (= asleep) |
| `test_eta_accumulators_gate_on_both_signs` | same name | each of the three ticks checked on its own (Docker: only the total after the third) |
| `test_grid_export_energy_accumulates` | same name | exact 60 s step 1800 → 1000 W, first step from HA timestamps, ±0.6 Wh (Docker: 1800 → 1801 W relative to a session total, ±2 Wh); import total unchanged |
| `test_night_no_grid_energy_accumulates` | same name | batt_out exactly +0.025/tick (Docker: "> 0"), grid totals unchanged over two ticks |
| `test_conversion_loss_energy_accumulates` | same name | two ticks |
| `test_solar_yield_ac_total_captures_baseline_on_first_tick` (**skipped** in Docker), `…_applies_delta_once_baselined`, `…_counter_reset_clamped_to_zero`, `…_holds_on_source_unavailable` | `test_solar_yield_ac_total_counter_delta` | ONE chain on real ticks: capture → +0.5 → reset clamp → real 7-day expiry holds → new: the returning counter's whole gap is added on the next tick. **The skipped flake is deterministic in-process**: 40/40 alone and 20/20 in the file run (no harness, no session state). Its Docker symptom ("the second jump never re-fires the trigger") is UNPROVEN as a harness fault, but a similar in-process cause was found and fixed (tick skip, below) |
| `test_battery_energy_residual_bootstrap_before_baseline`, `…_uses_counter_delta_once_baselined` | `test_battery_energy_residual` | chain: bootstrap tick captures both baselines, next tick +1.2 kWh in (Docker seeded the baselines) |

Two in-process flakes found by the stability runs and fixed (harness, not config):
- **Minute tick skipped** (1 in ~60 ticks; seen as `tick 2: loss_energy 0.01, want 0.02`). CONFIRMED in `helpers/event.py` (`_TrackUTCTimeChange`): a `time_pattern` tick is scheduled at hh:mm:00 + a random 0.05-0.5 s, `async_fire_time_changed` fires what is due up to 0.5 s past the new time and patches "now" to that, and the listener reschedules from now + 1 s; if the tick fell in the first second of the move, the next minute's slot is already behind "now + 1 s" and is skipped. Fix: `Clock.align()` moves to half past a minute before ticking (`_Ticker.start`), so every tick is mid-move. After: 0 skips in 210 + 220 runs.
- **Test MQTT client dropped after the 7-day move** (2 in 60 runs of the counter-delta test: "Message publish failed: The client is not currently connected"). HYPOTHESIS (same mechanism as HA's client above, not traced for the test client): its paho keep-alive runs on the frozen monotonic, and a move before the PINGRESP was read counts as a timeout. Fix: the test client connects with `keepalive=0` (local real-time broker). After: 40/40 alone, 220/220 for the whole file.

Stability: `tests/ha/test_victron.py --count=20 -n 4`: 220/220, 4m13s.

Mutation checks (in place, restored): ac_out gate without `ac > 0` → `inverting current while AC charges: ac_out -0.01`; loss energy `/60000` → `/6000` → both loss ticks; solar total clamp removed → steps 3-5 (-90.0); export integration `trapezoidal` → `left` → 0.030 vs 0.0233; battery residual AC-PV counter term dropped → `2. counter delta: batt_in 1.0, want 1.2`; batt_out halved → night ticks (and the battery spike test).

**airflow** (`tests/ha/test_airflow.py`, section "Item 4"; Docker `tests/test_airflow.py` deleted). Nothing of the decision chain is seeded: the five indicators (trigger-based, delay_on/off 10 min, `this.state` hysteresis) are driven through the seeded 5-min filter outputs (no real source here; their ComfoConnect sources are untouched, so the filters never overwrite the seeds) and the clock; the season is the real indicator via its 48h mean; workday and both boost schedules are the real helpers (clock moved to a working Wednesday 07:01 and to the next weekday public holiday, from the `holidays` package); the automations run on real triggers with their real conditions. Effects = calls recorded by the stubbed ComfoConnect/phone actions, attributed to the automation that made them by the context of its `automation_triggered` event, so the climate entity's own calls do not count. Each looping table resets to a reference scenario whose every value is past each hysteresis' release edge, and checks the reset.

New harness pieces (in the test module): `airflow_ha` (baseline before the freeze, real entities skipped, every automation except the two airflow ones off: the pergola cover response waits on timers longer than a move and hung `async_block_till_done`, seen); a **device echo** for the four ComfoConnect stubs (a write sets the entity state, as the integration reports it: without it every follow-up run, e.g. the decision writing state and attributes separately, repeated the write; with it the controller's own follow-ups run as in production, e.g. route-to-auto → `auto_mode_on` → medium); `_runs` counts `automation_triggered` events (on the frozen clock two runs share one `last_triggered`).

Mapping, Docker (65) → in-process:
| Docker | Now | Notes |
|---|---|---|
| controller S1 (6), S2 (3), medium preset (4), away preset (2), consistency (4), `heat_protection_low_wins_over_free_cooling_bump` = 20 | `test_controller`: 20 cases + 4 new | real `decision_changed` edge (automatic control off → on), exact call lists (Docker: trace only for every writing case, no-op cases by unchanged stub state). New: device reports another profile → re-asserted; away ends → low applied; route-to-auto from manual low; schedule drops preset to low → re-bumped. The auto-disabled cases now fire a real trigger and check the controller did not run |
| boost (5), `drying_boost_away_suppressed`, edge tests (4) = 10 | `test_drying_boost` (8 cases), `test_drying_boost_unavailable_to_boost_does_not_fire` (strict xfail, **config bug**, below) | `starts_when_needed` + `real_edge_into_boost_fires` → one case; exact calls of the boost automation (60 min, ON, notification; adoption without notification; stop; seamless re-arm) |
| `test_drying_boost_config_edge_only` | moved unchanged (static, no HA) | |
| drying sensor (3) + drying render (3) | `test_drying_needed` (one forward sequence, 10 checks) | real schedules/workday; new: the 07:00 window edge, hysteresis 0.3. **Dropped:** `drying_low_moisture_guard_prevents_boost`: the guard is no longer in the config (flush gates the guard: `new_low_needed_gated_off_by_flush`) |
| dew_max (4) | `test_indicator[free_cooling]` 4 cases (1 new) | `dew_max_formula_value_at_baseline` dropped as a duplicate of `test_dew_point_thresholds` (literal 12.08); new: exact gate edge 12.08/12.09, exact delay_on/off |
| low-needed (5) | `test_indicator[moisture_low]` 6 cases (1 new) | real Schmitt via `this.state`; combined low intent checked |
| flush (10) | `test_indicator[flush]` 11 cases | hysteresis split in from-off / from-on; season guard with its delay_off; unavailable at once (the Docker test leaned on an earlier test's clock move) |
| heat (2 of 3) | `test_indicator[heat_low]` 3 cases (1 new) | `heat_ventilation_low_needed_off_…` leaned on an earlier test's clock move; `ventilation_low_needed_derives_from_heat` now with the real heat low |
| hvac_action (5) | `test_hvac_action` 6 cases (2 new) | real decision, controller off; **dropped** `hvac_action_template_matches_mirror` (a text check of the copy; no copy left) |
| reload (2) | `test_reload_recovery` | real `template.reload` + the forced-unknown self-trigger |

Drift between the Docker copies and the config (CONFIRMED by the real sensors here):
- low-needed copy had no indoor-dew gate: `relative_fallback_fires_below_dew_threshold` (outdoor 13, indoor 10, max 65 → copy ON) is OFF in the real sensor. The `outdoor_dew >= indoor_dew` term can never decide alone (outdoor ≥ indoor ≥ edge implies outdoor ≥ edge), so the YAML comment "fallback … kicks in when neither boundary is met" describes a dead branch (comment issue, not a behaviour bug).
- drying copy read the raw `sensor.wheatherstation_outdoor_temperature` (known), had the removed `low_active` guard and no 0.3 hysteresis; `drying_non_workday_schedule_applies_on_holiday` asserted "off because of delay_on", but the sensor has no delay: it passed only because the template reads the 5-min filter (baseline 21.5), not the seeded raw station. In the real sensor the holiday case is ON from 09:00.
- flush copy matched the config.

Config findings (record only, not fixed; no issue opened):
1. **Input flap restarts a running drying boost (bug, #153).** CONFIRMED (state trace): a flush input going unavailable makes `airflow_humidity_flush_needed` unavailable; `airflow_humidity_drying_needed` (no availability, reads flush via `is_state`) drops to off at once; when the input returns, flush is back first, the decision passes `moisture_flush_cooling/medium`, then drying turns on → `medium → boost` is a real `boost_decided` edge: boost time 60 + ON re-sent (a running timer reset; a boost the user stopped would restart). Contradicts the note's rule "decision unavailable → boost is NOT an edge". Strict xfail test pins the intended behaviour.
2. **climate_template echoes writes (#154).** CONFIRMED in `custom_components/climate_template/climate.py` (`_update_hvac_mode` → `async_set_hvac_mode` → `set_hvac_mode` script): every change of `hvac_mode_template`'s result runs the `set_hvac_mode` action, e.g. switching automatic control off writes the device's current profile back (`select.select_option`) and turns the input_boolean off again; a profile change while automatic control is off is written back too. Redundant ComfoConnect writes; effect on the device UNPROVEN.
3. **template.reload logs a TemplateError (#155)** for `sensor.solar_yield_watts` (packages/victron.yaml): during the reload the η sensor is briefly unavailable and `| float` has no default (VIC-10 assumes η is always numeric). Tolerated by name in `test_reload_recovery` (`allow_log`).
4. **Reload restores, the comments say it does not (#155).** CONFIRMED: after a real `template.reload` the trigger-based indicators come back with their previous state at once (unavailable → previous value), not `unknown` as the airflow YAML comments state; the `to: "unknown"` self-triggers still work (forced `unknown` → recomputed at once).

Mutation checks (in place, restored with `git checkout`), each fails naming the case(s):
| Mutation | Failing check(s) |
|---|---|
| free cooling delay_on 10 → 5 min | `free_cooling_dew_max_passes_low_outdoor_dew step 1 at 599 s` |
| moisture low: on-state keeps the max edge | `low_needed_stays_on_above_target_dew step 2` |
| heat low without Schmitt | `ventilation_low_needed_derives_from_heat step 2`, `step 3 at 599 s` |
| flush without season guard | `flush_season_guard_heating_branch1_only step 2` |
| drying without hysteresis | `station 21.6 from on` |
| controller Away guard removed | both away cases, `new_away_ended_…` |
| controller low-branch idempotency removed | `moisture_ventilation_low_when_needed` (3× writes), `heat_protection_…`, `controller_low_idempotent_no_write`, `new_away_ended_…` |
| controller medium without "preset low" | both free-cooling cases, `new_schedule_low_preset_is_rebumped` |
| boost Away condition removed | `drying_boost_away_suppressed`, `…_away_unknown_to_off_fires` |
| boost `from:` without `off` | every start case, and `test_drying_boost_config_edge_only` |
| re-arm without the decision condition | `drying_boost_countdown_during_manual_boost_no_error step 3` |
| hvac_action drying only for flush-cooling | `hvac_action_drying_survives_boost_blip` |
| flush `to: unknown` self-trigger removed | `test_reload_recovery` (stays unknown) |

Case independence: controller, boost and the four indicator tables also pass with their case order reversed (temporary module, not committed).

Stability and time (owner rule: 20x on changed tests, full suite 1x). `--count=20 -n 4` on the three changed files after the last harness change: `test_heating_pv_boost.py` 180/180, `test_victron.py` 220/220, `test_airflow.py` 260/260 + 20 strict xfails (the boost bug), 11m00s wall. Full `tests/ha` 1x: 43 passed + 1 xfailed, 39.5 s (`-n 4`). Slowest calls: slab decision 3.9 s, controller 3.9 s, history_stats 3.5 s, last run 3.0 s, decision table 2.4 s; setup 2.3-3.5 s per test (HA boot).

CI: `.github/workflows/ha_check.yaml` "remaining tests" step now collects nothing (exit 5); treated as success until Step 4 replaces the workflow. Docker suite: 18 tests (pergola), collects.

### Step 2 results, item 5 (pergola)
`tests/ha/test_pergola.py` (14 tests incl. 6 parametrized scenarios); Docker `tests/test_pergola.py` deleted. Real `sun` integration at the configured location on the moved clock (`load_repo_config` now loads it as a config entry AFTER the package domains, else its sensor/binary_sensor forwarding hides the YAML platforms; `sun.sun` is no longer seeded, not in `tests/baseline.py` either). All automations run through real triggers and conditions; no `automation.trigger`. Effects are the recorded cover/Loxone calls, attributed to the automation by the context of its `automation_triggered` event. Weather station, Somfy covers and lock sensors are seeded (no integration); Victron PV/load go over the real broker; the season is the real indicator driven through its 48h mean.

Harness findings (each CONFIRMED by a failing then passing test):
- **500 ms settle delay vs frozen clock.** The cover response's `delay: 500 ms` never comes due on the frozen clock and `async_block_till_done` waits forever (the item-4 airflow hang). `_settle` runs HA until idle and moves the clock to a pending script delay only when it is at most 0.6 s away. The first value 1.0 s was wrong: a drain delay with 1 s left (`hold(29)` of the 30 s) was reached early, one step of the drain came a second too soon.
- **A scenario that fails while the post-rain drain waits** left the drain running on the frozen clock and hung HA's shutdown for minutes (mutation run: no result in 280 s). The `pergola_env` fixture now stops `script.pergola_post_rain_recovery` at teardown.
- A test must not end with a running drain either (same hang): the last scenario step is never one that starts it.

Mapping, Docker (18) → in-process:
| Docker | Now | Notes |
|---|---|---|
| `test_baseline_cooling_optimized`, `test_cooling_unoptimized`, `test_heating_mode` | `test_cover_formulas` | real sun positions chosen per branch of the PG-4 formulas (floor_90, max_tilt, moe_plus_db, flip, cap, lower bound, heating floor/follow), expected angles from the independent port `_Ref` (checked against the PG-4.8 table in `test_reference_model`); HA's sensors AND the sent tilt are compared. Docker seeded A_eff 67.9 and `sun.sun` |
| (new) | `test_deadbands` | tilt deadband per mode against the echoed cover position |
| `test_automation_disabled` | scenario `master_switch` | master off: no move, sensors keep computing, last angle kept; on again: next transition moves |
| `test_not_enough_sun`, `test_no_sun_behind_house`, `test_sun_down_state`, state part of `test_pv_power_zero_at_night_when_mppt_stale` | `test_sun_rules` (9 cases) | rules 5-9 on real days (March, June, December); shading threshold 512 × sin(el) × 0.9 checked ±30 W/m² against the real elevation; UV ≥ 3 and PV alone; azimuth window edge and min elevation edge on real mornings; steady `/5` tick calls |
| `test_frost_entry`, `test_frost_recovery` | scenario `frost` | entry tested at 2.0 °C (below the 2.5 threshold but above a lowered one), hysteresis 2.8, exit 3.5 |
| `test_post_rain_recovery` | scenario `frost_exit_with_hourly_rain_drains` | exact drain timing: 30 s, 8° (tilt 12) 5 min, 15° (tilt 18) 5 min, 30 min drying, then evaluate; Docker checked only the step sensor |
| `test_rain_starts` | scenario `rain_rate` | rain, hold, rain_stopped, short drain without the 8° step and the drying wait |
| `test_rain_lock_from_cover`, `test_rain_with_user_originator` | scenario `cover_rain_lock_then_user` | lock responders force a report (`stop_cover_tilt`) per originator change |
| `test_user_override_left` | scenario `user_override` | see finding 1 |
| wrapper part of `test_pv_power_zero_at_night_when_mppt_stale` | `test_pv_power_wrapper` | real `expire_after: 120`, GX/MPPT quiet combinations |
| `test_indicator_heating_season_…_on`, `…_cooling_season_…_off`, `…_unavailable_keeps_…` | `test_season_sync` | 7 real indicator transitions via the 48h mean, unavailable leaves it; Docker used `automation.trigger` |
| (new) | `test_watchdogs_responders_loxone`, `test_automation_set_is_complete`, `test_reference_model` | watchdogs, lock responders, Loxone mirror; guard that every automation is covered; reference model anchors |

Runtime: `tests/ha/test_pergola.py` 14 tests, ~27-34 s with `-n 4` (94 s serial, reversed order). Full `tests/ha`: 57 passed + 1 strict xfail, 59 s.

Stability: `--count=20 -n 4` on the file: 280/280, 6m43s. Reversed test order (serial, `-p no:randomly`): 14 passed.

Fix after review: `test_watchdogs_responders_loxone` then failed 20/20 in a later session (and passed in others). Cause: before `not_enough_sun` is reached, the cover response may or may not move the covers (the 12:05/12:10 ticks race the state change; the order differs between HA boots). When it moved them at 12:10:30, the 12:15:30 tick saw an update 4 min 59.5 s old and the watchdog rightly stayed silent. The test now reports the covers (tilt 73) at 12:11:30, after the state is reached, and counts the watchdog window from there (12:15 silent, 12:20 both stop). After the fix: 20/20 on the test, 280/280 on the file, passes with the boot time faked to three dates (libfaketime), and both mutations (window 5 → 10 min, `sun_automatik_cooling` dropped from the suppression list) fail it.

Mutation checks (in place on `packages/pergola.yaml`, restored with `git checkout`, `git diff packages/` empty), each fails:
| Mutation | Failing test |
|---|---|
| frost entry `below: 2.5` → 1.5 | `test_protected_states[frost]` (first version passed with a -1.5 °C seed; entry now tested at 2.0) |
| shining threshold `* sensitivity` → `* sensitivity * 1.5` | `test_sun_rules` |
| rain entry without the links `!= 'user'` guard | `test_protected_states[cover_rain_lock_then_user]` |
| rain → user_override transition writes `rain` | `test_protected_states[cover_rain_lock_then_user]` |
| drain first delay 30 → 45 s | `[frost_exit_with_hourly_rain_drains]`, `[rain_rate]` |
| shining `delay_on` 1 → 3 min | `test_cover_formulas` |
| 8° drain angle → 10° | `[frost_exit_with_hourly_rain_drains]` |

Config findings (record only, not fixed; no issue opened):
1. **User-lock clear while it rains goes straight to `rain`.** CONFIRMED (state trace): the state manager's rain entry (rule 2) comes before the user_override exit rule and only excludes `frost`/`rain`, so with `rain_rate > 0` and both locks `unknown` the state goes user_override → rain in the same run, `exit_to_normal` never runs. The comments at rule 2 → user_override (`packages/pergola.yaml` ~985-997) say the exit runs first and rain re-engages on the next trigger. Behaviour is sensible; the comment is stale. The test asserts the code.
2. The `tests/conftest.py` Docker fixtures `midday_sun`/`low_elevation_sun` and the "year-jump" explanation in `ha_check.yaml` are gone with the Docker pergola tests; `packages/notes/pergola.md` "Tests" section still describes `tests/test_pergola.py` (stale; notes are under `.claude/`-governed knowledge work, not touched here).

Leftover harness bits: removed `midday_sun`/`low_elevation_sun` (unused). Still present, unused now: the Docker `tests/conftest.py` (baseline fixtures, `wait_for_state` helpers if any), `tests/baseline.py` REST seeding (shared with `tests/ha`), `requirements.txt` Docker harness deps, the `ha_check.yaml` "remaining tests" step (exit 5 accepted) and `check_config` step: all for Step 4.

### Step 3 results (`tests/e2e/`)
Run: `pytest -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e -p no:homeassistant` (needs Docker, `mosquitto` on the host, `tests/e2e/requirements.txt`). `--confcutdir` keeps the old Docker-harness `tests/conftest.py` out until Step 4 deletes it. `pyproject.toml` `norecursedirs` gained `e2e`, else the old `pytest tests/` CI step would collect (and try to run) the new layer.

**Files.** `tests/e2e/{__init__.py, conftest.py, ha_client.py, stage.py, pytest.ini, requirements.txt, test_boot.py, test_check_config.py, test_restart.py, test_zz_log_hygiene.py}`; `.gitignore` (`tests/e2e/.artifacts/`); `pyproject.toml` (norecursedirs).
- `conftest.py`: marker `needs_real_ha("<reason>")`, closed `REAL_HA_REASONS`, enforced in `pytest_collection_modifyitems`; a session mosquitto (free port, 127.0.0.1) plus a paho publisher; ONE session container (`docker run --network host` of the image from the Dockerfile `FROM` line, read from the file; `E2E_IMAGE` overrides).
- `ha_client.py`: own client (`wait_ready`, `wait_running`, `onboard`, flows, websocket, `wait_for`, `wait_stable`, `assert_entity_state`); a timeout on every call; deadline polling; no fixed sleeps.
- `stage.py`: `stage(dir)` and `check_config(dir)`; CLI `python -m tests.e2e.stage <dir> [--check-config]`. Shared by the fixture, the check-config test and the future CI step.

**Reasons used.** `full-boot`, `check-config`, `restart-persistence`, `runtime-logs`. **Dropped: `http-surface`** (nothing needs it: `/api/template` is covered in-process by `tests/ha/test_templates.py`; REST and websocket are only the driver here, not the subject).

**Tests (5).** Each module docstring starts with "Needs a real HA because: …".
| Test | Reason | Checks |
|---|---|---|
| `test_boot.py::test_every_package_registers_its_entities` | full-boot | every `unique_id` any `packages/*.yaml` declares is in the real entity registry (utility meters as `<id>_single_tariff`); derived from the YAML, so a new entity is covered without editing the test |
| `test_boot.py::test_integrations_the_config_needs_are_alive` | full-boot | state RUNNING; `climate.airflow_climate` (HACS `climate_template`) exists; MQTT and workday entries `loaded`; the package integration domains are in `components`; `binary_sensor.workday` exists |
| `test_check_config.py::test_staged_config_passes_check_config` | check-config | HA's `check_config` script on `stage()` output in a throw-away container |
| `test_restart.py::test_totals_survive_a_real_restart` | restart-persistence | `utility_meter` `heating_electricity_daily` (Shelly Wh over real MQTT: 1000 kWh then +1.5 → `1.5`) and Riemann `integration` `victron_grid_energy_import` (three phases over MQTT) keep their exact value over `docker stop` + `start` |
| `test_zz_log_hygiene.py::test_no_errors_or_deprecations_in_the_session_log` | runtime-logs | every ERROR/CRITICAL, any deprecation, any traceback in the log from the clean boot on fails, except two commented lists (`EXTERNAL_NOISE`, `KNOWN_CONFIG_BUGS`); also asserts the log spans at least two boots |

**Design decisions (each verified by running).**
- **Bootstrap boot, then a clean boot.** A fresh HA has no MQTT entry, so its first boot logs ERROR on every `homeassistant: start` publish (`ebusd poll registration`, `Victron Bridge Initial Full Publish`: "make sure MQTT is set up"). The `session` fixture therefore boots, onboards, creates the MQTT entry (real flow, host mosquitto) and the workday entry (real flow, AT), renames entity ids, then restarts the container; the log offset taken at that stop marks the end of the bootstrap, and only the log after it is judged. In the clean boot those publishes succeed, so MQTT errors are NOT ignored, they do not occur. Cost: one extra boot (about 25 s).
- **MQTT is configured through the config flow**, not a pre-seeded `.storage` file (format-bound). Flow data (HA 2026.10.1): `broker`, `port`, `protocol`, `other_settings: {set_client_cert: false, set_ca_cert: "off"}`.
- **Workday is a config entry (flow), not the YAML fixture** `tests/custom_components.yaml` `ha_yaml_config`: HA at the pin rejects the YAML platform (see the comment in `tests/ha/conftest.py` `stage_config`; check_config of the staged config also passes without it); that fixture is dead and CI's `packages/ha_ci_fixtures.yaml` is no longer written by `stage.py`.
- **Production-like entity ids** (`PRODUCTION_IDS` in conftest, through the real registry API, as a user renames in the UI): `weather.forecast_home`→`weather.home`, `binary_sensor.workday_sensor_at`→`binary_sensor.workday`, the three Victron grid phases and the Shelly heating energy sensor (fresh registry ids differ, #146 class). Without them the config's templates have no source.
- **Custom component**: `stage.py` copies `custom_components/<domain>` from the repo if present (CI's download step, a developer checkout), else downloads the tarball of `tests/custom_components.yaml` itself. The download path could not run here (the sandbox proxy answers 403 for github.com archives); its extraction logic was run against a local tarball.
- **Riemann restore test uses absurd power (100 MW per phase), then 0 W.** The integral grows by whole kWh in the sub-second between publishes (no waiting for real time); the closing 0 W makes the sum final, so after the restart (restored source 0 W) any difference is a restore failure. First version kept the power on: the sum kept integrating after the restart (412 → 720) and the assertion was both wrong and weak.
- **`wait_stable`** exists for exactly that value that settles after a burst.
- The container logs at WARNING and above (HA default), so INFO lines are not in the log; the "right log" proof counts the per-boot `climate_template` custom-integration warning.

**Runtime (this sandbox, container already pulled).** Whole `tests/e2e`: 83 s, 79 s, 91 s (3 runs, 5/5 green each). Parts: bootstrap fixture about 50 s (two HA boots, onboarding), `test_boot` +2 s, check_config about 10 s, restart test about 30 s. Not 20×; per the task 3×.

Review re-run (Python 3.14 venv from `tests/e2e/requirements.txt`): the first run failed the log test on `radio_browser ... Setup of config entry 'Radio Browser' ... cancelled`. Onboarding creates that entry, its API is unreachable here, and a restart that lands during its setup retry logs the cancel as ERROR; timing decides whether a run sees it. Added to `EXTERNAL_NOISE`, allowed only together with the "Cannot connect to host ...radio-browser.info" cause. Then 3/3 green (88-89 s), one of them with the cancel present. Marker enforcement re-checked: unmarked and unknown reason both fail collection.

**What ran for real vs. what did not.**
- Ran for real: Docker daemon (started by hand with `dockerd`, it was not running), the pinned image `ghcr.io/home-assistant/home-assistant:2026.10.1` pulled through the proxy, host mosquitto 2.0.18, all five tests, 3× green.
- Not verified: the GitHub Actions runner (apt `mosquitto`, internet access); stage.py's tarball download from GitHub (403 in the sandbox; extraction run offline); behaviour with a reachable Met.no (here it is not: TLS interception, so `weather.home` never exists and the `EXTERNAL_NOISE` entries for Met.no and its follow-ups were used; online they are simply unused); the beta channel; Python 3.14 for the e2e venv (the sandbox run used Python 3.13 with the pinned requirements).

**Marker enforcement.** A test without the marker, and one with `needs_real_ha("nonsense")`, each fail at collection with a `UsageError` naming the test and the allowed reasons (exit code 4); the five real tests collect. (Throw-away file, deleted.)

**Mutation checks** (each restored, `git diff packages/ automations.yaml` empty):
| Mutation | Result |
|---|---|
| `packages/victron.yaml`: `platform: integration` → `integratio` | `test_check_config` fails (check_config output); `test_boot` fails: `declared in packages but not registered by the real boot: {'victron.yaml': ['victron_grid_energy_import']}`; the other tests unaffected |
| `automations.yaml`: a `homeassistant start` automation calling `notify.does_not_exist` | only `test_zz_log_hygiene` fails, naming the ERROR twice (clean boot and restart) |
| harness: delete `.storage/core.restore_state` between stop and start (no restore) | `test_totals_survive_a_real_restart` fails: the meter is `unknown` |

**In-process suite after the change:** 57 passed, 1 xfailed (66 s). `ci-local.sh`: all local checks passed. `git ls-files --eol`: no CRLF.



**Config findings from Step 3** (since tracked in issues or the package notes):
1. #147 confirmed in a real boot: `Received invalid sensor state: unknown for entity sensor.victron_solar_yield_dc_baseline_kwh` (and `victron_ac_pv_energy_baseline_kwh`) logged as ERROR; carried in `KNOWN_CONFIG_BUGS` of the hygiene test, delete the entry with the fix.
2. The config reads two ids that exist only after a manual rename on a fresh install (#146 class): `binary_sensor.workday` (the workday flow creates `binary_sensor.workday_sensor_at`) and `weather.home` (Met.no creates `weather.forecast_home`); likewise the MQTT sensors listed in `PRODUCTION_IDS`.
3. A fresh install's first boot logs ERROR for the `homeassistant: start` publishes (ebusd poll registration, Victron initial full publish) until the MQTT entry exists; harmless in production, which is why the e2e log is judged from the clean boot on.
4. With the external integrations absent (ComfoConnect, weather station, Somfy) the clean boot logs WARNINGs only: `numeric_state` triggers for `number.comfoconnect_pro_boost_time` and `sensor.wheatherstation_outdoor_temperature` ("unknown entity"), and the "Inactivity Watchdog" conditions. Not judged (WARNING, not deprecation).
5. Stale: the `workday` YAML fixture in `tests/custom_components.yaml` / `ha_check.yaml` (see Step 4 item 4).



### Step 4 results (CI and local runs)

**Mosquitto is a pinned dependency like HA (owner requirement).** Researched from source and the real image:
- Latest release of the official Home Assistant Mosquitto app (add-on, `home-assistant/addons`, `mosquitto/`): **7.1.3** (`config.yaml`, CHANGELOG top). It ships **mosquitto 2.1.2** (since 7.0.0; 6.x shipped 2.0.x). CONFIRMED by running the image: `mosquitto version 2.1.2`.
- Install method: NOT apk or a distribution package. The app's Dockerfile `git clone -b v${MOSQUITTO_VERSION}` (ARG, 2.1.2) of eclipse/mosquitto plus one websocket patch, `make`, `make install` into `/usr/local/sbin`, on `debian:trixie-slim` (base `trixie-2026.10.1`). The image is `ghcr.io/home-assistant/app-mosquitto:<version>` (multi-arch, also `amd64-app-mosquitto`); the old `{arch}-addon-mosquitto` name is denied by the registry.
- The sandbox's `apt` mosquitto is 2.0.18, so before this step the tests ran on a different broker than HA's. The whole in-process suite and the e2e suite pass on 2.1.2 (no test change needed).

**Options measured** (start to first accepted TCP connection, 15 starts, median):
| Option | Per-test start | Exact version | Verdict |
|---|---|---|---|
| distro `apt` mosquitto | 6 ms | no (2.0.18 here, runner differs) | rejected |
| binary extracted from the app image (`docker cp`) + wrapper | 6 ms | yes, the very binary | **chosen** |
| `docker run` of the app image per test (`--network host`) | 154 ms start, plus kill/rm | yes | rejected: 25x the cost, 57 tests x 0.15 s+ |
| job inside a container of the app image / compile the tag on the runner | n/a | yes | rejected: no Node in the image for the actions / 30+ s build and a cache to maintain |
The binary needs glibc <= 2.34 and `libcjson.so.1`; libssl/libz come from the host (Ubuntu 24.04 has them). `libcjson` is copied out of the image next to the binary and found through `LD_LIBRARY_PATH` (checked with `LD_DEBUG=libs`).

**Design (single source, guard, bump).**
- `.github/ha-versions/mosquitto/Dockerfile`: `FROM ghcr.io/home-assistant/app-mosquitto:7.1.3` (Dependabot `docker` entry, weekly) and, next to it, the recorded mapping line `# mosquitto-in-app: 7.1.3 = 2.1.2`. Dependabot only bumps the FROM line, so the guard fails with the exact line to add until the map is updated in the same PR.
- `.github/scripts/install-mosquitto.sh [dest]`: reads the FROM line, pulls, copies `/usr/local/sbin/mosquitto` and libcjson to `.cache/mosquitto` (git-ignored), writes a `bin/mosquitto` wrapper (`exec`, so `Popen.kill()` hits the broker). Linux only; macOS developers `brew install` that version.
- `tests/ha/test_versions.py::test_mosquitto_is_the_version_of_the_pinned_ha_app`: the first `mosquitto` on PATH (what `Broker` starts) must report the version the map gives for the pinned app. FAILS (no skip) when missing, wrong, or unmapped; the message names the fix.
- Mutation checks (all restored): FROM bumped to 7.1.4 -> "records no mosquitto version for it: add the line ..."; map changed to 2.0.22 -> "the tests start mosquitto 2.1.2 ..., but the pinned app 7.1.3 ships 2.0.22"; PATH without the extracted copy (system 2.0.18) -> mismatch message.
- Both workflows run the script and append `.cache/mosquitto/bin` to `$GITHUB_PATH`. e2e itself has no version assertion (only the in-process job runs the guard); both jobs use the same script, so they get the same binary.

**Python single source.** New `.github/ha-versions/ha-python.txt` (`3.14`), read by `setup-python` (`python-version-file`), `ci-local.sh`. Not Dependabot-bumped on purpose (`.github/ha-versions/python` is 3.15 for the YAML tooling and Dependabot would push this past HA). New guard `test_ci_python_is_the_python_home_assistant_requires` fails when the file differs from HA's `REQUIRED_PYTHON_VER` major.minor (mutation-checked with 3.15).

**Custom components: one implementation.** `.github/scripts/install_custom_components.py` (CLI `[config-dir] [--force]`, function `install(target, repo)`): `ref`/`repository`/`domain` honoured as before; copies the repo's `custom_components/<domain>` if present, else downloads the branch tarball (60 s timeout). Used by `tests.yaml` (once, into the checkout, because `tests/ha/conftest.py` copies `custom_components/` from the repo), `ci-local.sh`, and `tests/e2e/stage.py` (imports it by path). The duplicate `_install_custom_components` in `stage.py` and the inline Python of `ha_check.yaml` are deleted. `ha_yaml_config` dropped from `tests/custom_components.yaml`, header fixed.

**Workflows.**
- `tests.yaml` (job "In-process tests (tests/ha)"): checkout (depth 2), change detection (`.github/test-paths`), setup-python from `ha-python.txt` with pip cache on `requirements_test.txt`, install, pinned mosquitto, custom components, `pytest -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . tests/ha -n auto --timeout=60`. `pytest-timeout`, xdist and the annotate-failures plugin come with PHACC (no requirements change); the ini already sets `timeout_func_only`.
- `e2e.yaml` (job "e2e (pinned)", nightly also "e2e (beta)" with `E2E_IMAGE=...:beta`, `continue-on-error`): background image pull (FROM line), setup-python from `ha-python.txt` (3.14, not 3.15: wheels of the pinned requirements; also what the sandbox run used), `tests/e2e/requirements.txt`, pinned mosquitto, barrier, `pytest -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e -p no:homeassistant --timeout=300 --timeout-method=thread`, upload `tests/e2e/.artifacts/` on failure. No separate check_config step: `test_check_config.py` runs HA's check_config on the same staging (a separate step would repeat ~10 s). The nightly beta channel was trivial (copied from hrds), so it is in.
- Both: triggers `pull_request` + `push: [master]` + `workflow_dispatch`, concurrency group with cancel-in-progress on PRs, `permissions: contents: read`, actions pinned by major tag like `yaml-lint.yml` (`checkout@v7`, `setup-python@v7`, `upload-artifact@v7`). `.github/test-paths` lists what triggers tests (config files and dirs, `tests/`, `requirements_test.txt`, `.github/ha-versions/`, the installers, the workflow files).
- **Branch protection:** the old required check "Config Check · Template Validation · Automation Tests" no longer exists. Required checks must be changed to "In-process tests (tests/ha)" and "e2e (pinned)" (owner action in the repo settings).

**Removed.** `.github/workflows/ha_check.yaml` (image prefetch, `:stable` retag, AppDaemon prefetch, sed location edit, secrets copy, custom-component step, remaining-tests step, PR-comment and summary steps; nothing in it was left that another workflow lacks: yaml lint is in `yaml-lint.yml`, check_config in e2e). `tests/conftest.py` (Docker-harness fixtures, nothing used it). `pyproject.toml` (only the harness pytest config: `norecursedirs`, `timeout_func_only`; each layer has its own ini). Harness pin, `pytest-timeout` and annotate plugin from `.github/workflows/requirements.txt` (now `pyyaml`, plus `requests` for the dead `validate_templates.py`). Dependabot comment for that file.

**Local.** `ci-local.sh` now builds `.venv-test` (Python from `ha-python.txt`; `uv pip` if the venv has no pip), installs `requirements_test.txt`, runs the shared custom-component installer, puts `.cache/mosquitto/bin` on PATH, runs `install-mosquitto.sh` when the version is wrong (Linux + Docker), then the `tests/ha` suite. Missing Python 3.14 -> that step is SKIPPED and listed under "Skipped (NOT checked)"; wrong mosquitto -> the guard test FAILS. `--e2e` (opt-in, Docker) creates `.venv-e2e` and runs the real-HA layer. `.yamllint.yaml` now ignores `.venv*`/`.cache` (yamllint was scanning HA's own YAML in `.venv-test`).

**Ran locally (this sandbox, Python 3.14, mosquitto 2.1.2 from the app image, Docker started by hand):**
- `tests/ha`: 59 passed, 1 xfailed (57 + 2 new guards) three times: direct 67 s, via `ci-local.sh` 62 s and 64 s (`-n auto`, 4 cores).
- `tests/e2e`: 5 passed, 121 s (one run through `ci-local.sh --e2e`, image already pulled; earlier Step 3 runs took 80-90 s).
- `ci-local.sh`: all local checks passed. `actionlint` 1.7.7 on both workflows: clean. `git ls-files --eol`: no CRLF.

**Not verified (cannot run GitHub Actions here):** the workflows themselves; the runner's Docker pull of the app image and `install-mosquitto.sh` on a host without `libcjson` (here the system had it; `LD_DEBUG` shows the copied one is found first); `setup-python` reading `python-version-file` from a plain `3.14` file and the `exclude:` matrix expression for the beta channel (both copied from documented behaviour / hrds); the climate_template download in CI (`--force` path; 403 from the sandbox proxy); the nightly beta run; required-check names; wall times on the runner.

**First GitHub runs (PR #149).** The PR first conflicted with master, so no `pull_request` workflow ran; after merging master (`a160277`) both started. In-process: green, 3m20s. e2e: red on the log test, twice `habluetooth.manager` ERROR "Missing required permissions for Bluetooth management" (the runner has a Bluetooth stack, the container has no NET_ADMIN/NET_RAW): added to `EXTERNAL_NOISE`. The failure upload found nothing because `upload-artifact` skips dot-directories: `include-hidden-files: true`. On `0b44150` both green: e2e 1m45s, in-process 3m12s. So the runner path works: app-image pull and binary copy for mosquitto, `python-version-file`, the climate_template download (no `custom_components/` in the checkout; the boot test found `climate.airflow_climate`), and the e2e boot on a runner with internet. Still unverified: the nightly beta run.

**Findings, not fixed:**
1. FIXED after Step 5: ~3300 `sqlalchemy.engine` INFO lines per run. Root cause: PHACC's `plugins.py` (lines 157-158, import time) calls `logging.basicConfig(level=INFO)` (stderr root handler) and sets `sqlalchemy.engine` to INFO; `-p no:logging` never helped. `tests/ha/conftest.py` sets that one logger back to WARNING; the count is now 0.
2. FIXED after Step 5: `.github/scripts/validate_templates.py` (dead since the template test moved in-process) deleted, with its only dependency `requests` in the YAML tooling.
3. Knowledge files still describe the Docker harness: `.claude/skills/ha-test-harness/SKILL.md` (lines 40, 41, 45), `packages/notes/energy.md:38`, `.claude/rules/tests.md` (`pyproject.toml` in its `paths:`): Step 5.
4. FIXED after Step 5: README's yaml-lint section rewritten to match `yaml-lint.yml` (it checks, it does not auto-commit).



### Step 5 results (knowledge for the two test layers)
CLAUDE.md "Local CI checks" and the version gate were rewritten first (own commit; 97 lines).

Moved, one home per fact:
- `.claude/skills/ha-test-harness/SKILL.md` rewritten for `tests/ha` and `tests/e2e` (where a test goes, running, pins and guards, fixtures and gotchas, e2e design, quality rules: mutation check, 20x on changed tests, no retry plugins). The Docker-harness entries (libfaketime, `jump_to_next`, REST seeding, harness HTTP hangs, `pyproject.toml` timeouts, test ordering, per-file CI steps) are gone with the harness; the generic `set_state` entries of `ha-templates` and `ha-energy-metering` stay (they describe HA, and `hass.states.async_set` behaves the same).
- `.claude/rules/tests.md`: `paths:` now `tests/**`, both test workflows, `ci-local.sh`, the two installers, `.github/test-paths`, `requirements_test.txt` (no `pyproject.toml`, no `ha_check.yaml`); body points to the skill.
- `doc/KNOWLEDGE.md` K-3: `tests/ha/test_<pkg>.py` (plus `tests/e2e/` files that target the package). IDs unchanged.
- Package notes: Tests sections rewritten for energy, heating_cooling_indicator, airflow, pergola (watchdog race fix, 500 ms settle, drain at teardown, stale rule-2 comment), victron, heating_pv_boost; `tests/e2e/test_restart.py` added to the `paths:` of victron and heating_pv_boost (it checks their totals). Issues linked where they were missing: #146 (energy, victron, airflow, heating_pv_boost), #147 and #155 (victron), #153, #154, #155 (airflow). The #156 bullet of energy (Docker test read back its own seed) is removed: the in-process test replaced that file. #143 stays linked, reworded (Docker test gone).
- `plans/ci-test-speedups.md` and `plans/stateful-template-and-automation-tests.md` deleted. Their content is the Docker harness (timeout shim, image prefetch, REST seeding, `state_defaults.yaml`/`scenarios.yaml` runner, files that no longer exist); everything that was a confirmed fact is superseded by the skill or the in-process/e2e tests. The one open item in them, removing the `| float(default)` fallbacks in `packages/pergola.yaml`, is already tracked as #142 and in the pergola and airflow notes.

K-7 (fresh headless sessions from the repo root, `claude -p … --model haiku --allowedTools Read --max-turns 4`):
| Check | Result |
|---|---|
| `tests.md` rule, no tool use | absent (the model says it is not in context) |
| after reading `tests/ha/test_wallbox.py` | present, source `.claude/rules/tests.md` quoted |
| after reading `tests/e2e/test_boot.py` | present |
| after reading `README.md` | absent |
| skill, task prompt not naming it (`--tools Read,Skill,Grep,Glob`) | `Skill(ha-test-harness)` invoked in 3 of 3 further runs (the very first run, with Bash available, read the skill file by `cat` instead) |
| skill, unrelated prompt | no tool use |



## Rejected or superseded options from the original plan
- Module-scoped `hass` for the stateless tables: spiked and rejected (see "Step 2 results, first chunk").
- One mosquitto per xdist worker, cleared between tests: valid but not faster than restart (measured above).
- `amqtt` (pure-Python broker in the same process): easier to install but not the production broker, retain semantics differ, fidelity lower.
- `mqtt_mock`: the tests need the real integration against a real broker.
- Reason `http-surface` for e2e: dropped, nothing needs it.
- Keeping the harness `ha_integration_test_harness` with a retagged `:stable` image, a timeout shim and `docker exec` clock moves: replaced by an own client and `docker run --network host` of the pinned image.
- Per-test `docker run` of the Mosquitto app image, compiling mosquitto on the runner, a job inside the app image: see the options table in Step 4.



## Targeted local runs and the test recorder filter (PR #162)
Why `ci-local.sh` got `--package`, `--yaml` and `--`, and why the test recorder records only history sources. Current
facts are in the skill and `tests/ha/conftest.py`; this keeps the measurements behind the choices.
- Before: every call ran all YAML checks and all of `tests/ha` (about 60 s of tests plus pip/venv setup); copying the raw
  pytest line from the skill skipped the venv, custom component and pinned mosquitto and failed in fresh sessions.
- Timings (wall time of the whole script, 4 cores): full run 57 s; one test 6-11 s; `--package` energy 8.5 s,
  heating_pv_boost 16 s, victron 21 s, airflow_cooling 21 s, pergola 26 s; `--yaml` 2 s. A fresh agent given only
  "confirm the wallbox tests are green" picked `--package energy` from the guidance by itself.
- xdist: one file 7.3 s with `-n 0` vs 10.0 s with workers; `--package pergola` 79 s with `-n 0` vs 25 s with `-n auto`,
  victron 63 s vs 22 s. Hence `-n 0` for explicit ids, `-n auto` for packages.
- Install stamps (hash of requirement files + python version + command): saves about 1.5 s per call; verified that editing
  `requirements_test.txt` reinstalls `.venv-test` only. The `.venv-e2e` branch was only syntax-checked.
- Recorder (py-spy and per-thread CPU, single test, warm): ~0.4 s script, ~1.7 s Python + HA imports, ~1 s first-boot
  integration imports (both once per process), ~2.2 s boot per test of which ~1.1 s the Recorder thread (a SQLite commit
  per event, `commit_interval: 0`, GIL contention); recording nothing: boot 2.2 -> 0.9 s. Result of the filter: full
  `tests/ha` 66.6 -> ~46 s, `--package pergola` 31 -> 22.5 s, single test 7.0 -> 5.5 s (prototype on a quieter machine
  51 -> 35 s).
- Coverage gap found on the way: with `include.entities = [sensor.nothing]` the whole suite stayed green, because
  history_stats follows live events and reads the DB only on its first update; closed by
  `test_history_stats_read_back_from_recorder` (reload forces the read). Mutation checks and 20x stability runs of the
  structural guards were done; the results are not kept.
- Dropped alternative: a separate script for targeted runs (would duplicate the venv/mosquitto setup).
