"""PV slab pre-charging formulas (packages/heating_pv_boost.yaml), in-process.

plans/test-execution.md, Step 2, migration item 3. Replaces 21 of the 25 Docker tests of
tests/test_heating_pv_boost.py: the surplus formula, the compressor activity and cycling
formulas, the cooling interlock and the derived setpoint. Four stay in Docker until item 4,
because they need the clock for a delay or a `last_changed` span: the hot-water return mask
(`heating_dhw_active` delay_off 25 min), the master-switch decision (`heating_slab_mode_wanted`
delay_off 20 min) and the two `heating_compressor_last_run` tests.

Four tests, ONE fresh HA each (tier 1: stateless formulas). Each loops over its cases: publish
and check a reset vector, then the case's inputs (optionally followed by further steps without
a reset), collect every failure, one assert at the end that names each failing case.

How the inputs get in (Step 2b: MQTT-fed entities only over the real broker):
- ebusd registers: plain `;`-separated payloads on `ebusd/<circuit>/<name>` (positional fields,
  names or raw enum numbers, as ebusd sends them), so the real value_templates parse them.
- Shelly Pro 3EM "Heizung": `em:0` / `emdata:0` JSON; Victron: Venus OS `{"value": x}`.
- "Unavailable" is a real `expire_after` (Clock), or a sensor that never got a message.
- Seeded (no real path without the clock, item 4): the η accumulators (trigger-based minute
  ticks, as in tests/ha/test_victron.py), the two `history_stats` sensors behind the average
  run, and the 48h outdoor mean (statistics over a filter, registry-dependent id #146) that
  drives the REAL heating/cooling indicator. The daily meters behind the efficiency are the
  REAL `utility_meter`s: reset with their own action, fed by the MQTT counters.
- The clock is frozen (`clock` fixture) in the tables that need an expiry, so nothing ticks
  between a seed and its check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    Clock,
    SeedValue,
    apply_baseline,
    check_states,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    seed,
    wait_subscribed,
)

_GX = "N/c0619ab4c19e"
_KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
_UNAV = is_state("unavailable")
_ON, _OFF = is_state("on"), is_state("off")


# ── Inputs: an MQTT topic, its sensor's expire_after, and the device payload ──────────────
@dataclass
class Input:
    """One MQTT-fed input: topic, expire_after of its sensor (None: no expiry), payload maker."""

    topic: str
    expire: int | None
    payload: Callable[[Any], Any]


def _venus(topic: str) -> Input:
    """A Victron Venus OS topic (expire_after 120 s for every power reading used here)."""
    return Input(f"{_GX}/{topic}", 120, lambda v: {"value": v})


def _em(watts: float) -> dict:
    """Shelly Pro 3EM `status/em:0` payload; the sensor reads `total_act_power` (W)."""
    third = round(watts / 3, 1)
    return {"id": 0, "a_act_power": third, "b_act_power": third, "c_act_power": third,
            "a_voltage": 231.2, "b_voltage": 230.8, "c_voltage": 231.5,
            "total_current": round(watts / 230, 3), "total_act_power": watts,
            "total_aprt_power": watts}


def _emdata(wh: float) -> dict:
    """Shelly Pro 3EM `status/emdata:0` payload; the sensor reads `total_act` (Wh → kWh)."""
    return {"id": 0, "a_total_act_energy": round(wh / 3, 2), "total_act": wh, "total_act_ret": 0.0}


def _ebus(topic: str) -> Input:
    """An ebusd register: the payload is the raw string ebusd publishes (no expire_after)."""
    return Input(f"ebusd/{topic}", None, str)


def _status(mode: str) -> str:
    """ehp/Status: HcFlowTemp;HcPress;SourcePress;hcmode;raw. Only field 3 (mode) varies."""
    return f"25.2;1.5;1.2;{mode};0a01"


_VICTRON = {
    "dc_pv": _venus("system/0/Dc/Pv/Power"),
    "ac_pv": _venus("pvinverter/20/Ac/Power"),
    "ac_l1": _venus("system/0/Ac/Consumption/L1/Power"),
    "ac_l2": _venus("system/0/Ac/Consumption/L2/Power"),
    "ac_l3": _venus("system/0/Ac/Consumption/L3/Power"),
}
_HEAT = Input("shelly/shellypro3em-heizung/status/em:0", 120, _em)
_HEAT_ENERGY = Input("shelly/shellypro3em-heizung/status/emdata:0", 120, _emdata)
_HVAC = Input("ebusd/ehp/Status", None, _status)


# ── Cases and the generic table runner ───────────────────────────────────────────────────
@dataclass
class Step:
    """A further step of a case, applied WITHOUT a reset on top of the previous step."""

    inputs: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Callable[[str], bool]] = field(default_factory=dict)
    seeds: dict[str, SeedValue] = field(default_factory=dict)
    expire: frozenset[str] = frozenset()


@dataclass
class Case(Step):
    """One case: inputs over the table defaults, seeds, expiries, expectations, more steps."""

    name: str = ""
    then: list[Step] = field(default_factory=list)


@dataclass
class Table:
    """Everything a table needs besides its cases.

    inputs: key → Input.  outputs: key → (domain, platform, unique_id), looked up per test.
    defaults: input values of every case before its overrides.
    reset / reset_seeds / reset_expect: the reset applied and checked before each case.
    published: maps a step's input values to the values actually published (e.g. counters).
    after_reset: an extra reset action (e.g. the utility_meter reset), before the reset check.
    """

    inputs: dict[str, Input]
    outputs: dict[str, tuple[str, str, str]]
    defaults: dict[str, Any]
    reset: dict[str, Any]
    reset_expect: dict[str, Callable[[str], bool]]
    reset_seeds: dict[str, SeedValue] = field(default_factory=dict)
    published: Callable[[dict[str, Any]], dict[str, Any]] = lambda values: values
    after_reset: Callable[[HomeAssistant, dict[str, str]], Awaitable[None]] | None = None


async def _publish_all(
    hass: HomeAssistant, broker: Broker, table: Table, values: Mapping[str, Any],
    skip: frozenset[str] = frozenset(),
) -> None:
    """Publish every input of the table (except `skip`) with its device payload."""
    for key, inp in table.inputs.items():
        if key not in skip:
            await publish(hass, broker, inp.topic, inp.payload(values[key]))


async def _seed_keys(
    hass: HomeAssistant, ids: dict[str, str], seeds: Mapping[str, SeedValue]
) -> None:
    """Seed by output key (resolved to its registry id) or by a literal entity id."""
    if seeds:
        await seed(hass, {ids.get(key, key): value for key, value in seeds.items()})


async def _apply(
    hass: HomeAssistant, broker: Broker, clock: Clock | None, table: Table, ids: dict[str, str],
    values: dict[str, Any], seeds: Mapping[str, SeedValue], expire: frozenset[str],
) -> None:
    """Publish one input vector, let the `expire` inputs expire for real, sync, then seed."""
    published = table.published(values)
    await _publish_all(hass, broker, table, published)
    if expire:
        # Every input was published at the same frozen instant, so all expire_after sensors
        # expire on the move; the ones that must stay live are republished afterwards. Sync
        # first: a message delivered after the move would re-arm its expiry on the moved clock.
        assert clock is not None, "an expiry case needs the frozen clock"
        await mqtt_sync(hass, broker)
        await clock.advance(max(table.inputs[k].expire or 0 for k in expire) + 1)
        await _publish_all(hass, broker, table, published, skip=expire)
    # Sync BEFORE seeding: the messages can start refreshes of entities a case seeds (a
    # history_stats sensor recomputes when its source flips), which would overwrite the seed.
    await mqtt_sync(hass, broker)
    await _seed_keys(hass, ids, seeds)


async def _run_table(
    hass: HomeAssistant, broker: Broker, clock: Clock | None, table: Table, cases: list[Case],
    ids: dict[str, str],
) -> list[str]:
    """Run every case of a table; return one message per failed check."""
    await wait_subscribed(hass, broker, *(inp.topic for inp in table.inputs.values()))
    failures: list[str] = []
    for case in cases:
        # Reset and prove it took (a failed reset is reported; the case still runs).
        await _apply(hass, broker, clock, table, ids, dict(table.reset), table.reset_seeds,
                     frozenset())
        if table.after_reset is not None:
            await table.after_reset(hass, ids)
        failures += check_states(hass, ids, table.reset_expect, f"{case.name} (reset)")
        # The case, then each further step on top of it.
        values = dict(table.defaults) | case.inputs
        await _apply(hass, broker, clock, table, ids, values, case.seeds, case.expire)
        failures += check_states(hass, ids, case.expect, case.name)
        for n, step in enumerate(case.then, start=2):
            values |= step.inputs
            await _apply(hass, broker, clock, table, ids, values, step.seeds, step.expire)
            failures += check_states(hass, ids, step.expect, f"{case.name} step {n}")
    return failures


def _ids(hass: HomeAssistant, outputs: Mapping[str, tuple[str, str, str]]) -> dict[str, str]:
    """Registry ids of a table's outputs (repo rule: never derive an id)."""
    return {key: entity_id(hass, *spec) for key, spec in outputs.items()}


def _load(watts: float) -> dict[str, float]:
    """Split a house load over the three phases with integers that sum exactly.

    The Docker test seeded load/3 per phase as floats; the MQTT sensors round to whole watts,
    so an equal float split would no longer sum to the load.
    """
    third = watts // 3
    return {"ac_l1": watts - 2 * third, "ac_l2": third, "ac_l3": third}


# ── 1. Surplus: sensor.heating_pv_surplus ────────────────────────────────────────────────
_SURPLUS_TABLE = Table(
    inputs=_VICTRON | {"heat": _HEAT},
    outputs={
        "surplus": ("sensor", "template", "heating_pv_surplus"),
        "solar": ("sensor", "template", "victron_solar_yield"),
        "ac_out_energy": ("sensor", "template", "victron_multiplus_ac_out_energy"),
        "dc_in_energy": ("sensor", "template", "victron_multiplus_dc_in_energy"),
    },
    defaults={"dc_pv": 0, "ac_pv": 0, **_load(0), "heat": 0},
    # Reset: solar 100 × η 0.7 = 70; net = 70 + 3 - 37 + 7 = 43; PV cap 73 → 43 (no case has 43).
    reset={"dc_pv": 100, "ac_pv": 3, **_load(37), "heat": 7},
    reset_seeds={"ac_out_energy": ("7.0", _KWH), "dc_in_energy": ("10.0", _KWH)},
    reset_expect={"surplus": near(43), "solar": near(70)},
)
# η 100 % bootstrap (Docker baseline 0.0 / 0.0) unless a case seeds otherwise.
_ETA_100 = {"ac_out_energy": ("0.0", _KWH), "dc_in_energy": ("0.0", _KWH)}
_ETA_90 = {"ac_out_energy": ("9.0", _KWH), "dc_in_energy": ("10.0", _KWH)}


def _flows(dc_pv: float, ac_pv: float, house_load: float, heating: float) -> dict[str, float]:
    """The four inputs of the surplus formula (Docker `_seed_power_flows`)."""
    return {"dc_pv": dc_pv, "ac_pv": ac_pv, **_load(house_load), "heat": heating}


# One case per former Docker test (same names, same values), plus one new.
SURPLUS_CASES = [
    # PV 4000, house 2500 of which heat pump 1500 → 3000, not 1500.
    Case(name="surplus_excludes_the_heat_pumps_own_draw", inputs=_flows(3000, 1000, 2500, 1500),
         seeds=_ETA_100, expect={"surplus": near(3000)}),
    # MPPT 4000 W DC at η 90 % → 3600 AC; (3600 + 1000) - (2500 - 1500) = 3600.
    Case(name="surplus_uses_ac_referenced_mppt_not_raw_dc", inputs=_flows(4000, 1000, 2500, 1500),
         seeds=_ETA_90, expect={"solar": near(3600), "surplus": near(3600)}),
    # A boost starting (+2000 W on the clamp and the house total) must not move the surplus.
    Case(name="surplus_is_unchanged_when_only_the_heat_pump_draw_changes",
         inputs=_flows(4000, 0, 1000, 0), seeds=_ETA_100, expect={"surplus": near(3000)},
         then=[Step(inputs=_flows(4000, 0, 3000, 2000), expect={"surplus": near(3000)})]),
    # PV 2000, house 2500 incl. 1500 heating → 1000 (the signed net keeps the deficit).
    Case(name="surplus_keeps_the_deficit_when_adding_the_heat_pump_back",
         inputs=_flows(2000, 0, 2500, 1500), seeds=_ETA_100, expect={"surplus": near(1000)}),
    Case(name="surplus_clamps_at_zero", inputs=_flows(500, 0, 2500, 1500), seeds=_ETA_100,
         expect={"surplus": near(0)}),
    # GX outage: the load phases expire → a gap, not a false "no surplus".
    Case(name="surplus_propagates_unavailable_when_no_victron_load_data", seeds=_ETA_100,
         expire=frozenset({"ac_l1", "ac_l2", "ac_l3"}), expect={"surplus": _UNAV}),
    Case(name="surplus_is_zero_not_negative_without_sun", inputs=_flows(0, 0, 500, 0),
         seeds=_ETA_100, expect={"surplus": near(0)}),
    # The AC inverter sleeps (its sensor expires) → 0, not unavailable.
    Case(name="surplus_is_zero_when_inverter_sensor_unavailable", inputs=_flows(11, 0, 500, 80),
         seeds=_ETA_100, expire=frozenset({"ac_pv"}), expect={"surplus": near(0)}),
    # Live 2026-10-17: the clamp leads the Victron load at a night start; capped at PV (0).
    Case(name="surplus_is_zero_at_night_even_when_heater_leads_the_victron_load",
         inputs=_flows(0, 0, 500, 1562), seeds=_ETA_100, expect={"surplus": near(0)}),
    Case(name="surplus_never_exceeds_pv_generation", inputs=_flows(1000, 0, 500, 1800),
         seeds=_ETA_100, expect={"surplus": near(1000)}),
    # New: the heating clamp's own sensor expires (expire_after 120) → unavailable.
    Case(name="surplus_unavailable_when_the_heating_clamp_expires",
         inputs=_flows(2000, 0, 500, 300), seeds=_ETA_100, expire=frozenset({"heat"}),
         expect={"surplus": _UNAV}),
]


async def test_surplus_table(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """All surplus cases on one HA; every failing case is listed in the one assert."""
    # The templates read the clamp under its production id. It has no default_entity_id; a
    # fresh registry derives the same id (area + device + name), checked here so a drift shows
    # as one clear message instead of every case failing.
    assert entity_id(ha, "sensor", "mqtt", "shelly_pro3em_heizung_power") == (
        "sensor.technikraum_heizung_heizung_power"
    )
    failures = await _run_table(ha, broker, clock, _SURPLUS_TABLE, SURPLUS_CASES,
                                _ids(ha, _SURPLUS_TABLE.outputs))
    assert not failures, f"{len(failures)} surplus check(s) failed:\n" + "\n".join(failures)


# ── 2. Compressor activity and cycling formulas ──────────────────────────────────────────
# Counters behind the two daily utility meters. They only ever grow (as on the device); a case
# gives increments (`yield_inc` kWh, `elec_inc` kWh), turned into absolute counters here.
_COUNTERS = {"yield": 60000, "elec_wh": 1_000_000.0}


def _counters(values: dict[str, Any]) -> dict[str, Any]:
    """Advance the device counters by a step's increments; publish the absolute values.

    Called once per step (`Table.published`), so a republish after an expiry sends the same
    values again instead of adding twice.
    """
    _COUNTERS["yield"] += values["yield_inc"]
    _COUNTERS["elec_wh"] += values["elec_inc"] * 1000
    return values | {"yield": _COUNTERS["yield"], "elec_wh": _COUNTERS["elec_wh"]}


async def _reset_meters(hass: HomeAssistant, ids: dict[str, str]) -> None:
    """Reset both daily meters with the real utility_meter action (as the midnight reset does)."""
    await hass.services.async_call(
        "utility_meter", "reset", {"entity_id": [ids["yield_daily"], ids["elec_daily"]]},
        blocking=True,
    )
    await hass.async_block_till_done()


_H = {"unit_of_measurement": "h"}
_COMPRESSOR_TABLE = Table(
    inputs={
        "heat": _HEAT,
        "hvac": _HVAC,
        "flow_desired": Input("ebusd/mc/Status0a", None,
                              lambda t: f"27.5;45;on;on;{t}"),  # field 4 = flow setpoint
        "hysteresis": _ebus("ehp/CompHysteresis"),
        "yield": Input("ebusd/ehp/YieldTotal", None, lambda kwh: str(int(kwh))),
        "elec_wh": _HEAT_ENERGY,
    },
    outputs={
        "compressor": ("binary_sensor", "template", "heating_compressor_active"),
        "heating": ("binary_sensor", "template", "heating_compressor_heating_active"),
        "average": ("sensor", "template", "heating_compressor_average_run_today"),
        "runs": ("sensor", "history_stats", "heating_compressor_runs_today"),
        "runtime": ("sensor", "history_stats", "heating_compressor_runtime_today"),
        "stop_temp": ("sensor", "template", "heating_compressor_stop_temp"),
        # utility_meter registers its single-tariff sensor under `<unique_id>_single_tariff`.
        "yield_daily": ("sensor", "utility_meter", "heating_yield_daily_single_tariff"),
        "elec_daily": ("sensor", "utility_meter", "heating_electricity_daily_single_tariff"),
        "efficiency": ("sensor", "template", "heating_efficiency_today"),
    },
    defaults={"heat": 83, "hvac": "heat", "flow_desired": 26, "hysteresis": "7.0",
              "yield_inc": 0, "elec_inc": 0},
    # Reset: clamp 1000 W (running; the clamp case starts from "off"), mode raw 7 (an unmapped
    # enum → `unknown`, so the heating-only sensor is unavailable, which no case expects),
    # stop 20 + 5 = 25, average 0.5 h / 1 run = 30 min, meters reset to 0.
    reset={"heat": 1000, "hvac": "7", "flow_desired": 20, "hysteresis": "5.0",
           "yield_inc": 0, "elec_inc": 0},
    reset_seeds={"runtime": ("0.5", _H), "runs": ("1", {})},
    reset_expect={"compressor": _ON, "heating": _UNAV, "stop_temp": near(25),
                  "average": near(30), "yield_daily": near(0), "elec_daily": near(0)},
    published=_counters,
    after_reset=_reset_meters,
)

COMPRESSOR_CASES = [
    # ~83 W idle circulation → off; ~1.8 kW run → on; the clamp expires → unavailable.
    Case(name="compressor_active_follows_the_shelly_clamp", inputs={"heat": 83},
         expect={"compressor": _OFF},
         then=[Step(inputs={"heat": 1800}, expect={"compressor": _ON}),
               Step(expire=frozenset({"heat"}), expect={"compressor": _UNAV})]),
    Case(name="heating_active_is_on_for_a_heating_run", inputs={"hvac": "heat", "heat": 1800},
         expect={"heating": _ON}),
    # Heating → hot-water roll-over (hcmode raw 4 = water): all-runs on, heating-only off.
    Case(name="heating_active_is_off_for_a_hot_water_run", inputs={"hvac": "heat", "heat": 1800},
         expect={"heating": _ON},
         then=[Step(inputs={"hvac": "4", "heat": 3500},
                    expect={"compressor": _ON, "heating": _OFF})]),
    # Idle circulation in heating mode (hcmode raw 3 = heat) is not a run.
    Case(name="heating_active_is_off_when_the_compressor_is_off", inputs={"hvac": "3", "heat": 83},
         expect={"heating": _OFF}),
    # 4 runs in 1.0 h → 15 min; no runs → 0, not a division error.
    Case(name="average_run_is_runtime_over_runs",
         seeds={"runtime": ("1.0", _H), "runs": ("4", {})}, expect={"average": near(15)},
         then=[Step(seeds={"runtime": ("0.0", _H), "runs": ("0", {})},
                    expect={"average": near(0)})]),
    # Live 2026-10-30: setpoint 24 °C + hysteresis 7 K → forced stop at 31 °C.
    Case(name="stop_temp_is_flow_setpoint_plus_hysteresis",
         inputs={"flow_desired": 24, "hysteresis": "7.0"}, expect={"stop_temp": near(31)}),
    # 9 kWh heat from 3 kWh electricity → 3.0; under 1 kWh electricity → 0 (too coarse).
    Case(name="efficiency_is_heat_over_electricity_once_meaningful",
         inputs={"yield_inc": 9, "elec_inc": 3},
         expect={"yield_daily": near(9), "elec_daily": near(3), "efficiency": near(3.0)}),
    Case(name="efficiency_is_zero_under_one_kwh_electricity",
         inputs={"yield_inc": 9, "elec_inc": 0.5},
         expect={"yield_daily": near(9), "elec_daily": near(0.5), "efficiency": near(0)}),
]
# The Docker average-run and efficiency tests had two steps each: the average one is a case with
# a step; the efficiency one is two cases (its 2nd step changed only the electricity).


async def test_compressor_table(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """All compressor/cycling cases on one HA; every failing case is listed in the one assert."""
    ids = _ids(ha, _COMPRESSOR_TABLE.outputs)
    failures: list[str] = []
    topics = [inp.topic for inp in _COMPRESSOR_TABLE.inputs.values()]
    await wait_subscribed(ha, broker, *topics)
    # Startup phase (Docker `stop_temp…`, its "missing input" step): ebusd registers have no
    # expire_after, so "missing" is a register that never arrived (unknown), as after a restart
    # before the first poll. The setpoint is there, the hysteresis is not → unavailable.
    await publish(ha, broker, _COMPRESSOR_TABLE.inputs["flow_desired"].topic, "27.5;45;on;on;24")
    await mqtt_sync(ha, broker)
    failures += check_states(ha, ids, {"stop_temp": _UNAV},
                             "stop_temp_is_unavailable_while_the_hysteresis_is_missing")
    # First counter values initialise the two meters (the first reading only sets the start).
    await _publish_all(ha, broker, _COMPRESSOR_TABLE, _counters(dict(_COMPRESSOR_TABLE.reset)))
    await mqtt_sync(ha, broker)
    failures += await _run_table(ha, broker, clock, _COMPRESSOR_TABLE, COMPRESSOR_CASES, ids)
    # Leave the history_stats source unavailable (reset mode = unmapped enum): HA's shutdown
    # would otherwise flip it, and the history_stats refresh that follows would query the
    # recorder after it stopped ("cannot schedule new futures after shutdown" at teardown).
    await _publish_all(ha, broker, _COMPRESSOR_TABLE, _counters(dict(_COMPRESSOR_TABLE.reset)))
    await mqtt_sync(ha, broker)
    assert not failures, f"{len(failures)} compressor check(s) failed:\n" + "\n".join(failures)


# ── 3. Cooling interlock: binary_sensor.heating_cooling_active ───────────────────────────
_COOLING_TABLE = Table(
    inputs={
        "hvac": _HVAC,
        "demand": _ebus("uih/CoolingDemand"),
        "request": _ebus("mc/CoolingRequestHc2"),
        "uih": _ebus("uih/CoolingActive"),
    },
    outputs={"cooling": ("binary_sensor", "template", "heating_cooling_active")},
    defaults={"hvac": "off", "demand": "0", "request": "off", "uih": "no"},
    # Reset: every signal on, so each case's first step ("all off → off") is a real change.
    reset={"hvac": "cooling", "demand": "1", "request": "on", "uih": "yes"},
    reset_expect={"cooling": _ON},
)
# Every case: all four signals off → off, then one signal → on. The first is the Docker test;
# the other four are new (each signal alone, and the raw enum number for cooling).
COOLING_CASES = [
    Case(name="cooling_interlock_follows_the_machine_not_the_setting", expect={"cooling": _OFF},
         then=[Step(inputs={"hvac": "cooling"}, expect={"cooling": _ON})]),
    Case(name="cooling_interlock_hvac_action_raw_number", expect={"cooling": _OFF},
         then=[Step(inputs={"hvac": "1"}, expect={"cooling": _ON})]),
    Case(name="cooling_interlock_cooling_demand", expect={"cooling": _OFF},
         then=[Step(inputs={"demand": "1"}, expect={"cooling": _ON})]),
    Case(name="cooling_interlock_cooling_request", expect={"cooling": _OFF},
         then=[Step(inputs={"request": "on"}, expect={"cooling": _ON})]),
    Case(name="cooling_interlock_uih_cooling_active", expect={"cooling": _OFF},
         then=[Step(inputs={"uih": "true"}, expect={"cooling": _ON})]),
]


async def test_cooling_interlock(ha: HomeAssistant, broker: Broker) -> None:
    """All interlock cases on one HA; every failing case is listed in the one assert."""
    failures = await _run_table(ha, broker, None, _COOLING_TABLE, COOLING_CASES,
                                _ids(ha, _COOLING_TABLE.outputs))
    assert not failures, f"{len(failures)} interlock check(s) failed:\n" + "\n".join(failures)


# ── 4. Derived setpoint: sensor.heating_target_temp ──────────────────────────────────────
# The season is the REAL sensor.heating_cooling_indicator, driven through its seeded 48h mean
# (thresholds 12 / 16 / 20 from the baseline). Pinning the indicator instead would make its
# self-referencing template walk back (ha-test-harness skill). One mean per season, reached
# from neutral in at most two steps; the reset goes back to neutral first.
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_C = {"unit_of_measurement": "°C", "device_class": "temperature"}


def _mean(value: float) -> dict[str, SeedValue]:
    """Seed of the 48h mean (non-MQTT source, see the module docstring)."""
    return {_MEAN: (str(value), _C)}


_TARGET_TABLE = Table(
    inputs={"setback": _ebus("mc/TempDesiredLow")},
    outputs={
        "target": ("sensor", "template", "heating_target_temp"),
        "season_active": ("binary_sensor", "template", "heating_season_active"),
        "indicator": ("sensor", "template", "heating_cooling_indicator"),
    },
    defaults={"setback": "21.0"},
    # Reset: setback 18.0 in neutral → 19.0, a target no case expects.
    reset={"setback": "18.0"},
    reset_seeds=_mean(14.0),
    reset_expect={"indicator": is_state("neutral"), "target": near(19.0)},
)
# One case per former Docker test (same names, same values).
TARGET_CASES = [
    # Neutral counts as heating season → TempDesiredLow + 1.
    Case(name="target_temp_is_setback_plus_one_in_heating_season", seeds=_mean(14.0),
         expect={"indicator": is_state("neutral"), "target": near(22.0)}),
    # Out of season the setpoint collapses onto the setback (neutral → active_cooling, 2 steps).
    Case(name="target_temp_falls_back_to_setback_out_of_season", seeds=_mean(22.0),
         expect={"indicator": is_state("active_cooling"), "season_active": _OFF,
                 "target": near(21.0)}),
    # The only human knob: a changed setback moves the setpoint (neutral → active_heating).
    Case(name="target_temp_tracks_a_changed_setback", inputs={"setback": "20.0"},
         seeds=_mean(8.0), expect={"indicator": is_state("active_heating"),
                                   "target": near(21.0)}),
]


async def test_target_temp(ha: HomeAssistant, broker: Broker) -> None:
    """All setpoint cases on one HA; every failing case is listed in the one assert."""
    # Helpers (indicator thresholds, boost offset, boost switch off) and the non-MQTT baseline.
    await apply_baseline(ha, mqtt=False)
    failures = await _run_table(ha, broker, None, _TARGET_TABLE, TARGET_CASES,
                                _ids(ha, _TARGET_TABLE.outputs))
    assert not failures, f"{len(failures)} setpoint check(s) failed:\n" + "\n".join(failures)
