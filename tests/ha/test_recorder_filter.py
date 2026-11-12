"""Guards of the test recorder's filter (`recorder_config` in conftest.py).

The recorder records only the history sources of the entity platforms that read recorder history,
derived from the config at run time. These tests fail when the config or the tests outgrow that:
a new platform nobody classified, a classification the HA source contradicts, a test that reads
a recorded event type the filter drops. Static (no HA boot), so they run with every --package.
→ .claude/skills/ha-test-harness/SKILL.md (fixtures)
"""

from __future__ import annotations

import re
from pathlib import Path

import homeassistant.components
import yaml
from homeassistant.components.recorder import get_instance, history
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from conftest import (
    HISTORY_PLATFORMS,
    NO_HISTORY_PLATFORMS,
    RECORDER_EXCLUDED_EVENTS,
    RECORDER_IMPORTING_DOMAINS,
    REPO,
    _AnyTagLoader,
    config_entity_platforms,
    config_yaml_files,
    history_sources,
)

# What a component's source shows when it reads recorder data.
_RECORDER_USE = re.compile(r"components\.recorder|get_instance|import recorder|from \.+recorder")


def _reads_recorder(component: str) -> bool:
    """True when the installed HA component (or the repo's custom component) imports the recorder."""
    core = Path(homeassistant.components.__file__).parent / component
    folder = core if core.is_dir() else REPO / "custom_components" / component
    assert folder.is_dir(), f"no source for {component}: not in HA components nor custom_components/"
    return any(_RECORDER_USE.search(f.read_text()) for f in folder.rglob("*.py"))


def test_every_platform_classified() -> None:
    """Each `platform:` in the config is in exactly one of the two classification dicts."""
    assert not HISTORY_PLATFORMS.keys() & NO_HISTORY_PLATFORMS.keys(), "platform in both dicts"
    used = {p for _, _, p, _ in config_entity_platforms()}
    unknown = sorted(used - HISTORY_PLATFORMS.keys() - NO_HISTORY_PLATFORMS.keys())
    assert not unknown, (
        f"platform(s) {unknown} not classified: add to HISTORY_PLATFORMS (reads recorder history; "
        "value = config key of its source entity) or NO_HISTORY_PLATFORMS (with the reason) in "
        "tests/ha/conftest.py"
    )
    stale = sorted((HISTORY_PLATFORMS.keys() | NO_HISTORY_PLATFORMS.keys()) - used)
    assert not stale, f"classified but no longer used in the config (remove): {stale}"


def test_classification_matches_ha_source() -> None:
    """History platforms import the recorder, the others do not; same for every other domain."""
    wrong = [p for p in HISTORY_PLATFORMS if not _reads_recorder(p)]
    wrong += [p for p in NO_HISTORY_PLATFORMS if _reads_recorder(p)]
    assert not wrong, f"classification contradicts the component source: {wrong}"
    # Top-level domains (template, utility_meter, mqtt, group, ...) read no history either.
    domains = {
        d
        for path in config_yaml_files()
        for d in (yaml.load(path.read_text(), Loader=_AnyTagLoader) or {})
    }
    reading = sorted(d for d in domains if _component_exists(d) and _reads_recorder(d))
    assert set(reading) <= RECORDER_IMPORTING_DOMAINS.keys(), (
        f"domain(s) {sorted(set(reading) - RECORDER_IMPORTING_DOMAINS.keys())} import the "
        "recorder: classify (RECORDER_IMPORTING_DOMAINS or, if it reads history, extend the filter)"
    )


def _component_exists(domain: str) -> bool:
    """True when the domain has source to scan (HA core component or repo custom component)."""
    return (Path(homeassistant.components.__file__).parent / domain).is_dir()


def test_history_sources_derived() -> None:
    """The include list is non-empty, holds every history platform's source, only literal ids."""
    sources = history_sources()
    assert sources, "no history source in the config: the include list would record nothing"
    entries = [e for _, _, p, e in config_entity_platforms() if p in HISTORY_PLATFORMS]
    assert entries, "no filter/statistics/history_stats entry found"
    for entry in entries:
        source = entry[HISTORY_PLATFORMS[entry["platform"]]]
        assert source in sources
        assert re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", source), f"not a literal entity id: {source!r}"


# Recorder access a test could use to read recorded events or states back from the database.
_DB_READ = re.compile(
    r"get_instance|session_scope|recorder\.(?:db_schema|models|history|statistics)"
    r"|get_significant_states|statistics_during_period|logbook|history\.get"
)


def test_no_test_reads_the_recorder_database() -> None:
    """No test queries the recorder: the dropped event types (and unlisted entities) stay unread.

    A test that needs a recorded event or entity must extend `recorder_config` in conftest.py
    (shrink RECORDER_EXCLUDED_EVENTS or add the entity) and relax this guard for itself.
    `async_wait_recording_done` (commit barrier before a history_stats read) is allowed.
    """
    assert RECORDER_EXCLUDED_EVENTS and "state_changed" not in RECORDER_EXCLUDED_EVENTS
    offenders = [
        f"{path.name}: {m.group(0)}"
        for path in sorted(Path(__file__).parent.glob("test_*.py"))
        if path.name != Path(__file__).name
        for m in [_DB_READ.search(path.read_text())]
        if m
    ]
    assert not offenders, f"tests read the recorder database: {offenders}"


async def test_recorder_records_exactly_the_sources(ha: HomeAssistant) -> None:
    """After boot every history source that has a state is in the database, and nothing else is.

    The suite itself never reads recorded history back (history_stats follows live events), so
    this is what catches a source missing from the filter, or the filter not applied.
    """
    await async_wait_recording_done(ha)
    sources = history_sources()
    present = [e for e in sources if ha.states.get(e) is not None]
    assert present, "no history source has a state after boot: the check proves nothing"
    others = [s.entity_id for s in ha.states.async_all() if s.entity_id not in sources]
    assert others, "no non-source entity to prove the filter drops"

    async def recorded(entity_id: str) -> bool:
        rows = await get_instance(ha).async_add_executor_job(
            history.get_last_state_changes, ha, 1, entity_id
        )
        return bool(rows.get(entity_id))

    missing = [e for e in present if not await recorded(e)]
    assert not missing, f"history sources not recorded (filter or classification): {missing}"
    leaked = [e for e in others if await recorded(e)]
    assert not leaked, f"entities recorded although no platform reads their history: {leaked[:5]}"
