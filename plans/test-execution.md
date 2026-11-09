# Plan: test execution — in-process layer + real-HA layer (learned from innova_hrds)

## Status
- [x] Research and feasibility check (this file)
- [x] Step 0 spikes: DONE, exit criterion met (see "Step 0 results")
- [x] Step 1 HA version single source: DONE. `requirements_test.txt` (PHACC pin) replaces `tests/ha/requirements.txt`; `tests/ha/test_versions.py` guards Dockerfile year.month = PHACC's HA, holidays/cronsim = HA manifest pins, Python >= HA's; Dependabot pip entry for `/`; CLAUDE.md line
- [ ] Step 2 in-process layer, Step 2b real MQTT broker
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

### Step 0 results (spike code: `tests/ha/`, marked SPIKE)
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
1. **Entity IDs depend on the old `.storage`.** The MQTT sensors in `victron.yaml` and `energy.yaml` have no `default_entity_id`.
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
