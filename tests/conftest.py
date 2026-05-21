"""Session and per-test fixtures for Home Assistant integration tests.

Replaces seed_state.py and the manual HA container management in ha_check_frenk.yaml.
The ha_integration_test_harness plugin provides the `home_assistant` and `time_machine`
session-scoped fixtures automatically via its installed conftest.
"""

import pytest
from datetime import timedelta

from ha_integration_test_harness import HomeAssistant, TimeMachine


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
        "input_number.airflow_bypass_efficiency_max": 0.818,
        "input_number.airflow_bypass_efficiency_min": 0.05,
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
    # Victron MQTT sensors — all power sensors at 0 W so template sensors start
    # at 0 and energy accumulators do not advance during unrelated tests.
    attrs_w = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
    ha.set_state("sensor.victron_vebus_dc_power", "0", attrs_w)
    ha.set_state("sensor.victron_dc_pv_total_power", "0", attrs_w)
    ha.set_state("sensor.victron_battery_power", "0", attrs_w)
    ha.set_state("sensor.victron_grid_l1_power", "0", attrs_w)
    ha.set_state("sensor.victron_grid_l2_power", "0", attrs_w)
    ha.set_state("sensor.victron_grid_l3_power", "0", attrs_w)
    ha.set_state("sensor.victron_ac_load_l1", "0", attrs_w)
    ha.set_state("sensor.victron_ac_load_l2", "0", attrs_w)
    ha.set_state("sensor.victron_ac_load_l3", "0", attrs_w)
    ha.set_state("sensor.victron_ac_inverter_power", "0", attrs_w)
    ha.set_state("sensor.victron_battery_soc", "50",
                 {"unit_of_measurement": "%", "device_class": "battery", "state_class": "measurement"})
    ha.set_state("sensor.victron_battery_voltage", "48.0",
                 {"unit_of_measurement": "V", "device_class": "voltage", "state_class": "measurement"})
    ha.set_state("sensor.victron_battery_current", "0.0",
                 {"unit_of_measurement": "A", "device_class": "current", "state_class": "measurement"})
    ha.set_state("sensor.victron_solar_yield_total_kwh", "0.0",
                 {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
    ha.set_state("sensor.victron_solar_yield_today_kwh", "0.0",
                 {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
    ha.set_state("sensor.victron_solar_pv_voltage", "0.0",
                 {"unit_of_measurement": "V", "device_class": "voltage", "state_class": "measurement"})
    ha.set_state("sensor.victron_ac_inverter_energy_total_kwh", "0.0",
                 {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
    ha.set_state("sensor.victron_vebus_dc_to_ac_energy", "0.0",
                 {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
    ha.set_state("sensor.victron_vebus_ac_to_dc_energy", "0.0",
                 {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
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
    ha.set_state("sensor.comfoconnect_pro_outdoor_air_humidity", "61",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    ha.set_state("sensor.comfoconnect_pro_supply_air_temperature", "19.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.comfoconnect_pro_supply_air_humidity", "45",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    ha.set_state("sensor.comfoconnect_pro_supply_fan_volume", "150",
                 {"unit_of_measurement": "m³/h"})
    # Airflow filter sensors (platform:filter does not compute in CI; seed directly)
    ha.set_state("sensor.airflow_outdoor_temp_5min", "16.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_outdoor_dew_5min", "8.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_outdoor_air_humidity_5min", "61.0",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    ha.set_state("sensor.airflow_supply_air_temp_5min", "19.5",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_supply_air_humidity_5min", "45.0",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
    ha.set_state("sensor.airflow_extract_air_temp_5min", "21.0",
                 {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.set_state("sensor.airflow_extract_air_humidity_5min", "55.0",
                 {"unit_of_measurement": "%", "device_class": "humidity"})
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
def low_elevation_sun(home_assistant: HomeAssistant, time_machine: TimeMachine) -> None:
    """Jump to June 21 at 04:00 UTC — sun just above horizon, elevation ~3° (below min_sun_elevation=10°).

    Linz (48.3°N): June 21 sunrise ≈ 03:47 UTC; at 04:00 UTC elevation ≈ 3°, azimuth ≈ 55°.
    Mirrors midday_sun: pin clock so the sun integration computes a stable low elevation,
    then assert the integration settled before the test proceeds.
    """
    time_machine.jump_to_next(month="Jun", day_of_month=21, hour=4, minute=0, second=0)
    home_assistant.set_state("sun.sun", "above_horizon", {"elevation": 3, "azimuth": 55})
    home_assistant.assert_entity_state(
        "sun.sun",
        expected_state="above_horizon",
        expected_attributes={"elevation": lambda e: float(e) < 10},
        timeout=10,
    )


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
