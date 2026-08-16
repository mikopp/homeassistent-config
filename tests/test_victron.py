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
    ha.set_state("sensor.victron_vebus_dc_power", str(int(vebus_dc)), attrs_w)
    ha.set_state("sensor.victron_dc_pv_total_power", str(int(dc_pv)), attrs_w)
    ha.set_state("sensor.victron_ac_inverter_power", str(int(ac_inverter)), attrs_w)
    ha.set_state("sensor.victron_solar_yield_dc_watts", str(int(solar_dc)),
                 {"unit_of_measurement": "W", "device_class": "power"})
    ha.set_state("sensor.victron_ac_load_l1", str(int(ac_l1)), attrs_w)
    ha.set_state("sensor.victron_ac_load_l2", str(int(ac_l2)), attrs_w)
    ha.set_state("sensor.victron_ac_load_l3", str(int(ac_l3)), attrs_w)


def _reset_energy(ha: HomeAssistant) -> None:
    """Force all energy accumulation sensors to 0.0 kWh and un-baseline the counter-delta sensors.

    Called after the first clock jump in accumulation tests so any side-effect
    accumulation during the jump itself is wiped before the test scenario is seeded.
    The counter-delta baseline sensors (victron_solar_yield_dc_baseline_kwh,
    victron_ac_pv_energy_baseline_kwh — own dedicated sensors, not attributes; see
    packages/victron.yaml) are reset to literal 'unknown' so the AC-referenced accumulators
    that read them start un-baselined (bootstrap-fallback state) in every test.
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
        "sensor.victron_multiplus_ac_out_energy",
        "sensor.victron_multiplus_dc_in_energy",
        "sensor.victron_multiplus_conversion_loss_energy",
        "sensor.victron_solar_yield_total_kwh",
    ):
        ha.set_state(eid, "0.0", attrs_kwh)
    ha.set_state("sensor.victron_solar_yield_dc_baseline_kwh", "unknown", {})
    ha.set_state("sensor.victron_ac_pv_energy_baseline_kwh", "unknown", {})


def _seed_eta(ha: HomeAssistant, *, ac_out: float, dc_in: float) -> None:
    """Force the inverter-efficiency accumulators directly, hence eta = ac_out/dc_in * 100.

    sensor.victron_multiplus_conversion_efficiency is a plain template sensor that recomputes whenever
    these two change, so this makes eta directly controllable in a test without needing to
    run a real minute of accumulation first.
    """
    attrs_kwh = {
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    }
    ha.set_state("sensor.victron_multiplus_ac_out_energy", str(ac_out), attrs_kwh)
    ha.set_state("sensor.victron_multiplus_dc_in_energy", str(dc_in), attrs_kwh)


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


def test_ac_load_total(home_assistant: HomeAssistant) -> None:
    """AC load total: L1=500, L2=400, L3=300 → total=1200 W."""
    _seed(home_assistant, ac_l1=500, ac_l2=400, ac_l3=300)
    home_assistant.assert_entity_state("sensor.victron_ac_load_total_power", "1200.0", timeout=5)


def test_battery_ac_power_night(home_assistant: HomeAssistant) -> None:
    """Night: ac_load=102, grid=10, solar=0 → battery_ac = 102-10 = +92 W (discharging, positive).

    HA Power usage = solar(0) + grid(10) + battery(92) = 102 W = actual AC load.
    """
    _seed(home_assistant, grid_l1=10, ac_l1=102)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", lambda s: float(s) == 92, timeout=5)


def test_battery_ac_power_solar_charging(home_assistant: HomeAssistant) -> None:
    """Solar surplus charges battery: dc_pv=1200, ac_load=600, grid=0 → battery_ac = −600 W (charging, negative).

    HA Power usage = solar(1200) + grid(0) + battery(−600) = 600 W = actual AC load.
    """
    _seed(home_assistant, dc_pv=1200, ac_l1=600)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", lambda s: float(s) == -600, timeout=5)


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
        vebus_dc=-600,
        dc_pv=0, ac_inverter=0, solar_dc=0,
    )
    home_assistant.assert_entity_state("sensor.victron_grid_power_import", "1000.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_power_export", lambda s: float(s) == 0.0, timeout=5)


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
    """1200 W battery discharge supplying 1200 W AC load (no grid, no solar) × 1 min = 0.02 kWh.

    battery_ac_power = -(ac_load - grid - dc_pv - ac_pv) = -(1200 - 0 - 0 - 0) = -1200 W.
    Energy accumulates from the AC-equivalent half-wave, not the DC battery sensor.
    """
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, ac_l1=1200)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", lambda s: float(s) == 1200, timeout=5)
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
    """Night: zero grid flow, 1500 W battery discharge supplying 1500 W AC load → grid stays 0, batt_out grows.

    battery_ac_power = -(1500 - 0 - 0 - 0) = -1500 W → energy_out accumulates.
    """
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, grid_l1=0, grid_l2=0, grid_l3=0, ac_l1=1500)
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


# ── AC-referenced accounting tests ──────────────────────────────────────────────
# See plans/victron-ac-referenced-accounting.md for the full design rationale.


def test_multiplus_ac_net_inverting(home_assistant: HomeAssistant) -> None:
    """Inverting: ac_load=1000, grid=200 import, ac_pv=100 → mp_ac_net = 1000-200-100 = 700 W."""
    _seed(home_assistant, ac_l1=1000, grid_l1=200, ac_inverter=100)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_ac_net_power", lambda s: float(s) == 700, timeout=5
    )


def test_multiplus_ac_net_charging(home_assistant: HomeAssistant) -> None:
    """Charging: ac_load=200, grid=1000 import → mp_ac_net = 200-1000-0 = -800 W."""
    _seed(home_assistant, ac_l1=200, grid_l1=1000)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_ac_net_power", lambda s: float(s) == -800, timeout=5
    )


def test_inverter_efficiency_bootstrap(home_assistant: HomeAssistant) -> None:
    """Both accumulators at the conftest baseline 0.0 kWh → eta = 100 % bootstrap."""
    _seed_eta(home_assistant, ac_out=0.0, dc_in=0.0)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_efficiency", lambda s: float(s) == 100.0, timeout=5
    )


def test_inverter_efficiency_below_threshold_still_bootstraps(home_assistant: HomeAssistant) -> None:
    """E_dc_in < 1.0 kWh (not enough inverting yet) → still 100 % even though a ratio exists."""
    _seed_eta(home_assistant, ac_out=0.8, dc_in=0.9)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_efficiency", lambda s: float(s) == 100.0, timeout=5
    )


def test_inverter_efficiency_accumulated(home_assistant: HomeAssistant) -> None:
    """Real ratio once past the 1.0 kWh threshold: 9.0/10.0 → 90 %."""
    _seed_eta(home_assistant, ac_out=9.0, dc_in=10.0)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_efficiency", lambda s: float(s) == 90.0, timeout=5
    )


def test_inverter_efficiency_clamped_low(home_assistant: HomeAssistant) -> None:
    """A 10 % raw ratio is clamped up to the 50 % floor, never allowed to corrupt the split."""
    _seed_eta(home_assistant, ac_out=1.0, dc_in=10.0)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_efficiency", lambda s: float(s) == 50.0, timeout=5
    )


def test_inverter_efficiency_clamped_high(home_assistant: HomeAssistant) -> None:
    """A 120 % raw ratio (measurement noise) is clamped down to the 100 % ceiling."""
    _seed_eta(home_assistant, ac_out=12.0, dc_in=10.0)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_efficiency", lambda s: float(s) == 100.0, timeout=5
    )


def test_solar_yield_ac_watts_bootstrap(home_assistant: HomeAssistant) -> None:
    """At eta=100% bootstrap, solar_ac_watts equals dc_pv exactly — today's behaviour."""
    _seed_eta(home_assistant, ac_out=0.0, dc_in=0.0)
    _seed(home_assistant, dc_pv=1000)
    home_assistant.assert_entity_state(
        "sensor.solar_yield_watts", lambda s: float(s) == 1000, timeout=5
    )


def test_solar_yield_ac_watts_discounted_by_eta(home_assistant: HomeAssistant) -> None:
    """eta=90% → solar_ac_watts = 1000 * 0.90 = 900 W."""
    _seed_eta(home_assistant, ac_out=9.0, dc_in=10.0)
    _seed(home_assistant, dc_pv=1000)
    home_assistant.assert_entity_state(
        "sensor.solar_yield_watts", lambda s: float(s) == 900, timeout=5
    )


def test_battery_ac_power_with_eta(home_assistant: HomeAssistant) -> None:
    """Regression guard proving eta actually reaches battery_ac_power, not just solar.

    eta=90%, dc_pv=1200, ac_load=600, no grid/ac_pv:
      mp_ac_net = 600 - 0 - 0 = 600
      solar_ac  = 1200 * 0.90 = 1080
      batt_ac   = 600 - 1080 = -480  (charging)
    """
    _seed_eta(home_assistant, ac_out=9.0, dc_in=10.0)
    _seed(home_assistant, dc_pv=1200, ac_l1=600)
    home_assistant.assert_entity_state(
        "sensor.victron_battery_ac_power", lambda s: float(s) == -480, timeout=5
    )


def test_power_domain_identity_holds_with_eta(home_assistant: HomeAssistant) -> None:
    """solar_ac + ac_pv + grid + batt_ac == ac_load, exactly, for a non-trivial eta.

    eta=90%, dc_pv=2000, ac_pv=500, grid=-300 (exporting), ac_load=1200:
      mp_ac_net = 1200 - (-300) - 500 = 1000
      solar_ac  = 2000 * 0.90 = 1800
      batt_ac   = 1000 - 1800 = -800
      identity: 1800 + 500 + (-300) + (-800) = 1200 == ac_load
    """
    _seed_eta(home_assistant, ac_out=9.0, dc_in=10.0)
    _seed(home_assistant, dc_pv=2000, ac_inverter=500, grid_l1=-300, ac_l1=1000, ac_l2=200)
    home_assistant.assert_entity_state("sensor.victron_ac_load_total_power", lambda s: float(s) == 1200, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_grid_total_power", lambda s: float(s) == -300, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_ac_inverter_power", lambda s: float(s) == 500, timeout=5)
    home_assistant.assert_entity_state("sensor.solar_yield_watts", lambda s: float(s) == 1800, timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_ac_power", lambda s: float(s) == -800, timeout=5)
    # 1800 + 500 + (-300) + (-800) == 1200 == ac_load, the identity itself.


def test_conversion_loss_inverting(home_assistant: HomeAssistant) -> None:
    """Inverting: mp_ac_net=950 (from ac_load), vebus_dc=-1000 → loss = -(950-1000) = 50 W."""
    _seed(home_assistant, ac_l1=950, vebus_dc=-1000)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_loss_power", lambda s: float(s) == 50, timeout=5
    )


def test_conversion_loss_charging(home_assistant: HomeAssistant) -> None:
    """Charging: mp_ac_net=-1000 (from grid), vebus_dc=950 → loss = -(-1000+950) = 50 W."""
    _seed(home_assistant, grid_l1=1000, vebus_dc=950)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_loss_power", lambda s: float(s) == 50, timeout=5
    )


def test_conversion_loss_clamped_to_zero(home_assistant: HomeAssistant) -> None:
    """All sensors at 0 → loss = 0 (clamped, no negative values from sampling skew)."""
    _seed(home_assistant)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_loss_power", lambda s: float(s) == 0.0, timeout=5
    )


def test_conversion_loss_energy_accumulates(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """600 W loss (ac_load=600, vebus_dc=-1200) × 1 min = 0.01 kWh accumulated."""
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    _seed(home_assistant, ac_l1=600, vebus_dc=-1200)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_loss_power", lambda s: float(s) == 600, timeout=5
    )
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_multiplus_conversion_loss_energy",
        lambda s: abs(float(s) - 0.01) < 0.001,
        timeout=5,
    )


def test_solar_yield_ac_total_baselines_then_applies_delta(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """First tick after a reset only baselines (no delta exists yet); the next tick applies it.

    Also verifies a counter rollback is absorbed (no negative delta) rather than corrupting
    the running total, and that a source going unavailable holds both state and baseline.
    The baseline lives in sensor.victron_solar_yield_dc_baseline_kwh, its own dedicated
    state-only sensor (see packages/victron.yaml) — checked here as a separate entity_id,
    not as a custom attribute.
    """
    attrs_kwh = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "100.0", attrs_kwh)

    # Tick 1: no baseline yet -> hold at 0.0, but capture the baseline.
    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_total_kwh",
        expected_state=lambda s: float(s) == 0.0,
        timeout=5,
    )
    # DIAGNOSTIC (temporary): dump raw state of source + baseline before the real assertion,
    # to see what the baseline sensor actually rendered instead of guessing blind. Remove once
    # the underlying CI mystery (baseline never leaves 'unknown') is resolved.
    import sys
    print("DIAG src:", home_assistant.get_state("sensor.victron_solar_yield_dc_total_kwh"), file=sys.stderr)
    print("DIAG baseline:", home_assistant.get_state("sensor.victron_solar_yield_dc_baseline_kwh"), file=sys.stderr)
    print("DIAG consumer:", home_assistant.get_state("sensor.victron_solar_yield_total_kwh"), file=sys.stderr)
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_dc_baseline_kwh",
        lambda s: float(s) == 100.0,
        timeout=5,
    )

    # Tick 2: baseline now set, source advances by 0.5 kWh, eta at 100% bootstrap -> +0.5.
    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "100.5", attrs_kwh)
    time_machine.jump_to_next(hour=10, minute=2, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_total_kwh",
        expected_state=lambda s: abs(float(s) - 0.5) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_dc_baseline_kwh",
        lambda s: float(s) == 100.5,
        timeout=5,
    )

    # Tick 3: counter rolls back (device reset) -> delta clamped to 0, no negative energy,
    # baseline re-anchors to the lower value.
    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "10.0", attrs_kwh)
    time_machine.jump_to_next(hour=10, minute=3, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_total_kwh",
        expected_state=lambda s: abs(float(s) - 0.5) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_dc_baseline_kwh",
        lambda s: float(s) == 10.0,
        timeout=5,
    )

    # Tick 4: source goes unavailable -> state AND baseline both hold, no energy lost.
    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "unavailable", {})
    time_machine.jump_to_next(hour=10, minute=4, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_total_kwh",
        expected_state=lambda s: abs(float(s) - 0.5) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state(
        "sensor.victron_solar_yield_dc_baseline_kwh",
        lambda s: float(s) == 10.0,
        timeout=5,
    )


def test_battery_energy_residual_uses_counter_delta_once_baselined(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """Once both lifetime counters have a baseline, the accumulators switch from the
    power-domain bootstrap fallback to the true energy-domain counter-delta residual.

    Tick 1 only baselines both counters at 50.0/20.0 kWh (bootstrap fallback active, all
    power sensors at 0 -> no accumulation). Tick 2 advances MPPT by 1.0 kWh and AC-PV by
    0.2 kWh with zero AC load/grid, so the entire 1.2 kWh surplus must go to the battery:
        batt_inc = 0 - 0 - 0.2 - 1.0*eta(1.0) = -1.2  ->  energy_in += 1.2
    """
    attrs_kwh = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
    time_machine.jump_to_next(hour=10, minute=0, second=0)
    _reset_energy(home_assistant)
    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "50.0", attrs_kwh)
    home_assistant.set_state("sensor.victron_ac_inverter_energy_total_kwh", "20.0", attrs_kwh)
    _seed(home_assistant)  # all power sensors at 0

    time_machine.jump_to_next(hour=10, minute=1, second=0)
    home_assistant.assert_entity_state("sensor.victron_battery_energy_in", "0.0", timeout=5)
    home_assistant.assert_entity_state("sensor.victron_battery_energy_out", "0.0", timeout=5)

    home_assistant.set_state("sensor.victron_solar_yield_dc_total_kwh", "51.0", attrs_kwh)
    home_assistant.set_state("sensor.victron_ac_inverter_energy_total_kwh", "20.2", attrs_kwh)
    time_machine.jump_to_next(hour=10, minute=2, second=0)
    home_assistant.assert_entity_state(
        "sensor.victron_battery_energy_in",
        lambda s: abs(float(s) - 1.2) < 0.001,
        timeout=5,
    )
    home_assistant.assert_entity_state("sensor.victron_battery_energy_out", "0.0", timeout=5)
