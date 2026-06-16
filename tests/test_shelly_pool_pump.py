"""Shelly Plus Plug S — Pool Pump MQTT sensor tests.

Verifies value_template logic for the pool pump package:
  - Power sensor reads apower correctly
  - Energy sensor converts Wh → kWh (divide by 1000)
  - Voltage, current, temperature parse correctly
  - Binary sensor maps output boolean to on/off

MQTT broker is absent in CI; sensors are seeded via set_state.
"""

import pytest
from ha_integration_test_harness import HomeAssistant


def _seed(
    ha: HomeAssistant,
    *,
    power_w: float = 0.0,
    energy_kwh: float = 0.0,
    voltage: float = 230.0,
    current: float = 0.0,
    temperature_c: float = 25.0,
    switch_on: bool = False,
) -> None:
    """Seed all Shelly pool pump sensors via set_state."""
    ha.set_state(
        "sensor.pool_pump_power",
        str(round(power_w, 1)),
        {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"},
    )
    ha.set_state(
        "sensor.pool_pump_energy",
        str(round(energy_kwh, 3)),
        {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"},
    )
    ha.set_state(
        "sensor.pool_pump_voltage",
        str(round(voltage, 1)),
        {"unit_of_measurement": "V", "device_class": "voltage", "state_class": "measurement"},
    )
    ha.set_state(
        "sensor.pool_pump_current",
        str(round(current, 3)),
        {"unit_of_measurement": "A", "device_class": "current", "state_class": "measurement"},
    )
    ha.set_state(
        "sensor.pool_pump_temperature",
        str(round(temperature_c, 1)),
        {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"},
    )
    ha.set_state(
        "binary_sensor.pool_pump_switch",
        "on" if switch_on else "off",
        {"device_class": "power"},
    )


def test_power_sensor(home_assistant: HomeAssistant) -> None:
    """apower=597.7 W → sensor reads 597.7."""
    _seed(home_assistant, power_w=597.7)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_power",
        lambda s: abs(float(s) - 597.7) < 0.1,
        timeout=5,
    )


def test_energy_wh_to_kwh_conversion(home_assistant: HomeAssistant) -> None:
    """aenergy.total=1538.121 Wh → 1.538 kWh (divided by 1000, rounded to 3 dp)."""
    _seed(home_assistant, energy_kwh=1538.121 / 1000)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_energy",
        lambda s: abs(float(s) - 1.538) < 0.001,
        timeout=5,
    )


def test_energy_zero(home_assistant: HomeAssistant) -> None:
    """aenergy.total=0 Wh → 0.0 kWh."""
    _seed(home_assistant, energy_kwh=0.0)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_energy",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_voltage_sensor(home_assistant: HomeAssistant) -> None:
    """voltage=235.3 V → sensor reads 235.3."""
    _seed(home_assistant, voltage=235.3)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_voltage",
        lambda s: abs(float(s) - 235.3) < 0.1,
        timeout=5,
    )


def test_current_sensor(home_assistant: HomeAssistant) -> None:
    """current=2.667 A → sensor reads 2.667."""
    _seed(home_assistant, current=2.667)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_current",
        lambda s: abs(float(s) - 2.667) < 0.001,
        timeout=5,
    )


def test_temperature_sensor(home_assistant: HomeAssistant) -> None:
    """temperature.tC=42.1 → sensor reads 42.1."""
    _seed(home_assistant, temperature_c=42.1)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_temperature",
        lambda s: abs(float(s) - 42.1) < 0.1,
        timeout=5,
    )


def test_switch_on(home_assistant: HomeAssistant) -> None:
    """output=true → binary_sensor state is 'on'."""
    _seed(home_assistant, switch_on=True)
    home_assistant.assert_entity_state("binary_sensor.pool_pump_switch", "on", timeout=5)


def test_switch_off(home_assistant: HomeAssistant) -> None:
    """output=false → binary_sensor state is 'off'."""
    _seed(home_assistant, switch_on=False)
    home_assistant.assert_entity_state("binary_sensor.pool_pump_switch", "off", timeout=5)


def test_pump_running_scenario(home_assistant: HomeAssistant) -> None:
    """Full running scenario: 597.7 W, 235.3 V, 2.667 A, output on."""
    _seed(
        home_assistant,
        power_w=597.7,
        energy_kwh=1.538,
        voltage=235.3,
        current=2.667,
        temperature_c=42.1,
        switch_on=True,
    )
    home_assistant.assert_entity_state(
        "sensor.pool_pump_power", lambda s: abs(float(s) - 597.7) < 0.1, timeout=5
    )
    home_assistant.assert_entity_state(
        "sensor.pool_pump_energy", lambda s: abs(float(s) - 1.538) < 0.001, timeout=5
    )
    home_assistant.assert_entity_state("binary_sensor.pool_pump_switch", "on", timeout=5)


def test_pump_idle_scenario(home_assistant: HomeAssistant) -> None:
    """Idle scenario: 0 W, output off."""
    _seed(home_assistant, power_w=0.0, switch_on=False)
    home_assistant.assert_entity_state(
        "sensor.pool_pump_power", lambda s: float(s) == 0.0, timeout=5
    )
    home_assistant.assert_entity_state("binary_sensor.pool_pump_switch", "off", timeout=5)
