"""Pergola automation and template sensor tests.

Each test corresponds to one scenario from the former tests/scenarios.yaml.
All tests start from the baseline state applied by conftest autouse fixtures, then
apply test-specific overrides, trigger the relevant automation, and assert outcomes.

Automation entity IDs come from the `id:` field in packages/pergola.yaml.
"""

import pytest
from ha_integration_test_harness import HomeAssistant, TimeMachine


# ── Cover-response formula tests ─────────────────────────────────────────────────────────
# These tests verify that the correct slat-angle formula branch is selected and that
# the movement script writes the expected value. sensor.pergola_effective_sun_angle is
# seeded directly to avoid the sun integration race (sun.sun is recomputed by the
# built-in integration and can overwrite attributes seconds after seeding).


def test_baseline_cooling_optimized(home_assistant: HomeAssistant, midday_sun: None) -> None:
    """Optimized cooling: A_eff=67.9° → flip guard fails → slat = mow-5 = 13.0°."""
    home_assistant.set_state("sensor.pergola_effective_sun_angle", "67.9",
                             {"unit_of_measurement": "°"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    # Deadband (|current_tilt(50) - target_tilt(~16)| = 34 ≥ DB(4)) passes.
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "13.0", timeout=5)


def test_cooling_unoptimized(home_assistant: HomeAssistant, midday_sun: None) -> None:
    """Standard (non-optimized) cooling: A_eff=67.9° → slat = max(A_eff-90, LB) = 15.0°."""
    home_assistant.call_action("input_boolean", "turn_off",
                               {"entity_id": "input_boolean.pergola_cooling_optimized"})
    home_assistant.set_state("sensor.pergola_effective_sun_angle", "67.9",
                             {"unit_of_measurement": "°"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "15.0", timeout=5)


def test_heating_mode(home_assistant: HomeAssistant, midday_sun: None) -> None:
    """Heating mode: slat = max(A_eff=67.9°, min_heat=33.5°) = 67.9°."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.pergola_heating"})
    home_assistant.call_action("input_boolean", "turn_off",
                               {"entity_id": "input_boolean.pergola_cooling_optimized"})
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "sun_automatik_heating",
    })
    home_assistant.set_state("sensor.pergola_effective_sun_angle", "67.9",
                             {"unit_of_measurement": "°"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "67.9", timeout=5)


def test_automation_disabled(home_assistant: HomeAssistant, midday_sun: None) -> None:
    """Master switch off: script gate suppresses write → effective_slat stays at seeded 0."""
    home_assistant.call_action("input_boolean", "turn_off",
                               {"entity_id": "input_boolean.pergola_automatic_enabled"})
    # midday_sun fixture may have triggered cover_response during setup (time_pattern fires
    # on the clock jump) and written 13.0 to last_set_slat_angle. Reset explicitly now that
    # the gate is closed so the starting value is deterministic.
    home_assistant.call_action("input_number", "set_value", {
        "entity_id": "input_number.pergola_last_set_slat_angle",
        "value": 0,
    })
    home_assistant.set_state("sensor.pergola_effective_sun_angle", "67.9",
                             {"unit_of_measurement": "°"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    # Script exits early at the pergola_automatic_enabled gate; last_set_slat_angle stays 0.
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "0.0", timeout=5)


# ── State-manager tests ──────────────────────────────────────────────────────────────────
# These tests verify rules 1–5 of the state machine. Rules 1–4 are evaluated directly
# inside pergola_state_manager; rule 5 is evaluated via script.pergola_evaluate_state
# which state_manager calls asynchronously when rules 1–4 do not match.


def test_not_enough_sun(home_assistant: HomeAssistant, low_elevation_sun: None) -> None:
    """evaluate_state Rule 5: elevation < min_sun_elevation=10° → no_sun_behind_house → slat=90."""
    # low_elevation_sun pins the clock to June 21 04:00 UTC so the sun integration
    # computes elevation ≈ 3° — stable across runs. Fixture asserts it settled before here.
    # Keep sun_shining=on so Rule 6 (not_enough_sun) does not compete with Rule 5.
    home_assistant.set_state("binary_sensor.pergola_sun_shining", "on", {})
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "not_enough_sun",
    })
    # Low solar values match the original scenario for completeness.
    home_assistant.set_state("sensor.solar_yield_watts", "30", {"unit_of_measurement": "W"})
    home_assistant.set_state("sensor.wheatherstation_solar_radiation", "40",
                             {"unit_of_measurement": "W/m²"})
    home_assistant.set_state("sensor.wheatherstation_uv_index", "0.5", {})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    # state_manager → Rule 5 → sets state to no_sun_behind_house.
    # Explicitly trigger cover_response (automations do not fire automatically in harness).
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    # no_sun_behind_house branch has no deadband → unconditional move to 90°.
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "90.0", timeout=10)


def test_no_sun_behind_house(home_assistant: HomeAssistant) -> None:
    """no_sun_behind_house state: cover_response dispatches to slat=90 unconditionally."""
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "no_sun_behind_house",
    })
    home_assistant.set_state("sun.sun", "above_horizon", {"elevation": 25, "azimuth": 350})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "90.0", timeout=5)


def test_frost_entry(home_assistant: HomeAssistant) -> None:
    """Rule 1 ENTRY: temp < 2.5°C → state=frost; cover_response no-op; template slat=90."""
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "-1.5",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state", "frost", timeout=5)
    # Template sensor pergola_slat_angle returns 90° for frost state (else-branch neutral).
    home_assistant.assert_entity_state("sensor.pergola_slat_angle", "90", timeout=3)


def test_frost_recovery(home_assistant: HomeAssistant, midday_sun: None) -> None:
    """Rule 1 EXIT: temp > 3.0°C with state=frost → async exit; state leaves frost."""
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "frost",
    })
    # Explicit sun seed so evaluate_state (called async inside pergola_exit_to_normal)
    # sees a deterministic in-window azimuth and selects the correct sun state.
    home_assistant.set_state("sun.sun", "above_horizon", {"elevation": 45, "azimuth": 180})
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "5.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    # Script runs async — allow it to settle before asserting the state transition.
    home_assistant.assert_entity_state(
        "input_select.pergola_automation_state",
        lambda s: s != "frost",
        timeout=5,
    )


def test_rain_starts(home_assistant: HomeAssistant) -> None:
    """Rule 2 ENTRY: rain_rate > 0 → state=rain; cover_response no-op; template slat=90."""
    home_assistant.set_state("sensor.wheatherstation_rain_rate", "2.5",
                             {"unit_of_measurement": "mm/h"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state", "rain", timeout=5)
    home_assistant.assert_entity_state("sensor.pergola_slat_angle", "90", timeout=3)


def test_post_rain_recovery(home_assistant: HomeAssistant) -> None:
    """Template: sensor.pergola_rain_recovery_step returns step counter when state=rain_stopped."""
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "rain_stopped",
    })
    home_assistant.call_action("input_number", "set_value", {
        "entity_id": "input_number.pergola_rain_recovery_step",
        "value": 1,
    })
    # Template returns step counter for rain_stopped state — proves both the state guard
    # (protected-state kept state=rain_stopped) and the step counter are correct.
    home_assistant.assert_entity_state("sensor.pergola_rain_recovery_step", "1", timeout=3)


def test_user_override_left(home_assistant: HomeAssistant) -> None:
    """Rule 4 ENTRY: dach_links originator=user → state=user_override."""
    home_assistant.set_state("sensor.dach_links_priority_lock_originator", "user", {})
    home_assistant.set_state("sensor.dach_links_priority_lock_timer", "300", {})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state",
                                       "user_override", timeout=5)


def test_rain_lock_from_cover(home_assistant: HomeAssistant) -> None:
    """Rule 2 ENTRY via cover lock: both originators=rain → state=rain; slat_angle=90."""
    home_assistant.set_state("sensor.dach_links_priority_lock_originator", "rain", {})
    home_assistant.set_state("sensor.dach_rechts_priority_lock_originator", "rain", {})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state", "rain", timeout=5)
    home_assistant.assert_entity_state("sensor.pergola_slat_angle", "90", timeout=3)


def test_rain_with_user_originator(home_assistant: HomeAssistant) -> None:
    """Rule 2 → USER OVERRIDE: state=rain + dach_links originator=user → user_override."""
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "rain",
    })
    home_assistant.set_state("sensor.wheatherstation_rain_rate", "2.5",
                             {"unit_of_measurement": "mm/h"})
    home_assistant.set_state("sensor.dach_links_priority_lock_originator", "user", {})
    home_assistant.set_state("sensor.dach_rechts_priority_lock_originator", "user", {})
    home_assistant.set_state("sensor.dach_links_priority_lock_timer", "300", {})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state",
                                       "user_override", timeout=5)


def test_sun_down_state(home_assistant: HomeAssistant) -> None:
    """Rule 5: PV=0 AND solar_radiation=0 → state=sun_down; cover_response is a no-op."""
    # Ensure the state machine is not in a protected state before triggering.
    # test_rain_with_user_originator (runs just before this in file order) leaves the
    # lock originator as 'user'. baseline_states resets rain_rate first, which fires
    # the state manager while the lock is still 'user' → Rule 4 Entry → user_override.
    # The protected-state guard then blocks evaluate_state for the rest of the fixture.
    # Resetting to a non-protected state here guarantees the default branch runs.
    home_assistant.call_action("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "not_enough_sun",
    })
    # Seed a non-default slat angle so we can confirm no movement occurs.
    home_assistant.call_action("input_number", "set_value", {
        "entity_id": "input_number.pergola_last_set_slat_angle",
        "value": 45,
    })
    home_assistant.set_state("sensor.solar_yield_watts", "0", {"unit_of_measurement": "W"})
    home_assistant.set_state("sensor.wheatherstation_solar_radiation", "0",
                             {"unit_of_measurement": "W/m²"})
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_state_manager",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("input_select.pergola_automation_state",
                                       "sun_down", timeout=5)
    # cover_response must not move covers when state=sun_down.
    home_assistant.call_action("automation", "trigger", {
        "entity_id": "automation.pergola_cover_response",
        "skip_condition": True,
    })
    home_assistant.assert_entity_state("sensor.pergola_effective_slat_angle", "45.0", timeout=5)
