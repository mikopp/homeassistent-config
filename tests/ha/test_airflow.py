"""Airflow (packages/airflow_cooling.yaml, custom_templates/airflow_decision.jinja), in-process.

First part of this file: the formula tables (decision, bypass, dew points). Section "Item 4"
below: the real indicators with their delays and hysteresis, the controller and drying-boost
automations on real triggers, the drying schedules, the climate hvac_action and the reload
recovery, on the clock.

The tables: three tests, ONE fresh HA each (no clock, no accumulators, real triggers
only through state changes). Each loops over its cases, resets every input it depends on per
case, collects failures and fails with one assert that lists every failing case.

What is seeded and why (everything else goes through the real helpers):
- The decision's inputs are the airflow indicators (trigger-based template binary sensors with
  a 10-min delay_on/off, reading 5-min filters). Driving them for real needs the clock (item 4),
  so they are seeded, in the order the Docker suite found necessary: indoor dew and season FIRST
  (trigger inputs of the indicators: changing them re-renders the indicators, which have no
  internal state yet and write `unknown`), then flush before drying, the low guards, free
  cooling last. The season itself is the REAL heating/cooling indicator, driven through its
  seeded 48h mean (see `_SEASON_MEAN`).
- `sensor.airflow_min_indoor_dew_5min` is the id the decision reads. On a fresh registry the
  filter registers as `sensor.airflow_avg_indoor_dew_5min` (#146), so the production id is free
  for the seed.
- The bypass reads six 5-min filter sensors (time-weighted moving averages: item 4); they are
  seeded under their ids, as in the Docker suite. Their ComfoConnect sources are not touched
  during the test, so the filters do not write over the seeds.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import holidays as _holidays  # workday's own dependency (requirements_test.txt pin)
import pytest
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers.template import Template

from conftest import Clock, SeedValue, apply_baseline, entity_id, local_at, next_day, seed

_T = {"unit_of_measurement": "°C", "device_class": "temperature"}
_H = {"unit_of_measurement": "%", "device_class": "humidity"}
_AUTO = "input_boolean.airflow_cooling_automatic_enabled"


def _state(hass: HomeAssistant, eid: str) -> str | None:
    """Current state string of an entity, or None if it does not exist."""
    s = hass.states.get(eid)
    return s.state if s else None


async def _set_number(hass: HomeAssistant, eid: str, value: float) -> None:
    """Set an input_number through its real action."""
    await hass.services.async_call(
        "input_number", "set_value", {"entity_id": eid, "value": value}, blocking=True
    )


# ── Decision table: sensor.airflow_cooling_state ──────────────────────────────
# THE single decision: state = reason label, attributes profile + ventilation = what the
# controller and the boost apply. Baseline dew thresholds: min 45 % → dew_min ≈ 9.08 °C
# (retention enters below 8.98, leaves at 9.08); the default indoor dew 12.0 is in band.

# Decision inputs in seeding order (see the module docstring). Every case sets all of them.
_DEW = "sensor.airflow_min_indoor_dew_5min"
# The season is NOT seeded: the real sensor.heating_cooling_indicator (another package) is driven
# through its seeded 48h mean (production id; see tests/ha/test_heating_cooling_indicator.py).
# Pinning the indicator instead makes its self-referencing template (this.state) re-render on
# the pin and walk back toward its mean; more than two such self-triggered renders in a row log
# "Template loop detected" (template_entity.py, limit = number of templates). One mean per
# season, inside the band at the baseline thresholds 12 / 16 / 20, reached from neutral in at
# most two steps (the reset goes back to neutral first, so no chain is longer than that).
_SEASON = "sensor.heating_cooling_indicator"
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_SEASON_MEAN = {"active_heating": "11.0", "neutral": "14.0", "passive_cooling": "17.0",
                "active_cooling": "21.0"}
_INDICATORS = {
    "flush": "binary_sensor.airflow_humidity_flush_needed",
    "drying": "binary_sensor.airflow_humidity_drying_needed",
    "moist": "binary_sensor.airflow_moisture_ventilation_low_needed",
    "heat": "binary_sensor.airflow_heat_ventilation_low_needed",
    "free": "binary_sensor.airflow_free_cooling_available",
}
_DEFAULTS = {"dew": "12.0", "season": "neutral", "flush": "off", "drying": "off",
             "moist": "off", "heat": "off", "free": "off"}

# Device outputs the decision must NOT read; reset to their baseline per case.
_OUTPUTS = {
    "select.comfoconnect_pro_temperature_profile": "comfort",
    "switch.comfoconnect_pro_boost": "off",
}


@dataclass
class Step:
    """A further step of a decision case.

    changes: decision inputs (keys of _DEFAULTS, re-seeded in order with the case's inputs) or
      other entity states to seed.
    expect: (state, profile, ventilation), or "unavailable".
    macro: macro renders at the new inputs, as in Decision.macro.
    """

    changes: dict[str, SeedValue]
    expect: tuple[str, str, str] | str
    macro: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Decision:
    """One decision case.

    inputs: overrides of _DEFAULTS (dew, season, flush, drying, moist, heat, free).
    auto: input_boolean.airflow_cooling_automatic_enabled.
    outputs: device states seeded before the inputs (the decision must ignore them).
    expect: (state, profile, ventilation), or "unavailable".
    macro: (prev_profile, expected "state|profile|ventilation") renders of the macro itself with
      an explicit previous profile, at the case's inputs (the hysteresis memory; see below).
    then: further steps on top of the case, in order.
    """

    name: str
    inputs: dict[str, str] = field(default_factory=dict)
    auto: bool = True
    outputs: dict[str, SeedValue] = field(default_factory=dict)
    expect: tuple[str, str, str] | str = ("comfort", "comfort", "auto")
    macro: list[tuple[str, str]] = field(default_factory=list)
    then: list[Step] = field(default_factory=list)


# One case per former Docker test (names without the `test_decision_` prefix).
DECISIONS = [
    # Automation disabled → 'off' with no outputs, whatever the indicators say.
    Decision("off_when_auto_disabled", {"free": "on"}, auto=False, expect=("off", "off", "off")),
    # Free cooling in cooling season → cool profile + medium rate.
    Decision("free_cooling_cooling_season", {"season": "active_cooling", "free": "on"},
             expect=("free_cooling", "cool", "medium")),
    # 2026-10-23 regression: free cooling is never used in heating season.
    Decision("active_heating_ignores_free_cooling", {"season": "active_heating", "free": "on"},
             expect=("heating", "warm", "auto")),
    # Active heating, indoor dew in band → heating, warm, auto.
    Decision("active_heating", {"season": "active_heating"}, expect=("heating", "warm", "auto")),
    # Humidity flush (no boost) → cool profile + medium rate.
    Decision("flush", {"flush": "on"}, expect=("moisture_flush_cooling", "cool", "medium")),
    # A heating-season flush still opens the bypass: flush beats heating.
    Decision("flush_overrides_heating", {"season": "active_heating", "flush": "on"},
             expect=("moisture_flush_cooling", "cool", "medium")),
    # Flush + drying → boost on top of the cool profile.
    Decision("drying_boost", {"flush": "on", "drying": "on"},
             expect=("moisture_flush_boost", "cool", "boost")),
    # Flush and a (lagging) low guard both on → flush wins.
    Decision("flush_wins_over_low_guard", {"flush": "on", "moist": "on"},
             expect=("moisture_flush_cooling", "cool", "medium")),
    # Hot real outdoor + cool intake (free cooling) → bypass open at LOW rate.
    Decision("heat_protection_keeps_free_cooling_profile", {"free": "on", "heat": "on"},
             expect=("heat_protection", "cool", "low")),
    # Hot real outdoor, no free cooling → comfort profile at LOW rate.
    Decision("heat_protection_without_free_cooling", {"heat": "on"},
             expect=("heat_protection", "comfort", "low")),
    # Humid outdoor → moisture_protection at LOW rate (heat + moist also reports moisture).
    Decision("moisture_protection", {"moist": "on", "heat": "on"},
             expect=("moisture_protection", "comfort", "low")),
    # Protections only lower the rate; the season still picks the profile.
    Decision("moisture_protection_in_heating", {"season": "active_heating", "moist": "on"},
             expect=("moisture_protection", "warm", "low")),
    # Dry indoor air (dew 8.0 < dew_min 9.08) in neutral season → warm to retain moisture.
    Decision("moisture_retention_neutral", {"dew": "8.0"},
             expect=("moisture_retention", "warm", "auto")),
    # Dry indoor + free cooling available (neutral) → retention wins: warm, no medium bump.
    Decision("moisture_retention_beats_free_cooling", {"dew": "8.0", "free": "on"},
             expect=("moisture_retention", "warm", "auto")),
    # Dry indoor in active heating → warm, labelled moisture_retention.
    Decision("moisture_retention_in_heating", {"season": "active_heating", "dew": "8.0"},
             expect=("moisture_retention", "warm", "auto")),
    # Cooling season is exempt from retention (indoor dew naturally dips in summer) → comfort.
    Decision("dry_in_cooling_season_is_comfort", {"season": "active_cooling", "dew": "8.0"},
             expect=("comfort", "comfort", "auto")),
    # Humid indoor, no flush, neutral, a warm profile on the device → comfort (nothing sticks).
    Decision("humid_neutral_is_comfort", {"dew": "14.0"},
             outputs={"select.comfoconnect_pro_temperature_profile": "warm"},
             expect=("comfort", "comfort", "auto")),
    # Dry retention enters 0.1 °C below dew_min and leaves at dew_min (memory = previous
    # profile). dew 9.03 sits between the edges: the sensor (previous profile 'off' after the
    # reset) stays comfort; the macro from comfort stays comfort, from warm stays warm. At 9.2
    # warm leaves. The "from warm" memory is checked on the macro, as in the Docker test: a dew
    # change re-renders the indicators to `unknown` for a moment (no internal state without the
    # clock), so the sensor goes unavailable and drops its stored profile.
    Decision("retention_hysteresis", {"dew": "9.03"},
             expect=("comfort", "comfort", "auto"),
             macro=[("comfort", "comfort|comfort|auto"), ("warm", "moisture_retention|warm|auto")],
             then=[Step({"dew": "9.2"}, ("comfort", "comfort", "auto"),
                        macro=[("warm", "comfort|comfort|auto")])]),
    # The decision never reads the device: changing profile/boost/climate leaves it unchanged.
    Decision("ignores_outputs", {"season": "active_heating", "free": "on"},
             expect=("heating", "warm", "auto"),
             then=[Step({"select.comfoconnect_pro_temperature_profile": "cool",
                         "switch.comfoconnect_pro_boost": "on",
                         "climate.airflow_climate": ("auto", {"hvac_action": "cooling"})},
                        ("heating", "warm", "auto"))]),
    # Any indicator without a value → decision unavailable (the automations then do nothing).
    Decision("unavailable_when_indicator_missing",
             then=[Step({"binary_sensor.airflow_free_cooling_available": "unavailable"},
                        "unavailable")]),
]


async def _seed_inputs(hass: HomeAssistant, inputs: Mapping[str, str]) -> str | None:
    """Set every decision input (defaults overridden by `inputs`) in the required order.

    Indoor dew, then the season (through the 48h mean), then the delayed indicators. Returns an
    error message when the real season indicator did not reach the wanted season, else None.
    """
    values = _DEFAULTS | dict(inputs)
    await seed(hass, {_DEW: (values["dew"], _T)})
    await seed(hass, {_MEAN: (_SEASON_MEAN[values["season"]], _T)})
    if (got := _state(hass, _SEASON)) != values["season"]:
        return f"season {got!r} at mean {_SEASON_MEAN[values['season']]}, want {values['season']!r}"
    await seed(hass, {eid: values[key] for key, eid in _INDICATORS.items()})
    return None


def _decision(hass: HomeAssistant, eid: str) -> tuple[str, str, str] | str | None:
    """The decision as (state, profile, ventilation), or its bare state when unavailable."""
    s = hass.states.get(eid)
    if s is None:
        return None
    if s.state == "unavailable":
        return "unavailable"
    return s.state, s.attributes.get("profile"), s.attributes.get("ventilation")


def _render_macro(hass: HomeAssistant, prev_profile: str) -> str:
    """Render the decision macro directly with an explicit previous profile."""
    return Template(
        "{% from 'airflow_decision.jinja' import airflow_decision %}"
        f"{{{{ airflow_decision('{prev_profile}') }}}}",
        hass,
    ).async_render(parse_result=False)


async def test_decision_table(ha: HomeAssistant) -> None:
    """All decision cases on one HA; every failing case is listed in the one assert."""
    await apply_baseline(ha)
    eid = entity_id(ha, "sensor", "template", "airflow_cooling_state")
    failures: list[str] = []
    for case in DECISIONS:
        # Reset: automation off, device outputs and every input back to the defaults. The
        # decision must then read 'off' (also resets its hysteresis memory to profile 'off').
        # A failed reset is reported, and the case still runs so its own result is listed too.
        await ha.services.async_call("input_boolean", "turn_off", {"entity_id": _AUTO}, blocking=True)
        await seed(ha, _OUTPUTS)
        if error := await _seed_inputs(ha, {}):
            failures.append(f"{case.name} (reset): {error}")
        if (got := _decision(ha, eid)) != ("off", "off", "off"):
            failures.append(f"{case.name} (reset): {got!r}, want ('off', 'off', 'off')")
        # The case: outputs, then its inputs, then the automation switch (a real state change
        # the decision re-renders on).
        await seed(ha, case.outputs)
        if error := await _seed_inputs(ha, case.inputs):
            failures.append(f"{case.name}: {error}")
            continue
        if case.auto:
            await ha.services.async_call("input_boolean", "turn_on", {"entity_id": _AUTO}, blocking=True)
            await ha.async_block_till_done()
        if (got := _decision(ha, eid)) != case.expect:
            failures.append(f"{case.name}: {got!r}, want {case.expect!r}")
            continue
        for prev, expected in case.macro:
            if (got := _render_macro(ha, prev)) != expected:
                failures.append(f"{case.name}: macro from {prev!r} → {got!r}, want {expected!r}")
        # Further steps: decision inputs (re-seeded in order) or other entity states.
        inputs = dict(case.inputs)
        for step in case.then:
            if all(k in _DEFAULTS for k in step.changes):
                inputs |= step.changes
                if error := await _seed_inputs(ha, inputs):
                    failures.append(f"{case.name}: after {step.changes}: {error}")
                    break
            else:
                await seed(ha, step.changes)
            if (got := _decision(ha, eid)) != step.expect:
                failures.append(f"{case.name}: after {step.changes} → {got!r}, want {step.expect!r}")
            for prev, want in step.macro:
                if (got := _render_macro(ha, prev)) != want:
                    failures.append(f"{case.name}: after {step.changes}, macro from {prev!r} → "
                                    f"{got!r}, want {want!r}")
    assert not failures, f"{len(failures)} decision case(s) failed:\n" + "\n".join(failures)


# ── Bypass estimation: sensor.airflow_bypass_estimation ───────────────────────
# η_max = 0.818 (Zehnder Q350 enthalpy efficiency at 150 m³/h), η_min = 0.05. Expected values
# (moist-air enthalpy via Magnus, station pressure 1013.25 hPa):
#   baseline: h_oa ≈ 33.55, h_sa ≈ 35.67, h_ra ≈ 42.75 kJ/kg → η ≈ 0.231 → b_raw ≈ 0.76 → 75 %
#   clamped_zero: T_sa = T_ra → η = 1.0 → b_raw < 0 → 0 %
#   clamped_hundred: T_sa = T_oa → η ≈ 0 → b_raw > 1 → 100 %
#   inconclusive: T_oa ≈ T_ra, same humidity → |h_ra − h_oa| < 0.5 → none → 'unknown'

_BYPASS_INPUTS = {  # name → (entity, attributes, baseline value)
    "T_oa": ("sensor.airflow_outdoor_temp_5min", _T, "16.0"),
    "RH_oa": ("sensor.airflow_outdoor_air_humidity_5min", _H, "61.0"),
    "T_sa": ("sensor.airflow_supply_air_temp_5min", _T, "19.5"),
    "RH_sa": ("sensor.airflow_supply_air_humidity_5min", _H, "45.0"),
    "T_ra": ("sensor.airflow_extract_air_temp_5min", _T, "21.0"),
    "RH_ra": ("sensor.airflow_extract_air_humidity_5min", _H, "55.0"),
    # Ecowitt station pressure in hPa; the template divides by 10 (falls back to 1013.25).
    "P": ("sensor.wheatherstation_absolute_pressure", {"unit_of_measurement": "hPa"}, "1013.25"),
}
_ETA = {"eta_max": ("input_number.airflow_bypass_efficiency_max", 0.818),
        "eta_min": ("input_number.airflow_bypass_efficiency_min", 0.05)}


@dataclass
class Bypass:
    """One bypass case: overrides of the baseline inputs (strings, or floats for η), expected."""

    name: str
    inputs: dict[str, str | float]
    expect: str


BYPASSES = [
    # Baseline inputs give η ≈ 0.231 → 75 % (nearest lower 15 % step).
    Bypass("baseline", {}, "75"),
    # Supply air equals return air → η = 1.0 → clamped to 0 %.
    Bypass("clamped_zero", {"T_sa": "21.0", "RH_sa": "55.0"}, "0"),
    # Supply air equals outdoor air (RH ≈ 61 % at T_oa 16, dew 8.5) → η ≈ 0 → clamped to 100 %.
    Bypass("clamped_hundred", {"T_sa": "16.0", "RH_sa": "61.0"}, "100"),
    # Floor rounding: b_raw ≈ 9.4 % (in 7.5…15 %) must show 0 %, not round up to 15 %.
    Bypass("near_closed_floors_to_zero", {"T_sa": "20.0", "RH_sa": "55.0"}, "0"),
    # has_value guard: a missing filter input → unavailable.
    Bypass("unavailable_when_input_missing", {"T_oa": "unavailable"}, "unavailable"),
    # Indoor ≈ outdoor → the state template returns none → 'unknown' (availability holds).
    Bypass("inconclusive",
           {"T_oa": "20.0", "RH_oa": "55.0", "T_ra": "20.0", "RH_ra": "55.0"}, "unknown"),
    # New: no station pressure → standard atmosphere fallback, same 75 % as the baseline.
    Bypass("pressure_fallback", {"P": "unavailable"}, "75"),
    # New: the efficiency helpers are read: η_max 0.70 → b_raw ≈ 0.72 → 60 %.
    Bypass("efficiency_max_from_helper", {"eta_max": 0.70}, "60"),
]


async def _set_bypass_inputs(hass: HomeAssistant, inputs: Mapping[str, str | float]) -> None:
    """Set every bypass input: η helpers via set_value, the seven sensor inputs seeded."""
    for key, (eid, default) in _ETA.items():
        await _set_number(hass, eid, float(inputs.get(key, default)))
    await seed(hass, {
        eid: (str(inputs.get(key, default)), attrs)
        for key, (eid, attrs, default) in _BYPASS_INPUTS.items()
    })


async def test_bypass_estimation(ha: HomeAssistant) -> None:
    """All bypass cases on one HA; every failing case is listed in the one assert."""
    await apply_baseline(ha)
    eid = entity_id(ha, "sensor", "template", "airflow_bypass_estimation")
    failures: list[str] = []
    for case in BYPASSES:
        # Reset: T_sa 20.5 gives 45 %, a value no case expects; checked before the case. A
        # failed reset is reported, and the case still runs so its own result is listed too.
        await _set_bypass_inputs(ha, {"T_sa": "20.5"})
        if (got := _state(ha, eid)) != "45":
            failures.append(f"{case.name} (reset): {got!r}, want '45'")
        await _set_bypass_inputs(ha, case.inputs)
        if (got := _state(ha, eid)) != case.expect:
            failures.append(f"{case.name} {case.inputs}: {got!r}, want {case.expect!r}")
    assert not failures, f"{len(failures)} bypass case(s) failed:\n" + "\n".join(failures)


# ── Dew-point thresholds: sensor.airflow_dew_point_{min,target,max} ───────────
# Each humidity helper expressed as the dew point it implies at the target temperature (Magnus).
# The expectation is computed here in Python, independently of the YAML, and anchored by the
# literal baseline values the Docker tests and the YAML comments use (9.08 / 12.08 °C).


def _magnus_dew(t: float, rh: float) -> float:
    """Dew point (°C) of air at `t` °C and `rh` % (Magnus, same constants as the YAML)."""
    x = math.log(0.61078 * math.exp(17.27 * t / (t + 237.3)) * rh / 100 / 0.61078)
    return round(237.3 * x / (17.27 - x), 2)


@dataclass
class DewCase:
    """One threshold case: (target temp, min, target, max humidity), optional literal anchor."""

    name: str
    helpers: tuple[float, float, float, float]
    literal: tuple[float, float, float] | None = None


DEW_CASES = [
    # Baseline (21.5 °C, 45/55/55 %): replaces both Docker tests (sensors match the inline
    # formula; dew_point_target equals the free-cooling dew_max ≈ 12.08 °C).
    DewCase("baseline", (21.5, 45, 55, 55), literal=(9.08, 12.08, 12.08)),
    # New: three distinct humidities (max 65 % → 14.65 °C, the low-needed boundary value).
    DewCase("distinct_humidities", (21.5, 45, 60, 65), literal=(9.08, 13.41, 14.65)),
    # New: the target temperature is read too (both ends of the helper ranges).
    DewCase("warm_target", (26, 50, 60, 70)),
    DewCase("cool_target", (18, 30, 40, 50)),
]
_DEW_HELPERS = (
    "input_number.airflow_cooling_target_temperature",
    "input_number.airflow_min_humidity",
    "input_number.airflow_target_humidity",
    "input_number.airflow_max_humidity",
)


async def test_dew_point_thresholds(ha: HomeAssistant) -> None:
    """All threshold cases on one HA; every failing case is listed in the one assert."""
    await apply_baseline(ha)
    sensors = [
        entity_id(ha, "sensor", "template", uid)
        for uid in ("airflow_dew_point_min", "airflow_dew_point_target", "airflow_dew_point_max")
    ]

    async def apply(helpers: tuple[float, float, float, float]) -> list[float | None]:
        """Set all four helpers (real set_value) and read the three sensors."""
        for eid, value in zip(_DEW_HELPERS, helpers, strict=True):
            await _set_number(ha, eid, value)
        await ha.async_block_till_done()
        out: list[float | None] = []
        for s in sensors:
            try:
                out.append(float(_state(ha, s)))
            except (TypeError, ValueError):
                out.append(None)
        return out

    def expected(helpers: tuple[float, float, float, float]) -> list[float]:
        """Python Magnus for min, target and max humidity at the target temperature."""
        t, *rhs = helpers
        return [_magnus_dew(t, rh) for rh in rhs]

    failures: list[str] = []
    for case in DEW_CASES:
        # Reset: a helper set no case uses, checked, so the case's writes are real changes. A
        # failed reset is reported, and the case still runs so its own result is listed too.
        reset = (20, 35, 45, 52)
        if (got := await apply(reset)) != expected(reset):
            failures.append(f"{case.name} (reset): {got}, want {expected(reset)}")
        got = await apply(case.helpers)
        want = expected(case.helpers)
        if case.literal is not None and want != list(case.literal):
            failures.append(f"{case.name}: Python Magnus {want} != anchor {list(case.literal)}")
        if got != want:
            failures.append(f"{case.name} {case.helpers}: {sensors} = {got}, want {want}")
    assert not failures, f"{len(failures)} dew-point case(s) failed:\n" + "\n".join(failures)


# ══ Item 4: the real indicators, the automations and the climate entity, on the clock ═════════
# Controller, drying boost, indicator, reload and hvac_action tests.
# ONE fresh HA per test (delayed indicators, automations).
#
# Unlike the item-2 tables above, NOTHING of the decision chain is seeded here: the indicators
# (trigger-based template binary sensors, delay_on/off 10 min, `this.state` hysteresis) are
# driven through their real inputs and the clock, the season is the REAL heating/cooling
# indicator (through its seeded 48h mean), the schedules and binary_sensor.workday are the real
# helpers (the clock is moved to a known weekday and time), and the automations run on real
# triggers with their real conditions (never `automation.trigger`). Their effects are the calls
# recorded by the stubbed ComfoConnect / phone actions (tests/ha/conftest.py `_STUBBED_ACTIONS`).
#
# Still seeded, because they have no real source here: the 5-min filter outputs that are the
# indicators' inputs (time-weighted moving averages of ComfoConnect / weather-station sensors;
# their sources are not touched, so the filters never write over the seeds), the ComfoConnect
# device entities (profile, preset, auto mode, away, boost, boost time), and the 48h mean.

# Indicator inputs, by scenario key: the five filter outputs (seeded) …
_FILTERS = {
    "outdoor_dew": "sensor.airflow_outdoor_dew_5min",
    "indoor_dew": "sensor.airflow_min_indoor_dew_5min",
    "outdoor_temp": "sensor.airflow_outdoor_temp_5min",
    "indoor_temp": "sensor.airflow_avg_indoor_temp_5min",
    # Smoothed weather-station temperature (heat protection, drying boost). On a fresh registry
    # the filter registers as sensor.airflow_weatherstation_… (#146), so this id is free.
    "ws": "sensor.airflow_wheatherstation_outdoor_temp_5min",
}
# … and the helpers they compare against (set through input_number.set_value).
_HELPER_IDS = {
    "target_temp": "input_number.airflow_cooling_target_temperature",
    "min_dew_diff": "input_number.airflow_min_dew_diff",
    "min_temp_diff": "input_number.airflow_min_temp_diff",
    "target_hum": "input_number.airflow_target_humidity",
    "max_hum": "input_number.airflow_max_humidity",
}
# Reference scenario: every indicator off, decision comfort (with automatic control on).
# Thresholds at these helpers: dew_point_target = dew_point_max = 12.08 °C (55 %),
# dew_point_min = 9.08 °C (45 %).
#   free cooling: intake 21.0 is not below room 22.0 − 1.5 (nor 22.0 − 1.0 while on) → off
#   flush: indoor dew 11.5 not above 12.08 (nor 12.08 − 0.3 while on) → off
#   moisture low: 11.5 below 12.08 (both edges) → off;  drying: no flush → off
#   heat low: weather station 20.0 below room 22.0 (and below 22.0 − 1.5 while on) → off
# Every value is past the release edge of each indicator's hysteresis (`this.state`), so the
# reference resets them from any case.
_REFERENCE: dict[str, float | str] = {
    "outdoor_dew": 8.5, "indoor_dew": 11.5, "outdoor_temp": 21.0, "indoor_temp": 22.0,
    "ws": 20.0, "season": "neutral", "target_temp": 21.5, "min_dew_diff": 2.0,
    "min_temp_diff": 1.5, "target_hum": 55, "max_hum": 55,
}
# Named scenarios (overrides of the reference) used by several tests:
FREE = {"outdoor_temp": 16.0}                       # intake 16 < 20.5 → free cooling
MOIST = {"indoor_dew": 13.0, "outdoor_dew": 13.5}   # humid outdoor, indoor above 12.08
HEAT = {"ws": 23.0}                                 # real outdoor above the room (22)
FLUSH = {"indoor_dew": 13.0, "ws": 21.5}            # indoor above 12.08, outdoor 8.5 drier;
#                                                     weather station not below target: no boost
BOOST = {"indoor_dew": 13.0, "ws": 18.0}            # flush + cool weather station
SEASONS = {"heating": {"season": "active_heating"}, "cooling": {"season": "active_cooling"}}

_INDICATOR_UIDS = {
    "free": "airflow_free_cooling_available",
    "flush": "airflow_humidity_flush_needed",
    "drying": "airflow_humidity_drying_needed",
    "moist": "airflow_moisture_ventilation_low_needed",
    "heat": "airflow_heat_ventilation_low_needed",
}
# Entities the item-4 tests need REAL, so the shared baseline must not seed them: the
# indicators, the combined low intent, the season, workday and the schedules, the climate.
_REAL = frozenset({f"binary_sensor.{uid}" for uid in _INDICATOR_UIDS.values()} | {
    "binary_sensor.airflow_ventilation_low_needed", _SEASON, "binary_sensor.workday",
    "schedule.airflow_boost_workday", "schedule.airflow_boost_non_workday",
    "climate.airflow_climate",
})
# ComfoConnect device entities (no integration in the test HA: seeded), short key → entity.
_DEVICE = {
    "profile": "select.comfoconnect_pro_temperature_profile",
    "preset": "select.comfoconnect_pro_ventilation_preset",
    "auto_mode": "switch.comfoconnect_pro_auto_mode",
    "away": "switch.comfoconnect_pro_away_function",
    "boost": "switch.comfoconnect_pro_boost",
    "boost_time": "number.comfoconnect_pro_boost_time",
}
_DEVICE_REST = {"profile": "comfort", "preset": "medium", "auto_mode": "on", "away": "off",
                "boost": "off", "boost_time": "0"}
_CONTROLLER = "automation.airflow_ventilation_controller"
_BOOST_AUTO = "automation.airflow_humidity_drying_boost"
_DELAY = 10 * 60  # every airflow indicator's delay_on / delay_off


def _workday(after: date | None = None) -> date:
    """The next Wednesday that is a working day in Austria (no public holiday)."""
    day = next_day(2, after=after)
    while day in _holidays.country_holidays("AT", years=day.year):
        day = next_day(2, after=day)
    return day


def _holiday(after: date) -> date:
    """The first Austrian public holiday after `after` on a Monday-Friday (workday off, so the
    non-workday boost window applies)."""
    for year in (after.year, after.year + 1):
        for day in sorted(_holidays.country_holidays("AT", years=year)):
            if day > after and day.weekday() < 5:
                return day
    raise AssertionError("no weekday holiday within two years")


async def _apply(hass: HomeAssistant, values: Mapping[str, float | str]) -> None:
    """Set a full scenario: helpers (real action), the season (48h mean), the filter outputs.

    The indicators re-render on these changes; their new value lands after their delay.
    """
    for key, eid in _HELPER_IDS.items():
        await _set_number(hass, eid, float(values[key]))
    await seed(hass, {_MEAN: (_SEASON_MEAN[str(values["season"])], _T)})
    await seed(hass, {eid: (str(values[key]), _T) for key, eid in _FILTERS.items()})


async def _settle(clock: Clock) -> None:
    """Let every indicator change land: two delay windows (a flush that turns on re-renders
    the low guards, whose own change then needs a second window)."""
    await clock.advance(_DELAY + 1)
    await clock.advance(_DELAY + 1)


async def _scenario(hass: HomeAssistant, clock: Clock, *overrides: Mapping[str, Any]) -> None:
    """Apply the reference scenario with `overrides` (merged in order) and let it settle."""
    values: dict[str, Any] = dict(_REFERENCE)
    for o in overrides:
        values |= o
    await _apply(hass, values)
    await _settle(clock)


@pytest.fixture
async def airflow_ha(ha: HomeAssistant) -> HomeAssistant:
    """The repo HA with the shared baseline applied, the real entities left out (`_REAL`).

    Applied BEFORE the clock is frozen (request this fixture before `clock`): the baseline's
    helper actions and seeds start pergola automations whose runs wait on timers; under a
    frozen clock `async_block_till_done` never returns (seen: a hang inside `apply_baseline`).
    Then every automation except the two airflow ones is turned off (see below).
    """
    await apply_baseline(ha, mqtt=False, skip=_REAL)
    # Only the two airflow automations stay on. Others react to the clock moves with runs that
    # wait on timers longer than a move (pergola cover response: a settle `delay` in its
    # sun-tracking branch), so a move's `async_block_till_done` never returned (seen: a hang
    # in the first `move_to`, task "time pattern trigger … Pergola Cover Response", even with
    # pergola_automatic_enabled off). They are not under test here.
    others = [eid for eid in ha.states.async_entity_ids("automation")
              if eid not in (_CONTROLLER, _BOOST_AUTO)]
    await ha.services.async_call("automation", "turn_off", {"entity_id": others}, blocking=True)
    _install_device_echo(ha)
    # Which automation made a call: every run's actions carry the context of its
    # `automation_triggered` event (components/automation `trigger_context`).
    owners: dict[str, str] = ha.data.setdefault("airflow_call_owner", {})

    @callback
    def _triggered(event: Event) -> None:
        owners[event.context.id] = event.data["entity_id"]

    ha.bus.async_listen("automation_triggered", _triggered)
    return ha


async def _start(hass: HomeAssistant, clock: Clock, when: datetime) -> dict[str, str]:
    """Move the clock to `when` and settle the reference scenario.

    Returns the registry ids of the five indicators and the decision.
    """
    await clock.move_to(when)
    await _scenario(hass, clock)
    ids = {key: entity_id(hass, "binary_sensor", "template", uid)
           for key, uid in _INDICATOR_UIDS.items()}
    ids["decision"] = entity_id(hass, "sensor", "template", "airflow_cooling_state")
    return ids


async def _device(hass: HomeAssistant, states: Mapping[str, str]) -> None:
    """Seed ComfoConnect device states by short key (real state changes: controller triggers)."""
    await seed(hass, {_DEVICE[k]: v for k, v in states.items()})


async def _auto(hass: HomeAssistant, on: bool) -> None:
    """Switch automatic control (the decision goes 'off' ↔ its value: a real edge)."""
    await hass.services.async_call(
        "input_boolean", "turn_on" if on else "turn_off", {"entity_id": _AUTO}, blocking=True
    )
    await hass.async_block_till_done()


def _fmt_call(action: str, data: Mapping[str, Any]) -> str:
    """One recorded action call as a short, comparable string."""
    eids = data.get("entity_id") or [""]
    eid = (eids[0] if isinstance(eids, list) else eids).split(".", 1)[-1]
    eid = eid.removeprefix("comfoconnect_pro_")
    if action == "select.select_option":
        return f"select {eid}={data['option']}"
    if action == "number.set_value":
        return f"number {eid}={data['value']}"
    if action.startswith("switch."):
        return f"{action} {eid}"
    if action.startswith("notify."):
        return f"notify {str(data.get('title', '')).strip()}"
    return f"{action} {dict(data)}"


def _calls(hass: HomeAssistant, owner: str | None = _CONTROLLER) -> list[str]:
    """The recorded calls since the last `_clear` made by `owner` (an automation id; None:
    every call), sorted (each action records separately, so the order across actions is lost).

    Calls by nobody's automation are the climate entity's: climate_template runs its
    `set_hvac_mode` action whenever `hvac_mode_template` changes (custom_components/
    climate_template/climate.py `_update_hvac_mode` → `async_set_hvac_mode` → script), e.g. it
    writes the device's own profile back when automatic control is switched off.
    """
    owners = hass.data["airflow_call_owner"]
    return sorted(
        _fmt_call(action, call.data)
        for action, calls in hass.data["service_calls"].items() for call in calls
        if owner is None or owners.get(call.context.id) == owner
    )


# Device model of the stubbed ComfoConnect actions: the unit reports what was written, as the
# real integration does. Without it a stub leaves the device state unchanged, so every
# follow-up run (the decision writes state and attributes, the controller's own triggers)
# repeats the write, which production never sees.
_ECHO = {"select.select_option": lambda d: d["option"], "switch.turn_on": lambda d: "on",
         "switch.turn_off": lambda d: "off", "number.set_value": lambda d: str(d["value"])}


def _install_device_echo(hass: HomeAssistant) -> None:
    """Replace the four ComfoConnect stubs with recording handlers that also set the state."""
    for action, new_state in _ECHO.items():
        domain, name = action.split(".")
        calls = hass.data["service_calls"][action]

        async def handler(call: ServiceCall, calls: list = calls, new_state=new_state) -> None:
            calls.append(call)
            eids = call.data.get("entity_id")
            for eid in [eids] if isinstance(eids, str) else eids or []:
                old = hass.states.get(eid)
                hass.states.async_set(eid, new_state(call.data), old.attributes if old else {})

        hass.services.async_register(domain, name, handler)


def _clear(hass: HomeAssistant) -> None:
    """Forget every recorded stub call."""
    for calls in hass.data["service_calls"].values():
        calls.clear()


def _runs(hass: HomeAssistant, automation: str) -> int:
    """How often an automation ran so far (a trigger fired AND its conditions passed).

    Counted from `automation_triggered` events, not `last_triggered`: on the frozen clock two
    runs at the same instant carry the same timestamp.
    """
    return sum(1 for owner in hass.data["airflow_call_owner"].values() if owner == automation)


def _indicators(hass: HomeAssistant, ids: Mapping[str, str]) -> dict[str, str | None]:
    """The five indicators' states by key."""
    return {key: _state(hass, ids[key]) for key in _INDICATOR_UIDS}


_ALL_OFF = dict.fromkeys(_INDICATOR_UIDS, "off")


# ── Controller: automation.airflow_ventilation_controller ─────────────────────────────────
# Per case: reset (automatic control off, device at rest, reference scenario), then the case's
# scenario settles and the device states are seeded while automatic control is still off (the
# controller's condition blocks those triggers), the recorded calls are cleared, and automatic
# control is switched on: the decision changes from 'off' to the case's decision, a real
# `decision_changed` trigger with the real conditions. The check: the decision, every action
# call the run made (Section 1 profile, Section 2 preset / auto mode, notifications), and that
# the automation ran at all (`_runs`), so a "no call" case cannot pass on a run that
# never happened. Further steps (`then`) seed device states as real triggers.
@dataclass
class CtlStep:
    """A further step: device states seeded (a real trigger), the calls it must produce."""

    device: dict[str, str]
    calls: list[str]
    runs: bool = True


@dataclass
class Ctl:
    """One controller case.

    inputs: scenario overrides (see FREE, MOIST, …).  device: device states before the edge.
    expect: (state, profile, ventilation) after automatic control is switched on.
    calls: the calls of that run.  auto: False = automatic control stays off (the gate cases);
    then the first step is the trigger.  then: further steps.
    """

    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    device: dict[str, str] = field(default_factory=dict)
    expect: tuple[str, str, str] = ("comfort", "comfort", "auto")
    calls: list[str] = field(default_factory=list)
    auto: bool = True
    then: list[CtlStep] = field(default_factory=list)


_N_COOL = "notify Ventilation: Free Cooling"
_N_WARM = "notify Ventilation: Warm Profile"
_N_COMFORT = "notify Ventilation: Comfort Profile"
_N_LOW = "notify Ventilation: Low Level"
_N_MEDIUM = "notify Ventilation: Medium Preset"
_N_RESTORED = "notify Ventilation: Auto Mode Restored"

# One case per former Docker test (names without `test_`); "new" marks added ones.
CONTROLLER = [
    # Section 1: free cooling (cooling season) → write cool. Docker: trace only (no assert).
    Ctl("airflow_free_cooling_active", FREE | SEASONS["cooling"],
        expect=("free_cooling", "cool", "medium"), calls=["select temperature_profile=cool",
                                                           _N_COOL]),
    Ctl("airflow_free_cooling_neutral_season", FREE, expect=("free_cooling", "cool", "medium"),
        calls=["select temperature_profile=cool", _N_COOL]),
    # 2026-10-23 regression: active heating + free cooling + device on cool → warm written.
    Ctl("airflow_active_heating_free_cooling_on_writes_warm", FREE | SEASONS["heating"],
        device={"profile": "cool"}, expect=("heating", "warm", "auto"),
        calls=["select temperature_profile=warm", _N_WARM]),
    Ctl("airflow_profile_already_decided_no_write", SEASONS["heating"],
        device={"profile": "warm"}, expect=("heating", "warm", "auto")),
    Ctl("airflow_neutral"),
    # Automatic control off: decision 'off'; a real trigger (the device reports another
    # profile) does not run the controller (its condition), nothing is written.
    Ctl("airflow_auto_disabled", FREE | SEASONS["cooling"], auto=False,
        then=[CtlStep({"profile": "cool"}, [], runs=False)]),
    # Section 2.
    Ctl("moisture_ventilation_low_when_needed", MOIST,
        expect=("moisture_protection", "comfort", "low"),
        calls=["select ventilation_preset=low", "switch.turn_off auto_mode", _N_LOW]),
    Ctl("moisture_ventilation_restore_auto", device={"auto_mode": "off"},
        calls=["switch.turn_on auto_mode", _N_RESTORED]),
    Ctl("moisture_ventilation_disabled_no_action", MOIST, auto=False,
        then=[CtlStep({"preset": "low"}, [], runs=False)]),
    Ctl("medium_preset_enable_when_free_cooling_low_preset", FREE, device={"preset": "low"},
        expect=("free_cooling", "cool", "medium"),
        calls=["select temperature_profile=cool", _N_COOL, "select ventilation_preset=medium",
               "switch.turn_off auto_mode", _N_MEDIUM]),
    # Free cooling available in active heating → auto (NOT medium): only the profile is written.
    Ctl("medium_preset_not_raised_in_active_heating", FREE | SEASONS["heating"],
        device={"preset": "low"}, expect=("heating", "warm", "auto"),
        calls=["select temperature_profile=warm", _N_WARM]),
    Ctl("medium_preset_restore_when_free_cooling_gone",
        device={"auto_mode": "off", "preset": "medium"},
        calls=["switch.turn_on auto_mode", _N_RESTORED]),
    # A (manual) boost runs: the boost-owner branch only keeps auto on, no preset written.
    Ctl("medium_preset_boost_switch_blocks_preset_write", FREE,
        device={"preset": "low", "boost": "on"}, expect=("free_cooling", "cool", "medium"),
        calls=["select temperature_profile=cool", _N_COOL]),
    # Away: Section 2 is skipped; Section 1 still follows the decision.
    Ctl("moisture_preset_away_suppressed", MOIST, device={"away": "on"},
        expect=("moisture_protection", "comfort", "low")),
    Ctl("medium_preset_away_suppressed", FREE, device={"away": "on", "preset": "low"},
        expect=("free_cooling", "cool", "medium"),
        calls=["select temperature_profile=cool", _N_COOL]),
    # Heat protection with free cooling: bypass open (cool) at LOW; already low → no preset.
    Ctl("heat_protection_low_wins_over_free_cooling_bump", FREE | HEAT,
        device={"auto_mode": "off", "preset": "low"}, expect=("heat_protection", "cool", "low"),
        calls=["select temperature_profile=cool", _N_COOL]),
    # Idempotency: the device already matches the decision → no call at all.
    Ctl("controller_low_idempotent_no_write", MOIST,
        device={"auto_mode": "off", "preset": "low"},
        expect=("moisture_protection", "comfort", "low")),
    Ctl("controller_medium_idempotent_no_write", FLUSH,
        device={"profile": "cool", "auto_mode": "off", "preset": "medium"},
        expect=("moisture_flush_cooling", "cool", "medium")),
    Ctl("controller_restore_no_thrash_when_auto_already_on"),
    Ctl("controller_full_rest_state_is_total_no_op",
        device={"profile": "comfort", "auto_mode": "on", "preset": "medium"}),
    # New: the device reports another profile while automatic control is on → re-asserted.
    Ctl("new_profile_changed_by_device_is_reasserted",
        then=[CtlStep({"profile": "cool"}, ["select temperature_profile=comfort", _N_COMFORT])]),
    # New: Away ends while low is decided → Section 2 applies low on the away_ended trigger.
    Ctl("new_away_ended_applies_the_decided_level", MOIST, device={"away": "on"},
        expect=("moisture_protection", "comfort", "low"),
        then=[CtlStep({"away": "off"}, ["select ventilation_preset=low",
                                        "switch.turn_off auto_mode", _N_LOW])]),
    # New: manual low (auto off, preset low) and medium decided → route to auto first; the
    # unit reports auto on, the controller re-runs (auto_mode_on) and forces medium.
    Ctl("new_route_to_auto_from_manual_low", FREE,
        device={"profile": "cool", "auto_mode": "off", "preset": "low"},
        expect=("free_cooling", "cool", "medium"),
        calls=["switch.turn_on auto_mode", "switch.turn_off auto_mode",
               "select ventilation_preset=medium", _N_MEDIUM]),
    # New: the schedule lowers the preset while medium is decided → re-bumped (preset_set_low).
    Ctl("new_schedule_low_preset_is_rebumped", FREE, expect=("free_cooling", "cool", "medium"),
        device={"profile": "cool"},
        then=[CtlStep({"preset": "low"}, ["select ventilation_preset=medium",
                                          "switch.turn_off auto_mode", _N_MEDIUM])]),
]


async def test_controller(airflow_ha: HomeAssistant, clock: Clock) -> None:
    ha = airflow_ha
    """All controller cases on one HA; every failing check is listed in the one assert."""
    ids = await _start(ha, clock, local_at(_workday(), 7, 1))
    failures: list[str] = []
    for case in CONTROLLER:
        # Reset: automatic control off (decision 'off'), device at rest, reference scenario.
        # Nothing may run during the reset (automatic control is off for every trigger).
        await _auto(ha, False)
        await _device(ha, _DEVICE_REST)
        _clear(ha)
        await _scenario(ha, clock)
        if (got := _indicators(ha, ids)) != _ALL_OFF:
            failures.append(f"{case.name} (reset): indicators {got}")
        if (got := _decision(ha, ids["decision"])) != ("off", "off", "off"):
            failures.append(f"{case.name} (reset): decision {got!r}")
        # The case: scenario, device states (controller blocked), then the edge.
        await _scenario(ha, clock, case.inputs)
        await _device(ha, case.device)
        if calls := _calls(ha) + _calls(ha, _BOOST_AUTO):
            failures.append(f"{case.name}: automation calls before the edge {calls}")
        _clear(ha)
        before = _runs(ha, _CONTROLLER)
        if case.auto:
            await _auto(ha, True)
            if (got := _decision(ha, ids["decision"])) != case.expect:
                failures.append(f"{case.name}: decision {got!r}, want {case.expect!r}")
            if _runs(ha, _CONTROLLER) == before:
                failures.append(f"{case.name}: the controller did not run")
            if (got := _calls(ha)) != sorted(case.calls):
                failures.append(f"{case.name}: calls {got}, want {sorted(case.calls)}")
        for n, step in enumerate(case.then, start=2):
            _clear(ha)
            before = _runs(ha, _CONTROLLER)
            await _device(ha, step.device)
            if (_runs(ha, _CONTROLLER) != before) != step.runs:
                failures.append(f"{case.name} step {n}: ran {not step.runs}, want {step.runs}")
            if (got := _calls(ha)) != sorted(step.calls):
                failures.append(f"{case.name} step {n}: calls {got}, want {sorted(step.calls)}")
    assert not failures, f"{len(failures)} controller check(s) failed:\n" + "\n".join(failures)


# ── Drying boost: automation.airflow_humidity_drying_boost ────────────────────────────────
# Boost is decided by the REAL drying indicator: flush needed + weather station below target
# + inside the boost schedule, so this test runs on a working Wednesday from 07:01 (workday
# window 07:00-20:30). Each case: reset (automatic control off, device at rest, reference
# scenario), the case's scenario and device states, then the edge (automatic control on, or a
# device change). Checked: the calls made by the BOOST automation (the controller's own calls,
# e.g. the cool profile, are not part of these cases) and whether it ran.
@dataclass
class BoostStep:
    """A step: scenario overrides and/or device states, then the boost automation's calls."""

    inputs: dict[str, Any] | None = None
    device: dict[str, str] = field(default_factory=dict)
    auto: bool | None = None
    calls: list[str] = field(default_factory=list)
    runs: bool | None = True
    expect: tuple[str, str, str] | str | None = None


@dataclass
class BoostCase:
    """A boost case: the scenario and device before the steps, then the steps in order."""

    name: str
    inputs: dict[str, Any]
    device: dict[str, str]
    steps: list[BoostStep]


_START = ["number boost_time=60", "switch.turn_on boost",
          "notify Ventilation: Humidity Drying Boost"]
_ADOPT = ["number boost_time=60", "switch.turn_on boost"]  # boost already on: no notification
_STOP = ["switch.turn_off boost", "notify Ventilation: Drying Boost Stopped"]
_BOOSTED = ("moisture_flush_boost", "cool", "boost")

BOOSTS = [
    # Real off → boost edge (automatic control on) starts a 60 min boost and notifies. Docker:
    # `drying_boost_starts_when_needed` (trace only) and `…_real_edge_into_boost_fires`
    # (last_triggered moved).
    BoostCase("drying_boost_starts_on_a_real_edge", BOOST, {},
              [BoostStep(auto=True, calls=_START, expect=_BOOSTED)]),
    # A manual boost already running is adopted: boost time and ON re-sent, no notification.
    BoostCase("drying_boost_restart_when_already_running_no_error", BOOST, {"boost": "on"},
              [BoostStep(auto=True, calls=_ADOPT, expect=_BOOSTED)]),
    # Boost no longer decided (weather station warms to 22 °C: drying off; flush stays) →
    # the running boost is stopped and notified.
    BoostCase("drying_boost_stops_when_conditions_gone", BOOST, {},
              [BoostStep(auto=True, calls=_START, expect=_BOOSTED),
               BoostStep(inputs=BOOST | {"ws": 22.0}, calls=_STOP,
                         expect=("moisture_flush_cooling", "cool", "medium"))]),
    # The countdown drops below 5 while boost is decided and on → seamless re-arm: ON re-sent,
    # nothing else (no off, no boost time, no notification).
    BoostCase("drying_boost_rearm_keeps_switch_on", BOOST, {},
              [BoostStep(auto=True, calls=_START, expect=_BOOSTED),
               BoostStep(device={"boost_time": "10"}, calls=[], runs=False),
               BoostStep(device={"boost_time": "4"}, calls=["switch.turn_on boost"])]),
    # A manual boost reaching the threshold while boost is NOT decided → runs, does nothing.
    BoostCase("drying_boost_countdown_during_manual_boost_no_error", {}, {"boost": "on"},
              [BoostStep(auto=True, calls=[], runs=False, expect=("comfort", "comfort", "auto")),
               BoostStep(device={"boost_time": "10"}, calls=[], runs=False),
               BoostStep(device={"boost_time": "4"}, calls=[])]),
    # Away on: the edge does not run the boost automation (its condition).
    BoostCase("drying_boost_away_suppressed", BOOST, {"away": "on"},
              [BoostStep(auto=True, calls=[], runs=False, expect=_BOOSTED)]),
    # Away 'unknown' (ComfoConnect not up yet) is not away: the edge starts the boost.
    BoostCase("drying_boost_away_unknown_is_not_away", BOOST, {"away": "unknown"},
              [BoostStep(auto=True, calls=_START, expect=_BOOSTED)]),
    # Boost decided while away (blocked), away → unknown, then unknown → off: the away_ended
    # edge starts the boost (the boost switch is off).
    BoostCase("drying_boost_away_unknown_to_off_fires", BOOST, {"away": "on"},
              [BoostStep(auto=True, calls=[], runs=False, expect=_BOOSTED),
               BoostStep(device={"away": "unknown"}, calls=[], runs=False),
               BoostStep(device={"away": "off"}, calls=_START)]),
]

# The decision goes unavailable (an input missing) and comes back as boost: by design not an
# edge, so a running boost's timer is not reset (packages/notes/airflow_cooling.md, boost
# model). CONFIRMED CONFIG BUG (#153): with the REAL indicators it IS an edge. flush_needed goes unavailable, drying_needed (no availability
# template, reads flush with is_state) drops to off at once; when the input returns, flush is
# back first, the decision passes moisture_flush_cooling/medium, then drying → boost: a real
# medium → boost edge, and the boost is restarted. Seeding the indicators hides it.
UNAVAILABLE_TO_BOOST = BoostCase(
    "drying_boost_unavailable_to_boost_does_not_fire", BOOST, {},
    [BoostStep(auto=True, calls=_START, expect=_BOOSTED),
     BoostStep(inputs=BOOST | {"indoor_dew": "unavailable"}, calls=[], runs=None,
               expect="unavailable"),
     BoostStep(inputs=BOOST, calls=[], runs=None, expect=_BOOSTED)])


async def _run_boost_cases(ha: HomeAssistant, clock: Clock, cases: list[BoostCase]) -> list[str]:
    """Run boost cases on one HA (working Wednesday 07:01); one message per failed check."""
    ids = await _start(ha, clock, local_at(_workday(), 7, 1))
    failures: list[str] = []
    for case in cases:
        # Reset, as in test_controller.
        await _auto(ha, False)
        await _device(ha, _DEVICE_REST)
        await _scenario(ha, clock)
        if (got := _indicators(ha, ids)) != _ALL_OFF:
            failures.append(f"{case.name} (reset): indicators {got}")
        await _scenario(ha, clock, case.inputs)
        await _device(ha, case.device)
        for n, step in enumerate(case.steps, start=1):
            _clear(ha)
            before = _runs(ha, _BOOST_AUTO)
            if step.inputs is not None:
                await _apply(ha, dict(_REFERENCE) | step.inputs)
                await _settle(clock)
            await _device(ha, step.device)
            if step.auto is not None:
                await _auto(ha, step.auto)
            where = f"{case.name} step {n}"
            if step.expect is not None and (got := _decision(ha, ids["decision"])) != step.expect:
                failures.append(f"{where}: decision {got!r}, want {step.expect!r}")
            if step.runs is not None and (_runs(ha, _BOOST_AUTO) != before) != step.runs:
                failures.append(f"{where}: ran {not step.runs}, want {step.runs}")
            if (got := _calls(ha, _BOOST_AUTO)) != sorted(step.calls):
                failures.append(f"{where}: calls {got}, want {sorted(step.calls)}")
    return failures


async def test_drying_boost(airflow_ha: HomeAssistant, clock: Clock) -> None:
    """All boost cases on one HA; every failing check is listed in the one assert."""
    failures = await _run_boost_cases(airflow_ha, clock, BOOSTS)
    assert not failures, f"{len(failures)} boost check(s) failed:\n" + "\n".join(failures)


@pytest.mark.xfail(strict=True, reason="config bug: an input flap restarts the boost "
                   "(#153); passes once fixed")
async def test_drying_boost_unavailable_to_boost_does_not_fire(
    airflow_ha: HomeAssistant, clock: Clock
) -> None:
    """The design rule of UNAVAILABLE_TO_BOOST (see there); fails today: step 3 restarts."""
    failures = await _run_boost_cases(airflow_ha, clock, [UNAVAILABLE_TO_BOOST])
    assert not failures, f"{len(failures)} boost check(s) failed:\n" + "\n".join(failures)


def test_drying_boost_config_edge_only() -> None:
    """Static check of the package: from: on boost_decided, no ha_start trigger, no 'ha_start' id.

    Moved unchanged from the Docker file (it needs no HA).
    """
    import pathlib

    import yaml

    class _Loader(yaml.SafeLoader):
        pass

    # HA-specific tags (!include, !secret, ...) are irrelevant here: load them as plain strings.
    _Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    path = pathlib.Path(__file__).resolve().parents[2] / "packages" / "airflow_cooling.yaml"
    cfg = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    auto = next(a for a in cfg["automation"] if a.get("id") == "airflow_humidity_drying_boost")
    triggers = {t["id"]: t for t in auto["trigger"]}
    assert "ha_start" not in triggers
    assert not any(t.get("platform") == "homeassistant" for t in auto["trigger"])
    assert set(triggers["boost_decided"]["from"]) == {"medium", "low", "auto", "off"}
    assert triggers["boost_decided"]["to"] == "boost"
    assert "away_ended" in triggers


# ── The indicators themselves: free cooling, moisture low, heat low, flush ────────────────
# Replace the Docker tests that rendered a COPY of a formula over /api/template (dew_max gate,
# low-needed boundary, flush) and the indicator tests that leaned on an earlier test's clock
# move (heat protection, flush unavailable). Here the REAL binary sensors are driven through
# their inputs; hysteresis uses the sensor's real `this.state` (a first step switches it on);
# the 10 min delays are checked on a timeline where it matters.
@dataclass
class IStep:
    """One step: scenario overrides (from the reference), then the expected states.

    expect: key (indicator key, "low" = combined low intent, "decision") → state, checked after
    the settle wait; or, with `timeline`, a list of (seconds after the change, expect).
    """

    inputs: dict[str, Any]
    expect: dict[str, str] = field(default_factory=dict)
    timeline: list[tuple[int, dict[str, str]]] = field(default_factory=list)


@dataclass
class ICase:
    """An indicator case: steps in order, after a reset to the reference scenario."""

    name: str
    steps: list[IStep]


async def _run_indicator_cases(
    ha: HomeAssistant, clock: Clock, cases: list[ICase], when: datetime
) -> list[str]:
    """Run indicator cases on one HA; one message per failed check."""
    ids = await _start(ha, clock, when)
    ids["low"] = entity_id(ha, "binary_sensor", "template", "airflow_ventilation_low_needed")
    failures: list[str] = []

    def check(where: str, expect: Mapping[str, str]) -> None:
        for key, want in expect.items():
            if (got := _state(ha, ids[key])) != want:
                failures.append(f"{where}: {key} = {got!r}, want {want!r}")

    for case in cases:
        await _scenario(ha, clock)
        check(f"{case.name} (reset)", _ALL_OFF)
        for n, step in enumerate(case.steps, start=1):
            await _apply(ha, dict(_REFERENCE) | step.inputs)
            if step.timeline:
                elapsed = 0
                for at, expect in step.timeline:
                    await clock.advance(at - elapsed)
                    elapsed = at
                    check(f"{case.name} step {n} at {at} s", expect)
            else:
                await _settle(clock)
                check(f"{case.name} step {n}", step.expect)
    return failures


def _delay_on(key: str, **others: str) -> list[tuple[int, dict[str, str]]]:
    """Timeline of a delay_on: still off 1 s before 10 min, on (with `others`) after it."""
    return [(_DELAY - 1, {key: "off"}), (_DELAY + 1, {key: "on", **others}),
            (2 * _DELAY + 2, {key: "on", **others})]


def _delay_off(key: str, **others: str) -> list[tuple[int, dict[str, str]]]:
    """Timeline of a delay_off: still on 1 s before 10 min, off (with `others`) after it."""
    return [(_DELAY - 1, {key: "on"}), (_DELAY + 1, {key: "off", **others}),
            (2 * _DELAY + 2, {key: "off", **others})]


# Free cooling (binary_sensor.airflow_free_cooling_available): the absolute humidity gate
# outdoor dew ≤ dew_point_target (12.08 °C at 21.5 °C / 55 %). Replaces the Docker dew_max
# tests, which rendered a copy of the Magnus formula; `dew_max_formula_value_at_baseline` is
# covered by test_dew_point_thresholds (literal 12.08 at baseline).
_RELATIVE_OK = {"indoor_dew": 15.0, "min_dew_diff": 0}  # the relative dew check always passes
FREE_CASES = [
    # Baseline outdoor dew 8.5 passes; new: exact 10 min delay_on and delay_off.
    ICase("free_cooling_dew_max_passes_low_outdoor_dew",
          [IStep(FREE, timeline=_delay_on("free")), IStep({}, timeline=_delay_off("free"))]),
    # Outdoor dew 13 > 12.08: blocked although the relative check (13 < 15) passes.
    ICase("free_cooling_dew_max_blocks_high_outdoor_dew",
          [IStep(FREE | _RELATIVE_OK | {"outdoor_dew": 13.0}, {"free": "off"})]),
    # New: the gate's edge is the sensor value: 12.08 passes (≤), 12.09 blocks.
    ICase("new_free_cooling_dew_max_edge",
          [IStep(FREE | _RELATIVE_OK | {"outdoor_dew": 12.08}, {"free": "on"}),
           IStep(FREE | _RELATIVE_OK | {"outdoor_dew": 12.09}, {"free": "off"})]),
    # Target humidity 60 % → dew_point_target 13.41: outdoor dew 13 now passes.
    ICase("free_cooling_dew_max_shifts_with_target_humidity",
          [IStep(FREE | _RELATIVE_OK | {"outdoor_dew": 13.0, "target_hum": 60, "max_hum": 60},
                 {"free": "on"})]),
]

# Moisture low (binary_sensor.airflow_moisture_ventilation_low_needed): max 65 % →
# dew_point_max 14.65 (ON edge), target 55 % → 12.08 (OFF edge). min_dew_diff 5 keeps the
# flush off (its margin fails), so only this sensor's Schmitt is exercised. Replaces the five
# Docker `low_needed_*` tests (a copy without the sensor's indoor-dew gate; see the drift).
_M = {"max_hum": 65, "min_dew_diff": 5}
MOIST_CASES = [
    # OFF → ON: outdoor 15 ≥ 14.65 (indoor 16 ≥ 14.65); the combined low intent follows.
    ICase("low_needed_turn_on_boundary_fires_above_max_dew",
          [IStep(_M | {"outdoor_dew": 15.0, "indoor_dew": 16.0},
                 timeline=_delay_on("moist", low="on"))]),
    # Outdoor 14: below 14.65 and below indoor 16 → stays off.
    ICase("low_needed_turn_on_boundary_below_max_dew_and_indoor",
          [IStep(_M | {"outdoor_dew": 14.0, "indoor_dew": 16.0}, {"moist": "off"})]),
    # While ON, outdoor 13 (≥ 12.08, below the ON edge 14.65) keeps it on (real this.state).
    ICase("low_needed_stays_on_above_target_dew",
          [IStep(_M | {"outdoor_dew": 15.0, "indoor_dew": 16.0}, {"moist": "on"}),
           IStep(_M | {"outdoor_dew": 13.0, "indoor_dew": 16.0}, {"moist": "on", "low": "on"})]),
    # While ON, outdoor 11 (< 12.08, < indoor 16) → off after the delay_off.
    ICase("low_needed_disengages_below_target_dew",
          [IStep(_M | {"outdoor_dew": 15.0, "indoor_dew": 16.0}, {"moist": "on"}),
           IStep(_M | {"outdoor_dew": 11.0, "indoor_dew": 16.0},
                 timeline=_delay_off("moist", low="off"))]),
    # DRIFT: the Docker copy turned ON here (relative fallback 13 ≥ 10); the real sensor's
    # indoor gate (indoor dew ≥ 14.65 while off) keeps it OFF. The fallback term can never
    # decide alone (outdoor ≥ indoor ≥ edge implies outdoor ≥ edge).
    ICase("low_needed_relative_fallback_is_gated_by_indoor_dew",
          [IStep(_M | {"outdoor_dew": 13.0, "indoor_dew": 10.0}, {"moist": "off"})]),
    # New: ON, then the flush turns on (outdoor 12.5 within the hysteresis, margin 14.5 < 16):
    # the moisture guard is gated off once flush is on (they are opposite actions).
    ICase("new_low_needed_gated_off_by_flush",
          [IStep({"max_hum": 65, "outdoor_dew": 15.0, "indoor_dew": 16.0}, {"moist": "on"}),
           IStep({"max_hum": 65, "outdoor_dew": 12.5, "indoor_dew": 16.0, "ws": 21.5},
                 {"flush": "on", "moist": "off"})]),
]

# Heat low (binary_sensor.airflow_heat_ventilation_low_needed): ON when the smoothed weather
# station reaches the room temperature, OFF once it is min_temp_diff (1.5) below it.
HEAT_CASES = [
    # Docker `heat_ventilation_low_needed_off_when_outdoor_below_indoor` (room 26, station 20),
    # which relied on an earlier test's clock move.
    ICase("heat_ventilation_low_needed_off_when_outdoor_below_indoor",
          [IStep({"indoor_temp": 26.0, "ws": 20.0}, {"heat": "off", "low": "off"})]),
    # Docker `ventilation_low_needed_derives_from_heat` (seeded heat low): the real heat low
    # turns on (delay_on) and the combined state-based intent follows at once, both ways.
    ICase("ventilation_low_needed_derives_from_heat",
          [IStep({"indoor_temp": 26.0, "ws": 26.0}, timeline=_delay_on("heat", low="on")),
           IStep({"indoor_temp": 26.0, "ws": 25.0}, {"heat": "on", "low": "on"}),
           IStep({"indoor_temp": 26.0, "ws": 24.0}, timeline=_delay_off("heat", low="off"))]),
    # New: heat low is gated off while a flush runs.
    ICase("new_heat_low_gated_off_by_flush",
          [IStep({"ws": 23.0}, {"heat": "on"}),
           IStep(FLUSH | {"ws": 23.0}, {"flush": "on", "heat": "off"})]),
]

# Flush (binary_sensor.airflow_humidity_flush_needed): max 60 % → dew_point_max 13.41,
# dew_point_target 12.08. Branch 1 (indoor above max) ignores temperatures; branch 2 (above
# target only) needs the intake below target − min_temp_diff and the room at target; active
# heating allows branch 1 only; 0.3 °C hysteresis while on. Replaces the Docker flush copy.
_F = {"max_hum": 60, "ws": 21.5}  # weather station not below target: no drying boost
_B2 = _F | {"outdoor_dew": 9.0, "indoor_dew": 12.5, "outdoor_temp": 16.0}  # a branch-2 case
FLUSH_CASES = [
    ICase("flush_branch1_above_max_fires",
          [IStep(_F | {"outdoor_dew": 9.0, "indoor_dew": 14.0}, timeline=_delay_on("flush"))]),
    ICase("flush_branch1_margin_fails",
          [IStep(_F | {"outdoor_dew": 12.5, "indoor_dew": 14.0}, {"flush": "off"})]),
    ICase("flush_branch1_ignores_temperature_gate",
          [IStep(_F | {"outdoor_dew": 9.0, "indoor_dew": 14.0, "outdoor_temp": 25.0,
                       "indoor_temp": 19.0}, {"flush": "on"})]),
    # The Docker test set the RAW station; the 5-min filter is what the airflow sensors read.
    ICase("flush_branch1_ignores_weatherstation_temp",
          [IStep(_F | {"outdoor_dew": 9.0, "indoor_dew": 14.0, "ws": 30.0}, {"flush": "on"})]),
    ICase("flush_branch2_fires_with_temp_gate", [IStep(_B2, {"flush": "on"})]),
    ICase("flush_branch2_blocked_when_temp_gate_fails",
          [IStep(_B2 | {"outdoor_temp": 21.0}, {"flush": "off"})]),
    ICase("flush_branch2_blocked_when_indoor_below_target",
          [IStep(_B2 | {"indoor_temp": 21.0}, {"flush": "off"})]),
    # Branch-2 case flushes in neutral, not in active heating (off after the delay_off).
    ICase("flush_season_guard_heating_branch1_only",
          [IStep(_B2, {"flush": "on"}),
           IStep(_B2 | SEASONS["heating"], timeline=_delay_off("flush"))]),
    # Indoor dew 13.2 between 13.41 − 0.3 and 13.41: from off it stays off; from on (real
    # this.state after indoor 14) it stays on.
    ICase("flush_hysteresis_deadband_branch1_from_off",
          [IStep(_F | {"min_dew_diff": 0.5, "outdoor_dew": 12.5, "indoor_dew": 13.2},
                 {"flush": "off"})]),
    ICase("flush_hysteresis_deadband_branch1_from_on",
          [IStep(_F | {"min_dew_diff": 0.5, "outdoor_dew": 12.5, "indoor_dew": 14.0},
                 {"flush": "on"}),
           IStep(_F | {"min_dew_diff": 0.5, "outdoor_dew": 12.5, "indoor_dew": 13.2},
                 {"flush": "on"})]),
    # has_value guard: a missing input → unavailable at once (no delay); the decision too.
    ICase("flush_unavailable_when_dependency_missing",
          [IStep({"outdoor_dew": "unavailable"},
                 timeline=[(0, {"flush": "unavailable", "decision": "unavailable"})])]),
]


@pytest.mark.parametrize("cases", [FREE_CASES, MOIST_CASES, HEAT_CASES, FLUSH_CASES],
                         ids=["free_cooling", "moisture_low", "heat_low", "flush"])
async def test_indicator(airflow_ha: HomeAssistant, clock: Clock, cases: list[ICase]) -> None:
    """One indicator's cases on one fresh HA; every failing check is listed in the one assert."""
    failures = await _run_indicator_cases(airflow_ha, clock, cases, local_at(_workday(), 7, 1))
    assert not failures, f"{len(failures)} indicator check(s) failed:\n" + "\n".join(failures)


async def test_drying_needed(airflow_ha: HomeAssistant, clock: Clock) -> None:
    """binary_sensor.airflow_humidity_drying_needed through the real schedules and workday.

    Drying = flush needed AND smoothed weather station below target (+0.3 °C while on) AND in
    the boost schedule (workday 07:00-20:30, non-workday 09:00-20:30, chosen by the REAL
    binary_sensor.workday). No delay. One sequence, forward in time: a working Wednesday from
    05:30, then the next weekday public holiday. Replaces the Docker render tests
    `drying_requires_flush_needed`, `…_blocked_by_warm_weatherstation`,
    `…_fires_with_flush_and_cool_weatherstation` (a copy reading the RAW weather station, not
    its 5-min filter: drift) and the sensor tests `drying_schedule_off_sensor_not_triggered`,
    `drying_non_workday_schedule_applies_on_holiday` (it asserted "off" for a delay_on the
    sensor does not have; it passed because the template reads the filter, not the raw
    station it seeded). `drying_low_moisture_guard_prevents_boost` is dropped: the sensor no
    longer reads the moisture guard (removed from the config; flush gates the guard instead,
    see `new_low_needed_gated_off_by_flush`).
    """
    ha = airflow_ha
    workday = _workday()
    ids = await _start(ha, clock, local_at(workday, 5, 30))
    ids |= {"workday": "binary_sensor.workday", "window": "schedule.airflow_boost_workday",
            "window_off_day": "schedule.airflow_boost_non_workday"}
    failures: list[str] = []

    def check(where: str, **want: str) -> None:
        for key, value in want.items():
            if (got := _state(ha, ids[key])) != value:
                failures.append(f"{where}: {key} = {got!r}, want {value!r}")

    async def inputs(**overrides: Any) -> None:
        """Apply a scenario (reference + FLUSH-type overrides) and let it settle."""
        await _scenario(ha, clock, overrides)

    flush_cool = FLUSH | {"ws": 16.0}
    # Working day, before 07:00: flush on, station cool, but outside the window → off.
    await inputs(**flush_cool)
    check("workday 06:10, outside the window", flush="on", drying="off", workday="on",
          window="off")
    # 07:00 the workday window opens → on at once (the schedule is a trigger; no delay).
    await clock.move_to(local_at(workday, 7, 0, 30))
    check("workday 07:00, window opens", window="on", drying="on")
    # Station 22 °C ≥ target 21.5 (+0.3 while on) → off at once.
    await inputs(**flush_cool | {"ws": 22.0})
    check("station warm", flush="on", drying="off")
    # New: hysteresis 0.3 °C. 21.6 is below 21.8 but not below 21.5: off stays off …
    await inputs(**flush_cool | {"ws": 21.6})
    check("station 21.6 from off", drying="off")
    # … on (station 16) then 21.6 stays on.
    await inputs(**flush_cool)
    check("station 16", drying="on")
    await inputs(**flush_cool | {"ws": 21.6})
    check("station 21.6 from on", drying="on")
    # No flush (reference dew, station 16) → off once the flush has turned off.
    await inputs(ws=16.0)
    check("no flush", flush="off", drying="off")
    # Public holiday (workday off): non-workday window from 09:00 only.
    holiday = _holiday(workday)
    await clock.move_to(local_at(holiday, 8, 0))
    await inputs(**flush_cool)
    # The workday window is open on that weekday, but workday is off, so it does not count.
    check("holiday 08:20, before the non-workday window", workday="off", window="on",
          window_off_day="off", flush="on", drying="off")
    await clock.move_to(local_at(holiday, 9, 0, 30))
    check("holiday 09:00, non-workday window applies", window_off_day="on", drying="on")
    assert not failures, f"{len(failures)} drying check(s) failed:\n" + "\n".join(failures)


async def test_hvac_action(airflow_ha: HomeAssistant, clock: Clock) -> None:
    """climate.airflow_climate's hvac_action from the REAL decision and the device profile.

    Replaces the Docker render tests (a copy with the decision injected as a literal) and
    `hvac_action_template_matches_mirror` (a text check of the copy; no copy is left). The
    controller is switched off here, so the device profile is the seeded one and not the
    decided one ("not drying before the profile is applied").
    """
    ha = airflow_ha
    await ha.services.async_call("automation", "turn_off", {"entity_id": _CONTROLLER},
                                 blocking=True)
    ids = await _start(ha, clock, local_at(_workday(), 7, 1))
    failures: list[str] = []
    cases = [  # (name, scenario, device, decision state, expected hvac_action)
        ("hvac_action_drying_from_flush", FLUSH, {"profile": "cool"},
         "moisture_flush_cooling", "drying"),
        ("hvac_action_cooling_without_flush", FREE, {"profile": "cool"}, "free_cooling",
         "cooling"),
        # The re-arm blip: boost switch off for a moment while boost is decided.
        ("hvac_action_drying_survives_boost_blip", BOOST, {"profile": "cool", "boost": "off"},
         "moisture_flush_boost", "drying"),
        ("hvac_action_not_drying_before_profile_applied", FLUSH, {"profile": "comfort"},
         "moisture_flush_cooling", "fan"),
        # New: the other branches.
        ("new_hvac_action_heating", SEASONS["heating"], {"profile": "warm"}, "heating",
         "heating"),
        ("new_hvac_action_idle_without_profile", {}, {"profile": "unavailable"}, "comfort",
         "idle"),
    ]
    for name, scenario, device, decision, action in cases:
        await _auto(ha, False)
        await _device(ha, _DEVICE_REST)
        await _scenario(ha, clock)
        await _scenario(ha, clock, scenario)
        await _auto(ha, True)
        await _device(ha, device)
        if (got := _state(ha, ids["decision"])) != decision:
            failures.append(f"{name}: decision {got!r}, want {decision!r}")
        climate = ha.states.get("climate.airflow_climate")
        if (got := climate.attributes.get("hvac_action")) != action:
            failures.append(f"{name}: hvac_action {got!r}, want {action!r}")
    assert not failures, f"{len(failures)} hvac_action check(s) failed:\n" + "\n".join(failures)


@pytest.mark.allow_log(
    r"while processing template .*for attribute '_attr_native_value' in entity "
    r"'sensor\.solar_yield_watts'",
    reason="config finding: during template.reload the Victron η sensor is briefly "
    "unavailable and solar_yield_watts' `| float` without default logs a TemplateError "
    "(#155)",
)
async def test_reload_recovery(airflow_ha: HomeAssistant, clock: Clock) -> None:
    """The trigger-based indicators after a YAML reload, and their `to: unknown` self-trigger.

    Replaces the Docker `flush_needed_recomputes_after_reload_unknown` and
    `low_needed_recomputes_after_reload_unknown`, which simulated the reload by writing
    `unknown` over the entity. Here (1) a REAL `template.reload`: at the pin the entities come
    back RESTORED at once (CONFIRMED here; the YAML comments say a reload brings them back
    `unknown`), and (2) the Docker simulation: an `unknown` state fires the self-trigger,
    which recomputes the value from the inputs at once (the internal state still holds it).
    """
    ha = airflow_ha
    ids = await _start(ha, clock, local_at(_workday(), 7, 1))
    # Flush on, moisture low off (flush gates it), heat low off.
    await _scenario(ha, clock, FLUSH)
    want = {"flush": "on", "moist": "off", "heat": "off"}
    failures: list[str] = []

    def check(where: str) -> None:
        for key, value in want.items():
            if (got := _state(ha, ids[key])) != value:
                failures.append(f"{where}: {key} = {got!r}, want {value!r}")

    check("before")
    await ha.services.async_call("template", "reload", {}, blocking=True)
    await ha.async_block_till_done()
    check("right after template.reload")
    for key in ("flush", "moist", "heat"):
        ha.states.async_set(ids[key], "unknown")
        await ha.async_block_till_done()
    check("right after forcing unknown (self-trigger)")
    await clock.advance(_DELAY + 1)
    check("10 min later")
    assert not failures, f"{len(failures)} reload check(s) failed:\n" + "\n".join(failures)
