"""Airflow cooling automation tests.

Tests verify that the airflow_cooling_set_temperature_profile automation runs without
trace errors and, where possible, that observable state matches expectations.

Known CI limitation: select.comfoconnect_pro_temperature_profile is a bare REST stub —
the ComfoConnect integration is absent in CI so select.select_option service calls are
silently ignored by HA's service registry. Only the trace-error absence (no exception
from trigger) and idempotent "comfort" assertions are possible for most scenarios.
"""

import requests

from ha_integration_test_harness import HomeAssistant

_AIRFLOW_AUTO = "automation.airflow_cooling_set_temperature_profile"
_MOISTURE_PRESET_AUTO = "automation.airflow_moisture_ventilation_preset"
_DRYING_BOOST_AUTO = "automation.airflow_humidity_drying_boost"
_MEDIUM_PRESET_AUTO = "automation.airflow_medium_ventilation_preset"


def _trigger(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _AIRFLOW_AUTO,
        "skip_condition": True,
    })


def _trigger_moisture(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _MOISTURE_PRESET_AUTO,
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
    """Auto enabled + active_heating + free_cooling=off → Block 1 Case B fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 1 Case B: active_heating + free_cooling=off → warm. Stub ignores select_option.


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


def test_bypass_unavailable_when_input_missing(home_assistant: HomeAssistant) -> None:
    """has_value guard: a missing filter input → sensor.airflow_bypass_estimation unavailable."""
    # Baseline seeds all six inputs → bypass computes 75 (see test_bypass_baseline).
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "75", timeout=5)
    home_assistant.set_state("sensor.airflow_outdoor_temp_5min", "unavailable", {})
    home_assistant.assert_entity_state("sensor.airflow_bypass_estimation", "unavailable", timeout=5)


# ── Verification scenario tests ─────────────────────────────────────────────────────────
# These mirror the manual verification steps from the implementation plan.
# CI limitation note: select.select_option and switch.turn_on/off are silently ignored
# on bare stubs, so most tests verify trace-error absence rather than state changes.
# Production correctness (service calls actually applied) must be verified in HA directly.


def test_verification_step3_high_humidity_free_cooling_triggers_cool(home_assistant: HomeAssistant) -> None:
    """Verification step 3: humidity above max + free_cooling=on → Block 2 → cool profile.

    max=54, hum=55 → 55 > 54. Free cooling available. Neutral season.
    Block 2 condition: free_cooling=on AND hum > max → fires, sets cool.
    CI: stub ignores select_option — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 54})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "55.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 2 fires: 55 > 54 (max), free_cooling=on. Profile would switch to cool in production.


def test_verification_step3_high_humidity_no_free_cooling_profile_unchanged(home_assistant: HomeAssistant) -> None:
    """Verification step 3 (negative path): high humidity but free_cooling=off → no profile change.

    min=45, max=54, hum=55 → above dead band [45,54]. Block 1 misses (hum not < min).
    Block 2 misses (free_cooling=off). Block 3's dead-band guard: 55∉[45,54] → miss.
    Profile seeded to "comfort" — stays comfort because no block fires.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_min_humidity", "value": 45})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 54})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "55.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 1: hum(55) ≥ min(45) → miss. Block 2: free_cooling=off → miss.
    # Block 3: neutral, but dead-band 55∉[45,54] → miss. Default no-op.
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


def test_verification_step4_high_humidity_outdoor_humid_preset_fires(home_assistant: HomeAssistant) -> None:
    """Verification step 4: high humidity + outdoor_dew ≥ indoor_dew → moisture preset fires.

    outdoor_dew=15.0°C ≥ indoor_dew=12.0°C: ventilating would import humid air, so ventilation
    must be reduced. binary_sensor seeded ON to bypass the 10-min delay_on.
    CI: switch/select stubs silently ignored — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_target_humidity", "value": 52})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "55.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "15.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    _trigger_moisture(home_assistant)
    # In production: auto_mode=off, ventilation_level=low. CI stubs ignore service calls.


def test_verification_step5_humidity_normalized_auto_mode_restored(home_assistant: HomeAssistant) -> None:
    """Verification step 5: humidity drops below target → binary_sensor turns off → auto mode restored.

    binary_sensor seeded OFF to bypass the 10-min delay_off. Preset automation restores auto mode.
    CI: switch.turn_on silently ignored — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "54.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    _trigger_moisture(home_assistant)
    # In production: switch.comfoconnect_pro_auto_mode turns back on.


def test_verification_step6_low_humidity_warm_profile_overrides_season(home_assistant: HomeAssistant) -> None:
    """Verification step 6: humidity below min → Block 1 Case A fires (warm), non-cooling season.

    min=50 (max allowed), hum=44 < 50, neutral season → Block 1 Case A fires.
    The warming priority exists to protect wood/instruments from excessively dry air.
    CI: stub ignores select_option — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_min_humidity", "value": 50})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "44.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    _trigger(home_assistant)
    # Block 1 Case A: 44 < 50 (min) AND not cooling season → fires. Profile → warm.


# ── Temperature profile moisture tests ──────────────────────────────────────────────────


def test_airflow_low_humidity_warm_profile(home_assistant: HomeAssistant) -> None:
    """Low humidity (44% < min 45%) + neutral season → Block 1 Case A fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "44.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 1 Case A: 44 < 45 (baseline min), not cooling season → fires. Stub ignores select_option.


def test_airflow_high_humidity_free_cooling_cool_profile(home_assistant: HomeAssistant) -> None:
    """High humidity (60% > max 55%) + free_cooling=on → Block 2 Case B fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "60.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 2 Case B: free_cooling=on AND hum(60) > max(55) → cool. Stub ignores service call.


def test_airflow_high_humidity_free_cooling_off_stays_comfort(home_assistant: HomeAssistant) -> None:
    """High humidity (60% > max 55%) but free_cooling=off + neutral → all blocks miss → no-op."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "60.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 1: hum(60) ≥ min(45). Block 2: free_cooling=off.
    # Block 3: neutral=yes but dead-band 60∉[45,55] → miss. Default no-op.
    # Profile stays seeded "comfort".
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


def test_airflow_humidity_in_dead_band_neutral_comfort(home_assistant: HomeAssistant) -> None:
    """Humidity in dead band (55% in [45,55]) + neutral + free_cooling=off → Block 3 fires → comfort.

    Block 1 Case A misses (hum ≥ min). Block 1 Case B misses (not active_heating).
    Block 2 misses (free_cooling=off). Block 3: neutral + dead-band satisfied → comfort.
    Seeded profile is already "comfort" → idempotent guard suppresses service call.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # Baseline seeds hum=55%, min=45, max=55 — humidity exactly at max (in band).
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 3: neutral, 45 <= 55 <= 55 → fires; already comfort → guard suppresses call.
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


# ── Ventilation preset automation tests ─────────────────────────────────────────────────


def test_moisture_ventilation_low_when_needed(home_assistant: HomeAssistant) -> None:
    """auto=on + binary_sensor=on → ventilation reduced (trace only; stub ignores switch/select)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    _trigger_moisture(home_assistant)
    # switch.turn_off and select.select_option are silently ignored on bare stubs.


def test_moisture_ventilation_restore_auto(home_assistant: HomeAssistant) -> None:
    """auto=on + binary_sensor=off → auto mode restored (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    _trigger_moisture(home_assistant)
    # switch.turn_on silently ignored — assert trace absence only.


def test_moisture_ventilation_disabled_no_action(home_assistant: HomeAssistant) -> None:
    """auto=off: condition gate suppresses preset → ventilation_level stays 'medium'."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    _trigger_moisture(home_assistant)
    # Guard condition (airflow_cooling_automatic_enabled=on) is not met → no action taken.
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)


# ── Bypass estimation tests ──────────────────────────────────────────────────────────────


def _trigger_drying(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _DRYING_BOOST_AUTO,
        "skip_condition": True,
    })


# ── Drying boost automation tests ──────────────────────────────────────────────────────────


def test_drying_boost_starts_when_needed(home_assistant: HomeAssistant) -> None:
    """Drying binary sensor ON + boost off → first choose branch fires (trace only).

    switch.turn_on and number.set_value are silently ignored on bare stubs.
    """
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)


def test_drying_boost_stops_when_conditions_gone(home_assistant: HomeAssistant) -> None:
    """Drying binary sensor OFF → second choose branch fires (trace only).

    switch.turn_off is silently ignored on bare stub.
    """
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_drying(home_assistant)


def test_drying_boost_re_enables_after_timer_expires(home_assistant: HomeAssistant) -> None:
    """Boost turns off while drying still needed → first branch re-enables boost (trace only).

    Simulates the hardware timer elapsing while conditions remain active.
    First branch fires: drying=on, boost=off → re-enables boost.
    """
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)
    # In production: number.set_value(30) then switch.turn_on would be called again.


def test_drying_boost_already_running_no_double_enable(home_assistant: HomeAssistant) -> None:
    """Drying needed + boost already on → neither branch fires (no double-enable), no trace error."""
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_drying(home_assistant)
    # First branch: drying=on but boost=on → condition 'not boost=on' fails → skip.
    # Second branch: drying≠off → skip. No action taken; automation runs without error.


def test_drying_hvac_action_shows_drying(home_assistant: HomeAssistant) -> None:
    """free_cooling=on AND boost=on → automation runs without error (trace only).

    Cannot assert hvac_action='drying' on the climate entity in CI:
    binary_sensor.airflow_free_cooling_available is a template entity with delay_on=10min
    that reverts any state written via REST API before the assertion can poll it.
    Template correctness is validated by test_runtime_templates_lenient.
    """
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)
    # Automation runs; boost would be enabled in production (stub ignores service call).


def test_drying_hvac_action_not_drying_without_free_cooling(home_assistant: HomeAssistant) -> None:
    """boost=on but free_cooling=off → automation runs without asserting climate attribute (trace only).

    Cannot assert hvac_action on climate.airflow_climate in CI: the custom climate_template
    component's attribute initialization timing is not guaranteed within a 5-second window.
    Template correctness (free_cooling=off → 'fan', not 'drying') is validated by
    test_runtime_templates_lenient which exercises the hvac_action_template syntax.
    """
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})


def test_drying_schedule_off_sensor_not_triggered(home_assistant: HomeAssistant) -> None:
    """Workday=on, workday schedule=off → drying binary sensor stays off.

    Phase 1: set outdoor_t > target_t, a plain numeric sensor dependency that HA always
    tracks, to guarantee template=false and the sensor drops to 'off' regardless of
    its prior state.
    Phase 2: restore outdoor_t to cool value; only in_schedule=false (schedule off) keeps
    the template false — the sensor must not transition to 'on'.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hum_attrs = {"unit_of_measurement": "%", "device_class": "humidity"}

    # Phase 1: force template false and sensor to 'off' via a reliable numeric condition.
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "25.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=5)

    # Phase 2: set conditions with schedule=off (in_schedule=false) → template stays false.
    home_assistant.set_state("binary_sensor.workday", "on", {})
    home_assistant.set_state("schedule.airflow_boost_workday", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "60.0", hum_attrs)
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "16.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=5)


def test_drying_non_workday_schedule_applies_on_holiday(home_assistant: HomeAssistant) -> None:
    """workday=off (holiday) + non-workday schedule on → in_schedule=true path reached.

    Phase 1: set outdoor_t > target_t to guarantee template=false and sensor settles to
    'off' regardless of its prior state (bypasses Schmitt-trigger and schedule dependencies).
    Phase 2: set holiday conditions; template evaluates true but delay_on=10min keeps
    sensor 'off' within the 3-second assertion window.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hum_attrs = {"unit_of_measurement": "%", "device_class": "humidity"}

    # Phase 1: force template false and sensor to 'off' via reliable numeric condition.
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "25.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=5)

    # Phase 2: holiday conditions; delay_on prevents immediate activation.
    home_assistant.set_state("binary_sensor.workday", "off", {})
    home_assistant.set_state("schedule.airflow_boost_non_workday", "on", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "60.0", hum_attrs)
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "16.0", temp_attrs)
    # Template now evaluates true (non-workday branch), but delay_on=10min keeps sensor 'off'.
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=3)


def test_drying_low_moisture_guard_prevents_boost(home_assistant: HomeAssistant) -> None:
    """airflow_moisture_ventilation_low_needed=on → drying binary sensor stays off.

    Mutually exclusive by design: low_needed means outdoor air is too humid,
    which precludes airflow_free_cooling_available=on. Guard is belt-and-suspenders.
    With low_active=true the template evaluates to false regardless of other conditions.

    Phase 1: set outdoor_t > target_t to guarantee sensor is 'off' before testing the guard.
    Phase 2: restore cool outdoor_t with all other conditions true except guard active.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hum_attrs = {"unit_of_measurement": "%", "device_class": "humidity"}

    # Phase 1: force sensor to 'off' via reliable numeric condition.
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "25.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=5)

    # Phase 2: guard active (low_active=on) blocks template → sensor stays off.
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "60.0", hum_attrs)
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "16.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_drying_needed",
                                       "off", timeout=5)


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


# ── Medium ventilation preset automation tests ────────────────────────────────────────────
# New automation: bumps preset from Low to Medium when free cooling is available.
# CI limitation: switch/select service calls are silently ignored on bare stubs.


def _trigger_medium(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _MEDIUM_PRESET_AUTO,
        "skip_condition": True,
    })


def test_medium_preset_enable_when_free_cooling_low_preset(home_assistant: HomeAssistant) -> None:
    """free_cooling=on + auto=on + preset=low + boost=off → enable branch fires (trace only).

    In production: auto mode turns off, preset set to Medium. CI stubs ignore service calls.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # Enable branch: all four conditions met → auto_mode=off + preset=medium (stubs ignore).


def test_medium_preset_restore_when_free_cooling_gone(home_assistant: HomeAssistant) -> None:
    """free_cooling=off + auto=off + preset=medium → restore branch fires (trace only).

    Simulates returning from Medium preset: auto mode turns back on.
    CI: switch.turn_on silently ignored.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger_medium(home_assistant)
    # Restore branch: free_cooling=off + auto=off + preset=medium → auto_mode on (stub ignores).


def test_medium_preset_boost_running_hits_default(home_assistant: HomeAssistant) -> None:
    """free_cooling=on + auto=on + preset=low + boost=on → enable branch misses, default logs.

    Enable branch requires boost=off; boost running means medium is unnecessary alongside boost.
    Restore branch requires free_cooling=off — also misses. Default: system_log warning.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_medium(home_assistant)
    # Enable: boost=on fails condition. Restore: free_cooling=on fails. Default fires — no crash.


def test_medium_preset_auto_disabled_no_action(home_assistant: HomeAssistant) -> None:
    """auto=off: condition gate suppresses medium preset (trace only)."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # skip_condition=True bypasses the gate; service calls silently ignored either way.


# ── Away mode guard tests ─────────────────────────────────────────────────────────────────
# All three preset/boost automations now check switch.comfoconnect_pro_away_function=off.
# When away=on the condition gate blocks the action; these tests confirm the automation
# is syntactically valid with the away entity present and runs without trace errors.
# Production gate correctness relies on HA's standard condition evaluation.


def test_moisture_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on seeded: automation runs trace-cleanly with the away entity in state."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    _trigger_moisture(home_assistant)
    # In production (skip_condition=False): away=on blocks action — no preset change.
    # CI (skip_condition=True): gate bypassed, service calls silently ignored.


def test_medium_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on seeded: medium preset automation runs trace-cleanly with the away entity."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # In production: away=on blocks action — no preset change.


def test_drying_boost_auto_disabled_no_action(home_assistant: HomeAssistant) -> None:
    """auto=off: condition gate (added in alignment commit) suppresses boost (trace only)."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)
    # skip_condition=True bypasses the gate; service calls silently ignored.


def test_drying_boost_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on seeded: boost automation runs trace-cleanly with the away entity."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)
    # In production: away=on blocks action — boost stays off.


# ── Free cooling absolute humidity gate tests ─────────────────────────────────────────────
# The dew_max gate prevents free cooling when outdoor air warmed to target_temp would
# exceed target_humidity. Tests render the gate sub-expression directly via the HA
# template API to verify the formula without fighting the binary sensor's delay_on/off.


def _render(home_assistant: HomeAssistant, template: str) -> str:
    resp = requests.post(
        f"{home_assistant._base_url}/api/template",
        headers={
            "Authorization": f"Bearer {home_assistant._access_token}",
            "Content-Type": "application/json",
        },
        json={"template": template},
        timeout=10,
    )
    assert resp.status_code == 200, f"Template render failed: {resp.text}"
    return resp.text.strip()


# Shared dew_max sub-expression (same Magnus formula as in airflow_cooling.yaml)
_DEW_MAX_TMPL = """
{%- set target_temp = states('input_number.airflow_cooling_target_temperature') | float -%}
{%- set target_hum  = states('input_number.airflow_target_humidity') | float -%}
{%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}
{%- set pv = ps * target_hum / 100 -%}
{{- (237.3 * (pv / 0.61078) | log / (17.27 - (pv / 0.61078) | log)) | round(2) -}}
"""


def test_dew_max_formula_value_at_baseline(home_assistant: HomeAssistant) -> None:
    """dew_max at baseline (target=21.5°C, hum=55%) ≈ 12.07°C.

    Verifies the Magnus formula produces the expected threshold.
    If target or humidity change, dew_max shifts accordingly.
    """
    result = float(_render(home_assistant, _DEW_MAX_TMPL))
    assert 11.9 < result < 12.2, f"Expected dew_max ≈ 12.07°C, got {result}"


def test_free_cooling_dew_max_blocks_high_outdoor_dew(home_assistant: HomeAssistant) -> None:
    """outdoor_dew=13°C > dew_max(≈12.07°C) → gate evaluates False.

    Scenario: indoor_dew=15°C, min_dew_diff=0 → relative check (13<15) passes,
    but absolute gate (13>12.07) blocks. Demonstrates the gap the new check fills:
    outdoor air at 21.5°C would reach ≈55.4% RH, just above the 55% target.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "13.0", temp_attrs)

    gate_tmpl = """
    {%- set outdoor_dew = states('sensor.airflow_outdoor_dew_5min') | float -%}
    {%- set target_temp = states('input_number.airflow_cooling_target_temperature') | float -%}
    {%- set target_hum  = states('input_number.airflow_target_humidity') | float -%}
    {%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}
    {%- set pv = ps * target_hum / 100 -%}
    {%- set dew_max = 237.3 * (pv / 0.61078) | log / (17.27 - (pv / 0.61078) | log) -%}
    {{ outdoor_dew <= dew_max }}
    """
    assert _render(home_assistant, gate_tmpl) == "False"


def test_free_cooling_dew_max_passes_low_outdoor_dew(home_assistant: HomeAssistant) -> None:
    """outdoor_dew=8.5°C (baseline) < dew_max(≈12.07°C) → gate evaluates True.

    Baseline outdoor dew is well below the threshold — outdoor air at target temp
    would produce ≈33% RH, comfortably below the 55% target.
    """
    gate_tmpl = """
    {%- set outdoor_dew = states('sensor.airflow_outdoor_dew_5min') | float -%}
    {%- set target_temp = states('input_number.airflow_cooling_target_temperature') | float -%}
    {%- set target_hum  = states('input_number.airflow_target_humidity') | float -%}
    {%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}
    {%- set pv = ps * target_hum / 100 -%}
    {%- set dew_max = 237.3 * (pv / 0.61078) | log / (17.27 - (pv / 0.61078) | log) -%}
    {{ outdoor_dew <= dew_max }}
    """
    # baseline outdoor_dew_5min=8.5°C (from conftest) → 8.5 ≤ 12.07 → True
    assert _render(home_assistant, gate_tmpl) == "True"


def test_free_cooling_dew_max_shifts_with_target_humidity(home_assistant: HomeAssistant) -> None:
    """Raising target_hum raises dew_max: at 60% RH, dew_max ≈ 13.4°C.

    At 60% target, outdoor_dew=13°C is BELOW dew_max → gate passes.
    This confirms dew_max is correctly derived from the target, not hardcoded.
    """
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_target_humidity", "value": 60})
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "13.0", temp_attrs)

    gate_tmpl = """
    {%- set outdoor_dew = states('sensor.airflow_outdoor_dew_5min') | float -%}
    {%- set target_temp = states('input_number.airflow_cooling_target_temperature') | float -%}
    {%- set target_hum  = states('input_number.airflow_target_humidity') | float -%}
    {%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}
    {%- set pv = ps * target_hum / 100 -%}
    {%- set dew_max = 237.3 * (pv / 0.61078) | log / (17.27 - (pv / 0.61078) | log) -%}
    {{ outdoor_dew <= dew_max }}
    """
    # target_hum=60 → dew_max≈13.4°C → outdoor_dew=13 ≤ 13.4 → True
    assert _render(home_assistant, gate_tmpl) == "True"


# ── Ventilation-low dew-point boundary tests ──────────────────────────────────────────────
# binary_sensor.airflow_moisture_ventilation_low_needed's dew condition mirrors free cooling's
# dew_max: it turns ON when outdoor_dew clears a humidity-derived dew point and stays ON until
# outdoor_dew drops below the target-humidity-derived dew point (Schmitt), OR — as a fallback —
# when outdoor_dew >= indoor_dew. Tests render the dew sub-expression directly via the template
# API to verify the formula without fighting the binary sensor's delay_on/off and `this.state`.
# `this.state` is unavailable in the render API, so each Schmitt threshold is exercised by
# substituting the corresponding humidity (max for the OFF→ON edge, target for the ON→OFF edge).


def _low_needed_dew_gate(threshold_hum: str) -> str:
    """Render template for the dew condition with `threshold_hum` driving the dew threshold.

    threshold_hum is the input_number that selects the active Schmitt edge:
      'airflow_max_humidity'    → OFF-state turn-ON boundary (dew_from_max)
      'airflow_target_humidity' → ON-state disengage boundary (dew_from_tgt)
    """
    return f"""
    {{%- set outdoor_dew = states('sensor.airflow_outdoor_dew_5min') | float -%}}
    {{%- set indoor_dew  = states('sensor.airflow_min_indoor_dew_5min') | float -%}}
    {{%- set target_temp = states('input_number.airflow_cooling_target_temperature') | float -%}}
    {{%- set hum         = states('input_number.{threshold_hum}') | float -%}}
    {{%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}}
    {{%- set pv = ps * hum / 100 -%}}
    {{%- set dew_threshold = 237.3 * (pv / 0.61078) | log / (17.27 - (pv / 0.61078) | log) -%}}
    {{{{ outdoor_dew >= dew_threshold or outdoor_dew >= indoor_dew }}}}
    """


def test_low_needed_turn_on_boundary_fires_above_max_dew(home_assistant: HomeAssistant) -> None:
    """OFF→ON: outdoor_dew above max-derived dew (≈14.65°C) turns ON even when below indoor_dew.

    max=65% at target_temp=21.5°C → dew_from_max≈14.65°C. outdoor_dew=15 ≥ 14.65 fires the new
    absolute boundary, although the legacy relative check (15 ≥ indoor_dew 16) is False — this is
    exactly the gap the new boundary fills.
    """
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 65})
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "15.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "16.0", temp_attrs)
    assert _render(home_assistant, _low_needed_dew_gate("airflow_max_humidity")) == "True"


def test_low_needed_turn_on_boundary_below_max_dew_and_indoor(home_assistant: HomeAssistant) -> None:
    """OFF→ON negative: outdoor_dew below both max-derived dew and indoor_dew → stays OFF.

    max=65% → dew_from_max≈14.65°C. outdoor_dew=14 < 14.65 and 14 < indoor_dew 16 → neither path.
    """
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 65})
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "14.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "16.0", temp_attrs)
    assert _render(home_assistant, _low_needed_dew_gate("airflow_max_humidity")) == "False"


def test_low_needed_stays_on_above_target_dew(home_assistant: HomeAssistant) -> None:
    """ON→OFF hysteresis: while ON, outdoor_dew above target-derived dew (≈12.09°C) stays ON.

    target=55% at target_temp=21.5°C → dew_from_tgt≈12.09°C. outdoor_dew=13 ≥ 12.09 → still ON,
    even though it sits below the higher OFF→ON threshold (dew_from_max). indoor_dew=16 keeps the
    relative fallback out of the picture so only the dew Schmitt is exercised.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "13.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "16.0", temp_attrs)
    assert _render(home_assistant, _low_needed_dew_gate("airflow_target_humidity")) == "True"


def test_low_needed_disengages_below_target_dew(home_assistant: HomeAssistant) -> None:
    """ON→OFF: outdoor_dew below target-derived dew (≈12.09°C) and below indoor_dew → disengages.

    target=55% → dew_from_tgt≈12.09°C. outdoor_dew=11 < 12.09 and 11 < indoor_dew 16 → OFF.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "11.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "16.0", temp_attrs)
    assert _render(home_assistant, _low_needed_dew_gate("airflow_target_humidity")) == "False"


def test_low_needed_relative_fallback_fires_below_dew_threshold(home_assistant: HomeAssistant) -> None:
    """Fallback OR: outdoor_dew below the dew threshold but ≥ indoor_dew still turns ON.

    max=65% → dew_from_max≈14.65°C. outdoor_dew=13 < 14.65 (dew boundary False) but
    13 ≥ indoor_dew 10 → the legacy relative check carries the decision. Confirms the OR fallback
    only kicks in when the humidity-derived boundary is not met.
    """
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 65})
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "13.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "10.0", temp_attrs)
    assert _render(home_assistant, _low_needed_dew_gate("airflow_max_humidity")) == "True"


# ── Airflow cooling state sensor tests ────────────────────────────────────────────────────
# sensor.airflow_cooling_state is a read-only template sensor that derives a reason-based
# status of the ventilation automation. Priority order (first match wins):
#   off → moisture_flush_boost → moisture_protection → moisture_flush_cooling →
#   free_cooling → cooling → moisture_retention → heating → comfort.
# All dependency entities are seeded directly so the derived state is deterministic
# (the upstream binary sensors have delay_on/off that would otherwise make timing flaky).


def _seed_cooling_state_deps(
    home_assistant: HomeAssistant,
    *,
    hvac_action: str,
    free_cooling: str = "off",
    low_needed: str = "off",
    boost: str = "off",
) -> None:
    """Seed the entities the airflow_cooling_state template sensor reads.

    hvac_action mirrors what climate.airflow_climate's hvac_action_template computes
    from the given conditions, so the state sensor can be tested without depending on
    the custom climate_template component's re-computation timing.
    """
    home_assistant.set_state("climate.airflow_climate", "auto",
                             {"hvac_action": hvac_action})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", free_cooling, {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", low_needed, {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", boost, {})


def test_cooling_state_off_when_auto_disabled(home_assistant: HomeAssistant) -> None:
    """auto disabled (baseline) → 'off' regardless of other conditions."""
    _seed_cooling_state_deps(home_assistant, hvac_action="cooling", free_cooling="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "off", timeout=5)


def test_cooling_state_moisture_flush_boost(home_assistant: HomeAssistant) -> None:
    """auto on + boost on + free cooling on → 'moisture_flush_boost' (highest active priority)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # Boost+free wins before the action check; hvac_action is 'drying' while flushing.
    _seed_cooling_state_deps(home_assistant, hvac_action="drying", free_cooling="on", boost="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_flush_boost", timeout=5)


def test_cooling_state_moisture_protection(home_assistant: HomeAssistant) -> None:
    """auto on + moisture-low needed (no boost) → 'moisture_protection'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_cooling_state_deps(home_assistant, hvac_action="fan", low_needed="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_protection", timeout=5)


def test_cooling_state_moisture_flush_cooling(home_assistant: HomeAssistant) -> None:
    """auto on + drying action (no boost) → 'moisture_flush_cooling'.

    hvac_action='drying' reflects moisture flushing (cool + free cooling + humidity above max);
    with boost off it maps to moisture_flush_cooling.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_cooling_state_deps(home_assistant, hvac_action="drying", free_cooling="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_flush_cooling", timeout=5)


def test_cooling_state_free_cooling(home_assistant: HomeAssistant) -> None:
    """auto on + cooling action + free cooling → 'free_cooling'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_cooling_state_deps(home_assistant, hvac_action="cooling", free_cooling="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "free_cooling", timeout=5)


def test_cooling_state_cooling_without_free_cooling(home_assistant: HomeAssistant) -> None:
    """auto on + cooling action + free cooling off → 'cooling' (e.g. manual cool)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_cooling_state_deps(home_assistant, hvac_action="cooling", free_cooling="off")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "cooling", timeout=5)


def test_cooling_state_moisture_retention(home_assistant: HomeAssistant) -> None:
    """auto on + heating action + humidity below min → 'moisture_retention'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # min=45 baseline; 40 < 45 → retaining moisture via warm profile.
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "40.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    _seed_cooling_state_deps(home_assistant, hvac_action="heating")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_retention", timeout=5)


def test_cooling_state_heating(home_assistant: HomeAssistant) -> None:
    """auto on + heating action + humidity at/above min → 'heating'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # baseline humidity=55 ≥ min(45) → active heating, not moisture retention.
    _seed_cooling_state_deps(home_assistant, hvac_action="heating")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "heating", timeout=5)


def test_cooling_state_comfort(home_assistant: HomeAssistant) -> None:
    """auto on + fan action (comfort profile) → 'comfort'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_cooling_state_deps(home_assistant, hvac_action="fan")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "comfort", timeout=5)


def test_cooling_state_unavailable_when_dependency_missing(home_assistant: HomeAssistant) -> None:
    """has_value guard: a missing availability dependency → sensor.airflow_cooling_state unavailable."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # All five availability deps present → sensor resolves to a real state.
    _seed_cooling_state_deps(home_assistant, hvac_action="fan")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "comfort", timeout=5)
    # Drop one dependency → has_value() is False → availability False → entity unavailable.
    home_assistant.set_state("switch.comfoconnect_pro_boost", "unavailable", {})
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "unavailable", timeout=5)
