"""PV slab pre-charging tests that still need the Docker harness (packages/heating_pv_boost.yaml).

The formula tests (surplus, compressor activity and cycling formulas, cooling interlock, derived
setpoint) moved to tests/ha/test_heating_pv_boost.py (plans/test-execution.md, Step 2, item 3).
The four left here need the mocked clock and move in item 4:

  * the hot-water mask (`heating_dhw_active` delay_off 25 min);
  * the master-switch decision (`heating_slab_mode_wanted` delay_off 20 min);
  * the two `heating_compressor_last_run` tests (a `last_changed` span).

MQTT broker and ebus are absent in CI; every ebusd/Loxone entity is seeded via set_state
(baseline values come from tests/baseline.py).
"""

from datetime import timedelta

from ha_integration_test_harness import HomeAssistant, TimeMachine

_W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
_C = {"unit_of_measurement": "°C", "device_class": "temperature"}


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


def test_return_temp_is_masked_while_making_hot_water(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """During a DHW charge the water temperatures describe the cylinder, not the slab.

    The valid-return sensor must go unavailable so no numeric threshold downstream can fire on a
    reading that means something else.

    The clock is advanced first: binary_sensor.heating_dhw_active has a 25 min delay_off, so after
    a fresh boot it sits at 'unknown' (and the valid-return sensor is unavailable) until the mocked
    clock crosses that window. Without this the test only passed when earlier test files had
    already moved the clock.
    """
    time_machine.fast_forward(timedelta(minutes=26))
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


def test_decision_stays_off_while_the_master_switch_is_off(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """Abundant surplus must not produce a slab charge unless the feature is armed.

    The clock is advanced first: binary_sensor.heating_slab_mode_wanted has a 20 min delay_off, so
    after a fresh boot it sits at 'unknown' until the mocked clock crosses that window. Without
    this the test only passed when earlier test files had already moved the clock.
    """
    time_machine.fast_forward(timedelta(minutes=26))
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


def test_last_run_ignores_hot_water_runs(
    home_assistant: HomeAssistant, time_machine: TimeMachine
) -> None:
    """A 30-minute hot-water run must not update 'last run'; a following 12-minute heating run does.

    The HA instance is shared across the test session, so 'last run' may already hold a value
    from an earlier test (e.g. 7 min). The run lengths are chosen so neither can be mistaken for
    that leftover: the check is "never ≈ 30" after the DHW run and "≈ 12" after the heating run.
    """
    home_assistant.set_state("sensor.geotherm_heating_hvac_action", "water", {})
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "3500", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "on", timeout=5)
    time_machine.fast_forward(timedelta(minutes=30))
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "83", _W)
    home_assistant.assert_entity_state("binary_sensor.heating_compressor_active", "off", timeout=5)
    # The hot-water run never made the heating sensor go on→off, so last run did not take its 30 min.
    home_assistant.assert_entity_state(
        "sensor.heating_compressor_last_run",
        lambda s: s in ("unknown", "unavailable") or not 29.0 <= float(s) <= 31.0,
        timeout=5,
    )
    # Now a real heating run of 12 minutes → reported.
    home_assistant.set_state("sensor.geotherm_heating_hvac_action", "heat", {})
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "1800", _W)
    home_assistant.assert_entity_state(
        "binary_sensor.heating_compressor_heating_active", "on", timeout=5
    )
    time_machine.fast_forward(timedelta(minutes=12))
    home_assistant.set_state("sensor.technikraum_heizung_heizung_power", "83", _W)
    home_assistant.assert_entity_state(
        "sensor.heating_compressor_last_run",
        lambda s: s not in ("unknown", "unavailable") and 11.5 <= float(s) <= 13.0,
        timeout=5,
    )


