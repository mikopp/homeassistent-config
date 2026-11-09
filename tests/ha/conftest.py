"""Fixtures of the in-process test layer (plans/test-execution.md, Step 2).

The real Home Assistant core runs inside pytest (pytest-homeassistant-custom-component, PHACC).
It loads THIS repo's packages through HA's own YAML loader, and the real MQTT integration talks
to a real mosquitto started per test. Each test gets a fresh HA (function scope).

Parts, top to bottom:
- real clock and free-port helpers;
- config staging (`stage_config`, `hass_config_dir`);
- the shared baseline (`seed`, `apply_baseline`, data in tests/baseline.py);
- the real broker (`Broker`, `broker`);
- loading the repo config into HA (`load_repo_config`, `ha`);
- waiting and lookup helpers (`entity_id`, `wait_state`);
- the clock (`Clock`, `clock`);
- the log guard (autouse `log_guard`, marker `allow_log`).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import freezegun.api
import paho.mqtt.client as paho
import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import mqtt
from homeassistant.config import async_hass_config_yaml
from homeassistant.core import CoreState, HomeAssistant, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import async_load_custom_templates
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

REPO = Path(__file__).resolve().parents[2]


# ── Real clock, unaffected by freezer ─────────────────────────────────────────
# freezegun also freezes time.monotonic, so deadlines for real I/O (broker delivery) must use
# freezegun's saved originals; time.sleep is not patched.
# NOT a plain alias: freezegun replaces every module attribute that IS time.monotonic (an alias
# included), so look the saved original up at call time.
def _real_monotonic() -> float:
    return freezegun.api.real_monotonic()


def _free_port() -> int:
    """Return a free TCP port on 127.0.0.1 (bind port 0, read it back)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Config staging ────────────────────────────────────────────────────────────
# A temp config dir with the repo's packages, global automations/scripts, custom templates, fake
# secrets and any downloaded custom component. Only the package domains are loaded later, never
# default_config/frontend/lovelace (real-HA layer).
_CONFIGURATION = """\
homeassistant:
  packages: !include_dir_named packages
automation: !include automations.yaml
script: !include scripts.yaml
"""


def stage_config(tmp_path: Path) -> str:
    """Stage a copy of this repo's config under `tmp_path`/config; return its path.

    A plain function (not only the fixture below) so that a fixture of a wider scope can stage
    its own copy with `tmp_path_factory`.
    """
    cfg = tmp_path / "config"
    cfg.mkdir()
    for d in ("packages", "custom_templates", "custom_components", "blueprints"):
        if (REPO / d).is_dir():
            shutil.copytree(REPO / d, cfg / d)
    for f in ("automations.yaml", "scripts.yaml"):
        shutil.copy(REPO / f, cfg / f)
    shutil.copy(REPO / "fakesecrets.yaml", cfg / "secrets.yaml")
    (cfg / "configuration.yaml").write_text(_CONFIGURATION)
    # tests/custom_components.yaml `ha_yaml_config` (workday YAML platform) is NOT used: HA at
    # the pin rejects it ("does not support platform setup"). Workday is a config entry below.
    return str(cfg)


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Override PHACC's config dir with a staged copy of this repo."""
    return stage_config(tmp_path)


# ── Shared baseline (tests/baseline.py) ───────────────────────────────────────
# The same data the Docker-harness suite seeds over REST. Loaded by path: tests/ is not on
# sys.path in this layer (own rootdir conftest, `--confcutdir tests/ha`), and a path import
# cannot pick up tests/conftest.py by accident.
def _load_baseline() -> Any:
    spec = importlib.util.spec_from_file_location("baseline", REPO / "tests" / "baseline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINE = _load_baseline()

# A seed value: a bare state, or (state, attributes).
SeedValue = str | tuple[str, Mapping[str, Any]]


async def seed(hass: HomeAssistant, states: Mapping[str, SeedValue]) -> None:
    """Set entity states directly, in order, then let HA process the changes.

    Replaces the Docker suite's REST `set_state`. Meant for entities with no real source in the
    test HA (Somfy, ComfoConnect, weather station, ...). For MQTT-fed entities prefer the broker
    (plans/test-execution.md, Step 2b); the full baseline seeds them too, for tests that only
    need a value (template rendering).
    """
    for eid, value in states.items():
        state, attributes = (value, {}) if isinstance(value, str) else value
        hass.states.async_set(eid, state, dict(attributes))
    await hass.async_block_till_done()


async def apply_baseline(hass: HomeAssistant) -> None:
    """Apply the whole shared baseline: helper actions, input_number values, then the states.

    Same order as the Docker suite's `baseline_inputs` + `baseline_states`. Helpers are set
    through their real actions, so their own entities and listeners see a normal change.
    """
    for domain, action, data in BASELINE.BASELINE_ACTIONS:
        await hass.services.async_call(domain, action, data, blocking=True)
    for eid, value in BASELINE.BASELINE_NUMBERS.items():
        await hass.services.async_call(
            "input_number", "set_value", {"entity_id": eid, "value": value}, blocking=True
        )
    await seed(hass, BASELINE.BASELINE_STATES)
    # Second pass: a later seed can re-render an entity seeded earlier. The delayed trigger-based
    # airflow indicators (delay_on/delay_off never elapsed, so no internal state) re-render to
    # `unknown` when their inputs are seeded after them (ha-test-harness skill, "Seed trigger
    # inputs FIRST"). Restore every entry that no longer holds its baseline state, so the
    # baseline is one consistent snapshot. Why the Docker suite did not need this is UNPROVEN
    # (presumably REST timing).
    await seed(
        hass,
        {
            e: v
            for e, v in BASELINE.BASELINE_STATES.items()
            if (s := hass.states.get(e)) is None or s.state != v[0]
        },
    )


# ── Stand-ins for integrations the test HA does not run ───────────────────────
# Real workday integration, configured like the production UI entry (Austria).
_WORKDAY_OPTIONS = {
    "country": "AT",
    "excludes": ["sat", "sun", "holiday"],
    "workdays": ["mon", "tue", "wed", "thu", "fri"],
    "days_offset": 0,
    "add_holidays": [],
    "remove_holidays": [],
}


def hourly_forecast(hass: HomeAssistant, temperature: float, hours: int = 49) -> dict:
    """weather.get_forecasts response: `hours` hourly entries from now at one temperature."""
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    return {
        "weather.home": {
            "forecast": [
                {"datetime": (start + timedelta(hours=h)).isoformat(), "temperature": temperature}
                for h in range(hours)
            ]
        }
    }


# Every action the config calls whose integration is not in the test HA (mqtt.publish is real,
# weather.get_forecasts has its own stub above). Keep in sync with
# `grep -rhoE "action: *[a-z_]+\.[a-z_]+" packages automations.yaml scripts.yaml`.
_STUBBED_ACTIONS = (
    "cover.set_cover_tilt_position",
    "cover.stop_cover_tilt",
    "notify.mobile_app_greywinds_iphone",
    "number.set_value",
    "rest_command.send_to_loxone",
    "select.select_option",
    "switch.turn_off",
    "switch.turn_on",
)


# Entity id prefixes of integrations the test HA does not run: Somfy covers and their lock
# sensors, ComfoConnect, the weather station (UDP), go-e, sun. `sensor.wheatherstation_` also
# matches the production ids of two config sensors (statistics 48h mean, filter 15min) that a
# fresh registry derives as `sensor.weatherstation_...` (registry-dependent ids, as in #146), so
# seeding them cannot collide with the config entities.
_EXTERNAL_PREFIXES = (
    "cover.dach_",
    "sensor.dach_",
    "number.comfoconnect_pro_",
    "select.comfoconnect_pro_",
    "sensor.comfoconnect_pro_",
    "switch.comfoconnect_pro_",
    "sensor.wheatherstation_",
    "sensor.go_echarger_",
    "sun.sun",
)


# ── Real MQTT broker ──────────────────────────────────────────────────────────
class Broker:
    """A mosquitto process on a free localhost port, plus a paho test client."""

    def __init__(self, workdir: Path) -> None:
        self.port = _free_port()
        conf = workdir / "mosquitto.conf"
        conf.write_text(
            f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n"
        )
        self.log = workdir / "mosquitto.log"
        self._proc = subprocess.Popen(
            [shutil.which("mosquitto") or "mosquitto", "-c", str(conf), "-v"],
            stdout=self.log.open("w"),
            stderr=subprocess.STDOUT,
        )
        # Readiness: deadline-bounded connect poll, no fixed sleep.
        deadline = _real_monotonic() + 10
        while True:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                break
            except OSError:
                if _real_monotonic() > deadline or self._proc.poll() is not None:
                    raise RuntimeError(f"mosquitto did not start: {self.log.read_text()}")
                threading.Event().wait(0.02)
        self.received: list[tuple[str, str]] = []
        self._client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="pytest")
        self._client.on_message = lambda _c, _u, m: self.received.append(
            (m.topic, m.payload.decode())
        )
        self._client.connect("127.0.0.1", self.port)
        self._client.subscribe("#")
        self._client.loop_start()

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        """Publish like a device would (dict → JSON); waits for the broker's ack."""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=1, retain=retain).wait_for_publish(5)

    def wait_subscribed(self, topic: str, timeout: float = 5) -> None:
        """Wait until some client other than ours subscribed to `topic` (mosquitto -v log).

        A non-retained publish before HA's (debounced) subscribe would be lost; this makes the
        order deterministic without a sleep.
        """
        deadline = _real_monotonic() + timeout
        while f"\t{topic} (QoS" not in self.log.read_text():
            if _real_monotonic() > deadline:
                raise AssertionError(f"nobody subscribed to {topic}: {self.log.read_text()[-2000:]}")
            threading.Event().wait(0.01)

    def wait_received(self, topic: str, payload: str, after: int = 0, timeout: float = 5) -> None:
        """Wait until (topic, payload) was published by anyone, at index >= `after`."""
        deadline = _real_monotonic() + timeout
        while (topic, payload) not in self.received[after:]:
            if _real_monotonic() > deadline:
                raise AssertionError(f"not published: {topic} {payload!r}; got {self.received[-10:]}")
            threading.Event().wait(0.01)

    def stop(self) -> None:
        """Stop the client and the broker (no state survives into the next test).

        disconnect() BEFORE loop_stop(): it wakes paho's network thread at once. The reverse
        order lets the thread sit out its 1 s select() timeout (measured: 1.0 s per test).
        SIGKILL instead of SIGTERM: with `persistence false` there is nothing to save, and
        mosquitto's graceful shutdown costs about 110 ms (measured).
        """
        self._client.disconnect()
        self._client.loop_stop()
        self._proc.kill()
        self._proc.wait(5)


@pytest.fixture
def broker(tmp_path: Path, socket_enabled: None) -> Generator[Broker]:
    """A fresh broker per test, so retained messages cannot leak between tests.

    Kept over one broker per worker that is cleared between tests: clearing measured no faster
    (about 24 ms per test either way) and needs workarounds (plans/test-execution.md, Step 2
    results). tests/ha/test_broker_isolation.py proves the isolation.
    """
    b = Broker(tmp_path)
    yield b
    b.stop()


# ── Load the repo config into the in-process HA ───────────────────────────────
class _AnyTagLoader(yaml.SafeLoader):
    """SafeLoader that ignores HA tags (!secret, !include…) for read-only inspection."""


_AnyTagLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _victron_mqtt_unique_ids() -> list[str]:
    """unique_ids of packages/victron.yaml MQTT sensors (production id = sensor.<unique_id>)."""
    text = (REPO / "packages/victron.yaml").read_text()
    data = yaml.load(text, Loader=_AnyTagLoader)
    return [e["unique_id"] for e in data["mqtt"]["sensor"] if "default_entity_id" not in e]


async def load_repo_config(hass: HomeAssistant, *, mqtt_port: int | None) -> None:
    """Set up this repo's package domains on `hass` and start it.

    `mqtt_port`: the real broker to connect to, or None to leave MQTT out (its entities then
    do not exist). Custom integrations must already be enabled (`enable_custom_integrations`).
    """
    # Production location/time zone (CI used the same coordinates via sed).
    await hass.config.async_set_time_zone("Europe/Vienna")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 48.3069, 14.2858, 266
    await async_load_custom_templates(hass)

    if mqtt_port is not None:
        MockConfigEntry(domain="mqtt", data={"broker": "127.0.0.1", "port": mqtt_port}).add_to_hass(
            hass
        )
        # Production entity ids of MQTT sensors without `default_entity_id`. They live only in
        # the production entity registry (.storage); a fresh registry derives different ids
        # (sensor.electrical_victron_energy_system_victron_grid_l1_power) and every template
        # that reads sensor.victron_grid_l1_power breaks. Stand-in until #146 (default_entity_id
        # in the YAML) is fixed.
        reg = er.async_get(hass)
        for uid in _victron_mqtt_unique_ids():
            reg.async_get_or_create("sensor", "mqtt", uid, suggested_object_id=uid)

    conf = await async_hass_config_yaml(hass)
    conf.pop("homeassistant", None)
    conf.pop("recorder", None)  # the recorder is recorder_mock's
    if mqtt_port is None:
        conf.pop("mqtt", None)
    # Mirror bootstrap: set up every domain while HA is NOT running, then start. Otherwise
    # templates/automations render before input_* exist, and `homeassistant: start` triggers
    # never fire.
    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "homeassistant", {})
    MockConfigEntry(
        domain="workday", title="Workday", data={}, options=_WORKDAY_OPTIONS
    ).add_to_hass(hass)
    assert await async_setup_component(hass, "workday", {})
    # weather.home is Met.no in production (network). Stub the one action the config calls with
    # a deterministic forecast; the Docker suite used live Met.no data here.
    hass.data["forecast_calls"] = async_mock_service(
        hass,
        "weather",
        "get_forecasts",
        response=hourly_forecast(hass, 10.0),
        supports_response=SupportsResponse.ONLY,
    )
    results = await asyncio.gather(*(async_setup_component(hass, d, conf) for d in conf))
    failed = [d for d, ok in zip(conf, results, strict=True) if not ok]
    assert not failed, f"setup failed: {failed}"
    # Actions of integrations the test HA does not run (Somfy covers, ComfoConnect, phone,
    # Loxone). Stubbed only where no real action exists; each records its calls, so a test can
    # assert what an automation did: hass.data["service_calls"]["select.select_option"].
    calls = hass.data.setdefault("service_calls", {})
    for action in _STUBBED_ACTIONS:
        domain, name = action.split(".")
        if not hass.services.has_service(domain, name):
            calls[action] = async_mock_service(hass, domain, name)
    # Entities of integrations the test HA does not run exist in production from the start
    # (restored from the registry). Create them with their baseline state BEFORE start, so
    # `homeassistant: start` automations see them as in production (e.g. the pergola watchdogs'
    # template condition reads states.cover.dach_links). Selected by an explicit prefix list,
    # NOT by "does not exist yet": some config platforms (filter) register their entities only
    # after setup returns, and a seed under their id would push them to `_2` (seen once).
    await seed(
        hass,
        {e: v for e, v in BASELINE.BASELINE_STATES.items() if e.startswith(_EXTERNAL_PREFIXES)},
    )
    if mqtt_port is not None:
        # The broker is real I/O: wait (deadline-bounded) until HA's client is connected BEFORE
        # start, so `homeassistant: start` publishes (Victron keep-alive) reach the broker.
        deadline = _real_monotonic() + 10
        while not mqtt.is_connected(hass):
            assert _real_monotonic() < deadline, "HA did not connect to mosquitto"
            await hass.async_add_executor_job(threading.Event().wait, 0.01)
    await hass.async_start()
    await hass.async_block_till_done()


@pytest.fixture
async def ha(
    broker: Broker,  # first: torn down AFTER HA, so HA never sees the broker vanish
    recorder_mock: Any,
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> AsyncGenerator[HomeAssistant]:
    """A fresh HA with this repo's package domains set up, MQTT connected to the real broker."""
    await load_repo_config(hass, mqtt_port=broker.port)
    yield hass


@pytest.fixture
def expected_lingering_timers() -> bool:
    """YAML time_pattern/template timers stay scheduled on the stopped test HA; not a leak."""
    return True


# ── Lookup and waiting helpers ────────────────────────────────────────────────
def entity_id(hass: HomeAssistant, domain: str, platform: str, unique_id: str) -> str:
    """Look an entity id up by unique_id (repo rule: never derive ids)."""
    eid = er.async_get(hass).async_get_entity_id(domain, platform, unique_id)
    assert eid, f"no {domain} entity with unique_id {unique_id} on {platform}"
    return eid


async def wait_state(
    hass: HomeAssistant,
    entity_id: str,
    expected: str | Callable[[str], bool],
    timeout: float = 5,
) -> str:
    """Wait (real time, deadline-bounded) until an entity matches; for real-I/O delivery."""
    check = expected if callable(expected) else (lambda s: s == expected)
    deadline = _real_monotonic() + timeout
    while True:
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        if state is not None and check(state.state):
            return state.state
        if _real_monotonic() > deadline:
            raise AssertionError(
                f"{entity_id}: last state {state and state.state!r}, wanted {expected!r}"
            )
        # Real sleep in the executor: lets socket I/O on the loop run even under a frozen clock.
        await hass.async_add_executor_job(threading.Event().wait, 0.01)


# ── Clock ─────────────────────────────────────────────────────────────────────
class Clock:
    """Move HA's clock: freezer + async_fire_time_changed + async_block_till_done.

    Replaces the Docker suite's libfaketime jumps: any number of moves per test, and
    `move_to` may also go back (only meaningful for code that reads now(), since timers that
    already fired do not fire again). Every expectation must come from HA's own timestamps or
    from a state read after freezing (plans/test-execution.md, Step 0 results).
    """

    def __init__(self, hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
        self.hass = hass
        self._freezer = freezer

    async def advance(self, delta: timedelta | float, *, background: bool = False) -> None:
        """Move forward by `delta` (seconds or timedelta) and run everything that came due."""
        self._freezer.tick(delta if isinstance(delta, timedelta) else timedelta(seconds=delta))
        await self._fire(background)

    async def move_to(self, when: datetime, *, background: bool = False) -> None:
        """Jump to an absolute (aware) time and run everything that came due."""
        self._freezer.move_to(when)
        await self._fire(background)

    async def _fire(self, background: bool) -> None:
        # Time listeners first, then wait for the jobs they started.
        # `background=True` also waits for background tasks (interval jobs of coordinators run
        # as such). Off by default: with the real broker, MQTT's "re-subscribe and birth" task
        # sleeps on asyncio timers until a discovery cooldown has passed on time.monotonic,
        # which freezer stops, so waiting for it hangs until the test timeout (seen in the
        # keep-alive test when the clock is frozen right after start).
        async_fire_time_changed(self.hass)
        await self.hass.async_block_till_done(wait_background_tasks=background)


@pytest.fixture
def clock(ha: HomeAssistant, freezer: FrozenDateTimeFactory) -> Clock:
    """A Clock on the repo HA. `freezer` comes after `ha`: HA starts on the real clock."""
    return Clock(ha, freezer)


# ── Log guard ─────────────────────────────────────────────────────────────────
# Fails a test when HA logs, during the test's setup, call or teardown:
# - anything at WARNING or above from homeassistant.helpers.frame (deprecated API use),
# - a deprecation warning from any homeassistant logger,
# - a template error or warning: WARNING or above from the template helper or the template
#   integration, or a message that names a template failure (an automation's template
#   condition, an MQTT value_template, ...).
# A test that provokes such a log on purpose declares it: @pytest.mark.allow_log(regex, reason=).
_TEMPLATE_LOGGERS = ("homeassistant.helpers.template", "homeassistant.components.template")
_TEMPLATE_MESSAGE = re.compile(
    r"TemplateError|UndefinedError|Template variable (?:warning|error)|Error rendering template"
    r"|'template' condition"
)


# Known config issues the guard tolerates in EVERY test, each with its reason. Keep this list
# short: an entry is a defect to fix in the YAML (needs approval), not a permanent exception.
_KNOWN_CONFIG_LOGS = (
    # packages/victron.yaml counter-delta baselines render the string 'unknown' (src unknown and
    # this.state unknown) into a numeric energy sensor on a time_pattern tick before the Venus
    # counters arrived. Any test that crosses a real minute boundary before publishing them
    # logs it, so it cannot be avoided per test. Fix: render none instead (plans/
    # test-execution.md, Step 2 results).
    re.compile(
        r"Received invalid sensor state: unknown for entity "
        r"sensor\.victron_(?:solar_yield_dc|ac_pv_energy)_baseline_kwh, expected a number"
    ),
)


def _guarded(record: logging.LogRecord) -> str | None:
    """Why a log record fails the test, or None when it does not."""
    if record.levelno < logging.WARNING or not record.name.startswith("homeassistant"):
        return None
    message = record.getMessage()
    if record.name.startswith("homeassistant.helpers.frame"):
        return "frame"
    if "deprecated" in message.lower():
        return "deprecation"
    if record.name.startswith(_TEMPLATE_LOGGERS) or _TEMPLATE_MESSAGE.search(message):
        return "template"
    return None


class _GuardHandler(logging.Handler):
    """Collects the guarded records (any thread) while a test runs."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.hits: list[tuple[str, logging.LogRecord]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if (kind := _guarded(record)) is not None:
            self.hits.append((kind, record))


@pytest.fixture(autouse=True)
def log_guard(request: pytest.FixtureRequest) -> Generator[None]:
    """Autouse: fail the test on a guarded log record (see the block comment above).

    Autouse, so it is set up before `ha` and torn down after it: HA's boot and shutdown logs
    count. Works with `-p no:logging` (no caplog): the handler sits on the root logger.
    """
    allowed = [*_KNOWN_CONFIG_LOGS] + [
        re.compile(m.args[0]) for m in request.node.iter_markers("allow_log")
    ]
    handler = _GuardHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
    hits = [
        f"[{kind}] {rec.name}: {rec.getMessage()}"
        for kind, rec in handler.hits
        if not any(a.search(rec.getMessage()) for a in allowed)
    ]
    if hits:
        pytest.fail("guarded log records during the test:\n" + "\n".join(hits), pytrace=False)
