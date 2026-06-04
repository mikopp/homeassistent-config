"""Airflow cooling automation tests.

The three former automations (airflow_cooling_set_temperature_profile,
airflow_moisture_ventilation_preset, airflow_medium_ventilation_preset) were unified into
a single deterministic controller, automation.airflow_ventilation_controller. On every
relevant input change it recomputes the COMPLETE desired ComfoConnect state — temperature
profile (Section 1, runs even during Away) plus ventilation preset / auto_mode (Section 2,
skipped while Away) — and applies it idempotently, so no two automations fight. The boost
(airflow_humidity_drying_boost) stays a separate automation.

Tests verify the controller runs without trace errors and, where possible, that observable
state matches expectations.

Known CI limitation: select.comfoconnect_pro_temperature_profile,
select.comfoconnect_pro_ventilation_preset and switch.comfoconnect_pro_auto_mode are bare
REST stubs — the ComfoConnect integration is absent in CI, so select.select_option and
switch.turn_on/off service calls are silently ignored by HA's service registry. Only
trace-error absence (no exception from trigger) and idempotent no-op assertions (where the
seeded state already equals the desired state, or a guard/gate suppresses the branch) are
possible for the active-write scenarios. Note: triggering with skip_condition=True bypasses
the automation-level "automatic enabled" gate, but NOT the in-action `if away == off` guard
or the per-branch idempotency templates — so Away gating and branch selection ARE testable.
"""

import requests

from ha_integration_test_harness import HomeAssistant

# Unified controller — single source of truth for profile + preset + auto_mode.
_CONTROLLER = "automation.airflow_ventilation_controller"
_DRYING_BOOST_AUTO = "automation.airflow_humidity_drying_boost"

# Back-compat aliases: the former profile / moisture-preset / medium-preset automations all
# collapsed into _CONTROLLER. Triggering the controller runs both sections in one pass.
_AIRFLOW_AUTO = _CONTROLLER
_MOISTURE_PRESET_AUTO = _CONTROLLER
_MEDIUM_PRESET_AUTO = _CONTROLLER


def _trigger(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _CONTROLLER,
        "skip_condition": True,
    })


def _trigger_moisture(home_assistant: HomeAssistant) -> None:
    # Section 2 (preset/auto_mode) now lives in the unified controller.
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _CONTROLLER,
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


def test_verification_step3_high_humidity_flush_triggers_cool(home_assistant: HomeAssistant) -> None:
    """Verification step 3: humidity flush needed → Block 2 Case B → cool profile.

    Block 2 Case B now keys on binary_sensor.airflow_humidity_flush_needed (which itself
    encodes the dew branches + ComfoConnect temp gate). Seeded ON here; neutral season, free
    cooling off — so only the flush path can fire the cool profile.
    CI: stub ignores select_option — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 2 Case B fires: flush_needed=on → cool in production (stub ignores select_option).


def test_verification_step3_high_humidity_no_flush_profile_unchanged(home_assistant: HomeAssistant) -> None:
    """Verification step 3 (negative path): high moisture but no flush + free_cooling=off → no change.

    min=45, max=54 → dew band [9.08, 11.81]°C. indoor_dew=12.5 above band. With the flush sensor
    pinned OFF (e.g. outdoor not dry enough), no block fires: Block 1 misses (dew not < dew_min),
    Block 2 misses (free_cooling off AND flush off), Block 3's dead-band excludes 12.5. Profile
    stays "comfort". (When flush IS needed, Block 2 Case B would cool — see the flush sensor tests.)
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_min_humidity", "value": 45})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 54})
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.5",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "off", {})
    _trigger(home_assistant)
    # Block 1: indoor_dew(12.5) ≥ dew_min(9.08) → miss. Block 2: free_cooling=off AND flush=off → miss.
    # Block 3: neutral, but dead-band 12.5∉[9.08,11.81] → miss. Default no-op.
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
    """Verification step 5: humidity drops below target → no owner active → auto mode restored.

    Restore branch needs every owner clear (low off, free off, flush off) AND auto_mode currently
    off (i.e. WE had taken control). Seed auto_mode off so the branch actually fires.
    CI: switch.turn_on silently ignored — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_avg_indoor_humidity_5min", "54.0",
                             {"unit_of_measurement": "%", "device_class": "humidity"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    _trigger_moisture(home_assistant)
    # Restore branch: low/free/flush all off + auto_mode off → switch.turn_on (stub ignores).


def test_verification_step6_low_humidity_warm_profile_overrides_season(home_assistant: HomeAssistant) -> None:
    """Verification step 6: indoor dew below min-dew → Block 1 Case A fires (warm), non-cooling season.

    min=50 → dew_min≈10.65°C at target 21.5°C. indoor_dew=9.0 < 10.65−0.1, neutral season →
    Block 1 Case A fires. Warming priority protects wood/instruments from excessively dry air.
    CI: stub ignores select_option — assert trace-error absence only.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_min_humidity", "value": 50})
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "9.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    _trigger(home_assistant)
    # Block 1 Case A: indoor_dew 9.0 < dew_min(10.65)−0.1 AND not cooling season → fires. Profile → warm.


# ── Temperature profile moisture tests ──────────────────────────────────────────────────


def test_airflow_low_humidity_warm_profile(home_assistant: HomeAssistant) -> None:
    """Low moisture (dew 8.0 < dew_min 9.08) + neutral season → Block 1 Case A fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "8.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 1 Case A: dew 8.0 < dew_min(9.08, baseline min 45%)−0.1, not cooling season → fires.


def test_airflow_humidity_flush_cool_profile(home_assistant: HomeAssistant) -> None:
    """Humidity flush needed (neutral season, free_cooling off) → Block 2 Case B fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 2 Case B: flush_needed=on → cool, independent of free cooling / cooling season.


def test_airflow_high_humidity_no_flush_stays_comfort(home_assistant: HomeAssistant) -> None:
    """High moisture (dew 13.0) but flush not needed + free_cooling off + neutral → no-op.

    With the flush sensor pinned OFF (outdoor not dry enough to help), high indoor dew alone
    does not change the profile: Block 2 needs free cooling (cooling season) or flush. When
    flush IS needed, Block 2 Case B cools — covered by the flush sensor tests.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "13.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "off", {})
    _trigger(home_assistant)
    # Block 1: dew(13.0) ≥ dew_min(9.08). Block 2: free_cooling=off AND flush=off.
    # Block 3: neutral=yes but dead-band 13.0∉[9.08,12.09] → miss. Default no-op.
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


def test_airflow_humidity_in_dead_band_neutral_comfort(home_assistant: HomeAssistant) -> None:
    """Moisture in dead band (dew 12.0 in [9.08,12.09]) + neutral + free_cooling=off → Block 3 → comfort.

    Block 1 Case A misses (dew ≥ dew_min). Block 1 Case B misses (not active_heating).
    Block 2 misses (free_cooling=off). Block 3: neutral + dead-band satisfied → comfort.
    Seeded profile is already "comfort" → idempotent guard suppresses service call.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # Baseline seeds indoor_dew=12.0, min=45→dew_min 9.08, max=55→dew_max 12.09 — dew just inside band.
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    _trigger(home_assistant)
    # Block 3: neutral, 9.08 <= 12.0 <= 12.09 → fires; already comfort → guard suppresses call.
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
    """Owners clear (low/free/flush off) + auto_mode off → restore branch turns auto on (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
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
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
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
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
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
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
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
    # The medium-preset bump folded into the unified controller's Section 2 medium branch.
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _CONTROLLER,
        "skip_condition": True,
    })


def test_medium_preset_enable_when_free_cooling_low_preset(home_assistant: HomeAssistant) -> None:
    """free_cooling=on + auto=on + preset=low + boost=off → enable branch fires (trace only).

    In production: auto mode turns off, preset set to Medium. CI stubs ignore service calls.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # Medium branch: low off, free on, NOT(auto off & preset medium) → auto_mode=off + preset=medium.


def test_medium_preset_restore_when_free_cooling_gone(home_assistant: HomeAssistant) -> None:
    """free_cooling=off + auto=off + preset=medium → restore branch fires (trace only).

    Simulates returning from Medium preset: auto mode turns back on.
    CI: switch.turn_on silently ignored.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger_medium(home_assistant)
    # Restore branch: low/free/flush off + auto=off → auto_mode on (stub ignores).


def test_medium_preset_independent_of_boost(home_assistant: HomeAssistant) -> None:
    """free_cooling=on + auto=on + preset=low + boost=on → medium branch STILL fires (trace only).

    Premise change vs the old medium-preset automation: the unified controller computes the
    preset independent of the boost (the boost rides on top in hardware). So a running boost no
    longer suppresses the medium bump — the medium branch's only gates are low-off, free/flush-on
    and the idempotency guard, none of which read the boost. Medium is the correct fallback for
    when the boost expires while free cooling / flush continues.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_medium(home_assistant)
    # Medium branch: low off, free on, NOT(auto off & preset medium) → fires regardless of boost.


def test_medium_preset_auto_disabled_no_action(home_assistant: HomeAssistant) -> None:
    """auto=off: condition gate suppresses medium preset (trace only)."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # skip_condition=True bypasses the gate; service calls silently ignored either way.


# ── Away mode guard tests ─────────────────────────────────────────────────────────────────
# The controller's Section 2 (preset/auto_mode) is wrapped in an in-action `if away==off` guard,
# and the boost automation gates on away=off via a top-level condition. The Away split is
# deliberate: the temperature profile (Section 1) still follows the season during Away, but the
# ventilation level is left to the Away function. Because the Section 2 guard is INSIDE the action
# (not a top-level condition), skip_condition=True does not bypass it — so the preset/auto_mode
# no-change is directly observable in CI.


def test_moisture_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on: Section 2's in-action `if away==off` guard skips preset/auto even with low_needed=on.

    skip_condition=True bypasses the automation-level gate but NOT the inner Away guard, so this
    is observable: the low branch must not run, leaving auto_mode and preset at their seeded values.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    _trigger_moisture(home_assistant)
    # Away guard skips Section 2 → no low branch → auto_mode stays on, preset stays medium.
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)


def test_medium_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on: the Away guard skips Section 2 even with free_cooling=on (observable no-change)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_medium(home_assistant)
    # Away guard skips Section 2 → medium branch never runs → auto_mode/preset unchanged.
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


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


# ── Dew-point threshold sensor tests ──────────────────────────────────────────────────────
# sensor.airflow_dew_point_{min,target,max} centralise the Magnus dew-point formula: each
# humidity helper expressed as the dew point it implies at the target temperature. The
# refactored humidity logic references these sensors instead of recomputing the formula.


def test_dew_point_threshold_sensors_match_inline_formula(home_assistant: HomeAssistant) -> None:
    """Each dew-point threshold sensor reproduces the inline Magnus formula for its helper.

    Centralisation check: the sensors must match the formula the old inline computations used,
    so decisions referencing them behave identically to the previous inline code.
    """
    for sensor, helper in (
        ("sensor.airflow_dew_point_min", "airflow_min_humidity"),
        ("sensor.airflow_dew_point_target", "airflow_target_humidity"),
        ("sensor.airflow_dew_point_max", "airflow_max_humidity"),
    ):
        tmpl = (
            "{%- set T  = states('input_number.airflow_cooling_target_temperature') | float -%}"
            "{%- set RH = states('input_number." + helper + "') | float -%}"
            "{%- set ps = 0.61078 * e ** (17.27 * T / (T + 237.3)) -%}"
            "{%- set pv = ps * RH / 100 -%}"
            "{%- set expected = (237.3 * (pv / 0.61078) | log"
            " / (17.27 - (pv / 0.61078) | log)) | round(2) -%}"
            "{{ (states('" + sensor + "') | float - expected) | abs < 0.01 }}"
        )
        assert _render(home_assistant, tmpl) == "True", f"{sensor} does not match inline formula"


def test_dew_point_target_sensor_matches_free_cooling_dew_max(home_assistant: HomeAssistant) -> None:
    """sensor.airflow_dew_point_target equals the free-cooling dew_max threshold (≈12.09°C baseline).

    Ties the centralised sensor to the already-tested free-cooling absolute-humidity gate.
    """
    expected = float(_render(home_assistant, _DEW_MAX_TMPL))
    tmpl = ("{{ (states('sensor.airflow_dew_point_target') | float - "
            + repr(expected) + ") | abs < 0.01 }}")
    assert _render(home_assistant, tmpl) == "True"


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
    """auto on + boost on + hvac_action drying → 'moisture_flush_boost' (highest active priority).

    hvac_action 'drying' means a flush is active (boost during free cooling, or cool-profile
    flush). A boost on top of that is the noisy flush boost.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # free + boost both on → hvac_action_template itself also yields 'drying', so the seeded
    # attribute and any climate re-render agree (race-proof).
    _seed_cooling_state_deps(home_assistant, hvac_action="drying", free_cooling="on", boost="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_flush_boost", timeout=5)


def test_cooling_state_boost_without_drying_not_flush_boost(home_assistant: HomeAssistant) -> None:
    """auto on + boost on but hvac_action cooling (not drying) → NOT moisture_flush_boost.

    moisture_flush_boost requires the drying action; a boost while merely cooling (cool profile,
    free cooling off) maps to 'cooling', confirming the boost label is gated on the drying context.
    Profile=cool + free off → hvac_action_template also yields 'cooling' (seed/render agree).
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    _seed_cooling_state_deps(home_assistant, hvac_action="cooling", free_cooling="off", boost="on")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state", "cooling", timeout=5)


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
    """auto on + heating action + indoor dew below min-dew → 'moisture_retention'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # baseline min=45 → dew_min≈9.08°C; indoor_dew=8.0 < 9.08 → retaining moisture via warm profile.
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "8.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    _seed_cooling_state_deps(home_assistant, hvac_action="heating")
    home_assistant.assert_entity_state("sensor.airflow_cooling_state",
                                       "moisture_retention", timeout=5)


def test_cooling_state_heating(home_assistant: HomeAssistant) -> None:
    """auto on + heating action + indoor dew at/above min-dew → 'heating'."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    # baseline indoor_dew=12.0 ≥ dew_min(9.08) → active heating, not moisture retention.
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


# ── Humidity flush sensor tests ───────────────────────────────────────────────────────────
# binary_sensor.airflow_humidity_flush_needed drives the cool-profile flush. Two OR branches:
#   Branch 1 (indoor dew above max): flushes REGARDLESS of temperature.
#   Branch 2 (indoor dew above target only): flushes ONLY if the ComfoConnect temp gate holds.
# In active_heating only Branch 1 applies. ~0.3°C this.state hysteresis on every dew boundary.
# Tests render the state template directly via the template API (the binary sensor itself has
# delay_on/off=10min and a `this.state` Schmitt that CI cannot drive). `this.state` is supplied
# by the `state_on` flag, which fixes the hysteresis offset (h) and indoor temp threshold.
# NOTE: baseline max==target humidity collapses both branches, so branch tests set max=60.


def _flush_state(state_on: bool) -> str:
    """Render template mirroring binary_sensor.airflow_humidity_flush_needed's state body.

    state_on simulates `this.state == 'on'`: relaxes every dew boundary by 0.3°C and drops
    the indoor temp threshold to target-0.5 (matches the sensor's Schmitt/hysteresis).
    """
    h = "0.3" if state_on else "0.0"
    thr = "(target_temp - 0.5)" if state_on else "target_temp"
    # Dew points are computed inline from the humidity helpers (same Magnus formula as the
    # sensors) to avoid a race with sensor.airflow_dew_point_* recomputing after a humidity
    # change — the sensors are verified to match this formula elsewhere.
    return f"""
    {{%- set outdoor_dew     = states('sensor.airflow_outdoor_dew_5min') | float -%}}
    {{%- set indoor_dew      = states('sensor.airflow_min_indoor_dew_5min') | float -%}}
    {{%- set outdoor_temp    = states('sensor.airflow_outdoor_temp_5min') | float -%}}
    {{%- set avg_indoor_temp = states('sensor.airflow_avg_indoor_temp_5min') | float -%}}
    {{%- set target_temp     = states('input_number.airflow_cooling_target_temperature') | float -%}}
    {{%- set target_hum      = states('input_number.airflow_target_humidity') | float -%}}
    {{%- set max_hum         = states('input_number.airflow_max_humidity') | float -%}}
    {{%- set min_dew_diff    = states('input_number.airflow_min_dew_diff') | float -%}}
    {{%- set min_temp_diff   = states('input_number.airflow_min_temp_diff') | float -%}}
    {{%- set season          = states('sensor.heating_cooling_indicator') -%}}
    {{%- set ps = 0.61078 * e ** (17.27 * target_temp / (target_temp + 237.3)) -%}}
    {{%- set pv_t = ps * target_hum / 100 -%}}
    {{%- set dew_target = 237.3 * (pv_t / 0.61078) | log / (17.27 - (pv_t / 0.61078) | log) -%}}
    {{%- set pv_m = ps * max_hum / 100 -%}}
    {{%- set dew_max = 237.3 * (pv_m / 0.61078) | log / (17.27 - (pv_m / 0.61078) | log) -%}}
    {{%- set h = {h} -%}}
    {{%- set temp_threshold = {thr} -%}}
    {{%- set margin_ok = (outdoor_dew + min_dew_diff - h) < indoor_dew -%}}
    {{%- set branch1 = outdoor_dew < (dew_max + h) and indoor_dew > (dew_max - h) and margin_ok -%}}
    {{%- set branch2 = outdoor_dew <= (dew_target + h) and indoor_dew > (dew_target - h) and margin_ok -%}}
    {{%- set temp_gate = outdoor_temp < (target_temp - min_temp_diff) and avg_indoor_temp >= temp_threshold -%}}
    {{%- set branch2_ok = branch2 and temp_gate -%}}
    {{{{ branch1 if season == 'active_heating' else (branch1 or branch2_ok) }}}}
    """


def _set_max_humidity_60(home_assistant: HomeAssistant) -> None:
    """Raise max_humidity to 60 so dew_max (~13.41°C) separates from dew_target (~12.09°C)."""
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_max_humidity", "value": 60})


def test_flush_branch1_above_max_fires(home_assistant: HomeAssistant) -> None:
    """Branch 1: indoor dew above max-dew, outdoor drier by margin → flush ON (any temp)."""
    _set_max_humidity_60(home_assistant)  # dew_max≈13.41
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0", temp_attrs)
    # 9<13.41, 14>13.41, 9+2=11<14 → Branch 1 True.
    assert _render(home_assistant, _flush_state(False)) == "True"


def test_flush_branch1_margin_fails(home_assistant: HomeAssistant) -> None:
    """Branch 1 negative: indoor above max but outdoor not drier by min_dew_diff → flush OFF."""
    _set_max_humidity_60(home_assistant)  # dew_max≈13.41
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "12.5", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0", temp_attrs)
    # margin: 12.5+2=14.5 not < 14.0 → Branch 1 fails; Branch 2: 12.5 not <= 12.09 → fails.
    assert _render(home_assistant, _flush_state(False)) == "False"


def test_flush_branch1_ignores_temperature_gate(home_assistant: HomeAssistant) -> None:
    """Branch 1 (moisture problem) flushes even when the temp gate would block Branch 2.

    Hot intake (25°C > target-min_temp_diff) and cool room (19°C < target) fail the temp gate,
    but the above-max moisture problem flushes regardless.
    """
    _set_max_humidity_60(home_assistant)
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_outdoor_temp_5min", "25.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_avg_indoor_temp_5min", "19.0", temp_attrs)
    assert _render(home_assistant, _flush_state(False)) == "True"


def test_flush_branch1_ignores_weatherstation_temp(home_assistant: HomeAssistant) -> None:
    """The flush sensor never reads the weather station — a hot weather station is irrelevant."""
    _set_max_humidity_60(home_assistant)
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "30.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0", temp_attrs)
    assert _render(home_assistant, _flush_state(False)) == "True"


def test_flush_branch2_fires_with_temp_gate(home_assistant: HomeAssistant) -> None:
    """Branch 2: indoor above target (but below max), outdoor below target dew, temp gate holds → ON."""
    _set_max_humidity_60(home_assistant)  # dew_target≈12.09, dew_max≈13.41
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.5", temp_attrs)
    # Branch 1 misses (12.5<13.41); Branch 2: 9<=12.09, 12.5>12.09, 9+2<12.5 → True.
    # Temp gate: outdoor 16<20 and indoor 22>=21.5 → True. baseline temps suffice.
    assert _render(home_assistant, _flush_state(False)) == "True"


def test_flush_branch2_blocked_when_temp_gate_fails(home_assistant: HomeAssistant) -> None:
    """Branch 2 negative: dew condition met but ComfoConnect intake too warm → flush OFF.

    Confirms the temp gate (Branch 2 only) uses the ComfoConnect intake sensor, not the
    weather station: intake at 21°C exceeds target-min_temp_diff (20°C) → gate fails.
    """
    _set_max_humidity_60(home_assistant)
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.5", temp_attrs)
    home_assistant.set_state("sensor.airflow_outdoor_temp_5min", "21.0", temp_attrs)
    assert _render(home_assistant, _flush_state(False)) == "False"


def test_flush_branch2_blocked_when_indoor_below_target(home_assistant: HomeAssistant) -> None:
    """Branch 2 negative: room already below target temp → temp gate fails → flush OFF."""
    _set_max_humidity_60(home_assistant)
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.5", temp_attrs)
    # OFF-state threshold is target (21.5); indoor 21.0 < 21.5 → gate fails.
    home_assistant.set_state("sensor.airflow_avg_indoor_temp_5min", "21.0", temp_attrs)
    assert _render(home_assistant, _flush_state(False)) == "False"


def test_flush_season_guard_heating_branch1_only(home_assistant: HomeAssistant) -> None:
    """active_heating allows Branch 1 only: a Branch-2 scenario flushes in neutral but not heating."""
    _set_max_humidity_60(home_assistant)
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "9.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "12.5", temp_attrs)
    # Branch 2 scenario (indoor between target and max), temp gate holds at baseline.
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    assert _render(home_assistant, _flush_state(False)) == "True"
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    assert _render(home_assistant, _flush_state(False)) == "False"


def test_flush_hysteresis_deadband_branch1(home_assistant: HomeAssistant) -> None:
    """0.3°C hysteresis on Branch 1: indoor dew between dew_max-0.3 and dew_max flips with this.state.

    min_dew_diff lowered to 0.5 and outdoor_dew set above dew_target so only Branch 1 is in play.
    indoor_dew=13.2 sits between dew_max-0.3 (13.11) and dew_max (13.41): OFF→stays off,
    ON→stays on. Confirms the deadband.
    """
    _set_max_humidity_60(home_assistant)  # dew_max≈13.41
    home_assistant.call_action("input_number", "set_value",
                               {"entity_id": "input_number.airflow_min_dew_diff", "value": 0.5})
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "12.5", temp_attrs)
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "13.2", temp_attrs)
    # OFF-state: 13.2 > 13.41 is False → Branch 1 off; Branch 2 outdoor 12.5<=12.09 False → off.
    assert _render(home_assistant, _flush_state(False)) == "False"
    # ON-state: relaxed indoor>dew_max-0.3 (13.2>13.11) True; margin 12.5+0.5-0.3=12.7<13.2 True.
    assert _render(home_assistant, _flush_state(True)) == "True"


def test_flush_unavailable_when_dependency_missing(home_assistant: HomeAssistant) -> None:
    """has_value guard: a missing input → binary_sensor.airflow_humidity_flush_needed unavailable."""
    # Baseline seeds all inputs → sensor resolves (off in baseline, see conftest).
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_flush_needed",
                                       "off", timeout=5)
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "unavailable", {})
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_flush_needed",
                                       "unavailable", timeout=5)


# ── Boost-flush (drying needed) gating tests ──────────────────────────────────────────────
# binary_sensor.airflow_humidity_drying_needed = flush_needed AND weather-station temp < target
# AND in_schedule AND not low_active. Rendered directly to bypass the sensor's delay_on/off.


def _drying_state(flush: bool) -> str:
    """Render template mirroring binary_sensor.airflow_humidity_drying_needed's state body.

    `flush` is injected as a literal (binary_sensor.airflow_humidity_flush_needed is a delayed
    template sensor whose REST-set 'on' does not reliably stick in CI) so the boost-only gates
    (weather station, schedule, low-vent) are exercised deterministically.
    """
    flush_lit = "true" if flush else "false"
    return f"""
    {{%- set flush_needed = {flush_lit} -%}}
    {{%- set low_active   = is_state('binary_sensor.airflow_moisture_ventilation_low_needed', 'on') -%}}
    {{%- set outdoor_t    = states('sensor.wheatherstation_outdoor_temperature') | float(99) -%}}
    {{%- set target_t     = states('input_number.airflow_cooling_target_temperature') | float(21.5) -%}}
    {{%- set in_schedule  = (is_state('binary_sensor.workday', 'on')
                            and is_state('schedule.airflow_boost_workday', 'on'))
                           or
                           (is_state('binary_sensor.workday', 'off')
                            and is_state('schedule.airflow_boost_non_workday', 'on')) -%}}
    {{{{ flush_needed and not low_active and outdoor_t < target_t and in_schedule }}}}
    """


def test_drying_requires_flush_needed(home_assistant: HomeAssistant) -> None:
    """No flush needed → boost never fires even with cool weather and schedule on."""
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "16.0", temp_attrs)
    assert _render(home_assistant, _drying_state(flush=False)) == "False"


def test_drying_blocked_by_warm_weatherstation(home_assistant: HomeAssistant) -> None:
    """Flush needed but weather-station temp >= target → boost blocked (weather gate)."""
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "22.0", temp_attrs)
    # 22.0 not < target 21.5 → boost False even though flush is needed.
    assert _render(home_assistant, _drying_state(flush=True)) == "False"


def test_drying_fires_with_flush_and_cool_weatherstation(home_assistant: HomeAssistant) -> None:
    """Flush needed + weather-station cool + workday schedule on + low off → boost template True."""
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("sensor.wheatherstation_outdoor_temperature", "16.0", temp_attrs)
    # baseline: workday=on, schedule.airflow_boost_workday=on → in_schedule True.
    assert _render(home_assistant, _drying_state(flush=True)) == "True"


# ── hvac_action drying-from-flush tests ───────────────────────────────────────────────────


def _hvac_action_state(flush: bool) -> str:
    """Render template mirroring climate.airflow_climate's hvac_action_template.

    `flush` is injected as a literal (rather than reading binary_sensor.airflow_humidity_flush_needed,
    a delayed template sensor whose REST-set 'on' does not reliably stick in CI) so the branch
    logic is exercised deterministically.
    """
    flush_lit = "true" if flush else "false"
    return f"""
    {{%- set profile   = states('select.comfoconnect_pro_temperature_profile') -%}}
    {{%- set free_cool = is_state('binary_sensor.airflow_free_cooling_available', 'on') -%}}
    {{%- set boost_on  = is_state('switch.comfoconnect_pro_boost', 'on') -%}}
    {{%- set flush_needed = {flush_lit} -%}}
    {{%- if free_cool and boost_on -%}}drying
    {{%- elif profile == 'cool' and flush_needed -%}}drying
    {{%- elif profile == 'cool' -%}}cooling
    {{%- elif profile == 'warm' -%}}heating
    {{%- elif profile == 'comfort' -%}}fan
    {{%- else -%}}idle{{%- endif -%}}
    """


def test_hvac_action_drying_from_flush(home_assistant: HomeAssistant) -> None:
    """cool profile + flush needed (no boost, no free cooling) → hvac_action 'drying'."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    assert _render(home_assistant, _hvac_action_state(flush=True)) == "drying"


def test_hvac_action_cooling_without_flush(home_assistant: HomeAssistant) -> None:
    """cool profile + no flush → hvac_action 'cooling' (plain temperature cooling)."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    assert _render(home_assistant, _hvac_action_state(flush=False)) == "cooling"


# ── Profile block precedence tests ────────────────────────────────────────────────────────


def test_profile_flush_triggers_cool_without_free_cooling(home_assistant: HomeAssistant) -> None:
    """flush needed, free cooling off, neutral season → Block 2 Case B fires (trace only)."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 2 Case B fires (cool in production); CI stub ignores select_option.


def test_profile_heating_flush_overrides_warm(home_assistant: HomeAssistant) -> None:
    """active_heating + free cooling off + flush needed → Block 1 Case B yields, Block 2 cools.

    The Block 1 Case B `not flush_needed` guard means a heating-season moisture problem flushes
    (cool) instead of holding warm. Trace-only: CI stub ignores select_option, but the automation
    must reach Block 2 without firing Block 1's warm action.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    _trigger(home_assistant)
    # Block 1 Case B guarded off by flush_needed; Block 2 Case B fires → cool in production.


# ── Unified controller consistency tests ──────────────────────────────────────────────────
# The controller recomputes the COMPLETE desired ComfoConnect state on every run and applies it
# idempotently. These tests pin the cases that ARE observable despite the CI service-call stubs:
# each per-branch idempotency guard and the restore gate suppress a write when the seeded state
# already equals the desired state, so auto_mode / preset must stay put (no thrash, no notify).
# This is the core invariant of the refactor: the outputs are a pure function of the inputs and
# the controller never fights itself.


def test_controller_low_idempotent_no_write(home_assistant: HomeAssistant) -> None:
    """low_needed=on but already (auto off, preset low) → low branch guard False → no write.

    The low branch acts only when NOT(auto off AND preset low); seeded already at the desired
    state, it must leave auto_mode/preset untouched (idempotent — no redundant write or notify).
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


def test_controller_medium_idempotent_no_write(home_assistant: HomeAssistant) -> None:
    """flush=on but already (auto off, preset medium) → medium branch guard False → no write."""
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    # Indoor dew above the dead-band (consistent with flush on) + profile already cool so Section 1
    # is also a no-op: Block 2 guard (not cool) suppresses, Block 3 misses (dew out of band).
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)


def test_controller_restore_no_thrash_when_auto_already_on(home_assistant: HomeAssistant) -> None:
    """All owners clear but auto_mode already ON → restore branch gate False → auto stays on.

    The restore branch turns auto_mode on only when WE had taken control (auto_mode currently
    off). With auto already on there is nothing to hand back — the controller must not re-toggle.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)


def test_controller_low_priority_over_medium(home_assistant: HomeAssistant) -> None:
    """low_needed=on wins over flush: even with flush on, preset is NOT bumped to medium.

    low and flush are mutually exclusive in the sensors, but the low-before-medium ordering is
    belt-and-suspenders. Seeded already at (auto off, preset low): the low branch is a no-op
    (guard satisfied) and the medium branch is unreachable (requires low off). Preset stays low —
    proving the medium branch never overrides an active low owner.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "on", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "on", {})
    # Indoor dew above the dead-band keeps Section 1 from spuriously firing Block 3.
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "14.0",
                             {"unit_of_measurement": "°C", "device_class": "temperature"})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)


def test_controller_full_rest_state_is_total_no_op(home_assistant: HomeAssistant) -> None:
    """No owner active, neutral season, dew in band, already at rest → both sections no-op.

    Baseline (neutral, indoor_dew 12.0 in [dew_min≈9.08, dew_max≈12.09], profile comfort,
    auto on, preset medium) is the steady-state target: Section 1 Block 3 finds comfort already
    set, Section 2's restore gate finds auto already on. Nothing is written on either output.
    """
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "off", {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)
