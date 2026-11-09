"""Wallbox wrapper sensors (packages/energy.yaml), in-process (plans/test-execution.md, Step 2).

sensor.wallbox_power / sensor.wallbox_energy are source-independent wrappers: the Energy
Dashboard references them, never the go-e MQTT entities. The go-e firmware's discovery payload
may declare either W/Wh or kW/kWh, so the wrappers normalise the unit.

Replaces the Docker tests/test_wallbox.py (7 tests → 7 cases here). The go-e entities come from
MQTT discovery in production (not from this repo's YAML), so there is no real path for them in
the test HA: they are seeded, and the test reads the REAL wrapper templates' results.

ONE test on ONE fresh HA (tier 1 in the plan: stateless formulas, no clock, no automations):
it loops over the cases, collects every failure and fails with one assert that lists them all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant

from conftest import apply_baseline, entity_id, seed

# go-e source entities (production ids from MQTT discovery; seeded, see the docstring).
_POWER_SRC = "sensor.go_echarger_homekopp_power_total"
_ENERGY_SRC = "sensor.go_echarger_homekopp_total_energy_charged"


def _power(value: str, unit: str = "W") -> tuple[str, dict]:
    """A go-e total-power state with an explicit unit (as the discovery payload declares it)."""
    return value, {"unit_of_measurement": unit, "device_class": "power", "state_class": "measurement"}


def _energy(value: str, unit: str = "Wh") -> tuple[str, dict]:
    """A go-e lifetime-energy state. No state_class: the go-e payload omits it, which is why the
    wrapper supplies total_increasing itself."""
    return value, {"unit_of_measurement": unit, "device_class": "energy"}


def _near(expected: float, tolerance: float) -> Callable[[str], bool]:
    """Predicate: the state is a number within `tolerance` of `expected`."""

    def check(state: str) -> bool:
        try:
            return abs(float(state) - expected) < tolerance
        except ValueError:
            return False

    check.__doc__ = f"≈{expected} (±{tolerance})"
    return check


def _is(expected: str) -> Callable[[str], bool]:
    """Predicate: the state equals `expected` exactly."""

    def check(state: str) -> bool:
        return state == expected

    check.__doc__ = repr(expected)
    return check


# ── Reset ─────────────────────────────────────────────────────────────────────
# Every case starts from this source pair, and the test checks that both wrappers reflect it
# before the case applies its own inputs. The values differ from every case's expectation, so a
# case cannot pass on a value left over from the previous case.
_RESET = {_POWER_SRC: _power("1"), _ENERGY_SRC: _energy("1")}
_RESET_EXPECT = {"power": _near(1.0, 0.01), "energy": _near(0.001, 0.0001)}


@dataclass
class Case:
    """One wallbox case: the source states to set, and what each wrapper must then show."""

    name: str
    sources: dict[str, tuple[str, dict]]
    expect: dict[str, Callable[[str], bool]] = field(default_factory=dict)


# One case per former Docker test (same names, same values).
CASES = [
    # go-e API v2 native Wh → the wrapper divides by 1000.
    Case("energy_wh_source_converted_to_kwh", {_ENERGY_SRC: _energy("3500.0", "Wh")},
         {"energy": _near(3.5, 0.001)}),
    # Source already in kWh → the wrapper must NOT divide again.
    Case("energy_kwh_source_passed_through", {_ENERGY_SRC: _energy("3.5", "kWh")},
         {"energy": _near(3.5, 0.001)}),
    # go-e nrg[11] native W → passed straight through.
    Case("power_w_source_passed_through", {_POWER_SRC: _power("11040.0", "W")},
         {"power": _near(11040.0, 0.1)}),
    # Source in kW → the wrapper multiplies by 1000.
    Case("power_kw_source_converted_to_w", {_POWER_SRC: _power("11.04", "kW")},
         {"power": _near(11040.0, 0.1)}),
    # Not charging → 0 W, not unavailable (the charger still publishes).
    Case("power_zero_while_idle", {_POWER_SRC: _power("0.0", "W")},
         {"power": _near(0.0, 0.001)}),
    # Charger off MQTT → the energy wrapper is unavailable (a gap, not a fabricated reading).
    Case("energy_unavailable_source_propagates", {_ENERGY_SRC: ("unavailable", {})},
         {"energy": _is("unavailable")}),
    # Charger off MQTT → the power wrapper is unavailable rather than a false 0.
    Case("power_unavailable_source_propagates", {_POWER_SRC: ("unavailable", {})},
         {"power": _is("unavailable")}),
]


def _check(hass: HomeAssistant, wrappers: dict[str, str], expect: dict, where: str) -> list[str]:
    """Compare each wrapper's state with its predicate; return one message per mismatch."""
    failures = []
    for key, check in expect.items():
        state = hass.states.get(wrappers[key])
        got = state.state if state else None
        if got is None or not check(got):
            failures.append(f"{where}: {wrappers[key]} = {got!r}, want {check.__doc__}")
    return failures


async def test_wallbox_wrappers(ha: HomeAssistant) -> None:
    """All wallbox cases on one HA; every failing case is listed in the one assert."""
    await apply_baseline(ha)
    # Wrapper ids looked up by unique_id (repo rule: never derive an id).
    wrappers = {
        "power": entity_id(ha, "sensor", "template", "wallbox_power"),
        "energy": entity_id(ha, "sensor", "template", "wallbox_energy"),
    }
    failures: list[str] = []
    for case in CASES:
        # Reset both sources and prove the wrappers re-rendered from them.
        await seed(ha, _RESET)
        # A failed reset is reported, and the case still runs so its own result is listed too.
        failures += _check(ha, wrappers, _RESET_EXPECT, f"{case.name} (reset)")
        # The case's own inputs; the source it does not name keeps the reset value.
        await seed(ha, case.sources)
        failures += _check(ha, wrappers, case.expect, case.name)
    assert not failures, f"{len(failures)} wallbox check(s) failed:\n" + "\n".join(failures)
