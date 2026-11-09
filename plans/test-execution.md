# Plan: test execution — in-process layer + real-HA layer (learned from innova_hrds)

## Status
- [x] Research and feasibility check (this file)
- [x] Step 0 spikes: DONE, exit criterion met (see "Step 0 results")
- [x] Step 1 HA version single source: DONE. `requirements_test.txt` (PHACC pin) replaces `tests/ha/requirements.txt`; `tests/ha/test_versions.py` guards Dockerfile year.month = PHACC's HA, holidays/cronsim = HA manifest pins, Python >= HA's; Dependabot pip entry for `/`; CLAUDE.md line
- [ ] Step 2 in-process layer, Step 2b real MQTT broker (see "Step 2 results")
  - [x] Spike module-scoped `hass` (tier 1): works, but not clean; function scope kept, tier-1 tables become one looping test (decision below)
  - [x] Mosquitto clear vs restart: measured, restart kept; isolation proof `tests/ha/test_broker_isolation.py`
  - [x] Shared fixtures in `tests/ha/conftest.py`: `seed`, `apply_baseline` (data moved to `tests/baseline.py`, shared with the Docker suite), `Clock`/`clock`, autouse `log_guard` + `allow_log` marker, action stubs
  - [x] Migration item 1: `tests/test_templates.py` → `tests/ha/test_templates.py` (one test, one HA); Docker test and its CI extraction step removed
  - [x] Migration item 2: wallbox, heating_cooling_indicator, airflow decision/bypass/dew-point thresholds → `tests/ha/test_{wallbox,heating_cooling_indicator,airflow}.py` (one looping test per table); Docker tests removed (see "Step 2 results, item 2")
  - [ ] Migration items 3–5
  - [ ] **Gap until Step 4:** CI does not run `tests/ha` yet, so template rendering is checked only locally (`ci-local.sh` only smoke-runs the extractor)
- [ ] Step 3 real-HA layer
- [ ] Step 4 CI/local runs
- [ ] Step 5 knowledge update


## Context
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

## Feasibility: does the hrds setup fit a YAML/automation config?
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

## Approach

### Step 0 – Plan file and spikes (no test migration yet)
- Copy this plan to `homeassistent-config/plans/test-execution.md`, as CLAUDE.md requires.
- Spike 1: can PHACC load this repo's real config in-process?
  - Make a `hass` fixture whose config dir is a staged copy of the repo, with `fakesecrets.yaml` as `secrets.yaml`, the CI coordinates, and `custom_templates/`.
  - Load it with `homeassistant.config.async_hass_config_yaml` and set up the needed domains with `async_setup_component`.
  - Verify the PHACC API against its source at the pinned tag (CLAUDE.md version gate). Do not trust memory for fixture names (`hass_config_dir`?, `freezer`, `mqtt_mock`, `recorder_mock`).
- Spike 2: the Python version.
  - PHACC for HA 2026.10 requires the Python version that HA requires.
  - `.github/ha-versions/python/Dockerfile` says 3.15. Check which version PHACC/HA 2026.10 supports and align.
- Spike 3: a real mosquitto per test, with the HA MQTT integration connected to it. One Shelly payload goes through `value_template` to the entity, and one `mqtt.publish` is received by the test client.
- Exit criterion: three tests pass in-process, deterministically, 20 runs out of 20:
  - one airflow decision test;
  - one MQTT ingest test;
  - one Victron `time_pattern` accumulator test, fed through the real broker while `freezer` moves the clock.

### Step 0 results (spike tests: `tests/ha/test_spike.py`; the fixtures are final since Step 2)
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

### Step 2 results (first chunk: spikes, shared fixtures, migration item 1)
Run: `.venv-test/bin/python -m pytest -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . tests/ha -n 4 -q -p no:logging`.
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

### Step 1 – Single source of the HA version (copy the hrds pattern)
- Add `requirements_test.txt` pinning PHACC, which pins HA.
- Add `tests/ha/test_versions.py`: the Dockerfile `FROM` year.month must equal `homeassistant.const` (reuse the regex from hrds `tests/ha/test_versions.py`).
- Dependabot: add a pip entry for the new file, and add a comment on the docker entry saying "bump PHACC in the same PR".
- Remove the hardcoded `2026.10.1` from prose (CLAUDE.md, skill grades). Point to the `FROM` line instead.

### Step 2 – In-process layer `tests/ha/` (the default)
Shared fixtures in `tests/ha/conftest.py`:
- **`hass` with the repo config**: function-scoped, so each test gets a fresh HA. This removes the order dependencies and the skipped flake.
- **`seed(states)`**: wraps `hass.states.async_set`. Replaces REST `set_state`. The baseline stays one dict, reused from the current `baseline_states` data.
- **`Clock`**: uses `freezer` together with `async_fire_time_changed` and `async_block_till_done(wait_background_tasks=True)`. Any number of advances per test, in both directions where that is meaningful.
- **Real MQTT path**: a real broker, see Step 2b. This fixes `test_shelly_pool_pump.py`, which today tests only its own seed.
- **Deprecation guard**: autouse, fails a test on `homeassistant.helpers.frame` warnings or template errors that HA logs during the test.

Migrate per package, one PR each, with the old Docker test deleted in the same PR (never both):
1. `test_templates.py`: render each extracted template with `Template(...).async_render` in-process.
2. `test_wallbox.py`, `test_heating_cooling_indicator.py`, and the airflow decision, bypass and threshold tests.
3. `test_heating_pv_boost.py` and the Victron instant-power tests.
4. Time-based tests with Clock: `time_pattern`, `delay_on`/`delay_off`, `platform: integration` deltas, utility_meter, `last_changed` statistics. `recorder_mock` where statistics need it.
5. Pergola: sun is driven by freezer plus the sun integration, and automations are triggered through real state changes.

Rule for every migrated test: assert through real triggers where possible, rather than `automation.trigger` that skips conditions.

### Step 2 additions – how much HA per test
Why fresh HA per test is the default: a shared instance leaks state that cannot be reset: integration/utility_meter totals, `this.state` accumulators and hysteresis, pending `delay_on`/`time_pattern` timers, running `mode: single` automations and `last_triggered`, recorder history (statistics/history_stats), retained MQTT, a clock that only moves forward. These are today's ordering flakes. Cost ≈2.6 s/test. Three tiers:
1. **Shared per module** for stateless formula tests (decision table, bypass, wallbox, Victron power-domain math, indicator thresholds): only set inputs and read template results; no clock, accumulators, automations, MQTT.
   - Spike first whether PHACC supports a module-scoped `hass` (module-scoped event loop; PHACC's per-test `verify_cleanup` may object).
   - Each test resets the inputs it uses; a guard asserts no trigger-based/accumulator entity changed during the module.
   - If PHACC can't do it cleanly, stay function-scoped.
2. **Template validity** (`test_templates.py`): ONE test on one instance: render every extracted template in a loop, collect failures, single assert listing all. No per-template instance, no parametrize. Replaces `/api/template` REST round-trips.
3. **Fresh HA per test**: everything with time, accumulators, automations or MQTT.

Mosquitto: clear vs restart (measure in Step 2):
- Alternative: one broker per xdist worker session, cleared between tests (clear all retained messages: subscribe `#`, publish an empty retained payload per retained topic seen; clients disconnect anyway when the per-test HA stops).
- Valid only if a following test can't see anything from the previous: prove with a retained-publish test plus a test asserting no retained messages on `#`, both orders, 20×.
- Adopt only if measurably faster than restart (already a few ms + connect poll) and equally isolating; else keep restart.

### Step 2b – Real MQTT broker instead of faked MQTT entities
Why:
- 55 MQTT sensors (energy 18, heating_pv_boost 23, victron 14) and 21 `mqtt.publish` actions are the main source of data in production.
- Today the tests seed the MQTT entities' states, so `value_template`, `availability`, JSON parsing, `expire_after`, retain handling and the actual published payloads go untested.
- `test_shelly_pool_pump.py` only reads back its own seed.

Design. This is the hrds simulator pattern, with the broker in place of the Modbus simulator:
- **Broker**: a real `mosquitto` binary, the same broker as the production Mosquitto add-on. Install it with `apt-get install -y mosquitto` in CI and `brew install mosquitto` locally (add it to the CLAUDE.md prerequisites).
  - Start it as a subprocess **per test**, on a free port bound to 127.0.0.1, with a minimal config: `listener <port> 127.0.0.1`, `allow_anonymous true`, `persistence false`.
  - Per test, so retained messages cannot leak between tests. This is the isolation hrds gets from a fresh simulator per test.
  - Startup is milliseconds. Readiness is a deadline-bounded connect poll, not a sleep.
  - Not chosen: `amqtt` (a pure-Python broker that could run in the same process). It is easier to install, but it is not the production broker and its retain semantics differ, so fidelity is lower.
- **HA side**:
  - The real `mqtt` integration, set up through `MockConfigEntry(domain="mqtt", data={"broker": "127.0.0.1", "port": port})`. MQTT is configured through a config entry; the YAML `mqtt:` keys in packages only define entities.
  - The `socket_enabled` fixture: PHACC blocks sockets, and hrds does the same for its simulator.
  - Do not use `mqtt_mock`.
- **Test side**: a small `paho-mqtt` client fixture (PHACC already ships paho 2.1.0):
  - `publish(topic, payload, retain=...)` drives the device topics: Shelly JSON, ebusd, Victron Venus `{"value": …}`, Loxone.
  - `expect_publish(topic, payload, timeout)` subscribes and asserts what the automations published (ebusd writes, Victron keepalive).
- **Waiting**: network delivery is real I/O, so `async_block_till_done` alone does not wait for it.
  - Use a helper `await wait_state(entity_id, expected, deadline=5)` that alternates `async_block_till_done` with short awaits until a deadline. No fixed sleeps, matching hrds `assert_entity_state`.
  - On failure it reports the last state and the broker log.
- **Mix**: MQTT-fed entities are driven only over the broker. Non-MQTT sources (Somfy, ComfoConnect, go-e, sun, weather) stay seeded with `hass.states.async_set`, because there is no real path for them in CI anyway.
- **e2e**: the same mosquitto runs as a host process next to the container (`--network host`), so the full-boot tests use real MQTT too.

Risk, to close in the spike:
- `freezer` also freezes `time.monotonic`, and paho and HA's MQTT client loop use it for keepalive and ping. A big clock jump (for example 10 min for a `delay_on`) could trigger a ping timeout and a reconnect.
- The spike must show that a Victron `time_pattern` accumulator test runs with the real broker plus `freezer` and gives 20 green runs out of 20.
- If it does not, the fallback is to split the work:
  - The ingest and publish tests use the real broker and do not move the clock.
  - The tests that move the clock seed the MQTT entities' states.
  - Both kinds still run in-process.

### Step 3 – Real-HA layer `tests/e2e/` (only what needs the container)
- Marker `needs_real_ha("<reason>")`, with a closed `REAL_HA_REASONS` list enforced in `pytest_collection_modifyitems` (as hrds does). The proposed reasons:
  - `full-boot`: the real `configuration.yaml`, all packages, and the HACS `climate_template`.
  - `check-config`: the CLI script.
  - `restart-persistence`: restore_state of integration and utility_meter totals across a real restart.
  - `http-surface`: `/api/template`, and history if still needed.
  - `runtime-logs`: `test_zz_log_hygiene.py` parses the container log and fails on any ERROR or deprecation from the config.
- Each e2e module docstring starts with "Needs a real HA because: …".
- Drop the harness, AppDaemon and libfaketime. Instead:
  - Write a small own client modeled on hrds `tests/e2e/ha_client.py`: `wait_ready`, `wait_running`, onboarding, a timeout on every call, and polling with deadlines.
  - Start the container with `docker run --network host` of the pinned image, shared by session.
  - This removes the `:stable` retag, the timeout shim, and the `docker exec` clock hangs.
- Share config staging (`tests/e2e/stage.py`) between the pytest fixture and the CI check_config step.
- Never repeat an in-process scenario in e2e. hrds cut its e2e time from 6 to 2.5 min this way.

### Step 4 – CI and local runs
- `tests.yaml`, the in-process job:
  - pip cache keyed on `requirements_test.txt`.
  - `pytest tests/ha --timeout=60`.
  - `pyproject.toml` gets `asyncio_mode=auto` and `filterwarnings` on deprecations.
- `e2e.yaml`:
  - Pull the image in the background (keep the current pattern).
  - Run check_config, then `pytest tests/e2e -p no:homeassistant --timeout=300 --timeout-method=thread`.
  - A separate `tests/e2e/pytest.ini` and `requirements.txt`, without PHACC.
  - The image is read from the `FROM` line.
  - An optional nightly `beta` channel with `continue-on-error`.
- In both workflows:
  - A concurrency group, `cancel-in-progress` on PRs.
  - Change detection through `.github/test-paths`, skipping per step so required checks stay green.
  - Triggers `pull_request` plus `push: [master]`.
- `ci-local.sh` gains `pytest tests/ha`, so the main suite runs locally without Docker.
- No rerun or retry plugins. A flaky test is a bug: open a GitHub issue and fix it.

### Step 5 – Knowledge update
- Rewrite `.claude/skills/ha-test-harness/` for the two layers, with the where-does-a-test-go checklist from hrds `tests/CLAUDE.md`.
- Point `.claude/rules/tests.md` to it.
- Delete `plans/ci-test-speedups.md` and the stale `plans/stateful-template-and-automation-tests.md` once their content is superseded.
- Record only confirmed learnings through `record-learning`.

## Critical files
- New:
  - `requirements_test.txt`
  - `tests/ha/conftest.py`
  - `tests/ha/test_versions.py`
  - `tests/ha/test_<pkg>.py`
  - `tests/e2e/{conftest.py,ha_client.py,stage.py,pytest.ini,requirements.txt,test_boot.py,test_restart.py,test_zz_log_hygiene.py}`
  - `.github/workflows/{tests.yaml,e2e.yaml}`
  - `.github/test-paths`
- Changed:
  - `pyproject.toml`
  - `.github/dependabot.yml`
  - `.github/scripts/ci-local.sh`
  - `CLAUDE.md`
  - the skill `ha-test-harness`
- Removed:
  - `.github/workflows/ha_check.yaml`, once e2e replaces it
  - `.github/workflows/requirements.txt` harness pin
  - `tests/conftest.py` shim
  - the old `tests/test_*.py`, as they are migrated
- Reused from hrds as templates:
  - `tests/ha/conftest.py::Clock`
  - `tests/ha/test_versions.py`
  - `tests/e2e/conftest.py` (marker enforcement, container fixture)
  - `tests/e2e/ha_client.py`
  - `tests/e2e/test_zz_log_hygiene.py`
- Reused from this repo:
  - `.github/scripts/extract_templates.py`
  - `resolve_ha_yaml.py`
  - the baseline state data in `tests/conftest.py`

## Verification
- Spike exit criterion: 20 consecutive green runs (`pytest --count=20` locally, or a loop).
- Per migration PR:
  - The in-process test fails when the YAML under test is deliberately broken (mutation check). This proves the test is valid and not reading its own seed.
  - The test passes in isolation and under `-p random_order`.
- CI: compare wall time before (about 3m27s green) and after. Target: in-process under 1 min, e2e under 2 min.
- Run `.github/scripts/ci-local.sh` locally, and check `git ls-files --eol` (LF) before every commit.
