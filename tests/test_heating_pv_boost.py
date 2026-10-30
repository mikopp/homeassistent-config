"""PV slab pre-charging tests (packages/heating_pv_boost.yaml).

Phase 1 is a read-only decision layer, so these tests exercise the templates that carry the
design's actual reasoning rather than any device interaction:

  * the surplus formula, whose defining property is that it EXCLUDES the heating circuit's own
    draw — without that, a running boost cancels itself;
  * the derived setpoint, which is computed from mc/TempDesiredLow rather than captured;
  * the hot-water mask, which makes the return temperature unavailable rather than misleading;
  * the interlocks that must hold the decision off;
  * the compressor-cycling statistics (last run length, average run, daily efficiency).

MQTT broker and ebus are absent in CI; every ebusd/Loxone entity is seeded via set_state
(baseline values come from tests/conftest.py::baseline_states).
"""

from datetime import timedelta

from ha_integration_test_harness import HomeAssistant, TimeMachine

_W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_IND = "sensor.heating_cooling_indicator"


def _drive_season(ha: HomeAssistant, mean: float, expected: str) -> None:
    """Move the indicator through its real input (48h mean) and wait until it shows `expected`.

    The indicator is never pinned with set_state: it reads its own previous state (`this`), so
    HA re-renders it right after any external write and walks it back to what the mean says.
    Thresholds are 12 / 16 / 20 (conftest baseline). Hysteresis advances one step per render;
    HA allows the triggering render plus two self re-renders, so one mean change moves the
    indicator at most 3 steps.
    """
    ha.set_state(_MEAN, str(mean), _C)
    ha.assert_entity_state(_IND, expected, timeout=5)


def _seed_power_flows(
    ha: HomeAssistant,
    *,
    dc_pv: float,
    ac_pv: float,
    house_load: float,
    heating: float,
) -> None:
    """Seed the four inputs of the surplus formula.

    house_load is split across the three phases because sensor.victron_ac_load_total_power is
    itself a template over L1/L2/L3 — seeding the phases exercises that chain too.
    """
    ha.set_state("sensor.victron_dc_pv_total_power", str(dc_pv), _W)
    ha.set_state("sensor.victron_ac_inverter_power", str(ac_pv), _W)
    ha.set_state("sensor.victron_ac_load_l1", str(house_load / 3), _W)
    ha.set_state("sensor.victron_ac_load_l2", str(house_load / 3), _W)
    ha.set_state("sensor.victron_ac_load_l3", str(house_load / 3), _W)
    ha.set_state("sensor.technikraum_heizung_heizung_power", str(heating), _W)


def test_surplus_excludes_the_heat_pumps_own_draw(home_assistant: HomeAssistant) -> None:
    """PV 4000, house load 2500 of which 1500 is the heat pump → surplus 3000, not 1500.

    This is the property the whole controller rests on: the figure must answer "how much PV
    would be free if the heat pump were off", so it stays invariant once a boost starts drawing.
    """
    _seed_power_flows(home_assistant, dc_pv=3000, ac_pv=1000, house_load=2500, heating=1500)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 3000.0) < 1.0,
        timeout=5,
    )


def test_surplus_uses_ac_referenced_mppt_not_raw_dc(home_assistant: HomeAssistant) -> None:
    """MPPT 4000 W DC at η 90 % → 3600 W AC; AC PV 1000; house 2500 incl. heat pump 1500.

    Surplus must be (3600 + 1000) − (2500 − 1500) = 3600. Feeding raw DC in would give 4000,
    overstating free PV by the MultiPlus conversion loss.
    """
    # Force η to 90 % (ac_out / dc_in = 9 / 10). Accumulators are re-seeded to 0.0 by the autouse
    # baseline before each test, so this does not leak into other tests.
    kwh = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
    home_assistant.set_state("sensor.victron_multiplus_ac_out_energy", "9.0", kwh)
    home_assistant.set_state("sensor.victron_multiplus_dc_in_energy", "10.0", kwh)
    _seed_power_flows(home_assistant, dc_pv=4000, ac_pv=1000, house_load=2500, heating=1500)
    home_assistant.assert_entity_state(
        "sensor.solar_yield_watts",
        lambda s: abs(float(s) - 3600.0) < 1.0,
        timeout=5,
    )
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 3600.0) < 1.0,
        timeout=5,
    )


def test_surplus_is_unchanged_when_only_the_heat_pump_draw_changes(
    home_assistant: HomeAssistant,
) -> None:
    """Heat pump draw rising from 0 to 2000 (house load rising with it) must not move surplus."""
    _seed_power_flows(home_assistant, dc_pv=4000, ac_pv=0, house_load=1000, heating=0)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 3000.0) < 1.0,
        timeout=5,
    )
    # The boost starts: +2000 W on both the heating clamp and the house total.
    _seed_power_flows(home_assistant, dc_pv=4000, ac_pv=0, house_load=3000, heating=2000)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 3000.0) < 1.0,
        timeout=5,
    )


def test_surplus_keeps_the_deficit_when_adding_the_heat_pump_back(
    home_assistant: HomeAssistant,
) -> None:
    """PV 2000, house 2500 incl. heat pump 1500 → free PV is 2000 − 1000 = 1000, not 1500.

    A pre-clamped whole-house surplus (0) plus the heating draw (1500) would overstate it, which is
    why the heating sensor builds on the signed sensor.victron_pv_net_power.
    """
    _seed_power_flows(home_assistant, dc_pv=2000, ac_pv=0, house_load=2500, heating=1500)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 1000.0) < 1.0,
        timeout=5,
    )


def test_surplus_clamps_at_zero(home_assistant: HomeAssistant) -> None:
    """PV 500, non-heating load 1000 → free PV would be −500; reported as 0."""
    _seed_power_flows(home_assistant, dc_pv=500, ac_pv=0, house_load=2500, heating=1500)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_surplus_propagates_unavailable_when_no_victron_load_data(
    home_assistant: HomeAssistant,
) -> None:
    """No load data (GX outage) must produce a gap, not a false 'no surplus'."""
    for phase in ("l1", "l2", "l3"):
        home_assistant.set_state(f"sensor.victron_ac_load_{phase}", "unavailable", {})
    home_assistant.assert_entity_state("sensor.heating_pv_surplus", "unavailable", timeout=5)


def test_surplus_is_zero_not_negative_without_sun(home_assistant: HomeAssistant) -> None:
    """Night: PV 0, house load 500 → balance is -500, surplus must read 0."""
    _seed_power_flows(home_assistant, dc_pv=0, ac_pv=0, house_load=500, heating=0)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_surplus_is_zero_when_inverter_sensor_unavailable(
    home_assistant: HomeAssistant,
) -> None:
    """Inverter sleeps at night → its sensor is unavailable; surplus is 0, not unavailable."""
    _seed_power_flows(home_assistant, dc_pv=11, ac_pv=0, house_load=500, heating=80)
    home_assistant.set_state("sensor.victron_ac_inverter_power", "unavailable", {})
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_surplus_is_zero_at_night_even_when_heater_leads_the_victron_load(
    home_assistant: HomeAssistant,
) -> None:
    """Compressor starts at night: Shelly already reads 1562 W, Victron load still shows 500 W.

    net = (0 − 500) + 1562 = +1062 would be a false surplus (seen live: 1232 W at 00:17:44, gone
    ~2 s later). Capped at PV generation (0), it must stay 0.
    """
    _seed_power_flows(home_assistant, dc_pv=0, ac_pv=0, house_load=500, heating=1562)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: float(s) == 0.0,
        timeout=5,
    )


def test_surplus_never_exceeds_pv_generation(home_assistant: HomeAssistant) -> None:
    """PV 1000 W, Victron load lagging at 500 W while the heater already reads 1800 W.

    The raw sum is 1000 − 500 + 1800 = 2300 W; only 1000 W of PV exists, so that is the ceiling.
    """
    _seed_power_flows(home_assistant, dc_pv=1000, ac_pv=0, house_load=500, heating=1800)
    home_assistant.assert_entity_state(
        "sensor.heating_pv_surplus",
        lambda s: abs(float(s) - 1000.0) < 1.0,
        timeout=5,
    )


def test_compressor_active_follows_the_shelly_clamp(home_assistant: HomeAssistant) -> None:
    """~83 W is idle circulation (off); ~1.8 kW is a compressor run (on); the clamp gone → unavailable."""
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "83", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "off", timeout=5)
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "1800", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "on", timeout=5)
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "unavailable", {})
    home_assistant.assert_entity_state(
        "binary_sensor.heating_compressor_active", "unavailable", timeout=5
    )


def test_target_temp_is_setback_plus_one_in_heating_season(
    home_assistant: HomeAssistant,
) -> None:
    """Season neutral (seeded) counts as heating season → TempDesiredLow + 1."""
    home_assistant.set_state("sensor.geotherm_heating_temp_desired_low", "21.0", _C)
    _drive_season(home_assistant, 14.0, "neutral")
    home_assistant.assert_entity_state(
        "sensor.heating_target_temp",
        lambda s: abs(float(s) - 22.0) < 0.01,
        timeout=5,
    )


def test_target_temp_falls_back_to_setback_out_of_season(
    home_assistant: HomeAssistant,
) -> None:
    """Out of heating season the setpoint collapses onto the setback value, so the circuit idles."""
    home_assistant.set_state("sensor.geotherm_heating_temp_desired_low", "21.0", _C)
    _drive_season(home_assistant, 22.0, "active_cooling")  # neutral → active_cooling (2 steps)
    home_assistant.assert_entity_state("binary_sensor.heating_season_active", "off", timeout=5)
    home_assistant.assert_entity_state(
        "sensor.heating_target_temp",
        lambda s: abs(float(s) - 21.0) < 0.01,
        timeout=5,
    )


def test_target_temp_tracks_a_changed_setback(home_assistant: HomeAssistant) -> None:
    """TempDesiredLow is the only human knob — moving it must move the derived setpoint."""
    _drive_season(home_assistant, 8.0, "active_heating")  # neutral → active_heating (1 step)
    home_assistant.set_state("sensor.geotherm_heating_temp_desired_low", "20.0", _C)
    home_assistant.assert_entity_state(
        "sensor.heating_target_temp",
        lambda s: abs(float(s) - 21.0) < 0.01,
        timeout=5,
    )


def test_return_temp_is_masked_while_making_hot_water(home_assistant: HomeAssistant) -> None:
    """During a DHW charge the water temperatures describe the cylinder, not the slab.

    The valid-return sensor must go unavailable so no numeric threshold downstream can fire on a
    reading that means something else.
    """
    home_assistant.set_state("sensor.geotherm_heating_circuit_return_temp", "24.9", _C)
    home_assistant.assert_entity_state(
        "sensor.heating_circuit_return_temp_valid",
        lambda s: abs(float(s) - 24.9) < 0.01,
        timeout=5,
    )
    home_assistant.set_state("sensor.geotherm_heating_hvac_action", "water", {})
    home_assistant.assert_entity_state("binary_sensor.heating_dhw_active", "on", timeout=5)
    home_assistant.assert_entity_state(
        "sensor.heating_circuit_return_temp_valid", "unavailable", timeout=5
    )


def test_cooling_interlock_follows_the_machine_not_the_setting(
    home_assistant: HomeAssistant,
) -> None:
    """Any of the three activity signals means cooling; the generator's own mode is one of them."""
    home_assistant.assert_entity_state("binary_sensor.heating_cooling_active", "off", timeout=5)
    home_assistant.set_state("sensor.geotherm_heating_hvac_action", "cooling", {})
    home_assistant.assert_entity_state("binary_sensor.heating_cooling_active", "on", timeout=5)


def test_decision_stays_off_while_the_master_switch_is_off(
    home_assistant: HomeAssistant,
) -> None:
    """Abundant surplus must not produce a slab charge unless the feature is armed."""
    _seed_power_flows(home_assistant, dc_pv=6000, ac_pv=0, house_load=500, heating=0)
    home_assistant.call_action(
        "input_boolean", "turn_off", {"entity_id": "input_boolean.heating_pv_boost_enabled"}
    )
    home_assistant.assert_entity_state(
        "binary_sensor.heating_slab_mode_wanted", "off", timeout=5
    )


# ── Compressor cycling statistics (plans/heating-compressor-cycling.md) ──────────────────


def test_last_run_measures_the_on_to_off_transition(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """A 7-minute compressor run (Shelly 1.8 kW → 83 W) is reported as ~7 min when it ends.

    One clock op: fast_forward(7 min) while the run is on, so the off transition's last_changed
    is 7 mocked minutes after the on transition.
    """
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "83", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "off", timeout=5)
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "1800", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "on", timeout=5)
    time_machine.fast_forward(timedelta(minutes=7))
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "83", _W)
    home_assistant.assert_entity_state(
        "sensor.heating_compressor_last_run",
        lambda s: s not in ("unknown", "unavailable") and 6.5 <= float(s) <= 8.0,
        timeout=5,
    )


def test_average_run_is_runtime_over_runs(home_assistant: HomeAssistant) -> None:
    """4 runs in 1.0 h → 15 min per run; no runs yet → 0, not a division error."""
    home_assistant.set_state("sensor.heating_compressor_runtime_today", "1.0", {"unit_of_measurement": "h"})
    home_assistant.set_state("sensor.heating_compressor_runs_today", "4", {})
    home_assistant.assert_entity_state(
        "sensor.heating_compressor_average_run_today",
        lambda s: s not in ("unknown", "unavailable") and abs(float(s) - 15.0) < 0.01,
        timeout=5,
    )
    home_assistant.set_state("sensor.heating_compressor_runtime_today", "0.0", {"unit_of_measurement": "h"})
    home_assistant.set_state("sensor.heating_compressor_runs_today", "0", {})
    home_assistant.assert_entity_state(
        "sensor.heating_compressor_average_run_today",
        lambda s: s not in ("unknown", "unavailable") and float(s) == 0.0,
        timeout=5,
    )


def test_efficiency_is_heat_over_electricity_once_meaningful(home_assistant: HomeAssistant) -> None:
    """9 kWh heat from 3 kWh electricity → 3.0; under 1 kWh electricity it is too coarse → 0."""
    _kwh = {"unit_of_measurement": "kWh"}
    home_assistant.set_state("sensor.heating_yield_daily", "9", _kwh)
    home_assistant.set_state("sensor.heating_electricity_daily", "3", _kwh)
    home_assistant.assert_entity_state(
        "sensor.heating_efficiency_today",
        lambda s: s not in ("unknown", "unavailable") and abs(float(s) - 3.0) < 0.01,
        timeout=5,
    )
    home_assistant.set_state("sensor.heating_electricity_daily", "0.5", _kwh)
    home_assistant.assert_entity_state(
        "sensor.heating_efficiency_today",
        lambda s: s not in ("unknown", "unavailable") and float(s) == 0.0,
        timeout=5,
    )
