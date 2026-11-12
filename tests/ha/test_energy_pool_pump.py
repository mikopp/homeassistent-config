"""Shelly Plus Plug S pool pump MQTT sensors (packages/energy.yaml), in-process.

The payloads go over the real broker (MQTT-fed entities are never seeded), so the real
value_templates run; the ingest case is `ingest_rounds_like_the_firmware_values`.

ONE test on one fresh HA (stateless value_templates, no clock). Every case publishes a
complete, real switch-status payload (a real Plug S always sends all fields, `output` included)
to the device topic, so the five real sensors parse it. Before each case a reset payload is
published and checked; its values differ from every case's expectation, and the switch is reset
to the opposite of what the case expects. All failures are collected into one assert.

Entity ids come from the registry by unique_id: these sensors have no `default_entity_id`, so a
fresh registry derives ids like `sensor.pool_pool_pump_pool_pump_power` (the production ids
`sensor.pool_pump_*` live only in the production .storage, see #146).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    check_states,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    wait_subscribed,
)

_TOPIC = "shelly/shellyplusplugs-pool-pump/status/switch:0"

# Checked entities: key → (domain, unique_id) on the mqtt platform.
_ENTITIES = {
    "power": ("sensor", "shelly_pool_pump_power"),
    "energy": ("sensor", "shelly_pool_pump_energy"),
    "voltage": ("sensor", "shelly_pool_pump_voltage"),
    "current": ("sensor", "shelly_pool_pump_current"),
    "switch": ("binary_sensor", "shelly_pool_pump_switch"),
}


def _status(
    *,
    apower: float = 0.0,
    energy_wh: float = 0.0,
    voltage: float = 230.0,
    current: float = 0.0,
    temperature_c: float = 25.0,
    output: bool = False,
) -> dict:
    """A Plus Plug S `status/switch:0` payload (Gen2 RPC shape), defaults as the Docker `_seed`.

    The temperature block is part of every real payload; no sensor of this repo reads it.
    """
    return {
        "id": 0,
        "source": "timer",
        "output": output,
        "apower": apower,
        "voltage": voltage,
        "freq": 50.0,
        "current": current,
        "aenergy": {"total": energy_wh, "by_minute": [0.0, 0.0, 0.0], "minute_ts": 1762700000},
        "temperature": {"tC": temperature_c, "tF": round(temperature_c * 9 / 5 + 32, 1)},
    }


# Expected states for the default payload; a case overrides what it changes.
_DEFAULT_EXPECT = {"power": near(0.0), "energy": near(0.0), "voltage": near(230.0),
                   "current": near(0.0)}

# Reset payload: values no case expects (the switch is set per case, see the docstring).
_RESET = {"apower": 1.1, "energy_wh": 999.0, "voltage": 200.0, "current": 0.111}
_RESET_EXPECT = {"power": near(1.1), "energy": near(0.999), "voltage": near(200.0),
                 "current": near(0.111)}


@dataclass
class Case:
    """One payload and what each of the five entities must show for it."""

    name: str
    payload: dict = field(default_factory=dict)  # keyword overrides for `_status`
    expect: dict[str, Callable[[str], bool]] = field(default_factory=dict)

    @property
    def output(self) -> bool:
        """The relay state this case publishes."""
        return bool(self.payload.get("output", False))


# One case per former Docker test (same names, same values), plus the spike's ingest case.
# Every case now checks all five entities (Docker checked only the one it named).
CASES = [
    Case("power_sensor", {"apower": 597.7}, {"power": near(597.7)}),
    # aenergy.total is Wh; the template divides by 1000 and rounds to 3 decimals.
    Case("energy_wh_to_kwh_conversion", {"energy_wh": 1538.121}, {"energy": near(1.538)}),
    Case("energy_zero", {"energy_wh": 0.0}, {"energy": near(0.0)}),
    Case("voltage_sensor", {"voltage": 235.3}, {"voltage": near(235.3)}),
    Case("current_sensor", {"current": 2.667}, {"current": near(2.667)}),
    Case("switch_on", {"output": True}),
    Case("switch_off", {"output": False}),
    Case("pump_running_scenario",
         {"apower": 597.7, "energy_wh": 1538.0, "voltage": 235.3, "current": 2.667,
          "temperature_c": 42.1, "output": True},
         {"power": near(597.7), "energy": near(1.538), "voltage": near(235.3),
          "current": near(2.667)}),
    Case("pump_idle_scenario", {"apower": 0.0, "output": False}, {"power": near(0.0)}),
    # Spike port: raw firmware values with more decimals than the sensors keep.
    Case("ingest_rounds_like_the_firmware_values",
         {"apower": 597.66, "energy_wh": 12345.6, "voltage": 231.04, "current": 2.6123,
          "output": True},
         {"power": near(597.7), "energy": near(12.346), "voltage": near(231.0),
          "current": near(2.612)}),
]
# Docker `test_temperature_sensor` is NOT carried over: it seeded and read back
# `sensor.pool_pump_temperature`, which no YAML in this repo defines (energy.yaml has no
# temperature sensor). The temperature is still in every payload above.


async def test_pool_pump_sensors(ha: HomeAssistant, broker: Broker) -> None:
    """All pool pump cases on one HA; every failing case is listed in the one assert."""
    ids = {key: entity_id(ha, domain, "mqtt", uid) for key, (domain, uid) in _ENTITIES.items()}
    await wait_subscribed(ha, broker, _TOPIC)
    failures: list[str] = []
    for case in CASES:
        # Reset, with the relay opposite to the case, and prove all five entities took it.
        await publish(ha, broker, _TOPIC, _status(**_RESET, output=not case.output))
        await mqtt_sync(ha, broker)
        reset_switch = {"switch": is_state("off" if case.output else "on")}
        failures += check_states(ha, ids, _RESET_EXPECT | reset_switch, f"{case.name} (reset)")
        # The case's payload; every entity is checked (defaults where the case changes nothing).
        await publish(ha, broker, _TOPIC, _status(**case.payload))
        await mqtt_sync(ha, broker)
        expect = _DEFAULT_EXPECT | case.expect | {"switch": is_state("on" if case.output else "off")}
        failures += check_states(ha, ids, expect, case.name)
    assert not failures, f"{len(failures)} pool pump check(s) failed:\n" + "\n".join(failures)
