"""Pool pump package template sensor tests.

Covers the derived binary sensors in packages/pool_pump.yaml and the shared
energy template sensors in packages/energy.yaml:

  energy.yaml:
    sensor.energy_pv_surplus          — mirrors victron_grid_power_export
    binary_sensor.energy_free_available — surplus > noise floor AND soc >= min

  pool_pump.yaml:
    binary_sensor.pool_pv_surplus_available      — energy_pv_surplus >= threshold
    binary_sensor.pool_extended_run_energy_ok    — surplus OR soc >= pool min
    binary_sensor.pool_orp_alarm                 — ORP < alarm threshold
    binary_sensor.pool_extended_run_conditions_met — temp AND orp_alarm AND energy_ok

MQTT broker and VistaPool cloud are absent in CI; sensors are seeded via set_state.
"""

import pytest
from ha_integration_test_harness import HomeAssistant


# ── Helpers ───────────────────────────────────────────────────────────────────

_ATTRS_W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
_ATTRS_PCT = {"unit_of_measurement": "%", "device_class": "battery", "state_class": "measurement"}
_ATTRS_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
_ATTRS_MV = {"unit_of_measurement": "mV"}


def _set_grid_export(ha: HomeAssistant, export_w: float) -> None:
    """Drive the Victron grid sensors so that victron_grid_power_export = export_w.

    export_w positive  → distributes across L1/L2/L3 as negative (exporting).
    export_w zero      → all phases at 0.
    """
    per_phase = -export_w / 3
    ha.set_state("sensor.victron_grid_l1_power", str(round(per_phase, 1)), _ATTRS_W)
    ha.set_state("sensor.victron_grid_l2_power", str(round(per_phase, 1)), _ATTRS_W)
    ha.set_state("sensor.victron_grid_l3_power", str(round(per_phase, 1)), _ATTRS_W)


def _set_soc(ha: HomeAssistant, soc: float) -> None:
    ha.set_state("sensor.victron_battery_soc", str(soc), _ATTRS_PCT)


def _set_orp(ha: HomeAssistant, orp_mv: float) -> None:
    ha.set_state("sensor.vistapool_orp", str(orp_mv), _ATTRS_MV)


def _set_outdoor_temp(ha: HomeAssistant, temp_c: float) -> None:
    ha.set_state("sensor.wheatherstation_outdoor_temperature", str(temp_c), _ATTRS_C)


# ── sensor.energy_pv_surplus ──────────────────────────────────────────────────

def test_energy_pv_surplus_export(home_assistant: HomeAssistant) -> None:
    """Grid exporting 600 W → energy_pv_surplus = 600."""
    _set_grid_export(home_assistant, 600)
    home_assistant.assert_entity_state(
        "sensor.energy_pv_surplus",
        lambda s: abs(float(s) - 600) < 1,
        timeout=5,
    )


def test_energy_pv_surplus_import(home_assistant: HomeAssistant) -> None:
    """Grid importing 400 W (positive phases) → energy_pv_surplus = 0 (no export)."""
    # Positive grid power = importing; export half-wave is clamped to 0
    ha = home_assistant
    ha.set_state("sensor.victron_grid_l1_power", "133", _ATTRS_W)
    ha.set_state("sensor.victron_grid_l2_power", "133", _ATTRS_W)
    ha.set_state("sensor.victron_grid_l3_power", "134", _ATTRS_W)
    ha.assert_entity_state(
        "sensor.energy_pv_surplus",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


# ── binary_sensor.energy_free_available ───────────────────────────────────────

def test_energy_free_available_on(home_assistant: HomeAssistant) -> None:
    """Surplus > 50 W (noise floor) AND soc >= 80 % → energy_free_available on."""
    _set_grid_export(home_assistant, 200)  # > energy_min_surplus=50
    _set_soc(home_assistant, 85)           # >= energy_battery_soc_min=80
    home_assistant.assert_entity_state("binary_sensor.energy_free_available", "on", timeout=5)


def test_energy_free_available_surplus_below_floor(home_assistant: HomeAssistant) -> None:
    """Surplus at noise floor or below → energy_free_available off."""
    _set_grid_export(home_assistant, 30)   # <= energy_min_surplus=50
    _set_soc(home_assistant, 90)
    home_assistant.assert_entity_state("binary_sensor.energy_free_available", "off", timeout=5)


def test_energy_free_available_soc_too_low(home_assistant: HomeAssistant) -> None:
    """Good surplus but battery soc below minimum → energy_free_available off."""
    _set_grid_export(home_assistant, 500)
    _set_soc(home_assistant, 70)  # < energy_battery_soc_min=80
    home_assistant.assert_entity_state("binary_sensor.energy_free_available", "off", timeout=5)


# ── binary_sensor.pool_pv_surplus_available ───────────────────────────────────

def test_pool_pv_surplus_available_on(home_assistant: HomeAssistant) -> None:
    """PV export >= 500 W (pool threshold) → pool_pv_surplus_available on."""
    _set_grid_export(home_assistant, 600)
    home_assistant.assert_entity_state("binary_sensor.pool_pv_surplus_available", "on", timeout=5)


def test_pool_pv_surplus_available_at_threshold(home_assistant: HomeAssistant) -> None:
    """PV export exactly at threshold → on."""
    _set_grid_export(home_assistant, 500)
    home_assistant.assert_entity_state("binary_sensor.pool_pv_surplus_available", "on", timeout=5)


def test_pool_pv_surplus_available_below_threshold(home_assistant: HomeAssistant) -> None:
    """PV export below 500 W → pool_pv_surplus_available off."""
    _set_grid_export(home_assistant, 300)
    home_assistant.assert_entity_state("binary_sensor.pool_pv_surplus_available", "off", timeout=5)


def test_pool_pv_surplus_available_no_export(home_assistant: HomeAssistant) -> None:
    """No export at all → pool_pv_surplus_available off."""
    _set_grid_export(home_assistant, 0)
    home_assistant.assert_entity_state("binary_sensor.pool_pv_surplus_available", "off", timeout=5)


# ── binary_sensor.pool_extended_run_energy_ok ─────────────────────────────────

def test_pool_extended_run_energy_ok_via_surplus(home_assistant: HomeAssistant) -> None:
    """PV surplus available (high export), low soc → energy_ok on via surplus."""
    _set_grid_export(home_assistant, 600)
    _set_soc(home_assistant, 50)  # < pool_battery_soc_min=80
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_energy_ok", "on", timeout=5
    )


def test_pool_extended_run_energy_ok_via_soc(home_assistant: HomeAssistant) -> None:
    """Low PV export but soc >= 80 % → energy_ok on via battery."""
    _set_grid_export(home_assistant, 0)
    _set_soc(home_assistant, 85)  # >= pool_battery_soc_min=80
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_energy_ok", "on", timeout=5
    )


def test_pool_extended_run_energy_ok_off(home_assistant: HomeAssistant) -> None:
    """No PV surplus AND soc < 80 % → energy_ok off."""
    _set_grid_export(home_assistant, 0)
    _set_soc(home_assistant, 50)
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_energy_ok", "off", timeout=5
    )


# ── binary_sensor.pool_orp_alarm ──────────────────────────────────────────────

def test_pool_orp_alarm_on(home_assistant: HomeAssistant) -> None:
    """ORP below threshold (650 mV) → alarm on."""
    _set_orp(home_assistant, 600)
    home_assistant.assert_entity_state("binary_sensor.pool_orp_alarm", "on", timeout=5)


def test_pool_orp_alarm_at_threshold(home_assistant: HomeAssistant) -> None:
    """ORP exactly at threshold → NOT alarming (alarm requires strictly less than)."""
    _set_orp(home_assistant, 650)
    home_assistant.assert_entity_state("binary_sensor.pool_orp_alarm", "off", timeout=5)


def test_pool_orp_alarm_off(home_assistant: HomeAssistant) -> None:
    """ORP above threshold → alarm off."""
    _set_orp(home_assistant, 720)
    home_assistant.assert_entity_state("binary_sensor.pool_orp_alarm", "off", timeout=5)


def test_pool_orp_alarm_unavailable_propagates(home_assistant: HomeAssistant) -> None:
    """VistaPool sensor unavailable → pool_orp_alarm becomes unavailable."""
    home_assistant.set_state("sensor.vistapool_orp", "unavailable", _ATTRS_MV)
    home_assistant.assert_entity_state(
        "binary_sensor.pool_orp_alarm", "unavailable", timeout=5
    )


# ── binary_sensor.pool_extended_run_conditions_met ────────────────────────────

def test_pool_extended_run_conditions_all_met(home_assistant: HomeAssistant) -> None:
    """temp > 30, ORP alarm, PV surplus → conditions_met on."""
    _set_outdoor_temp(home_assistant, 32)
    _set_orp(home_assistant, 600)      # alarm on
    _set_grid_export(home_assistant, 600)  # surplus on
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_conditions_met", "on", timeout=5
    )


def test_pool_extended_run_conditions_temp_too_low(home_assistant: HomeAssistant) -> None:
    """temp <= 30 → conditions_met off even if ORP and energy are met."""
    _set_outdoor_temp(home_assistant, 29)
    _set_orp(home_assistant, 600)
    _set_grid_export(home_assistant, 600)
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_conditions_met", "off", timeout=5
    )


def test_pool_extended_run_conditions_orp_ok(home_assistant: HomeAssistant) -> None:
    """ORP above alarm threshold → conditions_met off (ORP alarm off)."""
    _set_outdoor_temp(home_assistant, 32)
    _set_orp(home_assistant, 720)      # alarm off
    _set_grid_export(home_assistant, 600)
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_conditions_met", "off", timeout=5
    )


def test_pool_extended_run_conditions_no_energy(home_assistant: HomeAssistant) -> None:
    """No PV surplus and low soc → energy_ok off → conditions_met off."""
    _set_outdoor_temp(home_assistant, 32)
    _set_orp(home_assistant, 600)
    _set_grid_export(home_assistant, 0)
    _set_soc(home_assistant, 50)  # < pool_battery_soc_min=80
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_conditions_met", "off", timeout=5
    )


def test_pool_extended_run_conditions_battery_saves_it(home_assistant: HomeAssistant) -> None:
    """No PV surplus but soc >= 80 % → energy_ok on → conditions_met on (if temp+ORP met)."""
    _set_outdoor_temp(home_assistant, 32)
    _set_orp(home_assistant, 600)
    _set_grid_export(home_assistant, 0)
    _set_soc(home_assistant, 85)  # >= pool_battery_soc_min=80
    home_assistant.assert_entity_state(
        "binary_sensor.pool_extended_run_conditions_met", "on", timeout=5
    )
