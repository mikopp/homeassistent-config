"""Needs a real HA because: only a real Home Assistant process boots the repo's real
`configuration.yaml` the way production does (`full-boot`): `default_config`, the frontend, the
YAML dashboards, `!include_dir_named packages`, the HACS `climate_template` custom component,
the recorder, a real MQTT connection and the config entries. The in-process layer (tests/ha) loads
only the package domains through HA's YAML loader and mocks the rest.

What is checked here and nowhere else: the whole config boots, every package registers its
entities, and the pieces tests/ha has to stub (custom component, MQTT entry, workday entry) are
alive. Behaviour (formulas, delays, automations) is tested in tests/ha, never repeated here.
"""

from __future__ import annotations

import pytest
import yaml

from .conftest import ROOT

pytestmark = pytest.mark.needs_real_ha("full-boot")


class _AnyTagLoader(yaml.SafeLoader):
    """SafeLoader that ignores HA's tags (!secret, !include, ...); only the structure is read."""


_AnyTagLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _unique_ids(node: object) -> set[str]:
    """Every `unique_id` value anywhere in a parsed package."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "unique_id" and isinstance(value, str):
                found.add(value)
            else:
                found |= _unique_ids(value)
    elif isinstance(node, list):
        for item in node:
            found |= _unique_ids(item)
    return found


def _package_unique_ids() -> dict[str, set[str]]:
    """package file -> the unique ids its entities declare."""
    result = {}
    for path in sorted((ROOT / "packages").glob("*.yaml")):
        package = yaml.load(path.read_text(), Loader=_AnyTagLoader)
        ids = _unique_ids({k: v for k, v in package.items() if k != "utility_meter"})
        # A utility meter without tariffs registers its sensor as "<unique_id>_single_tariff";
        # one with tariffs registers a select under "<unique_id>" and "<unique_id>_<tariff>".
        for meter in (package.get("utility_meter") or {}).values():
            if tariffs := meter.get("tariffs"):
                ids |= {meter["unique_id"]} | {f"{meter['unique_id']}_{t}" for t in tariffs}
            else:
                ids.add(f"{meter['unique_id']}_single_tariff")
        result[path.name] = ids
    return result


def test_every_package_registers_its_entities(ha):
    """All packages loaded: each unique id a package declares is in the entity registry."""
    registered = {e["unique_id"] for e in ha.entity_registry() if e.get("unique_id")}
    declared = _package_unique_ids()
    assert all(declared.values()), f"a package declares no unique ids: {declared}"
    missing = {
        package: sorted(ids - registered) for package, ids in declared.items() if ids - registered
    }
    assert not missing, f"declared in packages but not registered by the real boot: {missing}"


def test_integrations_the_config_needs_are_alive(ha):
    """Core up, the HACS climate platform loaded, MQTT and workday entries loaded."""
    config = ha.get("/api/config")
    assert config["state"] == "RUNNING"
    # climate_template is a custom platform (downloaded by stage.py); its entity is the proof.
    assert ha.get_state("climate.airflow_climate") is not None
    for domain in ("mqtt", "workday"):
        entries = ha.config_entries(domain)
        assert [e["state"] for e in entries] == ["loaded"], (domain, entries)
    # The YAML platform of the integration domains of the packages is set up.
    for domain in ("template", "input_boolean", "utility_meter", "history_stats", "statistics", "filter"):
        assert domain in config["components"] or any(c.startswith(f"{domain}.") for c in config["components"]), domain
    # The workday entity is renamed to the id the config reads (a user would do that in the UI).
    assert ha.get_state("binary_sensor.workday") is not None
