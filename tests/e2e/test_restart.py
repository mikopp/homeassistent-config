"""Needs a real HA because: a restart proves what no in-process test can show, namely that
totals written to Home Assistant's disk storage on a real shutdown are read back after a real boot
(`restart-persistence`). Inside pytest the restore cache is faked or primed by hand; here the
container is stopped (HA saves the restore state on the stop event) and started again, and the
sensors must come back with their totals instead of starting from zero.

Two representative sensors, each the platform that matters in this config, with a real mosquitto
feeding them like the devices do:
- utility_meter: `heating_electricity_daily` (packages/heating_pv_boost.yaml), fed by the
  Shelly Pro 3EM energy counter;
- integration (Riemann sum): `victron_grid_energy_import` (packages/victron.yaml), fed by the
  three Victron grid phases through two template sensors.

One restart covers both (a restart costs about 30 s). The formulas, delays and resets of these
sensors are tested in-process (tests/ha/test_heating_pv_boost.py, tests/ha/test_victron.py);
this file is only about the restore.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.needs_real_ha("restart-persistence")

SHELLY_ENERGY_TOPIC = "shelly/shellypro3em-heizung/status/emdata:0"
VICTRON_GRID_TOPIC = "N/c0619ab4c19e/system/0/Ac/Grid/L{phase}/Power"
METER_UNIQUE_ID = "heating_electricity_daily_single_tariff"
RIEMANN_UNIQUE_ID = "victron_grid_energy_import"


def _entity_id(ha, unique_id: str) -> str:
    """The entity id of a registry entry, looked up by unique id (never guessed)."""
    return ha.wait_for(
        lambda: next((e["entity_id"] for e in ha.entity_registry() if e.get("unique_id") == unique_id), None),
        f"registry entry {unique_id}",
        timeout=30,
    )


def test_totals_survive_a_real_restart(ha, publish, restart_ha):
    meter = _entity_id(ha, METER_UNIQUE_ID)
    riemann = _entity_id(ha, RIEMANN_UNIQUE_ID)

    # utility_meter: the first reading is the baseline, the second adds the difference.
    # Shelly sends Wh; the sensor shows kWh (1 000 000 Wh = 1000 kWh, then +1.5 kWh).
    publish(SHELLY_ENERGY_TOPIC, {"total_act": 1_000_000})
    ha.assert_entity_state("sensor.technikraum_heizung_heizung_energy", "1000.0")
    publish(SHELLY_ENERGY_TOPIC, {"total_act": 1_001_500})
    ha.assert_entity_state(meter, "1.5")

    # integration: a Riemann sum needs two source changes. The power is absurdly large on purpose:
    # the integral then grows by whole kWh in the sub-second between the publishes, so the test
    # does not have to wait for real time to pass. The last publish drops the power to zero, so
    # the sum stops growing: after the restart the (restored) source is 0 W, and any difference
    # from `before` is a restore failure, not integration.
    for phase in (1, 2, 3):
        publish(VICTRON_GRID_TOPIC.format(phase=phase), {"value": 100_000_000})
    ha.assert_entity_state("sensor.victron_grid_total_power", "300000000.0")
    for phase in (1, 2, 3):
        publish(VICTRON_GRID_TOPIC.format(phase=phase), {"value": 110_000_000})
    ha.assert_entity_state("sensor.victron_grid_total_power", "330000000.0")
    for phase in (1, 2, 3):
        publish(VICTRON_GRID_TOPIC.format(phase=phase), {"value": 0})
    ha.assert_entity_state("sensor.victron_grid_total_power", "0.0")
    # The closing trapezoid (330 MW down to 0) is added; then the sum is final once it is quiet.
    before = float(ha.wait_stable(riemann)["state"])
    assert before > 0, "the sum never grew, the test setup is broken"

    restart_ha()

    # Both come back with exactly what they had: not "unknown", not zero.
    restored_meter = ha.assert_entity_state(meter, lambda s: s["state"] not in ("unknown", "unavailable"))
    assert restored_meter["state"] == "1.5"
    restored_total = ha.assert_entity_state(riemann, lambda s: s["state"] not in ("unknown", "unavailable"))
    assert float(restored_total["state"]) == before

