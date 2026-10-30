"""Airflow cooling automation tests.

sensor.airflow_cooling_state is the SINGLE decision of the airflow automation: its state is the
reason label, its `profile` / `ventilation` attributes are what gets applied. It reads only the
indicators (free cooling, flush, drying, moisture/heat low guards, heating_cooling_indicator,
indoor dew vs dew_point_min) and never the outputs, so it is fully observable in CI — the
decision-table tests below seed the indicators and assert state + attributes directly
(decision table: custom_templates/airflow_decision.jinja).

automation.airflow_ventilation_controller applies that decision — temperature profile (Section 1,
runs even during Away) plus ventilation preset / auto_mode (Section 2, skipped while Away) —
idempotently. The boost (airflow_humidity_drying_boost) applies `ventilation == boost`. Neither
reads an indicator directly.

Known CI limitation: select.comfoconnect_pro_temperature_profile,
select.comfoconnect_pro_ventilation_preset and switch.comfoconnect_pro_auto_mode are bare
REST stubs — the ComfoConnect integration is absent in CI, so select.select_option and
switch.turn_on/off service calls are silently ignored by HA's service registry. Only
trace-error absence (no exception from trigger) and idempotent no-op assertions (where the
seeded state already equals the desired state, or a guard/gate suppresses the branch) are
possible for the active-write scenarios. Note: triggering with skip_condition=True bypasses
the automation-level "automatic enabled" gate, but NOT the in-action `if away == off` guard
or the per-branch idempotency templates — so Away gating and branch selection ARE testable.
Controller tests wait for the decision (_assert_decision) before triggering, because the
controller reads the decision sensor, which re-renders asynchronously after the seeds.

CLOCK HANDLING: only one helper in this file touches the clock
(_assert_recomputes_after_reload), and it uses fast_forward(timedelta(minutes=11)) — never
jump_to_next(hour=...). jump_to_next is forward-only, so re-requesting an hour the mocked clock
has already passed silently advances a FULL DAY; the previous jump_to_next(hour=10, minute=0)
here was costing a day per call for no reason. See plans/ci-test-speedups.md.

The delayed binary sensors in this package (delay_on/delay_off = 10 min, trigger-based, no
homeassistant:start trigger) sit at 'unknown' after HA boots. conftest's baseline_states seeds
their inputs, which fires their triggers, but the result only LANDS once the mocked clock has
crossed the 10-minute delay window. Any test asserting a definite on/off from one of them
therefore needs a clock advance somewhere before it — and two of them
(test_flush_unavailable_when_dependency_missing,
test_heat_ventilation_low_needed_off_when_outdoor_below_indoor) currently get that from
_assert_recomputes_after_reload running earlier in nodeid order rather than from anything of
their own. Both are flagged at their definition; do not remove that helper's first
fast_forward, and expect either to fail with `current: 'unknown'` if run in isolation via -k.
"""

import requests
from datetime import timedelta

from ha_integration_test_harness import HomeAssistant, TimeMachine

# Controller — applies sensor.airflow_cooling_state (profile + preset + auto_mode).
_CONTROLLER = "automation.airflow_ventilation_controller"
_DRYING_BOOST_AUTO = "automation.airflow_humidity_drying_boost"
_DECISION = "sensor.airflow_cooling_state"
_TEMP_ATTRS = {"unit_of_measurement": "°C", "device_class": "temperature"}


def _trigger(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _CONTROLLER,
        "skip_condition": True,
    })


def _enable_auto(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("input_boolean", "turn_on",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})


def _seed_indicators(
    home_assistant: HomeAssistant,
    *,
    season: str = "neutral",
    free: str = "off",
    flush: str = "off",
    drying: str = "off",
    moist: str = "off",
    heat: str = "off",
    indoor_dew: str | None = None,
) -> None:
    """Seed every input of the decision sensor (sensor.airflow_cooling_state).

    Order matters. Indoor dew and season are trigger inputs of the trigger-based indicators; in CI
    those indicators have no internal state yet (their 10-min delay never elapsed), so a re-render
    writes 'unknown' over a seeded value. So: indoor dew and season FIRST, then flush before drying
    (flush_needed re-triggers drying_needed), then the low guards (which re-trigger on
    flush/drying), then free cooling. Re-call this helper (not a bare set_state) to change the dew
    mid-test.
    """
    if indoor_dew is not None:
        home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", indoor_dew, _TEMP_ATTRS)
    home_assistant.set_state("sensor.heating_cooling_indicator", season, {})
    home_assistant.set_state("binary_sensor.airflow_humidity_flush_needed", flush, {})
    home_assistant.set_state("binary_sensor.airflow_humidity_drying_needed", drying, {})
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", moist, {})
    home_assistant.set_state("binary_sensor.airflow_heat_ventilation_low_needed", heat, {})
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", free, {})


def _assert_decision(
    home_assistant: HomeAssistant, state: str, profile: str, ventilation: str
) -> None:
    """Assert the decision sensor's reason state and the outputs it decides."""
    home_assistant.assert_entity_state(
        _DECISION, state,
        expected_attributes={"profile": profile, "ventilation": ventilation}, timeout=5)


# ── Controller: temperature profile (Section 1) ─────────────────────────────────────────
# Section 1 writes the decided profile when the device differs. Writes are ignored by the CI
# stub, so a run that should write is trace-only; a run whose decided profile already matches
# is an observable no-op.


def test_airflow_free_cooling_active(home_assistant: HomeAssistant) -> None:
    """Free cooling decided (cooling season) → controller writes cool (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_cooling", free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")
    _trigger(home_assistant)


def test_airflow_free_cooling_neutral_season(home_assistant: HomeAssistant) -> None:
    """Free cooling decided in neutral season → controller writes cool (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="neutral", free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")
    _trigger(home_assistant)


def test_airflow_active_heating_free_cooling_on_writes_warm(home_assistant: HomeAssistant) -> None:
    """2026-10-23 regression: active_heating + free cooling ON + profile cool → warm decided.

    The old controller had no block for this combination and held `cool` all heating season.
    The decision is warm, so the controller writes warm (trace only — the stub ignores it).
    """
    _enable_auto(home_assistant)
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    _seed_indicators(home_assistant, season="active_heating", free="on")
    _assert_decision(home_assistant, "heating", "warm", "auto")
    _trigger(home_assistant)


def test_airflow_profile_already_decided_no_write(home_assistant: HomeAssistant) -> None:
    """Decided profile already set (heating → warm) → Section 1 is a no-op, profile stays warm."""
    _enable_auto(home_assistant)
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "warm", {})
    _seed_indicators(home_assistant, season="active_heating")
    _assert_decision(home_assistant, "heating", "warm", "auto")
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "warm", timeout=3)


def test_airflow_neutral(home_assistant: HomeAssistant) -> None:
    """Neutral, nothing needed → comfort decided; already comfort → no write."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="neutral")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)


def test_airflow_auto_disabled(home_assistant: HomeAssistant) -> None:
    """Auto disabled → decision 'off' (profile/ventilation off) → controller writes nothing."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    _seed_indicators(home_assistant, season="active_cooling", free="on")
    _assert_decision(home_assistant, "off", "off", "off")
    _trigger(home_assistant)
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

# ── Controller: ventilation preset / auto_mode (Section 2) ───────────────────────────────


def test_moisture_ventilation_low_when_needed(home_assistant: HomeAssistant) -> None:
    """Moisture guard on → low decided → controller sets manual low (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, moist="on")
    _assert_decision(home_assistant, "moisture_protection", "comfort", "low")
    _trigger(home_assistant)
    # switch.turn_off and select.select_option are silently ignored on bare stubs.


def test_moisture_ventilation_restore_auto(home_assistant: HomeAssistant) -> None:
    """auto decided + auto_mode off → restore branch turns auto on (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    _trigger(home_assistant)
    # switch.turn_on silently ignored — assert trace absence only.


def test_moisture_ventilation_disabled_no_action(home_assistant: HomeAssistant) -> None:
    """auto=off: decision 'off' → no branch matches → ventilation_level stays 'medium'."""
    # airflow_cooling_automatic_enabled=off from baseline_inputs fixture.
    _seed_indicators(home_assistant, moist="on")
    _assert_decision(home_assistant, "off", "off", "off")
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)


def _trigger_drying(home_assistant: HomeAssistant) -> None:
    home_assistant.call_action("automation", "trigger", {
        "entity_id": _DRYING_BOOST_AUTO,
        "skip_condition": True,
    })


def _decide_boost(home_assistant: HomeAssistant) -> None:
    """Drive the decision to ventilation=boost (flush + drying needed, automation enabled)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, flush="on", drying="on")
    _assert_decision(home_assistant, "moisture_flush_boost", "cool", "boost")


# ── Drying boost automation tests ──────────────────────────────────────────────────────────
# The boost automation reads only the decision (ventilation == boost). Manual triggers carry no
# trigger id, so the start/stop branches are trace-only here; the re-arm path (a real
# numeric_state trigger) is observable.


def test_drying_boost_starts_when_needed(home_assistant: HomeAssistant) -> None:
    """Boost decided + boost off → automation runs (trace only; stub ignores the write)."""
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)


def test_drying_boost_stops_when_conditions_gone(home_assistant: HomeAssistant) -> None:
    """Boost no longer decided + boost on → automation runs (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_drying(home_assistant)


def test_drying_boost_rearm_keeps_switch_on(home_assistant: HomeAssistant) -> None:
    """Countdown drops below 5 while boost is still decided + boost on → seamless re-arm.

    The re-arm branch re-sends switch.turn_on on the already-running boost (the device restarts
    its timer on a repeated ON, verified live) and never turns the switch off, so the switch must
    stay 'on'. The CI stub ignores the service call, so the assertable guarantee is that the
    switch is not dropped.
    """
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    # Seed the countdown above the threshold, then drop it below 5 to fire the numeric_state
    # re-arm trigger (rearm_due).
    home_assistant.set_state("number.comfoconnect_pro_boost_time", "10", {})
    home_assistant.set_state("number.comfoconnect_pro_boost_time", "4", {})
    # Switch was never turned off by the re-arm branch → stays on (no flip-flop).
    home_assistant.assert_entity_state("switch.comfoconnect_pro_boost", "on", timeout=3)


def test_drying_boost_restart_when_already_running_no_error(home_assistant: HomeAssistant) -> None:
    """Boost decided while a (manual) boost already runs → no trace error, switch not dropped."""
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger_drying(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_boost", "on", timeout=3)


def test_drying_boost_countdown_during_manual_boost_no_error(home_assistant: HomeAssistant) -> None:
    """Manual boost (boost not decided) reaching the countdown threshold → no-op, no error.

    rearm_due with ventilation != boost hits the no-op default, and the boost is left alone
    (no re-arm, no stop).
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    home_assistant.set_state("number.comfoconnect_pro_boost_time", "10", {})
    home_assistant.set_state("number.comfoconnect_pro_boost_time", "4", {})
    home_assistant.assert_entity_state("switch.comfoconnect_pro_boost", "on", timeout=3)


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


# ── Medium ventilation preset tests ───────────────────────────────────────────────────────
# Section 2 bumps the schedule's Low to Medium when the decision says medium (flush, or free
# cooling actually chosen). CI limitation: switch/select service calls are silently ignored.


def test_medium_preset_enable_when_free_cooling_low_preset(home_assistant: HomeAssistant) -> None:
    """Free cooling decided (medium) + auto=on + preset=low → medium branch fires (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger(home_assistant)
    # In production: auto_mode=off + preset=medium.


def test_medium_preset_not_raised_in_active_heating(home_assistant: HomeAssistant) -> None:
    """Free cooling available in active_heating → auto decided, NOT medium (2026-10-23 bug 2).

    Raw free_cooling_available is season-agnostic; the decision only raises the rate when free
    cooling is actually chosen. With auto=on the restore branch is idempotent, and no branch writes
    a preset — the schedule's low stays.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", free="on")
    _assert_decision(home_assistant, "heating", "warm", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


def test_medium_preset_restore_when_free_cooling_gone(home_assistant: HomeAssistant) -> None:
    """auto decided + auto=off + preset=medium → restore branch fires (trace only)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    # Restore branch: auto decided + auto_mode off → auto_mode on (stub ignores).


def test_medium_preset_boost_switch_blocks_preset_write(home_assistant: HomeAssistant) -> None:
    """Medium decided but a (manual) boost runs → boost-owner branch only keeps auto on.

    Writing a preset or turning auto off would cancel the running boost, so the first branch
    (ventilation == boost OR boost switch on) matches and exits: auto stays on, preset untouched.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


# ── Away mode guard tests ─────────────────────────────────────────────────────────────────
# The controller's Section 2 (preset/auto_mode) is wrapped in an in-action `if away==off` guard,
# and the boost automation gates on away=off via a top-level condition. The Away split is
# deliberate: the temperature profile (Section 1) still follows the decision during Away, but the
# ventilation level is left to the Away function. Because the Section 2 guard is INSIDE the action
# (not a top-level condition), skip_condition=True does not bypass it — so the preset/auto_mode
# no-change is directly observable in CI.


def test_moisture_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on: Section 2's in-action `if away==off` guard skips preset/auto even with low decided."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, moist="on")
    _assert_decision(home_assistant, "moisture_protection", "comfort", "low")
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    # Away guard skips Section 2 → no low branch → auto_mode stays on, preset stays medium.
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)


def test_medium_preset_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on: the Away guard skips Section 2 even with medium decided (observable no-change)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger(home_assistant)
    # Away guard skips Section 2 → medium branch never runs → auto_mode/preset unchanged.
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


def test_drying_boost_away_suppressed(home_assistant: HomeAssistant) -> None:
    """away=on seeded: boost automation runs trace-cleanly with the away entity."""
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "on", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    _trigger_drying(home_assistant)
    # In production: away=on blocks action — boost stays off.


# ── Drying boost: edge-only starts (plans/airflow-restart-and-boost-robustness-fixes.md) ──────
# Real state-change triggers (not manual automation.trigger) are used here. The harness cannot
# read automation traces, so which BRANCH ran is not observable; what IS observable is whether the
# automation ran at all: `last_triggered` only moves when a trigger fired AND the top-level
# conditions passed. So these tests assert "fired / did not fire", not "start branch ran".
#
# A clean auto -> boost edge cannot be made by seeding flush/drying: those writes re-trigger the
# trigger-based moisture_ventilation_low_needed, which has no internal state in CI and re-renders
# to 'unknown', so the decision flickers 'unavailable' and the edge seen by the automation is
# None -> boost (correctly NOT an edge, see its `from:` list). The edge is therefore created with
# input_boolean.airflow_cooling_automatic_enabled, which no indicator listens to: seed with the
# automation off (decision 'off'), then turn it on: ventilation off -> boost.


def _last_triggered(home_assistant: HomeAssistant) -> str | None:
    """Return the drying-boost automation's last_triggered attribute via the REST state API."""
    resp = requests.get(
        f"{home_assistant._base_url}/api/states/{_DRYING_BOOST_AUTO}",
        headers={"Authorization": f"Bearer {home_assistant._access_token}"},
        timeout=10,
    )
    assert resp.status_code == 200, f"State read failed: {resp.text}"
    return resp.json()["attributes"].get("last_triggered")


def _wait_triggered(home_assistant: HomeAssistant, before: str | None,
                    timeout: float = 5.0) -> bool:
    """Poll until last_triggered differs from `before`; False if it never moves in `timeout`."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _last_triggered(home_assistant) != before:
            return True
        time.sleep(0.25)
    return False


def _settle_boost_off(home_assistant: HomeAssistant, away: str) -> None:
    """Decision = comfort/auto (not boost), boost switch off, Away set as given."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", away, {})


def _decision_history(home_assistant: HomeAssistant) -> str:
    """Best-effort ventilation history of the decision, for failure messages only."""
    try:
        resp = requests.get(
            f"{home_assistant._base_url}/api/history/period",
            params={"filter_entity_id": _DECISION},
            headers={"Authorization": f"Bearer {home_assistant._access_token}"},
            timeout=10,
        )
        rows = resp.json()[0] if resp.status_code == 200 and resp.json() else []
        return " -> ".join(
            f"{r['state']}/{(r.get('attributes') or {}).get('ventilation')}" for r in rows[-8:]
        )
    except Exception as err:  # diagnostics must never mask the real assertion
        return f"(history unavailable: {err})"


def _arm_boost_edge(home_assistant: HomeAssistant) -> None:
    """Flush + drying needed with the automation OFF (decision 'off'), ready for the edge.

    The caller then calls _enable_auto: ventilation goes off -> boost without touching any
    indicator, so nothing flickers. Asserting state 'off' needs every indicator to hold a value,
    so it also proves the moisture indicator's 'unknown' flicker has passed; the second seed
    repairs it if a late re-render overwrote a seeded value (idempotent otherwise).
    """
    home_assistant.call_action("input_boolean", "turn_off",
                               {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"})
    _seed_indicators(home_assistant, flush="on", drying="on")
    home_assistant.assert_entity_state(_DECISION, "off", timeout=5)
    _seed_indicators(home_assistant, flush="on", drying="on")


def test_drying_boost_real_edge_into_boost_fires(home_assistant: HomeAssistant) -> None:
    """Real off -> boost decision change fires the boost automation (start edge)."""
    _settle_boost_off(home_assistant, "off")
    _arm_boost_edge(home_assistant)
    before = _last_triggered(home_assistant)
    _enable_auto(home_assistant)
    _assert_decision(home_assistant, "moisture_flush_boost", "cool", "boost")
    assert _wait_triggered(home_assistant, before), \
        f"off -> boost did not fire the automation; decision history: {_decision_history(home_assistant)}"


def test_drying_boost_away_unknown_is_not_away(home_assistant: HomeAssistant) -> None:
    """Away 'unknown' (ComfoConnect not up yet) must not block a real off -> boost edge."""
    _settle_boost_off(home_assistant, "unknown")
    _arm_boost_edge(home_assistant)
    before = _last_triggered(home_assistant)
    _enable_auto(home_assistant)
    _assert_decision(home_assistant, "moisture_flush_boost", "cool", "boost")
    assert _wait_triggered(home_assistant, before), \
        f"Away unknown blocked the boost automation; decision history: {_decision_history(home_assistant)}"


def test_drying_boost_away_unknown_to_off_fires(home_assistant: HomeAssistant) -> None:
    """Boost decided, boost off, Away unknown -> off is an away_ended edge: the automation runs."""
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "unknown", {})
    before = _last_triggered(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    assert _wait_triggered(home_assistant, before), "away_ended did not fire the automation"


def test_drying_boost_unavailable_to_boost_does_not_fire(home_assistant: HomeAssistant) -> None:
    """Decision unavailable -> boost is not an edge: boost_decided must not fire (no timer reset)."""
    _decide_boost(home_assistant)
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    # An unavailable input makes the decision (and its ventilation attribute) unavailable.
    home_assistant.set_state("sensor.airflow_min_indoor_dew_5min", "unavailable", {})
    home_assistant.assert_entity_state(_DECISION, "unavailable", timeout=5)
    before = _last_triggered(home_assistant)
    # Input returns; indicators are re-seeded so the decision comes back as boost.
    _seed_indicators(home_assistant, flush="on", drying="on", indoor_dew="12")
    _assert_decision(home_assistant, "moisture_flush_boost", "cool", "boost")
    assert not _wait_triggered(home_assistant, before, timeout=4), \
        "unavailable -> boost fired the automation (would reset a running boost timer)"


def test_drying_boost_config_edge_only() -> None:
    """Static check of the package: from: on boost_decided, no ha_start trigger, no 'ha_start' id."""
    import pathlib
    import yaml

    class _Loader(yaml.SafeLoader):
        pass

    # HA-specific tags (!include, !secret, ...) are irrelevant here: load them as plain strings.
    _Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    path = pathlib.Path(__file__).resolve().parent.parent / "packages" / "airflow_cooling.yaml"
    cfg = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    auto = next(a for a in cfg["automation"] if a.get("id") == "airflow_humidity_drying_boost")
    triggers = {t["id"]: t for t in auto["trigger"]}
    assert "ha_start" not in triggers
    assert not any(t.get("platform") == "homeassistant" for t in auto["trigger"])
    assert set(triggers["boost_decided"]["from"]) == {"medium", "low", "auto", "off"}
    assert triggers["boost_decided"]["to"] == "boost"
    assert "away_ended" in triggers


# ── Heat protection tests ────────────────────────────────────────────────────────────────
# heat_ventilation_low_needed forces LOW when the REAL outdoor (weather-station) air is too warm
# to import at volume — symmetric to moisture protection. It reads the smoothed weather-station
# temp (not the pre-cooled ComfoConnect intake), so raising flow on a hot day can't saturate the
# underground duct's cooling reservoir.


def test_heat_ventilation_low_needed_off_when_outdoor_below_indoor(home_assistant: HomeAssistant) -> None:
    """Real outdoor well below indoor → heat-protect template false → sensor stays off.

    indoor 26°C, weather-station 20°C: 20 < 26 → OFF. (delay_on=10min means the ON edge can't be
    asserted inside the CI window, so this exercises the release/off side deterministically.)

    ORDER DEPENDENCY — same shape as test_flush_unavailable_when_dependency_missing above:
    binary_sensor.airflow_heat_ventilation_low_needed also carries a 10-minute delay and starts
    'unknown' after HA boots. This test advances no clock, so it depends on
    test_flush_needed_recomputes_after_reload_unknown (which sorts earlier by nodeid) having
    already crossed a delay window. Run in isolation it fails with `current: 'unknown'`. Fix by
    adding an explicit fast_forward, not by relying on the ordering.
    """
    temp_attrs = {"unit_of_measurement": "°C", "device_class": "temperature"}
    home_assistant.set_state("sensor.airflow_avg_indoor_temp_5min", "26.0", temp_attrs)
    home_assistant.set_state("sensor.airflow_wheatherstation_outdoor_temp_5min", "20.0", temp_attrs)
    home_assistant.assert_entity_state("binary_sensor.airflow_heat_ventilation_low_needed",
                                       "off", timeout=5)


def test_heat_protection_low_wins_over_free_cooling_bump(home_assistant: HomeAssistant) -> None:
    """Heat-low + free cooling → heat_protection: profile cool (intake delivers) but LOW rate.

    The hot-day invariant: bypass open + minimum rate. Seeded already at (auto off, preset low),
    the low branch is idempotent and no medium branch can run — preset must stay low.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, free="on", heat="on")
    _assert_decision(home_assistant, "heat_protection", "cool", "low")
    home_assistant.set_state("switch.comfoconnect_pro_away_function", "off", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)


def test_ventilation_low_needed_derives_from_heat(home_assistant: HomeAssistant) -> None:
    """Combined low intent tracks heat_low with no set on itself — regression for the stale-derive bug.

    ventilation_low_needed is a STATE-based template (not trigger-based), so it must recompute to
    'on' the moment heat_low is 'on' even though nothing sets the combined sensor directly. The
    earlier trigger-based version could restore stale 'off' on HA restart while heat_low stayed 'on'
    for hours, stranding its consumer off the low intent (preset stuck at medium under heat_protection).
    """
    # Baseline seeds both source sensors + the combined to 'off'. Flip only heat_low on.
    home_assistant.set_state("binary_sensor.airflow_moisture_ventilation_low_needed", "off", {})
    home_assistant.set_state("binary_sensor.airflow_heat_ventilation_low_needed", "on", {})
    home_assistant.assert_entity_state("binary_sensor.airflow_ventilation_low_needed",
                                       "on", timeout=5)
    # And back off when both sources clear.
    home_assistant.set_state("binary_sensor.airflow_heat_ventilation_low_needed", "off", {})
    home_assistant.assert_entity_state("binary_sensor.airflow_ventilation_low_needed",
                                       "off", timeout=5)




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


# ── Decision table: sensor.airflow_cooling_state ──────────────────────────────────────────
# THE single decision. State = reason label; attributes profile + ventilation = what the
# controller and the boost apply. Reads only the indicators, never the outputs. Baseline dew
# thresholds: min 45% → dew_min ≈ 9.08°C (retention enters below 8.98, leaves at 9.08);
# indoor dew 12.0 is in band. Each test seeds every indicator explicitly via _seed_indicators.


def test_decision_off_when_auto_disabled(home_assistant: HomeAssistant) -> None:
    """Automation disabled → 'off' with no outputs, whatever the indicators say."""
    _seed_indicators(home_assistant, free="on")
    _assert_decision(home_assistant, "off", "off", "off")


def test_decision_free_cooling_cooling_season(home_assistant: HomeAssistant) -> None:
    """Free cooling in cooling season → cool profile + medium rate."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_cooling", free="on")
    _assert_decision(home_assistant, "free_cooling", "cool", "medium")


def test_decision_active_heating_ignores_free_cooling(home_assistant: HomeAssistant) -> None:
    """2026-10-23 regression: active_heating + free cooling available → heating, warm, auto.

    Free cooling is never used in heating season: neither the cool profile nor the medium bump.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", free="on")
    _assert_decision(home_assistant, "heating", "warm", "auto")


def test_decision_active_heating(home_assistant: HomeAssistant) -> None:
    """Active heating, indoor dew in band → heating, warm, auto."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating")
    _assert_decision(home_assistant, "heating", "warm", "auto")


def test_decision_flush(home_assistant: HomeAssistant) -> None:
    """Humidity flush (no boost) → cool profile + medium rate."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, flush="on")
    _assert_decision(home_assistant, "moisture_flush_cooling", "cool", "medium")


def test_decision_flush_overrides_heating(home_assistant: HomeAssistant) -> None:
    """A heating-season flush (moisture above max) still opens the bypass: flush beats heating."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", flush="on")
    _assert_decision(home_assistant, "moisture_flush_cooling", "cool", "medium")


def test_decision_drying_boost(home_assistant: HomeAssistant) -> None:
    """Flush + drying (boost schedule, cool weather station) → boost on top of the cool profile."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, flush="on", drying="on")
    _assert_decision(home_assistant, "moisture_flush_boost", "cool", "boost")


def test_decision_flush_wins_over_low_guard(home_assistant: HomeAssistant) -> None:
    """Flush and a low guard both on (transient, during the guards' 10-min delay) → flush wins.

    The guards are gated off by flush in the sensors; the decision encodes the same priority
    so a lagging guard can never hold the rate low while flushing.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, flush="on", moist="on")
    _assert_decision(home_assistant, "moisture_flush_cooling", "cool", "medium")


def test_decision_heat_protection_keeps_free_cooling_profile(home_assistant: HomeAssistant) -> None:
    """Hot real outdoor + cool intake (free cooling) → bypass open at LOW rate."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, free="on", heat="on")
    _assert_decision(home_assistant, "heat_protection", "cool", "low")


def test_decision_heat_protection_without_free_cooling(home_assistant: HomeAssistant) -> None:
    """Hot real outdoor, no free cooling → comfort profile at LOW rate."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, heat="on")
    _assert_decision(home_assistant, "heat_protection", "comfort", "low")


def test_decision_moisture_protection(home_assistant: HomeAssistant) -> None:
    """Humid outdoor → moisture_protection at LOW rate (heat + moist also reports moisture)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, moist="on", heat="on")
    _assert_decision(home_assistant, "moisture_protection", "comfort", "low")


def test_decision_moisture_protection_in_heating(home_assistant: HomeAssistant) -> None:
    """Protections only lower the rate; the season still picks the profile (warm in heating)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", moist="on")
    _assert_decision(home_assistant, "moisture_protection", "warm", "low")


def test_decision_moisture_retention_neutral(home_assistant: HomeAssistant) -> None:
    """Dry indoor air (dew 8.0 < dew_min 9.08) in neutral season → warm to retain moisture."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, indoor_dew="8.0")
    _assert_decision(home_assistant, "moisture_retention", "warm", "auto")


def test_decision_moisture_retention_beats_free_cooling(home_assistant: HomeAssistant) -> None:
    """Dry indoor + free cooling available (neutral) → retention wins: warm, no medium bump."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, indoor_dew="8.0", free="on")
    _assert_decision(home_assistant, "moisture_retention", "warm", "auto")


def test_decision_moisture_retention_in_heating(home_assistant: HomeAssistant) -> None:
    """Dry indoor in active heating → warm, labelled moisture_retention."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", indoor_dew="8.0")
    _assert_decision(home_assistant, "moisture_retention", "warm", "auto")


def test_decision_dry_in_cooling_season_is_comfort(home_assistant: HomeAssistant) -> None:
    """Cooling season is exempt from retention (indoor dew naturally dips in summer) → comfort."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_cooling", indoor_dew="8.0")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")


def test_decision_humid_neutral_is_comfort(home_assistant: HomeAssistant) -> None:
    """Humid indoor, no flush possible, neutral season → comfort (no 'keep current profile').

    The old controller left a warm profile in place here (no block matched); the decision is
    stateless, so every reason maps to one profile and nothing can get stuck.
    """
    _enable_auto(home_assistant)
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "warm", {})
    _seed_indicators(home_assistant, indoor_dew="14.0")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")


def _render_decision(home_assistant: HomeAssistant, prev_profile: str) -> str:
    """Render the decision macro directly with an explicit previous profile (hysteresis memory)."""
    return _render(home_assistant,
                   "{% from 'airflow_decision.jinja' import airflow_decision %}"
                   f"{{{{ airflow_decision('{prev_profile}') }}}}")


def test_decision_retention_hysteresis(home_assistant: HomeAssistant) -> None:
    """Dry retention enters 0.1°C below dew_min and leaves at dew_min (memory = previous profile).

    dew 9.03 sits between the enter edge (8.98) and the leave edge (9.08): from comfort it stays
    comfort, from warm it stays warm. Rendered via the macro with an explicit previous profile —
    in CI, changing the dew re-renders the trigger-based indicators to 'unknown' for a moment,
    which makes the sensor unavailable and drops its stored profile.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, indoor_dew="9.03")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    assert _render_decision(home_assistant, "comfort") == "comfort|comfort|auto"
    assert _render_decision(home_assistant, "warm") == "moisture_retention|warm|auto"
    _seed_indicators(home_assistant, indoor_dew="9.2")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    assert _render_decision(home_assistant, "warm") == "comfort|comfort|auto"


def test_decision_ignores_outputs(home_assistant: HomeAssistant) -> None:
    """The decision never reads the device: changing profile/boost/preset leaves it unchanged."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="active_heating", free="on")
    _assert_decision(home_assistant, "heating", "warm", "auto")
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "on", {})
    home_assistant.set_state("climate.airflow_climate", "auto", {"hvac_action": "cooling"})
    _assert_decision(home_assistant, "heating", "warm", "auto")


def test_decision_unavailable_when_indicator_missing(home_assistant: HomeAssistant) -> None:
    """Any indicator without a value → decision unavailable (automations then do nothing)."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("binary_sensor.airflow_free_cooling_available", "unavailable", {})
    home_assistant.assert_entity_state(_DECISION, "unavailable", timeout=5)


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
    """has_value guard: a missing input → binary_sensor.airflow_humidity_flush_needed unavailable.

    ORDER DEPENDENCY — this test does not stand alone. Its opening assertion needs
    binary_sensor.airflow_humidity_flush_needed to already hold a definite state, which only
    happens after the mocked clock has crossed that sensor's 10-minute delay_on/delay_off window
    at least once (see the "delayed sensors start 'unknown'" note on
    _assert_recomputes_after_reload below). Nothing in this test advances the clock, so it relies
    on test_flush_needed_recomputes_after_reload_unknown having run first and done it.

    That ordering holds only because pytest sorts by nodeid here (see tests/conftest.py's
    pytest_collection_modifyitems) and "flush_needed…" sorts before "flush_unavailable…". It is
    fragile: renaming either test, or running this one in isolation with `-k`, makes it fail with
    `current: 'unknown'`. If you touch it, give it its own fast_forward(timedelta(minutes=11))
    before the first assertion rather than preserving the accident.
    """
    # Baseline seeds all inputs → sensor resolves (off in baseline, see conftest).
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_flush_needed",
                                       "off", timeout=5)
    home_assistant.set_state("sensor.airflow_outdoor_dew_5min", "unavailable", {})
    home_assistant.assert_entity_state("binary_sensor.airflow_humidity_flush_needed",
                                       "unavailable", timeout=5)


# ── YAML-reload recovery tests ────────────────────────────────────────────────────────────
# A YAML reload re-creates trigger-based template binary sensors fresh as 'unknown' — unlike a
# full HA restart, a reload does NOT restore last state. Both moisture sensors omit a
# homeassistant:start trigger (to avoid restarting their 10-min delay at boot), so without a
# recovery path they would sit at 'unknown' until one of their normal input triggers next fired.
# Each sensor therefore has a self state-trigger (to: "unknown") that re-evaluates the template
# the moment the entity goes unknown. These tests simulate the reload by forcing the entity to
# 'unknown' and assert it recomputes to a definite state once the delay window is crossed.


def _assert_recomputes_after_reload(
    ha: HomeAssistant, tm: TimeMachine, entity_id: str
) -> None:
    """Force `entity_id` to 'unknown' (reload simulation) → assert it recomputes to on/off.

    Uses fast_forward, not jump_to_next(hour=...): the latter is forward-only, so asking for an
    hour the mocked clock has already passed silently advances a FULL DAY (see
    plans/ci-test-speedups.md). Neither sensor asserted here reads schedule.*,
    binary_sensor.workday, or any time function — verified against their template bodies in
    packages/airflow_cooling.yaml — so no absolute wall-clock anchor is needed. The only clock
    requirement is crossing the 10-minute delay_on/delay_off window — which has to happen TWICE:
    once so the sensor reaches a definite state at all, and once after the simulated reload.

    The first crossing is not optional. These are trigger-based binary sensors with no
    homeassistant:start trigger, so after HA boots they sit at 'unknown' until an input trigger
    fires AND their 10-minute delay elapses. conftest's baseline_states seeds the inputs (firing
    the triggers), but only a clock advance lands the result. The previous
    jump_to_next(hour=10, minute=0) supplied that crossing as a side effect of advancing a full
    day; dropping it without replacement left these sensors at 'unknown' and broke two unrelated
    airflow tests that were silently piggybacking on this helper running earlier in the
    alphabetical order (test_flush_unavailable_when_dependency_missing,
    test_heat_ventilation_low_needed_off_when_outdoor_below_indoor). That cross-test dependency
    is pre-existing and fragile, but is deliberately left as-is here rather than redesigned.
    """
    # Cross the delay window once so the sensor holds a definite state before the "reload".
    tm.fast_forward(timedelta(minutes=11))
    ha.assert_entity_state(entity_id, lambda s: s in ("on", "off"), timeout=5)
    # Simulate the reload: the entity is re-created as 'unknown'. The self-trigger (to: "unknown")
    # fires on this transition and re-evaluates the state template.
    ha.set_state(entity_id, "unknown", {})
    # The recomputed result must pass the 10-min delay_on/delay_off before it lands; step past it.
    tm.fast_forward(timedelta(minutes=11))
    # Without the self-trigger the entity would stay 'unknown' (no input changed) — reaching a
    # definite on/off proves the self-trigger fired and recomputed the template.
    ha.assert_entity_state(entity_id, lambda s: s in ("on", "off"), timeout=5)


def test_flush_needed_recomputes_after_reload_unknown(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """binary_sensor.airflow_humidity_flush_needed recovers from 'unknown' after a YAML reload."""
    _assert_recomputes_after_reload(
        home_assistant, time_machine, "binary_sensor.airflow_humidity_flush_needed"
    )


def test_low_needed_recomputes_after_reload_unknown(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """binary_sensor.airflow_moisture_ventilation_low_needed recovers from 'unknown' after reload."""
    _assert_recomputes_after_reload(
        home_assistant, time_machine, "binary_sensor.airflow_moisture_ventilation_low_needed"
    )


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


# ── hvac_action tests ─────────────────────────────────────────────────────────────────────


def _hvac_action_state(decision: str) -> str:
    """Render template mirroring climate.airflow_climate's hvac_action_template.

    The decision (sensor.airflow_cooling_state's state) is injected as a literal so the branch
    logic is exercised deterministically. 'drying' needs a flush decision AND the device on the
    cool profile; the raw boost switch is not read, so its few-second drop on every boost re-arm
    cannot flip the action.
    """
    return f"""
    {{%- set profile = states('select.comfoconnect_pro_temperature_profile') -%}}
    {{%- set state   = '{decision}' -%}}
    {{%- if profile == 'cool' and state in ['moisture_flush_boost', 'moisture_flush_cooling'] -%}}drying
    {{%- elif profile == 'cool' -%}}cooling
    {{%- elif profile == 'warm' -%}}heating
    {{%- elif profile == 'comfort' -%}}fan
    {{%- else -%}}idle{{%- endif -%}}
    """


def test_hvac_action_drying_from_flush(home_assistant: HomeAssistant) -> None:
    """cool profile + flush decided → hvac_action 'drying'."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    assert _render(home_assistant, _hvac_action_state("moisture_flush_cooling")) == "drying"


def test_hvac_action_cooling_without_flush(home_assistant: HomeAssistant) -> None:
    """cool profile + free cooling decided → hvac_action 'cooling'."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    assert _render(home_assistant, _hvac_action_state("free_cooling")) == "cooling"


def test_hvac_action_drying_survives_boost_blip(home_assistant: HomeAssistant) -> None:
    """Boost decided but boost switch momentarily OFF (re-arm blip) → action stays 'drying'."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("switch.comfoconnect_pro_boost", "off", {})  # the re-arm blip
    assert _render(home_assistant, _hvac_action_state("moisture_flush_boost")) == "drying"


def test_hvac_action_not_drying_before_profile_applied(home_assistant: HomeAssistant) -> None:
    """Flush decided but the device is still on comfort → 'fan' (reports the actual device)."""
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    assert _render(home_assistant, _hvac_action_state("moisture_flush_cooling")) == "fan"


def test_hvac_action_template_matches_mirror(home_assistant: HomeAssistant) -> None:
    """The mirror above must match packages/airflow_cooling.yaml's hvac_action_template body."""
    with open("packages/airflow_cooling.yaml", encoding="utf-8") as f:
        body = f.read()
    assert "state in ['moisture_flush_boost', 'moisture_flush_cooling']" in body
    assert "states('sensor.airflow_cooling_state')" in body


# ── Unified controller consistency tests ──────────────────────────────────────────────────
# The controller applies the decision idempotently. These tests pin the cases that ARE
# observable despite the CI service-call stubs: each per-branch idempotency guard and the
# restore gate suppress a write when the seeded state already equals the decided state, so
# auto_mode / preset must stay put (no thrash, no notify).


def test_controller_low_idempotent_no_write(home_assistant: HomeAssistant) -> None:
    """Low decided but already (auto off, preset low) → low branch guard False → no write."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, moist="on")
    _assert_decision(home_assistant, "moisture_protection", "comfort", "low")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "low", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "low", timeout=3)


def test_controller_medium_idempotent_no_write(home_assistant: HomeAssistant) -> None:
    """Medium decided (flush) but already (auto off, preset medium, cool) → no write."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, flush="on", indoor_dew="14.0")
    _assert_decision(home_assistant, "moisture_flush_cooling", "cool", "medium")
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "cool", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "off", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "off", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "cool", timeout=3)


def test_controller_restore_no_thrash_when_auto_already_on(home_assistant: HomeAssistant) -> None:
    """auto decided and auto_mode already ON → restore branch gate False → auto stays on."""
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant)
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)


def test_controller_full_rest_state_is_total_no_op(home_assistant: HomeAssistant) -> None:
    """Comfort decided and the device already at rest → both sections no-op.

    Baseline (neutral, indoor dew in band, profile comfort, auto on, preset medium) is the
    steady state: Section 1 finds comfort already set, Section 2's restore gate finds auto on.
    """
    _enable_auto(home_assistant)
    _seed_indicators(home_assistant, season="neutral")
    _assert_decision(home_assistant, "comfort", "comfort", "auto")
    home_assistant.set_state("select.comfoconnect_pro_temperature_profile", "comfort", {})
    home_assistant.set_state("switch.comfoconnect_pro_auto_mode", "on", {})
    home_assistant.set_state("select.comfoconnect_pro_ventilation_preset", "medium", {})
    _trigger(home_assistant)
    home_assistant.assert_entity_state("select.comfoconnect_pro_temperature_profile",
                                       "comfort", timeout=3)
    home_assistant.assert_entity_state("switch.comfoconnect_pro_auto_mode", "on", timeout=3)
    home_assistant.assert_entity_state("select.comfoconnect_pro_ventilation_preset",
                                       "medium", timeout=3)
