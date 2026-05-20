"""Victron MQTT energy system tests.

Verifies the full chain:
  MQTT sensor values (seeded via set_state; MQTT broker absent in CI)
  → derived template sensors (grid, battery, VEBus attribution)
  → energy accumulation sensors (trigger-based, 1-minute intervals)

time_machine.jump_to_next() fires all time_pattern triggers that were crossed,
including the every-minute energy accumulation trigger — no real waiting needed.
"""

import pytest
from ha_integration_test_harness import HomeAssistant, TimeMachine


def _seed(
    ha: HomeAssistant,
    *,
    grid_l1: float = 0,
    grid_l2: float = 0,
    grid_l3: float = 0,
    battery_power: float = 0,
    vebus_dc: float = 0,
    dc_pv: float = 0,
    ac_inverter: float = 0,
    solar_dc: float = 0,
    ac_l1: float = 0,
    ac_l2: float = 0,
    ac_l3: float = 0,
) -> None:
    """Seed all Victron MQTT power sensors via set_state."""
    attrs_w = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
    ha.set_state("sensor.victron_grid_l1_power", str(int(grid_l1)), attrs_w)
    ha.set_state("sensor.victron_grid_l2_power", str(int(grid_l2)), attrs_w)
    ha.set_state("sensor.victron_grid_l3_power", str(int(grid_l3)), attrs_w)
    ha.set_state("sensor.victron_battery_power", str(int(battery_power)), attrs_w)
    ha.set_state("sensor.victron_vebus_dc_power", str(int(vebus_dc)), attrs_w)
    ha.set_state("sensor.victron_dc_pv_total_power", str(int(dc_pv)), attrs_w)
    ha.set_state("sensor.victron_ac_inverter_power", str(int(ac_inverter)), attrs_w)
    ha.set_state("sensor.solar_yield_watts", str(int(solar_dc)),
                 {"unit_of_measurement": "W", "device_class": "power"})
    ha.set_state("sensor.victron_ac_load_l1", str(int(ac_l1)), attrs_w)
    ha.set_state("sensor.victron_ac_load_l2", str(int(ac_l2)), attrs_w)
    ha.set_state("sensor.victron_ac_load_l3", str(int(ac_l3)), attrs_w)


def _reset_energy(ha: HomeAssistant) -> None:
    """Force all four energy accumulation sensors to 0.0 kWh.

    Called after the first clock jump in accumulation tests so any side-effect
    accumulation during the jump itself is wiped before the test scenario is seeded.
    """
    attrs_kwh = {
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    }
    for eid in (
        "sensor.victron_grid_energy_import",
        "sensor.victron_grid_energy_export",
        "sensor.victron_battery_energy_in",
        "sensor.victron_battery_energy_out",
    ):
        ha.set_state(eid, "0.0", attrs_kwh)


# ── Template sensor tests ─────────────────────────────────────────────────────
# No time jump needed — just seed MQTT sensors and assert derived template values.


def test_grid_import_half_wave(home_assistant: HomeAssistant) -> None:
    """Grid import: L1=200, L2=200, L3=100 → total=500 W, import=500, export=0."""
    _seed(home_assistant, grid_l1=200, grid_l2=200, grid_l3=100)
    home_assistant.assert_entity_state("sensor.victron_grid_total_power", "500.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", "500.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", lambda s: float(s) == 0.0, timeout=5)


def test_grid_export_half_wave(home_assistant: HomeAssistant) -> None:
    """Grid export: L1=−300, L2=−200, L3=−200 → total=−700 W, export=700, import=0."""
    _seed(home_assistant, grid_l1=-300, grid_l2=-200, grid_l3=-200)
    home_assistant.assert_entity_state("sensor.victron_grid_total_power", "-700.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", "700.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", lambda s: float(s) == 0.0, timeout=5)


def test_battery_charge_half_wave(home_assistant: HomeAssistant) -> None:
    """Battery charging: power=+1200 W → charge=1200, discharge=0."""
    _seed(home_assistant, battery_power=1200)
    home_assistant.assert_entity_state("sensor.victron_battery_power_charge", "1200.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_power_discharge", lambda s: float(s) == 0.0, timeout=5)


def test_battery_discharge_half_wave(home_assistant: HomeAssistant) -> None:
    """Battery discharging: power=−800 W → discharge=800, charge=0."""
    _seed(home_assistant, battery_power=-800)
    home_assistant.assert_entity_state("sensor.victron_battery_power_discharge", "800.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_power_charge", lambda s: float(s) == 0.0, timeout=5)


def test_vebus_inverter_mode(home_assistant: HomeAssistant) -> None:
    """VEBus inverter mode: vebus_dc=−2000, dc_pv=2500.

    Inverter output 2000 W < PV 2500 W → all inverter output attributed to PV,
    battery contributes 0 (excess PV is absorbed by battery instead).
    """
    _seed(home_assistant, vebus_dc=-2000, dc_pv=2500)
    home_assistant.assert_entity_state("sensor.victron_vebus_inverter_power", "2000.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_vebus_charger_power", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_dc_pv_to_ac_power", "2000.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_to_ac_power", lambda s: float(s) == 0.0, timeout=5)


def test_vebus_charger_mode(home_assistant: HomeAssistant) -> None:
    """VEBus charger mode: vebus_dc=+1500 W → charger=1500, inverter=0."""
    _seed(home_assistant, vebus_dc=1500)
    home_assistant.assert_entity_state("sensor.victron_vebus_charger_power", "1500.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_vebus_inverter_power", lambda s: float(s) == 0.0, timeout=5)


def test_battery_supplements_pv_in_inverter_mode(home_assistant: HomeAssistant) -> None:
    """Battery supplements PV: vebus_dc=−3000, dc_pv=1000.

    Inverter output 3000 W > PV 1000 W → 1000 W attributed to PV, 2000 W to battery.
    """
    _seed(home_assistant, vebus_dc=-3000, dc_pv=1000)
    home_assistant.assert_entity_state("sensor.victron_dc_pv_to_ac_power", "1000.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_to_ac_power", "2000.0", timeout=5)


def test_ac_load_total(home_assistant: HomeAssistant) -> None:
    """AC load total: L1=500, L2=400, L3=300 → total=1200 W."""
    _seed(home_assistant, ac_l1=500, ac_l2=400, ac_l3=300)
    home_assistant.assert_entity_state("sensor.victron_ac_load_total_power", "1200.0", timeout=5)


def test_battery_ac_power_night(home_assistant: HomeAssistant) -> None:
    """Night: ac_load=102, grid=10, solar=0 → battery_ac = -(102-10) = -92 W (Standard: discharging).

    HA Power usage = grid(10) + |battery_discharge(92)| = 102 W = actual AC load.
    """
    _seed(home_assistant, grid_l1=10, ac_l1=102)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", "-92.0", timeout=5)


def test_battery_ac_power_solar_charging(home_assistant: HomeAssistant) -> None:
    """Solar surplus charges battery: dc_pv=1200, ac_load=600, grid=0 → battery_ac = +600 W (charging).

    HA Power usage = solar(1200) + grid(0) - battery_charge(600) = 600 W = actual AC load.
    """
    _seed(home_assistant, dc_pv=1200, ac_l1=600)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", "600.0", timeout=5)


def test_battery_ac_power_grid_exporting(home_assistant: HomeAssistant) -> None:
    """Solar covers load and exports: dc_pv=800, ac_load=600, grid=−200 → battery_ac = 0.

    HA Power usage = solar(800) + grid(−200) + battery(0) = 600 W = actual AC load.
    """
    _seed(home_assistant, dc_pv=800, grid_l1=-200, ac_l1=600)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", lambda s: float(s) == 0.0, timeout=5)


# ── Night scenario test ───────────────────────────────────────────────────────


def test_night_solar_off_battery_discharge(home_assistant: HomeAssistant) -> None:
    """Night scenario: solar off, battery discharging 600 W, grid supplying 1000 W.

    Grid: L1=400, L2=350, L3=250 → total 1000 W import.
    Battery: −600 W (discharging). VEBus: −600 W (inverter mode).
    DC PV: 0 W, AC inverter: 0 W (solar fully off).
    VEBus output entirely attributed to battery (no PV available).
    """
    _seed(
        home_assistant,
        grid_l1=400, grid_l2=350, grid_l3=250,
        battery_power=-600, vebus_dc=-600,
        dc_pv=0, ac_inverter=0, solar_dc=0,
    )
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", "1000.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_power_discharge", "600.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_power_charge", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_vebus_inverter_power", "600.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_vebus_charger_power", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_dc_pv_to_ac_power", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_to_ac_power", "600.0", timeout=5)


# ── Energy accumulation tests ─────────────────────────────────────────────────
# Pattern: jump to :00 boundary, reset energy counters, seed power, assert source
# settled, jump to :01 → fires the time_pattern:/1 trigger, assert accumulated kWh.
# Formula: power_W / 60000 kWh per minute.


def test_grid_import_energy_accumulates(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """3000 W grid import × 1 min = 0.05 kWh accumulated in grid_energy_import."""
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, grid_l1=3000)
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", "3000.0", timeout=5)
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_grid_energy_import",
        lambda s: abs(float(s) - 0.05) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state("sensor.victron_grid_energy_export", "0.0", timeout=5)


def test_grid_export_energy_accumulates(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """1800 W grid export × 1 min = 0.03 kWh accumulated in grid_energy_export."""
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, grid_l1=-1800)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", "1800.0", timeout=5)
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_grid_energy_export",
        lambda s: abs(float(s) - 0.03) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state("sensor.victron_grid_energy_import", "0.0", timeout=5)


def test_battery_discharge_energy_accumulates(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """1200 W battery discharge × 1 min = 0.02 kWh accumulated in battery_energy_out."""
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, battery_power=-1200)
    home_assistant.assert_entity_state("sensor.victron_battery_power_discharge", "1200.0", timeout=5)
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_battery_energy_out",
        lambda s: abs(float(s) - 0.02) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state("sensor.victron_battery_energy_in", "0.0", timeout=5)


def test_night_no_grid_energy_accumulates(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """Night: zero grid flow, 1500 W battery discharge → grid energy stays 0, batt_out grows."""
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, grid_l1=0, grid_l2=0, grid_l3=0, battery_power=-1500)
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", lambda s: float(s) == 0.0, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", lambda s: float(s) == 0.0, timeout=5)
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state("sensor.victron_grid_energy_import", "0.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_energy_export", "0.0", timeout=5)
    home_assistant.assert_entity_state(
        "sensor.victron_battery_energy_out",
        lambda s: float(s) > 0,
        timeout=5,
    )
