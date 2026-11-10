"""Real Home Assistant in Docker, fed by a real mosquitto on the host.

This layer is deliberately small: it only holds tests that need a real Home Assistant (see the
module docstrings, plans/test-execution.md). Everything a Home Assistant inside pytest can show
runs in `tests/ha`. Every test here says why with `@pytest.mark.needs_real_ha("<reason>")`;
collection fails without it.

Parts, top to bottom:
- the closed list of reasons and its enforcement at collection;
- docker and mosquitto helpers;
- `broker`: a mosquitto process (session), and a paho client that publishes like the devices;
- `ha`: ONE container for the whole session (staged config, onboarded, MQTT and workday set up
  through the real config flows, entity ids made production-like, restarted into a clean boot);
- `restart_ha`, `ha_log`, `publish`: what the tests use.

Environment: `E2E_IMAGE` (default: the `FROM` line of .github/ha-versions/ha/Dockerfile),
`E2E_ARTIFACTS` (where logs land, default `tests/e2e/.artifacts`).

Run: pytest -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e -p no:homeassistant
(`-p no:homeassistant` only matters when PHACC is installed in the same venv; `--confcutdir`
keeps this run from collecting conftest files above tests/e2e).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import paho.mqtt.client as paho
import pytest

from .ha_client import HomeAssistant
from .stage import ROOT, image_from_dockerfile, stage

CONTAINER = "ha-config-e2e"
ARTIFACTS = Path(os.environ.get("E2E_ARTIFACTS", ROOT / "tests/e2e/.artifacts"))
HERE = Path(__file__).resolve().parent

# ── Why a test may live in this directory ─────────────────────────────────────
# A closed list: a new reason is a deliberate decision (it needs a line here and in the module
# docstring), not a way around the rule. If a check can be made with `hass` inside pytest it
# belongs in tests/ha, not here.
REAL_HA_REASONS = {
    "full-boot": "the real configuration.yaml, every package and the HACS climate_template load in a real HA",
    "check-config": "HA's own check_config script accepts the staged configuration",
    "restart-persistence": "restore_state: totals written on a real shutdown are read back after a real boot",
    "runtime-logs": "the real HA log of the whole session is free of errors and deprecations from this config",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A test in tests/e2e must justify needing a real Home Assistant."""
    for item in items:
        if not Path(str(item.path)).is_relative_to(HERE):
            continue
        marker = item.get_closest_marker("needs_real_ha")
        reason = marker.args[0] if marker and marker.args else None
        if reason not in REAL_HA_REASONS:
            raise pytest.UsageError(
                f"{item.nodeid}: tests in tests/e2e need @pytest.mark.needs_real_ha('<reason>') "
                f"with one of {sorted(REAL_HA_REASONS)}. If it can run in-process (tests/ha) it "
                "does not belong here."
            )


# ── docker helpers ────────────────────────────────────────────────────────────
def docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """Run the docker CLI with a timeout; stderr is merged into stdout (HA logs on both)."""
    return subprocess.run(
        ["docker", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=check,
        timeout=timeout,
    )


def container_log() -> str:
    """The container's whole log (it spans restarts), in order."""
    return docker("logs", CONTAINER, check=False).stdout


# ── mosquitto on the host ─────────────────────────────────────────────────────
def _free_port() -> int:
    """A free TCP port on 127.0.0.1 (bind port 0, read it back)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Broker:
    """A mosquitto process plus a paho client that publishes like the devices do.

    The HA container runs with `--network host`, so it reaches the broker on 127.0.0.1 and the
    config flow of the MQTT integration uses `port` (plans/test-execution.md, Step 2b).
    """

    def __init__(self, workdir: Path) -> None:
        mosquitto = shutil.which("mosquitto")
        if mosquitto is None:
            raise RuntimeError("mosquitto not installed (apt-get install mosquitto / brew install mosquitto)")
        self.port = _free_port()
        conf = workdir / "mosquitto.conf"
        # Nothing is saved to disk and no retained message outlives the session.
        conf.write_text(f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
        self.log = workdir / "mosquitto.log"
        self._proc = subprocess.Popen(
            [mosquitto, "-c", str(conf)], stdout=self.log.open("w"), stderr=subprocess.STDOUT
        )
        # Readiness: a deadline-bounded connect poll, no fixed sleep.
        deadline = time.monotonic() + 15
        while True:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                break
            except OSError:
                if time.monotonic() > deadline or self._proc.poll() is not None:
                    raise RuntimeError(f"mosquitto did not start: {self.log.read_text()}") from None
                time.sleep(0.05)
        self._client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="e2e-devices")
        self._client.connect("127.0.0.1", self.port)
        self._client.loop_start()

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        """Publish like a device (dict -> JSON); returns when the broker has acked it."""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=1, retain=retain).wait_for_publish(10)

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
        self._proc.terminate()
        self._proc.wait(10)


@pytest.fixture(scope="session")
def broker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Broker]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    b = Broker(tmp_path_factory.mktemp("mosquitto"))
    yield b
    b.stop()
    shutil.copy(b.log, ARTIFACTS / "mosquitto.log")


# ── the Home Assistant container ──────────────────────────────────────────────
# Entity ids production has and a fresh registry derives differently (#146: MQTT sensors
# without default_entity_id get area + device + name ids; weather and workday are named by the
# onboarding/config flow). A user renames them in the UI; so does this table, through the real
# registry API, so the config's templates find their sources. Key: (domain, platform, unique_id
# or None for "the only one of that platform"), value: the entity id the config reads.
PRODUCTION_IDS: dict[tuple[str, str, str | None], str] = {
    ("weather", "met", None): "weather.home",
    ("binary_sensor", "workday", None): "binary_sensor.workday",
    ("sensor", "mqtt", "shelly_pro3em_heizung_energy"): "sensor.technikraum_heizung_heizung_energy",
    ("sensor", "mqtt", "victron_grid_l1_power"): "sensor.victron_grid_l1_power",
    ("sensor", "mqtt", "victron_grid_l2_power"): "sensor.victron_grid_l2_power",
    ("sensor", "mqtt", "victron_grid_l3_power"): "sensor.victron_grid_l3_power",
}

# The workday options production has (the integration is configured in the UI there).
WORKDAY_OPTIONS = {
    "workdays": ["mon", "tue", "wed", "thu", "fri"],
    "excludes": ["sat", "sun", "holiday"],
    "days_offset": 0,
    "add_holidays": [],
    "remove_holidays": [],
}


def _add_integrations(ha: HomeAssistant, broker: Broker) -> None:
    """MQTT (the host mosquitto) and workday (AT), through the real config flows."""
    flow = ha.flow_start("mqtt")
    result = ha.flow_configure(
        flow["flow_id"],
        {
            "broker": "127.0.0.1",
            "port": broker.port,
            "protocol": "5",
            "other_settings": {"set_client_cert": False, "set_ca_cert": "off"},
        },
    )
    assert result["type"] == "create_entry", result
    flow = ha.flow_start("workday")
    result = ha.flow_configure(flow["flow_id"], {"country": "AT"})
    result = ha.flow_configure(result["flow_id"], WORKDAY_OPTIONS)
    assert result["type"] == "create_entry", result


def _make_ids_production_like(ha: HomeAssistant) -> None:
    """Rename the entities of PRODUCTION_IDS to the ids the config reads."""
    for (domain, platform, unique_id), wanted in PRODUCTION_IDS.items():

        def find(domain=domain, platform=platform, unique_id=unique_id) -> dict | None:
            for entry in ha.entity_registry():
                if entry["platform"] != platform or not entry["entity_id"].startswith(f"{domain}."):
                    continue
                if unique_id is None or entry.get("unique_id") == unique_id:
                    return entry
            return None

        # The entities appear a moment after their entry is created.
        # Met.no needs the internet; offline (a sandbox) it has no weather entity and the
        # config's forecast call fails, which the log test allows for by name.
        entry = None
        try:
            entry = ha.wait_for(find, f"{platform} {unique_id or domain} in the registry", timeout=15)
        except AssertionError:
            if platform != "met":
                raise
        if entry is not None and entry["entity_id"] != wanted:
            ha.entity_registry_update(entry["entity_id"], new_entity_id=wanted)


def _restart(ha: HomeAssistant) -> None:
    ha.close()
    docker("stop", "--timeout", "60", CONTAINER, timeout=120)
    docker("start", CONTAINER)
    ha.wait_ready()
    ha.wait_running()


class Session:
    """What `ha` yields: the client plus the log offset after the bootstrap."""

    def __init__(self, client: HomeAssistant) -> None:
        self.client = client
        self.log_offset = 0


@pytest.fixture(scope="session")
def session(broker: Broker, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Session]:
    """One container for the whole session, bootstrapped like an installation that has run.

    A fresh Home Assistant has no MQTT entry, so its first boot cannot satisfy the config's
    `homeassistant: start` publishes (ERROR "make sure MQTT is set up"). That boot is the
    bootstrap: onboarding, the MQTT and workday entries, production-like entity ids. Then the
    container restarts, and from that boot on everything is as on a running installation. The log
    offset marks where the bootstrap ends; the log test judges only what comes after it.
    """
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    image = os.environ.get("E2E_IMAGE") or image_from_dockerfile()
    config = stage(tmp_path_factory.mktemp("ha") / "config")
    docker("rm", "-f", CONTAINER, check=False)
    docker(
        "run", "-d", "--name", CONTAINER, "--network", "host", "-e", "TZ=Europe/Vienna",
        "-v", f"{config}:/config", image,
        timeout=600,  # the first run may pull the image
    )
    client = HomeAssistant()
    current = Session(client)
    try:
        client.wait_ready()
        client.onboard()
        client.wait_running()
        _add_integrations(client, broker)
        _make_ids_production_like(client)
        # The offset is taken after the stop, when nothing more is written to the log.
        client.close()
        docker("stop", "--timeout", "60", CONTAINER, timeout=120)
        current.log_offset = len(container_log())
        docker("start", CONTAINER)
        client.wait_ready()
        client.wait_running()
        yield current
    finally:
        client.close()
        (ARTIFACTS / "home-assistant-docker.log").write_text(container_log())
        docker("rm", "-f", CONTAINER, check=False)


@pytest.fixture(scope="session")
def ha(session: Session) -> HomeAssistant:
    """The onboarded client of the session's container."""
    return session.client


@pytest.fixture(scope="session")
def restart_ha(session: Session) -> Callable[[], None]:
    """Restart the container for real (stop = clean shutdown that saves state) and wait for RUNNING."""
    return lambda: _restart(session.client)


@pytest.fixture(scope="session")
def ha_log(session: Session) -> Callable[[], str]:
    """The log since the bootstrap (the clean boot and everything after it), as text."""
    return lambda: container_log()[session.log_offset :]


@pytest.fixture(scope="session")
def publish(broker: Broker) -> Callable[..., None]:
    """Publish like a device: publish(topic, payload, retain=False)."""
    return broker.publish
