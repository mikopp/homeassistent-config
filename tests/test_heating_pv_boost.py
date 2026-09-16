"""PV slab pre-charging tests (packages/heating_pv_boost.yaml).

Phase 1 is a read-only decision layer, so these tests exercise the templates that carry the
design's actual reasoning rather than any device interaction:

  * the surplus formula, whose defining property is that it EXCLUDES the heating circuit's own
    draw — without that, a running boost cancels itself;
  * the derived setpoint, which is computed from mc/TempDesiredLow rather than captured;
  * the hot-water mask, which makes the return temperature unavailable rather than misleading;
  * the interlocks that must hold the decision off.

MQTT broker and ebus are absent in CI; every ebusd/Loxone entity is seeded via set_state
(baseline values come from tests/conftest.py::baseline_states).
"""

from ha_integration_test_harness import HomeAssistant

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
    ha.set_state("sensor.heizung_power", str(heating), _W)


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


def test_surplus_propagates_unavailable_rather_than_fabricating_zero(
    home_assistant: HomeAssistant,
) -> None:
    """A GX outage must produce a gap, not a false 'no surplus' that silently blocks charging."""
    home_assistant.set_state("sensor.heizung_power", "unavailable", {})
    home_assistant.assert_entity_state("sensor.heating_pv_surplus", "unavailable", timeout=5)


def test_target_temp_is_setback_plus_one_in_heating_season(
    home_assistant: HomeAssistant,
) -> None:
    """Season neutral (seeded) counts as heating season → TempDesiredLow + 1."""
    home_assistant.set_state("sensor.heating_setback_temp", "21.0", _C)
    home_assistant.set_state("sensor.heating_cooling_indicator", "neutral", {})
    home_assistant.assert_entity_state(
        "sensor.heating_target_temp",
        lambda s: abs(float(s) - 22.0) < 0.01,
        timeout=5,
    )


def test_target_temp_falls_back_to_setback_out_of_season(
    home_assistant: HomeAssistant,
) -> None:
    """Out of heating season the setpoint collapses onto the setback value, so the circuit idles."""
    home_assistant.set_state("sensor.heating_setback_temp", "21.0", _C)
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_cooling", {})
    home_assistant.assert_entity_state("binary_sensor.heating_season_active", "off", timeout=5)
    home_assistant.assert_entity_state(
        "sensor.heating_target_temp",
        lambda s: abs(float(s) - 21.0) < 0.01,
        timeout=5,
    )


def test_target_temp_tracks_a_changed_setback(home_assistant: HomeAssistant) -> None:
    """TempDesiredLow is the only human knob — moving it must move the derived setpoint."""
    home_assistant.set_state("sensor.heating_cooling_indicator", "active_heating", {})
    home_assistant.set_state("sensor.heating_setback_temp", "20.0", _C)
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
    home_assistant.set_state("sensor.heating_return_temp", "24.9", _C)
    home_assistant.assert_entity_state(
        "sensor.heating_return_temp_valid",
        lambda s: abs(float(s) - 24.9) < 0.01,
        timeout=5,
    )
    home_assistant.set_state("sensor.heating_hvac_action", "water", {})
    home_assistant.assert_entity_state("binary_sensor.heating_dhw_active", "on", timeout=5)
    home_assistant.assert_entity_state(
        "sensor.heating_return_temp_valid", "unavailable", timeout=5
    )


def test_cooling_interlock_follows_the_machine_not_the_setting(
    home_assistant: HomeAssistant,
) -> None:
    """Any of the three activity signals means cooling; the generator's own mode is one of them."""
    home_assistant.assert_entity_state("binary_sensor.heating_cooling_active", "off", timeout=5)
    home_assistant.set_state("sensor.heating_hvac_action", "cooling", {})
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
