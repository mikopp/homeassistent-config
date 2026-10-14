"""Heating/cooling indicator tests (packages/heating_cooling_indicator.yaml).

The three main thresholds are input_numbers; hysteresis is fixed and relative. The template reads
its own previous state (hysteresis) and re-renders on any dependency change, so every test:
  1. sets the helpers and waits for the *_effective sensors to settle,
  2. sets the 48h mean to a value consistent with the state it is about to pin,
  3. pins the indicator with set_state,
  4. moves the mean across the boundary under test.
Pinning AFTER the mean is set keeps a late re-render from changing the pinned state.
"""

from ha_integration_test_harness import HomeAssistant

_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_HEAT = "input_number.heating_indicator_heating_below"
_PASSIVE = "input_number.heating_indicator_passive_cooling_above"
_ACTIVE = "input_number.heating_indicator_active_cooling_above"
_IND = "sensor.heating_cooling_indicator"
_EFF_PASSIVE = "sensor.heating_indicator_passive_cooling_effective"
_EFF_ACTIVE = "sensor.heating_indicator_active_cooling_effective"


def _set(ha: HomeAssistant, entity_id: str, value: float) -> None:
    ha.call_action("input_number", "set_value", {"entity_id": entity_id, "value": value})


def _effective(ha: HomeAssistant, entity_id: str, expected: float) -> None:
    """Wait until an effective-threshold sensor reflects the helpers just written."""
    ha.assert_entity_state(entity_id, lambda s: float(s) == expected, timeout=5)


def _pin(ha: HomeAssistant, mean: float, state: str) -> None:
    """Set the mean, then pin the indicator to a state consistent with it."""
    ha.set_state(_MEAN, str(mean), _C)
    ha.set_state(_IND, state, {})


def test_heating_threshold_is_taken_from_the_helper(home_assistant: HomeAssistant) -> None:
    """Raising 'heating below' to 14 makes a 13 °C mean count as heating (neutral at 12)."""
    _set(home_assistant, _HEAT, 14)
    _effective(home_assistant, _EFF_PASSIVE, 16)
    _pin(home_assistant, 15.0, "neutral")
    home_assistant.set_state(_MEAN, "13.0", _C)
    home_assistant.assert_entity_state(_IND, "active_heating", timeout=5)


def test_heating_hysteresis_is_one_degree_above_the_threshold(
    home_assistant: HomeAssistant,
) -> None:
    """Leaving heating needs heat + 1: threshold 14 → 14.5 stays heating, 15 goes neutral."""
    _set(home_assistant, _HEAT, 14)
    _effective(home_assistant, _EFF_PASSIVE, 16)
    _pin(home_assistant, 13.0, "active_heating")
    home_assistant.set_state(_MEAN, "14.5", _C)
    home_assistant.assert_entity_state(_IND, "active_heating", timeout=5)
    home_assistant.set_state(_MEAN, "15.0", _C)
    home_assistant.assert_entity_state(_IND, "neutral", timeout=5)


def test_passive_cooling_threshold_is_taken_from_the_helper(
    home_assistant: HomeAssistant,
) -> None:
    """Lowering 'passive cooling above' to 15 makes a 15 °C mean passive cooling (neutral at 16)."""
    _set(home_assistant, _PASSIVE, 15)
    _effective(home_assistant, _EFF_PASSIVE, 15)
    _pin(home_assistant, 14.0, "neutral")
    home_assistant.set_state(_MEAN, "15.0", _C)
    home_assistant.assert_entity_state(_IND, "passive_cooling", timeout=5)


def test_order_is_enforced_when_passive_is_set_below_heating(
    home_assistant: HomeAssistant,
) -> None:
    """heat 18, passive typed as 10 → effective passive is 20 (heat + 2); 19 °C stays neutral."""
    _set(home_assistant, _HEAT, 18)
    _set(home_assistant, _PASSIVE, 10)
    _effective(home_assistant, _EFF_PASSIVE, 20)
    _pin(home_assistant, 18.5, "neutral")
    home_assistant.set_state(_MEAN, "19.0", _C)
    home_assistant.assert_entity_state(_IND, "neutral", timeout=5)


def test_active_cooling_threshold_is_taken_from_the_helper(
    home_assistant: HomeAssistant,
) -> None:
    """Lowering 'active cooling above' to 18 (passive 16) makes an 18 °C mean active cooling."""
    _set(home_assistant, _ACTIVE, 18)
    _effective(home_assistant, _EFF_ACTIVE, 18)
    _pin(home_assistant, 17.0, "passive_cooling")
    home_assistant.set_state(_MEAN, "18.0", _C)
    home_assistant.assert_entity_state(_IND, "active_cooling", timeout=5)


def test_effective_thresholds_show_the_clamp(home_assistant: HomeAssistant) -> None:
    """heat 18, passive typed 6, active typed 7 → effective passive 20, active 22 (dashboard)."""
    _set(home_assistant, _HEAT, 18)
    _set(home_assistant, _PASSIVE, 6)
    _set(home_assistant, _ACTIVE, 7)
    _effective(home_assistant, _EFF_PASSIVE, 20)
    _effective(home_assistant, _EFF_ACTIVE, 22)
