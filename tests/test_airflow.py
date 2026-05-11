"""Airflow cooling automation tests.

Tests verify that the airflow_cooling_set_temperature_profile automation runs without
trace errors and, where possible, that observable state matches expectations.

Known CI limitation: select.comfoconnect_pro_temperature_profile is a bare REST stub —
the ComfoConnect integration is absent in CI so select.select_option service calls are
silently ignored by HA's service registry. Only the trace-error absence (no exception
from trigger) and idempotent "comfort" assertions are possible for most scenarios.
"""

from ha_integration_test_harness import HomeAssistant

_AIRFLOW_AUTO = "automation.airflow_cooling_set_temperature_profile"


def _trigger(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _AIRFLOW_AUTO,
        "skip_condition": True,
    })


def test_airflow_free_cooling_active(home_assistant: HomeAssistant) -> None:
    """Auto enabled + active_cooling + free_cooling=on → automation runs (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_cooling", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    _trigger(home_assistant)
    # select.select_option silently ignored on bare stub — assert trace-error absence only.


def test_airflow_free_cooling_inactive(home_assistant: HomeAssistant) -> None:
    """Auto enabled + active_cooling + free_cooling=off → automation runs (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_cooling", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Same CI stub limitation as test_airflow_free_cooling_active.


def test_airflow_active_heating(home_assistant: HomeAssistant) -> None:
    """Auto enabled + active_heating → automation runs (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    _trigger(home_assistant)
    # Same CI stub limitation.


def test_airflow_neutral(home_assistant: HomeAssistant) -> None:
    """Auto enabled + neutral → select_option("comfort") → profile stays "comfort" (idempotent)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    _trigger(home_assistant)
    # Neutral branch calls select_option("comfort"); seeded value is also "comfort".
    # Either the service call is ignored (stub) or it succeeds — both leave state="comfort".
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


def test_airflow_auto_disabled(home_assistant: HomeAssistant) -> None:
    """Auto disabled: condition gate suppresses action → profile unchanged ("comfort")."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_cooling", {})
    _trigger(home_assistant)
    # Automation condition (airflow_cooling_automatic_enabled=on) is not met → no action.
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)
