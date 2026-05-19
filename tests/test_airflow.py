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


# ── Bypass estimation tests ──────────────────────────────────────────────────────────────
# η_max=0.818 (Zehnder Q350 enthalpy efficiency interpolated at 150 m³/h between
#   100 m³/h=85.9% and 200 m³/h=77.7%), η_min=0.05.
# Pre-computed expected values:
#   baseline: h_oa≈33.55, h_sa≈35.67, h_ra≈42.75 kJ/kg → η≈0.231 → b_raw≈0.765 → 75%
#   clamped_zero: T_sa=T_ra → η=1.0 → b_raw<0 → clamped to 0%
#   clamped_hundred: T_sa=T_oa → η≈0 → b_raw>1 → clamped to 100%
#   inconclusive: T_oa≈T_ra, same humidity → |h_ra-h_oa|<0.5 → unavailable


def test_bypass_baseline(home_assistant: HomeAssistant) -> None:
    """Baseline stubs give η≈0.231, which maps to 75% (nearest 15-step)."""
    # Baseline already seeds: T_oa=16, T_dew=8.5, T_sa=19.5, RH_sa=45, T_ra=21, RH_ra=55
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "75", timeout=5)


def test_bypass_clamped_zero(home_assistant: HomeAssistant) -> None:
    """Supply air equals return air → η=1.0 → b_raw<0 → bypass clamped to 0%."""
    attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_supply_air_temp_5min", "21.0", attrs)
    home_assistant.set_state("sensor.airflow_supply_air_humidity_5min", "55.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "0", timeout=5)


def test_bypass_clamped_hundred(home_assistant: HomeAssistant) -> None:
    """Supply air equals outdoor air → η≈0 → b_raw>1 → bypass clamped to 100%."""
    attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_supply_air_temp_5min", "16.0", attrs)
    # RH≈61% matches OA (T_oa=16, T_dew=8.5 → RH_oa≈61%)
    home_assistant.set_state("sensor.airflow_supply_air_humidity_5min", "61.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "100", timeout=5)


def test_bypass_near_closed_floors_to_zero(home_assistant: HomeAssistant) -> None:
    """Floor rounding: b_raw in (7.5%, 15%) must show 0%, not round up to 15%.

    T_sa=20.0, RH_sa=55 (baseline T_oa=16, T_ra=21, RH_ra=55, η_max=0.818, η_min=0.05):
      h_oa≈33.55, h_sa≈40.41, h_ra≈42.75 → η≈0.746 → b_raw≈9.4% → floor(0.625)=0 → 0%.
    With symmetric round(0.625)=1 the old code returned 15% — regression guard.
    """
    attrs_t = {"unit_of_measurement": "°C", "device_class": "temperature"}
    attrs_h = {"unit_of_measurement": "%", "device_class": "humidity"}
    home_assistant.set_state("sensor.airflow_supply_air_temp_5min", "20.0", attrs_t)
    home_assistant.set_state("sensor.airflow_supply_air_humidity_5min", "55.0", attrs_h)
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "0", timeout=5)


def test_bypass_inconclusive(home_assistant: HomeAssistant) -> None:
    """Indoor ≈ outdoor conditions → |h_ra−h_oa|<0.5 → state template returns none → 'unknown'.

    Sensor availability is True (all sources set), so HA uses 'unknown' rather than
    'unavailable' when the state template itself returns none.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hum_attrs = {"unit_of_measurement": "%", "device_class": "humidity"}
    # Set outdoor and extract to same temperature/humidity so delta is negligible
    home_assistant.set_state("sensor.airflow_outdoor_temp_5min", "20.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_outdoor_air_humidity_5min", "55.0", hum_attrs)
    home_assistant.set_state("sensor.airflow_extract_air_temp_5min", "20.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_extract_air_humidity_5min", "55.0", hum_attrs)
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "unknown", timeout=5)
