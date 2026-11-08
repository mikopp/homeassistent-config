"""SPIKE fixtures of the in-process test layer (plans/test-execution.md, Step 0).

The real Home Assistant core runs inside pytest (pytest-homeassistant-custom-component). It
loads THIS repo's packages through HA's own YAML loader, and the real MQTT integration talks
to a real mosquitto started per test. Nothing here is final; the spike only has to show the
approach is valid and stable.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import threading
from collections.abc import AsyncGenerator, Callable, Generator
from pathlib import Path
from typing import Any

import freezegun.api
import paho.mqtt.client as paho
import pytest
import yaml
from homeassistant.components import mqtt
from homeassistant.config import async_hass_config_yaml
from homeassistant.core import CoreState, HomeAssistant, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import async_load_custom_templates
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

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
# secrets, the CI-only YAML fixtures (workday) and any downloaded custom component. Only the
# package domains are loaded later, never default_config/frontend/lovelace (real-HA layer).
_CONFIGURATION = """\
homeassistant:
  packages: !include_dir_named packages
automation: !include automations.yaml
script: !include scripts.yaml
"""


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Override PHACC's config dir with a staged copy of this repo."""
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
    from homeassistant.util import dt as dt_util
    from datetime import timedelta

    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    return {
        "weather.home": {
            "forecast": [
                {"datetime": (start + timedelta(hours=h)).isoformat(), "temperature": temperature}
                for h in range(hours)
            ]
        }
    }


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
        """Stop the client and the broker (no state survives into the next test)."""
        self._client.loop_stop()
        self._client.disconnect()
        self._proc.terminate()
        self._proc.wait(5)


@pytest.fixture
def broker(tmp_path: Path, socket_enabled: None) -> Generator[Broker]:
    """A fresh broker per test, so retained messages cannot leak between tests."""
    b = Broker(tmp_path)
    yield b
    b.stop()


# ── Load the repo config into the in-process HA ───────────────────────────────
def _victron_mqtt_unique_ids() -> list[str]:
    """unique_ids of packages/victron.yaml MQTT sensors (production id = sensor.<unique_id>)."""
    text = (REPO / "packages/victron.yaml").read_text()
    data = yaml.load(text, Loader=_AnyTagLoader)
    return [e["unique_id"] for e in data["mqtt"]["sensor"] if "default_entity_id" not in e]


class _AnyTagLoader(yaml.SafeLoader):
    """SafeLoader that ignores HA tags (!secret, !include…) for read-only inspection."""


_AnyTagLoader.add_multi_constructor("!", lambda loader, suffix, node: None)

@pytest.fixture
async def ha(
    broker: Broker,  # first: torn down AFTER HA, so HA never sees the broker vanish
    recorder_mock: Any,
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> AsyncGenerator[HomeAssistant]:
    """HA with this repo's package domains set up, MQTT connected to the real broker."""
    # Production location/time zone (CI used the same coordinates via sed).
    await hass.config.async_set_time_zone("Europe/Vienna")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 48.3069, 14.2858, 266
    await async_load_custom_templates(hass)

    MockConfigEntry(
        domain="mqtt", data={"broker": "127.0.0.1", "port": broker.port}
    ).add_to_hass(hass)

    # SPIKE: production entity ids of MQTT sensors without `default_entity_id`. They live only in
    # the production entity registry (.storage); a fresh registry derives different ids
    # (sensor.electrical_victron_energy_system_victron_grid_l1_power) and every template that
    # reads sensor.victron_grid_l1_power breaks. Final fix: default_entity_id in the YAML.
    reg = er.async_get(hass)
    for uid in _victron_mqtt_unique_ids():
        reg.async_get_or_create("sensor", "mqtt", uid, suggested_object_id=uid)

    conf = await async_hass_config_yaml(hass)
    conf.pop("homeassistant", None)
    conf.pop("recorder", None)  # the recorder is recorder_mock's
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
    # The broker is real I/O: wait (deadline-bounded) until HA's client is connected BEFORE
    # start, so `homeassistant: start` publishes (Victron keep-alive) reach the broker.
    deadline = _real_monotonic() + 10
    while not mqtt.is_connected(hass):
        assert _real_monotonic() < deadline, "HA did not connect to mosquitto"
        await hass.async_add_executor_job(threading.Event().wait, 0.01)
    await hass.async_start()
    await hass.async_block_till_done()
    yield hass


def entity_id(hass: HomeAssistant, domain: str, platform: str, unique_id: str) -> str:
    """Look an entity id up by unique_id (repo rule: never derive ids)."""
    from homeassistant.helpers import entity_registry as er

    eid = er.async_get(hass).async_get_entity_id(domain, platform, unique_id)
    assert eid, f"no {domain} entity with unique_id {unique_id} on {platform}"
    return eid


@pytest.fixture
def expected_lingering_timers() -> bool:
    """YAML time_pattern/template timers stay scheduled on the stopped test HA; not a leak."""
    return True


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
