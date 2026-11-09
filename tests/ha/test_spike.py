"""Step 0 spike test (plans/test-execution.md) that has no package home: the package load.

The other spike tests moved into their package files as the packages migrated (Step 2):
the two airflow decision ports into tests/ha/test_airflow.py (item 2); the Shelly ingest into
tests/ha/test_shelly_pool_pump.py and the Victron accumulator and keep-alive tests into
tests/ha/test_victron.py (item 3).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def test_packages_load(ha: HomeAssistant) -> None:
    """All package domains set up; a few entities from different packages exist."""
    for eid in (
        "sensor.airflow_cooling_state",
        "sensor.victron_grid_total_power",
        "input_select.pergola_automation_state",
    ):
        assert ha.states.get(eid) is not None, eid
    # No id collision: a `_2` suffix means two entities wanted one id (e.g. a fixture seed that
    # took a config entity's id before the entity registered).
    taken = [e.entity_id for e in er.async_get(ha).entities.values() if e.entity_id.endswith("_2")]
    assert not taken, taken
