"""Airflow decision table, bypass estimation and dew-point thresholds, in-process.

Formula tables of packages/airflow_cooling.yaml and custom_templates/airflow_decision.jinja
(plans/test-execution.md, Step 2, migration item 2). Replaces these Docker tests of
tests/test_airflow.py: the 20 `test_decision_*`, the 6 `test_bypass_*` and the 2
`test_dew_point_*` (one case each, plus a few new cases, marked "new"). Controller, boost,
indicator (delay_on/off) and reload tests stay in the Docker file until item 4.

Three tests, ONE fresh HA each (tier 1 in the plan: no clock, no accumulators, real triggers
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

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from conftest import SeedValue, apply_baseline, entity_id, seed

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
