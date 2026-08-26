"""Wallbox abstraction layer tests (packages/energy.yaml).

sensor.wallbox_power / sensor.wallbox_energy are deliberately source-independent
wrappers: the Energy Dashboard references them, never the go-e MQTT entities.
These tests seed the SOURCE entity and assert on the WRAPPER, so they exercise
the template itself — including the unit normalisation, which exists because the
go-e firmware's discovery payload is free to declare either W/Wh or kW/kWh.

MQTT broker is absent in CI; the go-e source entities are seeded via set_state
(baseline values come from tests/conftest.py::baseline_states).
"""

from ha_integration_test_harness import HomeAssistant

_POWER_SRC = "sensor.go_echarger_homekopp_power_total"
_ENERGY_SRC = "sensor.go_echarger_homekopp_total_energy_charged"


def _seed_power(ha: HomeAssistant, value: float, unit: str = "W") -> None:
    """Seed the go-e total-power source entity with an explicit unit."""
    ha.set_state(
        _POWER_SRC,
        str(value),
        {"unit_of_measurement": unit, "device_class": "power", "state_class": "measurement"},
    )


def _seed_energy(ha: HomeAssistant, value: float, unit: str = "Wh") -> None:
    """Seed the go-e lifetime-energy source entity with an explicit unit.

    Note the source carries no state_class — the go-e discovery payload omits it,
    which is precisely why the wrapper has to supply total_increasing itself.
    """
    ha.set_state(
        _ENERGY_SRC,
        str(value),
        {"unit_of_measurement": unit, "device_class": "energy"},
    )


def test_energy_wh_source_converted_to_kwh(home_assistant: HomeAssistant) -> None:
    """Source reports Wh (go-e API v2 native) → wrapper divides by 1000."""
    _seed_energy(home_assistant, 3500.0, unit="Wh")
    home_assistant.assert_entity_state(
        "sensor.wallbox_energy",
        lambda s: abs(float(s) - 3.5) < 0.001,
        timeout=5,
    )


def test_energy_kwh_source_passed_through(home_assistant: HomeAssistant) -> None:
    """Source already reports kWh → wrapper must NOT divide again."""
    _seed_energy(home_assistant, 3.5, unit="kWh")
    home_assistant.assert_entity_state(
        "sensor.wallbox_energy",
        lambda s: abs(float(s) - 3.5) < 0.001,
        timeout=5,
    )


def test_power_w_source_passed_through(home_assistant: HomeAssistant) -> None:
    """Source reports W (go-e nrg[11] native) → wrapper passes it straight through."""
    _seed_power(home_assistant, 11040.0, unit="W")
    home_assistant.assert_entity_state(
        "sensor.wallbox_power",
        lambda s: abs(float(s) - 11040.0) < 0.1,
        timeout=5,
    )


def test_power_kw_source_converted_to_w(home_assistant: HomeAssistant) -> None:
    """Source reports kW → wrapper multiplies by 1000."""
    _seed_power(home_assistant, 11.04, unit="kW")
    home_assistant.assert_entity_state(
        "sensor.wallbox_power",
        lambda s: abs(float(s) - 11040.0) < 0.1,
        timeout=5,
    )


def test_power_zero_while_idle(home_assistant: HomeAssistant) -> None:
    """Not charging → 0 W, not unavailable (the charger is still publishing)."""
    _seed_power(home_assistant, 0.0, unit="W")
    home_assistant.assert_entity_state(
        "sensor.wallbox_power",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_energy_unavailable_source_propagates(home_assistant: HomeAssistant) -> None:
    """Charger off MQTT → wrapper is unavailable, so the dashboard shows a gap
    rather than a fabricated counter reading."""
    home_assistant.set_state(_ENERGY_SRC, "unavailable", {})
    home_assistant.assert_entity_state("sensor.wallbox_energy", "unavailable", timeout=5)


def test_power_unavailable_source_propagates(home_assistant: HomeAssistant) -> None:
    """Charger off MQTT → power wrapper is unavailable rather than a false 0."""
    home_assistant.set_state(_POWER_SRC, "unavailable", {})
    home_assistant.assert_entity_state("sensor.wallbox_power", "unavailable", timeout=5)
