"""Heating/cooling indicator tests (packages/heating_cooling_indicator.yaml).

The three main thresholds are input_numbers; hysteresis is fixed and relative. The template reads
its own previous state (hysteresis), so each test first pins the indicator to a known state with
set_state, then moves the helpers / the 48h mean.
"""

from ha_integration_test_harness import HomeAssistant

_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_HEAT = "input_number.heating_indicator_heating_below"
_PASSIVE = "input_number.heating_indicator_passive_cooling_above"
_ACTIVE = "input_number.heating_indicator_active_cooling_above"


def _set(ha: HomeAssistant, entity_id: str, value: float) -> None:
    ha.call_action("input_number", "set_value", {"entity_id": entity_id, "value": value})


def test_heating_threshold_is_taken_from_the_helper(home_assistant: HomeAssistant) -> None:
    """Raising 'heating below' to 8 makes a 7 °C mean count as heating (it is neutral at 5)."""
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    _set(home_assistant, _HEAT, 8)
    home_assistant.set_state(_MEAN, "7.0", _C)
    home_assistant.assert_entity_state("sensor.heating_cooling_indicator", "active_heating", timeout=5)


def test_heating_hysteresis_is_one_degree_above_the_threshold(
    home_assistant: HomeAssistant,
) -> None:
    """Leaving heating needs heat + 1: threshold 8 → 8.5 stays heating, 9 goes neutral."""
    _set(home_assistant, _HEAT, 8)
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    home_assistant.set_state(_MEAN, "8.5", _C)
    home_assistant.assert_entity_state("sensor.heating_cooling_indicator", "active_heating", timeout=5)
    home_assistant.set_state(_MEAN, "9.0", _C)
    home_assistant.assert_entity_state("sensor.heating_cooling_indicator", "neutral", timeout=5)


def test_passive_cooling_threshold_is_taken_from_the_helper(
    home_assistant: HomeAssistant,
) -> None:
    """Lowering 'passive cooling above' to 9 makes a 9 °C mean passive cooling (neutral at 11)."""
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    _set(home_assistant, _PASSIVE, 9)
    home_assistant.set_state(_MEAN, "9.0", _C)
    home_assistant.assert_entity_state(
        "sensor.heating_cooling_indicator", "passive_cooling", timeout=5
    )


def test_order_is_enforced_when_passive_is_set_below_heating(
    home_assistant: HomeAssistant,
) -> None:
    """heat 12, passive typed as 6 → effective passive is 14 (heat + 2); 13 °C stays neutral."""
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    _set(home_assistant, _HEAT, 12)
    _set(home_assistant, _PASSIVE, 6)
    home_assistant.set_state(_MEAN, "13.0", _C)
    home_assistant.assert_entity_state("sensor.heating_cooling_indicator", "neutral", timeout=5)


def test_active_cooling_threshold_is_taken_from_the_helper(
    home_assistant: HomeAssistant,
) -> None:
    """Lowering 'active cooling above' to 13 (passive 11) makes a 13 °C mean active cooling."""
    home_assistant.set_state("sensor.heating_cooling_indicator", "passive_cooling", {})
    _set(home_assistant, _ACTIVE, 13)
    home_assistant.set_state(_MEAN, "13.0", _C)
    home_assistant.assert_entity_state(
        "sensor.heating_cooling_indicator", "active_cooling", timeout=5
    )


def test_effective_thresholds_show_the_clamp(home_assistant: HomeAssistant) -> None:
    """heat 12, passive typed 6, active typed 7 → effective passive 14, active 16 (dashboard)."""
    _set(home_assistant, _HEAT, 12)
    _set(home_assistant, _PASSIVE, 6)
    _set(home_assistant, _ACTIVE, 7)
    home_assistant.assert_entity_state(
        "sensor.heating_indicator_passive_cooling_effective",
        lambda s: float(s) == 14.0,
        timeout=5,
    )
    home_assistant.assert_entity_state(
        "sensor.heating_indicator_active_cooling_effective",
        lambda s: float(s) == 16.0,
        timeout=5,
    )
