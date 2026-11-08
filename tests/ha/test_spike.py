"""SPIKE tests (plans/test-execution.md Step 0): prove the in-process layer is valid and stable."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from conftest import Broker, entity_id, wait_state

POOL = "shelly/shellyplusplugs-pool-pump/status/switch:0"


async def test_packages_load(ha: HomeAssistant) -> None:
    """All package domains set up; a few entities from different packages exist."""
    for eid in (
        "sensor.airflow_cooling_state",
        "sensor.victron_grid_total_power",
        "input_select.pergola_automation_state",
    ):
        assert ha.states.get(eid) is not None, eid


async def test_mqtt_ingest_shelly_pool_pump(ha: HomeAssistant, broker: Broker) -> None:
    """A real Shelly payload runs through the real value_templates (Wh → kWh)."""
    await ha.async_add_executor_job(broker.wait_subscribed, POOL)
    broker.publish(
        POOL,
        {"apower": 597.66, "voltage": 231.04, "current": 2.6123, "aenergy": {"total": 12345.6}},
    )
    def eid(uid: str) -> str:
        return entity_id(ha, "sensor", "mqtt", uid)

    await wait_state(ha, eid("shelly_pool_pump_power"), "597.7")
    await wait_state(ha, eid("shelly_pool_pump_energy"), "12.346")
    await wait_state(ha, eid("shelly_pool_pump_voltage"), "231.0")



# ── Airflow decision (custom_templates/airflow_decision.jinja) ────────────────
_DECISION = "sensor.airflow_cooling_state"
_INPUTS = {  # same values as tests/conftest.py::baseline_inputs (production thresholds)
    "input_number.airflow_cooling_target_temperature": 21.5,
    "input_number.airflow_min_dew_diff": 2.0,
    "input_number.airflow_min_temp_diff": 1.5,
    "input_number.airflow_target_humidity": 55,
    "input_number.airflow_min_humidity": 45,
    "input_number.airflow_max_humidity": 55,
    "input_number.heating_indicator_heating_below": 12,
    "input_number.heating_indicator_passive_cooling_above": 16,
    "input_number.heating_indicator_active_cooling_above": 20,
}


async def _set_inputs(hass: HomeAssistant) -> None:
    for eid, value in _INPUTS.items():
        await hass.services.async_call(
            "input_number", "set_value", {"entity_id": eid, "value": value}, blocking=True
        )


async def _seed_indicators(
    hass: HomeAssistant, *, season: str = "neutral", free: str = "off", flush: str = "off"
) -> None:
    """Same order as tests/test_airflow.py::_seed_indicators (season first)."""
    hass.states.async_set("sensor.airflow_min_indoor_dew_5min", "12.0",
                          {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.heating_cooling_indicator", season)
    for eid, val in (
        ("binary_sensor.airflow_humidity_flush_needed", flush),
        ("binary_sensor.airflow_humidity_drying_needed", "off"),
        ("binary_sensor.airflow_moisture_ventilation_low_needed", "off"),
        ("binary_sensor.airflow_heat_ventilation_low_needed", "off"),
        ("binary_sensor.airflow_free_cooling_available", free),
    ):
        hass.states.async_set(eid, val)
    await hass.async_block_till_done()


def _assert_decision(hass: HomeAssistant, state: str, profile: str, ventilation: str) -> None:
    s = hass.states.get(_DECISION)
    assert (s.state, s.attributes.get("profile"), s.attributes.get("ventilation")) == (
        state, profile, ventilation
    )


async def test_decision_active_heating_ignores_free_cooling(ha: HomeAssistant) -> None:
    """Port of test_airflow.py: active_heating + free cooling → heating, warm, auto."""
    await _set_inputs(ha)
    await ha.services.async_call("input_boolean", "turn_on",
        {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"}, blocking=True)
    await _seed_indicators(ha, season="active_heating", free="on")
    _assert_decision(ha, "heating", "warm", "auto")


async def test_decision_free_cooling_cooling_season(ha: HomeAssistant) -> None:
    """Port of test_airflow.py: free cooling in cooling season → cool + medium."""
    await _set_inputs(ha)
    await ha.services.async_call("input_boolean", "turn_on",
        {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"}, blocking=True)
    await _seed_indicators(ha, season="active_cooling", free="on")
    _assert_decision(ha, "free_cooling", "cool", "medium")


# ── Victron: real broker + moved clock ────────────────────────────────────────
_GX = "N/c0619ab4c19e"
_TOPICS = {
    "grid_l1": "system/0/Ac/Grid/L1/Power",
    "grid_l2": "system/0/Ac/Grid/L2/Power",
    "grid_l3": "system/0/Ac/Grid/L3/Power",
    "ac_l1": "system/0/Ac/Consumption/L1/Power",
    "ac_l2": "system/0/Ac/Consumption/L2/Power",
    "ac_l3": "system/0/Ac/Consumption/L3/Power",
    "dc_pv": "system/0/Dc/Pv/Power",
    "ac_pv": "pvinverter/20/Ac/Power",
    "vebus_i": "system/0/Dc/Vebus/Current",
    "batt_v": "system/0/Dc/Battery/Voltage",
}


async def _publish_gx(ha: HomeAssistant, broker: Broker, **values: float) -> None:
    """Publish Venus OS payloads ({"value": x}) for every power topic (defaults 0, 50 V)."""
    vals = {k: 0.0 for k in _TOPICS} | {"batt_v": 50.0} | values
    for key, topic in _TOPICS.items():
        await ha.async_add_executor_job(broker.wait_subscribed, f"{_GX}/{topic}")
        await ha.async_add_executor_job(broker.publish, f"{_GX}/{topic}", {"value": vals[key]})


async def test_battery_discharge_energy_accumulates(
    ha: HomeAssistant, broker: Broker, freezer: FrozenDateTimeFactory
) -> None:
    """Port: 1200 W battery discharge × one time_pattern minute = 0.02 kWh (fed over MQTT)."""
    await _publish_gx(ha, broker, ac_l1=1200)
    await wait_state(ha, "sensor.victron_battery_ac_power", lambda s: s not in ("unknown", "unavailable") and float(s) == 1200)
    # Trigger-based accumulator: `unknown` until its first time_pattern tick (this.state → 0).
    # A real minute boundary during HA start (before the freeze) may already have ticked it.
    st = ha.states.get("sensor.victron_battery_energy_out").state
    before = 0.0 if st == "unknown" else float(st)
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(ha)
    await ha.async_block_till_done()
    out = float(ha.states.get("sensor.victron_battery_energy_out").state)
    assert abs((out - before) - 0.02) < 0.001
    assert float(ha.states.get("sensor.victron_battery_energy_in").state) == 0.0


async def test_grid_import_energy_accumulates(
    ha: HomeAssistant, broker: Broker, freezer: FrozenDateTimeFactory
) -> None:
    """0→3000→1000 W import; the 3000→1000 step is EXACTLY 60 s (frozen clock) → exact kWh.

    Stronger than the Docker port (3000→3001 W, tolerance 2 Wh, which `method: left` also
    passed). The 0→3000 step spans HA start → freeze (real time, load dependent), so its area is
    computed from HA's own timestamps rather than assumed zero; the displayed total rounds to
    1 Wh (`round: 3`), hence the 0.6 Wh tolerance.
    """
    src = "sensor.victron_grid_power_import"
    prev = ha.states.get(src)
    assert prev.state == "0"
    await _publish_gx(ha, broker, grid_l1=3000)
    await wait_state(ha, src, "3000.0")
    first_s = ha.states.get(src).last_updated_timestamp - prev.last_reported_timestamp
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(ha)
    await _publish_gx(ha, broker, grid_l1=1000)
    await wait_state(ha, src, "1000.0")
    expected = ((0 + 3000) / 2 * first_s + (3000 + 1000) / 2 * 60) / 3_600_000
    total = float(ha.states.get("sensor.victron_grid_energy_import").state)
    assert abs(total - expected) < 0.0006, (total, expected, first_s)
    assert ha.states.get("sensor.victron_grid_energy_export").state in ("0.0", "0.000", "unknown")


async def test_victron_keepalive_published(
    ha: HomeAssistant, broker: Broker, freezer: FrozenDateTimeFactory
) -> None:
    """Automations really publish: empty keep-alive on HA start, suppress-republish every 30 s."""
    topic = f"R/{_GX[2:]}/keepalive"
    await ha.async_add_executor_job(broker.wait_received, topic, "")
    mark = len(broker.received)
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(ha)
    await ha.async_block_till_done()
    await ha.async_add_executor_job(
        broker.wait_received, topic, '{"keepalive-options":["suppress-republish"]}', mark
    )
