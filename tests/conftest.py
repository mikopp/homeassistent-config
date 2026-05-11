"""Session and per-test fixtures for Home Assistant integration tests.

Replaces seed_state.py and the manual HA container management in ha_check_frenk.yaml.
The ha_integration_test_harness plugin provides the `home_assistant` and `time_machine`
session-scoped fixtures automatically via its installed conftest.
"""

import pytest
import requests
from datetime import timedelta

from ha_integration_test_harness import HomeAssistant, TimeMachine


# ── Session setup ────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def set_location(home_assistant: HomeAssistant) -> None:
    """Set HA core location to Linz, Austria for reproducible sun calculations.

    Without an explicit location the harness onboarding may default to 0,0 or some
    arbitrary position, making sun elevation/azimuth non-deterministic across runs.
    POST /api/config/core/update fires EVENT_CORE_CONFIG_UPDATE so the sun integration
    recomputes with the new coordinates immediately.
    """
    requests.post(
        f"{home_assistant._base_url}/api/config/core/update",
        headers={
            "Authorization": f"Bearer {home_assistant._access_token}",
            "Content-Type": "application/json",
        },
        json={"latitude": 48.3069, "longitude": 14.2858, "elevation": 266},
        timeout=10,
    ).raise_for_status()
    # Wait for the sun integration to recompute and emit a valid state.
    home_assistant.assert_entity_state(
        "sun.sun", lambda s: s in ("above_horizon", "below_horizon"), timeout=15
    )


# ── Per-test baseline fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def baseline_inputs(home_assistant: HomeAssistant) -> None:
    """Reset all pergola and airflow input helpers to known-good values before each test."""
    ha = home_assistant
    ha.call_action("input_boolean", "turn_on",  {"entity_id": "input_boolean.pergola_automatic_enabled"})
    ha.call_action("input_boolean", "turn_off", {"entity_id": "input_boolean.pergola_heating"})
    ha.call_action("input_boolean", "turn_on",  {"entity_id": "input_boolean.pergola_cooling_optimized"})
    ha.call_action("input_boolean", "turn_off", {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    ha.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "sun_automatik_cooling",
    })
    for entity_id, value in {
        "input_number.pergola_pv_conversion_factor": 3.2,
        "input_number.pergola_shading_sensitivity": 0.9,
        "input_number.pergola_min_sun_elevation": 10,
        "input_number.pergola_deadband_angle": 5,
        "input_number.pergola_rain_recovery_step": 0,
        "input_number.pergola_last_set_slat_angle": 0,
        "input_number.airflow_cooling_target_temperature": 21.5,
        "input_number.airflow_min_dew_diff": 2.0,
        "input_number.airflow_min_temp_diff": 1.5,
        "input_number.pergola_max_tilt_angle": 122,
        "input_number.pergola_wall_azimuth": 204,
        "input_number.pergola_slat_width": 22,
        "input_number.pergola_slat_pivot_spacing": 20,
        "input_number.pergola_slat_thickness": 3,
    }.items():
        ha.call_action("input_number", "set_value", {"entity_id": entity_id, "value": value})


@pytest.fixture(autouse=True)
def baseline_states(home_assistant: HomeAssistant, baseline_inputs: None) -> None:
    """Seed all CI-stub entity states (integrations absent in CI) before each test.

    Runs after baseline_inputs to ensure input helpers are set before external stubs;
    this matters for template sensors that read both.
    """
    ha = home_assistant
    # Sun — seeded to midday above_horizon; may be overwritten by the sun integration
    # within seconds if the fake time is set to night. Tests that need a specific sun
    # position use the midday_sun fixture which uses the time machine.
    ha.set_state("sun.sun", "above_horizon", {"elevation": 45, "azimuth": 180})
    # Victron solar charger (MQTT — broker absent in CI)
    ha.set_state("sensor.solar_yield_watts", "1500",
                 {"unit_of_measurement": "W", "device_class": "power"})
    # Weather station (UDP integration — absent in CI)
    ha.set_state("sensor.wheatherstation_outdoor_temperature", "18.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.wheatherstation_solar_radiation", "650",
                 {"unit_of_measurement": "W/m²"})
    ha.set_state("sensor.wheatherstation_uv_index", "5", {})
    ha.set_state("sensor.wheatherstation_hourly_rain", "0",
                 {"unit_of_measurement": "mm"})
    ha.set_state("sensor.wheatherstation_rain_rate", "0",
                 {"unit_of_measurement": "mm/h"})
    ha.set_state("sensor.wheatherstation_outdoor_temperature_48h_mean", "14.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    # Sun-shining binary_sensor — seeded on so evaluate_state Rule 6 (not_enough_sun)
    # does not fire unexpectedly. The template has delay_on/delay_off that prevent it
    # reaching "on" naturally within a CI test run.
    ha.set_state("binary_sensor.pergola_sun_shining", "on", {})
    # Somfy cover priority-lock sensors (UI integration — absent in CI)
    ha.set_state("sensor.dach_links_priority_lock_originator", "none", {})
    ha.set_state("sensor.dach_rechts_priority_lock_originator", "none", {})
    ha.set_state("sensor.dach_links_priority_lock_timer", "0", {})
    ha.set_state("sensor.dach_rechts_priority_lock_timer", "0", {})
    # Somfy covers (UI integration — absent in CI)
    ha.set_state("cover.dach_links", "open", {"current_tilt_position": 50})
    ha.set_state("cover.dach_rechts", "open", {"current_tilt_position": 50})
    # ComfoConnect (absent in CI)
    ha.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    ha.set_state("sensor.comfoconnect_pro_extract_air_temperature", "21.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.comfoconnect_pro_extract_air_humidity", "55",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    ha.set_state("sensor.comfoconnect_pro_outdoor_air_temperature", "16.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.comfoconnect_pro_outdoor_air_dewpoint", "8.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    # Airflow filter sensors (platform:filter does not compute in CI; seed directly)
    ha.set_state("sensor.airflow_outdoor_temp_5min", "16.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_outdoor_dew_5min", "8.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_min_indoor_dew_5min", "12.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_avg_indoor_temp_5min", "22.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_avg_indoor_humidity_5min", "55.0",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    # Heating/cooling indicator (template sensor from another package)
    ha.set_state("sensor.heating_cooling_indicator", "neutral", {})


# ── Shared time-machine fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def midday_sun(home_assistant: HomeAssistant, time_machine: TimeMachine) -> None:
    """Jump to June 21 at 10:00 UTC — sun above_horizon, elevation ~45°, azimuth ~150°.

    Linz (48.3°N): June 21 solar noon ≈ 11:50 UTC; at 10:00 UTC elevation ≈ 45°.
    Uses jump_to_next so subsequent tests jump to the same time next year — sun
    position at June 21 10:00 UTC is identical across years.
    """
    time_machine.jump_to_next(month="Jun", day_of_month=21, hour=10, minute=0, second=0)
    # Seed immediately to prevent a race between the sun integration recomputing and
    # automations reading sun.sun during the first moments after the time jump.
    home_assistant.set_state("sun.sun", "above_horizon", {"elevation": 45, "azimuth": 150})
    home_assistant.assert_entity_state("sun.sun", "above_horizon", timeout=10)
