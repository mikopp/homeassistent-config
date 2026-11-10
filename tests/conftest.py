"""Session and per-test fixtures for Home Assistant integration tests.

Replaces seed_state.py and the manual HA container management in ha_check_frenk.yaml.
The ha_integration_test_harness plugin provides the `home_assistant` and `time_machine`
session-scoped fixtures automatically via its installed conftest.
"""

import pytest
import requests
from datetime import timedelta

from ha_integration_test_harness import HomeAssistant

from baseline import BASELINE_ACTIONS, BASELINE_NUMBERS, BASELINE_STATES


# ── Bound every HTTP call the harness makes ──────────────────────────────────────────────
# ha_integration_test_harness (pinned at v0.11.0) calls requests.get/post/delete with NO
# timeout= kwarg, so a Home Assistant container that accepts the TCP connection but never
# answers blocks the test process forever. This is not hypothetical: CI hung repeatedly on
# this branch, and the pytest-timeout thread dump (see plans/ci-test-speedups.md) put the
# main thread in socket.recv_into inside requests.get, waiting on the HTTP status line.
#
# assert_entity_state(timeout=5) does NOT protect against this. Its timeout is checked
# BETWEEN poll iterations; each iteration calls get_state(), and one unbounded get_state()
# inside the loop means the 5s ceiling is never reached. Every timeout= in this suite is
# decorative against a wedged container without this shim.
#
# The harness is a pinned pip dependency, so it cannot be fixed in place. Instead default a
# timeout onto the module-level requests helpers it uses. setdefault, not an override: any
# caller passing its own timeout= still wins. Result: a wedged container produces a
# requests.exceptions.ReadTimeout naming the failing call within 30s, and the remaining
# tests still run — instead of the whole invocation stalling until pytest-timeout kills it.
_HTTP_TIMEOUT_SECONDS = 30


def _with_default_timeout(func):
    """Wrap a requests helper so it carries a default timeout unless the caller set one."""
    def wrapper(*args, **kwargs):
        kwargs.setdefault("timeout", _HTTP_TIMEOUT_SECONDS)
        return func(*args, **kwargs)
    return wrapper


for _name in ("get", "post", "delete", "put", "patch", "request"):
    setattr(requests, _name, _with_default_timeout(getattr(requests, _name)))


# Originally: run pergola tests before airflow tests to prevent event-loop load from airflow
# automations (mode:restart + humidity trigger) causing sun-integration race conditions that
# overwrite sensor.pergola_effective_slat_angle with the script's float(90) default before the
# test assertion fires. That race is now handled structurally instead: .github/workflows/
# ha_check.yaml runs test_pergola.py as its own pytest invocation (its own fresh HA instance,
# see plans/ci-test-speedups.md), so airflow tests are never even collected in the same process.
# This sort is harmless to keep — for that isolated run everything already matches "test_pergola"
# and sorts alphabetically among itself either way.
def pytest_collection_modifyitems(items: list) -> None:
    def sort_key(item):
        return (0 if "test_pergola" in item.nodeid else 1, item.nodeid)
    items.sort(key=sort_key)


# ── Default weather entity ───────────────────────────────────────────────────────────────
# A fresh HA instance onboards a default weather entity (Met.no) whose entity_id is derived from
# the location name (e.g. weather.forecast_home), not the weather.home that packages/ reference
# (heating_cooling_indicator's 48h forecast mean). Rename it once per session so the
# weather.get_forecasts call resolves in CI exactly as it does on the live instance.
_WEATHER_ENTITY_ID = "weather.home"


@pytest.fixture(scope="session", autouse=True)
def default_weather_entity_id(home_assistant: HomeAssistant) -> None:
    """Rename the default weather entity to weather.home (no-op if already named so / absent)."""
    listing = home_assistant._ws_send_receive({"id": 1, "type": "config/entity_registry/list"})
    weather_ids = [
        entry["entity_id"]
        for entry in listing.get("result", [])
        if entry["entity_id"].startswith("weather.")
    ]
    if not weather_ids or _WEATHER_ENTITY_ID in weather_ids:
        return
    home_assistant._ws_send_receive({
        "id": 1,
        "type": "config/entity_registry/update",
        "entity_id": weather_ids[0],
        "new_entity_id": _WEATHER_ENTITY_ID,
    })


# ── Per-test baseline fixtures ───────────────────────────────────────────────────────────
# The data lives in tests/baseline.py, shared with the in-process layer (tests/ha), so both
# suites seed the same baseline. These fixtures only apply it over REST, in the data's order.


@pytest.fixture(autouse=True)
def baseline_inputs(home_assistant: HomeAssistant) -> None:
    """Reset all pergola and airflow input helpers to known-good values before each test."""
    ha = home_assistant
    for domain, action, data in BASELINE_ACTIONS:
        ha.call_action(domain, action, data)
    for entity_id, value in BASELINE_NUMBERS.items():
        ha.call_action("input_number", "set_value", {"entity_id": entity_id, "value": value})


@pytest.fixture(autouse=True)
def baseline_states(home_assistant: HomeAssistant, baseline_inputs: None) -> None:
    """Seed all CI-stub entity states (integrations absent in CI) before each test.

    Runs after baseline_inputs to ensure input helpers are set before external stubs;
    this matters for template sensors that read both.
    """
    for entity_id, (state, attributes) in BASELINE_STATES.items():
        home_assistant.set_state(entity_id, state, attributes)
