"""Heating/cooling indicator thresholds (packages/heating_cooling_indicator.yaml), in-process.

The three thresholds are input_numbers; the order heating < passive < active is enforced by the
two *_effective template sensors (each at least 2 °C above the previous threshold), and the
1 °C hysteresis is fixed inside the indicator template, which reads its own previous state
(`this.state`).

Replaces the Docker tests/test_heating_cooling_indicator.py (6 tests → 6 cases here). Inputs go
through real paths: the thresholds through `input_number.set_value`, the 48h mean as a seeded
state. The mean is seeded under its production id: the statistics sensor that feeds it needs the
recorder history of a moving filter (time, tier 3 in the plan), and on a fresh registry it even
registers under another id (#146), so `sensor.wheatherstation_outdoor_temperature_48h_mean` is
free for the seed.

ONE test on ONE fresh HA (tier 1: no clock, no automations): it loops over the cases, collects
every failure and fails with one assert that lists them all.

How a case sets the indicator's previous state (`this.state`): set the mean to a value that
keeps the wanted state, THEN pin the indicator with a seed. The pin makes the template re-render
on its own change; because the mean already matches, the re-render keeps the pinned state. The
test checks that the pin held before it moves the mean across the boundary under test (a pin
that did not hold would make the case meaningless, so it is reported as a failure).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant

from conftest import apply_baseline, entity_id, seed

_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
# Production id of the 48h statistics mean, read by the indicator (seeded, see the docstring).
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_HEAT = "input_number.heating_indicator_heating_below"
_PASSIVE = "input_number.heating_indicator_passive_cooling_above"
_ACTIVE = "input_number.heating_indicator_active_cooling_above"


@dataclass
class Case:
    """One indicator case.

    helpers: (heating below, passive cooling above, active cooling above) as typed in the boxes.
    effective: expected (passive effective, active effective) after the order clamp.
    pin: (mean, indicator state) that sets the previous state, or None for a threshold-only case.
    steps: (mean, expected indicator state) applied in order after the pin.
    """

    name: str
    helpers: tuple[float, float, float]
    effective: tuple[float, float]
    pin: tuple[float, str] | None = None
    steps: list[tuple[float, str]] = field(default_factory=list)


# One case per former Docker test. The Docker tests checked only the effective value they relied
# on; every case here checks both effective sensors (values from the same clamp rule).
CASES = [
    # Raising 'heating below' to 14 makes a 13 °C mean count as heating (it is neutral at 12).
    Case("heating_threshold_is_taken_from_the_helper", (14, 16, 20), (16, 20),
         pin=(15.0, "neutral"), steps=[(13.0, "active_heating")]),
    # Leaving heating needs heat + 1: threshold 14 → 14.5 stays heating, 15 goes neutral.
    Case("heating_hysteresis_is_one_degree_above_the_threshold", (14, 16, 20), (16, 20),
         pin=(13.0, "active_heating"), steps=[(14.5, "active_heating"), (15.0, "neutral")]),
    # Lowering 'passive cooling above' to 15 makes a 15 °C mean passive cooling (neutral at 16).
    Case("passive_cooling_threshold_is_taken_from_the_helper", (12, 15, 20), (15, 20),
         pin=(14.0, "neutral"), steps=[(15.0, "passive_cooling")]),
    # heat 18, passive typed as 10 → effective passive is 20 (heat + 2); 19 °C stays neutral.
    Case("order_is_enforced_when_passive_is_set_below_heating", (18, 10, 20), (20, 22),
         pin=(18.5, "neutral"), steps=[(19.0, "neutral")]),
    # Lowering 'active cooling above' to 18 (passive 16) makes an 18 °C mean active cooling.
    Case("active_cooling_threshold_is_taken_from_the_helper", (12, 16, 18), (16, 18),
         pin=(17.0, "passive_cooling"), steps=[(18.0, "active_cooling")]),
    # heat 18, passive typed 6, active typed 7 → effective passive 20, active 22 (dashboard).
    Case("effective_thresholds_show_the_clamp", (18, 6, 7), (20, 22)),
]


def _state(hass: HomeAssistant, eid: str) -> str | None:
    """Current state string of an entity, or None if it does not exist."""
    s = hass.states.get(eid)
    return s.state if s else None


async def _set_helpers(hass: HomeAssistant, values: tuple[float, float, float]) -> None:
    """Type the three thresholds into their boxes (real input_number.set_value)."""
    for eid, value in zip((_HEAT, _PASSIVE, _ACTIVE), values, strict=True):
        await hass.services.async_call(
            "input_number", "set_value", {"entity_id": eid, "value": value}, blocking=True
        )
    await hass.async_block_till_done()


def _effective_failures(hass: HomeAssistant, ids: dict, want: tuple[float, float], where: str) -> list[str]:
    """Compare both effective-threshold sensors with the expected clamp result."""
    failures = []
    for key, expected in zip(("passive", "active"), want, strict=True):
        got = _state(hass, ids[key])
        try:
            ok = got is not None and float(got) == expected
        except ValueError:
            ok = False
        if not ok:
            failures.append(f"{where}: {ids[key]} = {got!r}, want {expected}")
    return failures


async def test_indicator_thresholds(ha: HomeAssistant) -> None:
    """All indicator cases on one HA; every failing case is listed in the one assert."""
    await apply_baseline(ha)
    # Config entity ids looked up by unique_id (repo rule: never derive an id).
    ids = {
        "indicator": entity_id(ha, "sensor", "template", "heating_cooling_indicator"),
        "passive": entity_id(ha, "sensor", "template", "heating_indicator_passive_cooling_effective"),
        "active": entity_id(ha, "sensor", "template", "heating_indicator_active_cooling_effective"),
    }
    failures: list[str] = []
    for case in CASES:
        # Reset: a threshold set no case uses (13/17/21 → effective 17/21), checked, so the
        # case's own helper writes are real changes that the effective sensors must follow.
        await _set_helpers(ha, (13, 17, 21))
        # A failed reset is reported, and the case still runs so its own result is listed too.
        failures += _effective_failures(ha, ids, (17, 21), f"{case.name} (reset)")
        # The case's thresholds and the clamp they lead to.
        await _set_helpers(ha, case.helpers)
        failures += _effective_failures(ha, ids, case.effective, case.name)
        if case.pin is None:
            continue
        # Previous state: mean first, then the pin (see the module docstring), then check it held.
        mean, pinned = case.pin
        await seed(ha, {_MEAN: (str(mean), _C)})
        await seed(ha, {ids["indicator"]: pinned})
        if (got := _state(ha, ids["indicator"])) != pinned:
            failures.append(f"{case.name}: pin {pinned!r} at mean {mean} did not hold, got {got!r}")
            continue
        # Move the mean across the boundary under test, step by step.
        for step_mean, expected in case.steps:
            await seed(ha, {_MEAN: (str(step_mean), _C)})
            if (got := _state(ha, ids["indicator"])) != expected:
                failures.append(
                    f"{case.name}: mean {step_mean} (from {pinned!r} at {mean}) → {got!r}, "
                    f"want {expected!r}"
                )
    assert not failures, f"{len(failures)} indicator check(s) failed:\n" + "\n".join(failures)
