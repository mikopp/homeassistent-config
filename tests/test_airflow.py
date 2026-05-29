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
_MOISTURE_PRESET_AUTO = "automation.airflow_moisture_ventilation_preset"


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
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_level",
                                       "medium", timeout=3)


# ── Bypass estimation tests ──────────────────────────────────────────────────────────────


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
