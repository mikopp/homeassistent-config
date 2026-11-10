"""Package load: every package loads together in the in-process HA, with no `_2` entity ids."""

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
