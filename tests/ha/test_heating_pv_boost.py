"""PV slab pre-charging (packages/heating_pv_boost.yaml), in-process.

Tables 1-4: the surplus formula, the compressor activity and cycling formulas, the cooling
interlock and the derived setpoint. Section 5 needs the clock: the hot-water return mask
(`heating_dhw_active` delay_off 25 min), the master-switch decision (`heating_slab_mode_wanted`
delay_on 15 / delay_off 20 min), `heating_compressor_last_run` (a `last_changed` span), the
REAL history_stats sensors (recorder) and the daily utility meters' midnight reset.

Tables 1-4: ONE fresh HA each (stateless formulas). Each loops over its cases: publish
and check a reset vector, then the case's inputs (optionally followed by further steps without
a reset), collect every failure, one assert at the end that names each failing case.
Section 5: ONE fresh HA per test (delays, spans, recorder history, meter cycles), the
steps in order on a frozen clock; every check is collected, one assert at the end.

How the inputs get in (MQTT-fed entities only over the real broker):
- ebusd registers: plain `;`-separated payloads on `ebusd/<circuit>/<name>` (positional fields,
  names or raw enum numbers, as ebusd sends them), so the real value_templates parse them.
- Shelly Pro 3EM "Heizung": `em:0` / `emdata:0` JSON; Victron: Venus OS `{"value": x}`.
- "Unavailable" is a real `expire_after` (Clock), or a sensor that never got a message.
- Seeded (no real source in the test HA): the 48h outdoor mean (statistics over a filter,
  registry-dependent id #146) that drives the REAL heating/cooling indicator. In tables 1-2
  also the η accumulators (as in tests/ha/test_victron.py's table) and the two history_stats
  sensors behind the average run; section 5 has them real. The daily meters are the REAL
  `utility_meter`s: reset with their own action in table 2, by their midnight cycle in
  section 5.
- The clock is frozen (`clock` fixture) in the tests that need an expiry or a delay, so
  nothing ticks between a step and its check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from conftest import (
    Broker,
    Clock,
    SeedValue,
    apply_baseline,
    check_states,
    entity_id,
    is_state,
    local_at,
    mqtt_sync,
    near,
    next_day,
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
# Energy-mode inputs: ehp/Comp and ehp/Hc1Pump, plain on/off registers (no expire_after).
_COMP = _ebus("ehp/Comp")
_PUMP = _ebus("ehp/Hc1Pump")


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


# The surplus reads the REAL Victron templates (solar yield, η accumulators, PV net power), fed by
# Victron MQTT topics: a change to victron.yaml can fail this test, so it also runs under
# `--package victron`.
@pytest.mark.package("victron")
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
        "comp": _COMP,
        "pump": _PUMP,
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
    defaults={"heat": 83, "hvac": "heat", "comp": "off", "pump": "on", "flow_desired": 26,
              "hysteresis": "7.0", "yield_inc": 0, "elec_inc": 0},
    # Reset: clamp 1000 W (running; the clamp case starts from "off"), compressor on, mode raw 7
    # (an unmapped enum → `unknown`, so the energy mode and the heating-only sensor are
    # unavailable, which no case expects), stop 20 + 5 = 25, average 0.5 h / 1 run = 30 min,
    # meters reset to 0.
    reset={"heat": 1000, "hvac": "7", "comp": "on", "pump": "on", "flow_desired": 20,
           "hysteresis": "5.0", "yield_inc": 0, "elec_inc": 0},
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
    # The heating-only run sensor follows ehp/Comp (through the energy mode), not the clamp.
    Case(name="heating_active_is_on_for_a_heating_run",
         inputs={"hvac": "heat", "comp": "on", "heat": 1800}, expect={"heating": _ON}),
    # Heating → hot-water roll-over (hcmode raw 4 = water): all-runs on, heating-only off.
    Case(name="heating_active_is_off_for_a_hot_water_run",
         inputs={"hvac": "heat", "comp": "on", "heat": 1800}, expect={"heating": _ON},
         then=[Step(inputs={"hvac": "4", "heat": 3500},
                    expect={"compressor": _ON, "heating": _OFF})]),
    # Pump only in heating mode (hcmode raw 3 = heat) is not a run.
    Case(name="heating_active_is_off_when_the_compressor_is_off",
         inputs={"hvac": "3", "comp": "off", "heat": 83}, expect={"heating": _OFF}),
    # A clamp dropout mid-run does not end the run: ehp/Comp still says on.
    Case(name="heating_active_ignores_a_clamp_dropout",
         inputs={"hvac": "heat", "comp": "on", "heat": 1800}, expect={"heating": _ON},
         then=[Step(expire=frozenset({"heat"}), expect={"compressor": _UNAV, "heating": _ON})]),
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


# The season comes from the REAL heating_cooling_indicator (seeded 48h mean): also runs under
# `--package heating_cooling_indicator`.
@pytest.mark.package("heating_cooling_indicator")
async def test_cooling_interlock(ha: HomeAssistant, broker: Broker) -> None:
    """All interlock cases on one HA; every failing case is listed in the one assert."""
    failures = await _run_table(ha, broker, None, _COOLING_TABLE, COOLING_CASES,
                                _ids(ha, _COOLING_TABLE.outputs))
    assert not failures, f"{len(failures)} interlock check(s) failed:\n" + "\n".join(failures)


# ── 3b. Energy mode: sensor.heating_energy_mode ──────────────────────────────────────────
_MODE_TABLE = Table(
    inputs={"comp": _COMP, "pump": _PUMP, "hvac": _HVAC},
    outputs={"mode": ("sensor", "template", "heating_energy_mode")},
    defaults={"comp": "off", "pump": "off", "hvac": "heat"},
    # Reset: hcmode raw 7 (unmapped → unknown) makes the mode unavailable, which no case expects.
    reset={"comp": "on", "pump": "on", "hvac": "7"},
    reset_expect={"mode": _UNAV},
)
_MODE = {m: is_state(m) for m in
         ("active_heating", "passive_heating", "water_heating", "cooling", "off")}
# One case per row of the mode table (first match wins), the row order, raw enum numbers and
# ebusd's raw on/off numbers. → doc/heating_pv_boost/notes.md "Energy modes"
MODE_CASES = [
    Case(name="compressor_heating_is_active_heating", inputs={"comp": "on", "pump": "on"},
         expect={"mode": _MODE["active_heating"]}),
    Case(name="compressor_hot_water_is_water_heating",
         inputs={"comp": "on", "pump": "on", "hvac": "water"},
         expect={"mode": _MODE["water_heating"]}),
    Case(name="compressor_hot_water_raw_enum", inputs={"comp": "on", "hvac": "4"},
         expect={"mode": _MODE["water_heating"]}),
    Case(name="pump_only_is_passive_heating", inputs={"pump": "on"},
         expect={"mode": _MODE["passive_heating"]}),
    Case(name="pump_only_in_hot_water_is_the_run_on", inputs={"pump": "on", "hvac": "water"},
         expect={"mode": _MODE["water_heating"]}),
    Case(name="pump_while_cooling_is_cooling", inputs={"pump": "on", "hvac": "cooling"},
         expect={"mode": _MODE["cooling"]}),
    Case(name="pump_while_cooling_raw_enum", inputs={"pump": "on", "hvac": "1"},
         expect={"mode": _MODE["cooling"]}),
    Case(name="nothing_running_is_off", expect={"mode": _MODE["off"]}),
    Case(name="cooling_without_pump_is_off", inputs={"hvac": "cooling"},
         expect={"mode": _MODE["off"]}),
    # Row order: the compressor wins over the cooling indicator (passive cooling never runs it).
    Case(name="compressor_wins_over_cooling", inputs={"comp": "on", "pump": "on", "hvac": "cooling"},
         expect={"mode": _MODE["active_heating"]}),
    # ebusd raw numbers for on/off; an unrecognised payload is ignored (last value kept).
    Case(name="raw_numbers_and_garbage", inputs={"comp": "1", "pump": "0"},
         expect={"mode": _MODE["active_heating"]},
         then=[Step(inputs={"comp": "n/a"}, expect={"mode": _MODE["active_heating"]}),
               Step(inputs={"comp": "0"}, expect={"mode": _MODE["off"]})]),
]


async def test_energy_mode(ha: HomeAssistant, broker: Broker) -> None:
    """All energy-mode cases on one HA; every failing case is listed in the one assert."""
    failures = await _run_table(ha, broker, None, _MODE_TABLE, MODE_CASES,
                                _ids(ha, _MODE_TABLE.outputs))
    assert not failures, f"{len(failures)} energy-mode check(s) failed:\n" + "\n".join(failures)


# Tariff meter outputs: (sensor, utility_meter, "<meter unique_id>_<tariff>").
_TARIFFS = ("active_heating", "passive_heating", "water_heating", "cooling", "off")


def _tariff_ids(hass: HomeAssistant, meter: str) -> dict[str, str]:
    """Registry ids of one per-mode meter's tariff sensors, keyed by tariff."""
    return {t: entity_id(hass, "sensor", "utility_meter", f"{meter}_{t}") for t in _TARIFFS}


async def test_energy_split_by_mode(ha: HomeAssistant, broker: Broker) -> None:
    """Electricity and yield are booked to the energy mode active when each increment arrives.

    New. Real chain: ebusd/Shelly payloads → energy mode → the tariff automation → the two
    tariff `utility_meter`s → the two per-mode efficiencies (and the combined one). One step
    per mode, each adding electricity (Shelly `emdata:0`, Wh) and yield (`YieldTotal`, kWh):
    passive 0.2 kWh / 0; active 2.0 / 6; water 1.0 / 3; hot-water run-on 0.01 / 0;
    cooling 0.3 / 0; off 0.05 / 0. Space heating = 6 / 2.2, hot water = 3 / 1.01.
    """
    yield_in = _COMPRESSOR_TABLE.inputs["yield"]
    elec = _tariff_ids(ha, "heating_electricity_by_mode")
    heat = _tariff_ids(ha, "heating_yield_by_mode")
    ids = {f"elec_{t}": e for t, e in elec.items()} | {f"yield_{t}": e for t, e in heat.items()}
    ids |= {"mode": entity_id(ha, "sensor", "template", "heating_energy_mode"),
            "select_elec": "select.heating_electricity_by_mode",
            "select_yield": "select.heating_yield_by_mode",
            "space": entity_id(ha, "sensor", "template", "space_heating_efficiency_today"),
            "dhw": entity_id(ha, "sensor", "template", "hot_water_efficiency_today"),
            "combined": entity_id(ha, "sensor", "template", "heating_efficiency_today")}
    await wait_subscribed(ha, broker, _COMP.topic, _PUMP.topic, _HVAC.topic, yield_in.topic,
                          _HEAT_ENERGY.topic)
    failures: list[str] = []
    counters = {"wh": 1_000_000.0, "kwh": 60000}

    async def step(where: str, comp: str, pump: str, hvac: str, elec_kwh: float, yield_kwh: int,
                   mode: str) -> None:
        """Set the mode, check the tariff switched, then add the step's energy."""
        await _send(ha, broker, (_COMP, comp), (_PUMP, pump), (_HVAC, hvac))
        failures.extend(check_states(ha, ids, {"mode": is_state(mode),
                                               "select_elec": is_state(mode),
                                               "select_yield": is_state(mode)}, where))
        counters["wh"] += elec_kwh * 1000
        counters["kwh"] += yield_kwh
        await _send(ha, broker, (_HEAT_ENERGY, counters["wh"]), (yield_in, counters["kwh"]))

    # First readings only initialise the meters (all tariffs start at 0).
    await _send(ha, broker, (_HEAT_ENERGY, counters["wh"]), (yield_in, counters["kwh"]))
    await step("passive heating", "off", "on", "heat", 0.2, 0, "passive_heating")
    await step("active heating", "on", "on", "heat", 2.0, 6, "active_heating")
    await step("water heating", "on", "on", "water", 1.0, 3, "water_heating")
    await step("hot-water run-on", "off", "on", "water", 0.01, 0, "water_heating")
    await step("cooling", "off", "on", "cooling", 0.3, 0, "cooling")
    await step("off", "off", "off", "off", 0.05, 0, "off")
    want = {"elec_active_heating": near(2.0), "elec_passive_heating": near(0.2),
            "elec_water_heating": near(1.01), "elec_cooling": near(0.3), "elec_off": near(0.05),
            "yield_active_heating": near(6), "yield_water_heating": near(3),
            "yield_passive_heating": near(0), "yield_cooling": near(0), "yield_off": near(0),
            "space": near(round(6 / 2.2, 2)), "dhw": near(round(3 / 1.01, 2)),
            "combined": near(round(9 / 3.56, 2))}
    failures.extend(check_states(ha, ids, want, "after all modes"))
    assert not failures, f"{len(failures)} energy-split check(s) failed:\n" + "\n".join(failures)


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


# The season comes from the REAL heating_cooling_indicator (seeded 48h mean): also runs under
# `--package heating_cooling_indicator`.
@pytest.mark.package("heating_cooling_indicator")
async def test_target_temp(ha: HomeAssistant, broker: Broker) -> None:
    """All setpoint cases on one HA; every failing case is listed in the one assert."""
    # Helpers (indicator thresholds, boost offset, boost switch off) and the non-MQTT baseline.
    await apply_baseline(ha, mqtt=False)
    failures = await _run_table(ha, broker, None, _TARGET_TABLE, TARGET_CASES,
                                _ids(ha, _TARGET_TABLE.outputs))
    assert not failures, f"{len(failures)} setpoint check(s) failed:\n" + "\n".join(failures)


# ── 5. Clock-dependent sensors ───────────────────────────────────────────────────────────
# Each test is ONE fresh HA (delays, `last_changed` spans, recorder history, meters).
# The clock is frozen right after start (`clock` fixture) and moved explicitly, so every delay
# and span is exact. Inputs that expire (Shelly/Victron power, 120 s) are republished during
# long waits, as the devices do (`Clock.hold`).
_RETURN = Input("ebusd/ehp/HcReturnTemp", None, lambda t: f"{t};ok")  # field 1 = sensor status
_HWC = Input("ebusd/hwc/Status", None, lambda on: f"50;{on};48;50")  # field 1 = DHW circuit
_SOC = _venus("system/0/Dc/Battery/Soc")


async def _send(hass: HomeAssistant, broker: Broker, *values: tuple[Input, Any]) -> None:
    """Publish each (input, value) as its device payload, then wait until HA handled them all."""
    for inp, value in values:
        await publish(hass, broker, inp.topic, inp.payload(value))
    await mqtt_sync(hass, broker)


def _state(hass: HomeAssistant, eid: str) -> str | None:
    """Current state string of an entity (None if it does not exist)."""
    s = hass.states.get(eid)
    return s.state if s else None


async def test_dhw_mask(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Hot-water charging masks the return temperature, held 25 min after it ends (delay_off).

    Replaces the Docker `test_return_temp_is_masked_while_making_hot_water`, which checked only
    the mask going on. Here every edge of `binary_sensor.heating_dhw_active` is checked: both
    sources (hcmode `water`, `hwc/Status` on) and the exact 25 min delay_off (still on at 24 min,
    off after 25 min). The valid-return sensor follows the mask.
    """
    dhw = entity_id(ha, "binary_sensor", "template", "heating_dhw_active")
    valid = entity_id(ha, "sensor", "template", "heating_circuit_return_temp_valid")
    await wait_subscribed(ha, broker, _RETURN.topic, _HVAC.topic, _HWC.topic)
    failures: list[str] = []

    def check(where: str, want_dhw: str, want_valid: Callable[[str], bool]) -> None:
        """Record a failure unless the mask and the valid return show the wanted states."""
        failures.extend(check_states(ha, {"dhw": dhw, "valid": valid},
                                     {"dhw": is_state(want_dhw), "valid": want_valid}, where))

    # Start: no hot water, return 24.9 °C. The mask's boot render (false) went through the
    # 25 min delay_off from no state; the `clock` fixture fired that boot timer (see its
    # docstring), so the mask is already off here. (The Docker test needed a 26 min jump first.)
    await _send(ha, broker, (_RETURN, 24.9), (_HVAC, "heat"), (_HWC, "off"))
    check("start: no hot water", "off", near(24.9))

    # Source 1, hcmode `water`: the mask goes on at once (no delay_on) …
    await _send(ha, broker, (_HVAC, "water"))
    check("hcmode water masks at once", "on", _UNAV)
    # … and holds through the thermal tail: still on 24 min after the charge, off after 25.
    await _send(ha, broker, (_HVAC, "heat"))
    await clock.advance(24 * 60)
    check("hcmode heat: mask still held at 24 min", "on", _UNAV)
    await clock.advance(61)
    check("hcmode heat: mask released after 25 min", "off", near(24.9))

    # Source 2, the DHW circuit (`hwc/Status` field 1) alone, same delay_off.
    await _send(ha, broker, (_HWC, "on"))
    check("hwc on masks at once", "on", _UNAV)
    await _send(ha, broker, (_HWC, "off"), (_RETURN, 26.1))
    await clock.advance(24 * 60)
    check("hwc off: mask still held at 24 min", "on", _UNAV)
    await clock.advance(61)
    check("hwc off: mask released after 25 min", "off", near(26.1))
    assert not failures, f"{len(failures)} DHW mask check(s) failed:\n" + "\n".join(failures)


# The slab decision's inputs, all live: PV and house load (Victron), the heating clamp, the
# battery SOC, and ehp/Status (hcmode + the flow temperature that proves ebusd is online).
_SLAB_HELPERS = {
    "input_number.heating_pv_surplus_threshold": 1500,
    "input_number.heating_pv_deficit_threshold": 500,
    "input_number.heating_pv_min_battery_soc": 70,
    "input_number.heating_return_temp_max": 30,
    "input_number.heating_indicator_heating_below": 12,
    "input_number.heating_indicator_passive_cooling_above": 16,
    "input_number.heating_indicator_active_cooling_above": 20,
}


# The decision reads the REAL Victron surplus and battery SOC (Victron MQTT topics) and the REAL
# heating_cooling_indicator season: also runs under `--package victron` and
# `--package heating_cooling_indicator`.
@pytest.mark.package("victron", "heating_cooling_indicator")
async def test_slab_mode_wanted_delays(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """The slab decision: master switch, 15 min delay_on, Schmitt hold, 20 min delay_off.

    Replaces the Docker `test_decision_stays_off_while_the_master_switch_is_off` (abundant
    surplus, switch off → off). New, through the same real inputs: the switch on starts a
    charge only after 15 min (delay_on); a surplus between the two thresholds holds it
    (`this.state` Schmitt); the switch off ends it only after 20 min (delay_off, the
    compressor's minimum restart interval).

    Every gate of the decision is driven for real: active heating season (the REAL indicator
    via its seeded 48h mean, as in `test_target_temp`), the PV window (a schedule helper: the
    clock is moved to 10:00), ebusd online (ehp/Status republished, its flow temperature has
    `force_update`), SOC 80 % over the 70 % floor, no cooling, no DHW.
    """
    slab = entity_id(ha, "binary_sensor", "template", "heating_slab_mode_wanted")
    surplus = entity_id(ha, "sensor", "template", "heating_pv_surplus")
    ids = {"slab": slab, "surplus": surplus,
           "indicator": entity_id(ha, "sensor", "template", "heating_cooling_indicator"),
           "window": "schedule.heating_pv_window",
           "online": entity_id(ha, "binary_sensor", "template", "heating_ebusd_online")}
    for eid, value in _SLAB_HELPERS.items():
        await ha.services.async_call("input_number", "set_value",
                                     {"entity_id": eid, "value": value}, blocking=True)
    # Tomorrow 10:00, inside the 09:00-16:00 PV window (forward only: see `next_day`).
    await clock.move_to(local_at(next_day(), 10))
    await seed(ha, _mean(11.0))  # active heating season
    inputs = list(_VICTRON.values()) + [_HEAT, _SOC, _HVAC]
    await wait_subscribed(ha, broker, *(inp.topic for inp in inputs))
    # PV 4000 W DC (η 100 % bootstrap), house load 1000 W, heat pump 0 W → surplus 3000 W.
    live = {"dc_pv": 4000, "ac_pv": 0, **_load(1000), "heat": 0}

    async def refresh() -> None:
        """Republish every live input (the devices push continuously), then sync."""
        await _send(ha, broker, *((_VICTRON[k], v) for k, v in live.items() if k in _VICTRON),
                    (_HEAT, live["heat"]), (_SOC, 80), (_HVAC, "heat"))

    failures: list[str] = []

    def check(where: str, **want: Callable[[str], bool]) -> None:
        """Record a failure for every entity (key of `ids`) not matching its predicate."""
        failures.extend(check_states(ha, ids, want, where))

    await refresh()
    # Master switch off (default), every other gate open. The sensor was unavailable (no data)
    # until now; the first data renders false, which goes through delay_off from no state: it
    # reads `unknown` for 20 min (as after every restart), then off: no charge.
    check("first data: delay_off from no state", slab=is_state("unknown"), surplus=near(3000),
          indicator=is_state("active_heating"), window=_ON, online=_ON)
    await clock.hold(20 * 60 + 1, refresh)
    check("switch off, 20 min later", slab=_OFF)

    # Switch on: delay_on 15 min.
    await ha.services.async_call("input_boolean", "turn_on",
                                 {"entity_id": "input_boolean.heating_pv_boost_enabled"},
                                 blocking=True)
    await clock.hold(14 * 60, refresh)
    check("switch on: 14 min, still within delay_on", slab=_OFF)
    await clock.hold(61, refresh)
    check("switch on: charge wanted after 15 min", slab=_ON, online=_ON)

    # Surplus 1000 W: below the start threshold (1500) but above the stop threshold (500).
    live |= _load(3000)  # 4000 - 3000 = 1000 W
    await clock.hold(21 * 60, refresh)
    check("surplus between the thresholds holds the charge (Schmitt)", slab=_ON,
          surplus=near(1000))

    # Switch off: delay_off 20 min.
    await ha.services.async_call("input_boolean", "turn_off",
                                 {"entity_id": "input_boolean.heating_pv_boost_enabled"},
                                 blocking=True)
    await clock.hold(19 * 60, refresh)
    check("switch off: 19 min, still within delay_off", slab=_ON)
    await clock.hold(61, refresh)
    check("switch off: charge ends after 20 min", slab=_OFF)
    assert not failures, f"{len(failures)} slab check(s) failed:\n" + "\n".join(failures)


def _clamp(watts: float) -> tuple[tuple[Input, Any], tuple[Input, Any]]:
    """A compressor state as the two devices report it: the clamp and ehp/Comp (on above 500 W)."""
    return (_HEAT, watts), (_COMP, "on" if watts > 500 else "off")


async def _compressor_run(
    hass: HomeAssistant, broker: Broker, clock: Clock, *, mode: str, watts: float, minutes: float,
) -> None:
    """One compressor run: hcmode `mode` at `watts` on the clamp for exactly `minutes`.

    The clamp (`em:0`, expire_after 120 s) is republished every minute during the run, as the
    Shelly does; the same value does not change the state, so `last_changed` stays at the start.
    """
    async def refresh() -> None:
        """Republish the mode and the clamp (same values: no state change)."""
        await _send(hass, broker, (_HVAC, mode), *_clamp(watts))

    await clock.hold(minutes * 60, refresh)


async def test_last_run(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """`heating_compressor_last_run` measures a heating run from its own on→off transition.

    Replaces the Docker `test_last_run_measures_the_on_to_off_transition` and
    `test_last_run_ignores_hot_water_runs` (one HA, no leftover from earlier tests, so the
    hot-water check is exact: the sensor keeps its previous value, it does not just avoid ≈30).
    The frozen clock makes each span exact (Docker: 6.5…8.0 min for a 7 min run). New: a
    heating run that rolls into hot water without the compressor stopping reports only its
    heating part (the documented edge case of `heating_compressor_heating_active`).
    """
    ids = {"active": entity_id(ha, "binary_sensor", "template", "heating_compressor_active"),
           "heating": entity_id(ha, "binary_sensor", "template",
                                "heating_compressor_heating_active"),
           "last_run": entity_id(ha, "sensor", "template", "heating_compressor_last_run")}
    await wait_subscribed(ha, broker, _HVAC.topic, _HEAT.topic, _COMP.topic, _PUMP.topic)
    await _send(ha, broker, (_PUMP, "on"))
    failures: list[str] = []

    def check(where: str, **want: Callable[[str], bool]) -> None:
        """Record a failure for every entity (key of `ids`) not matching its predicate."""
        failures.extend(check_states(ha, ids, want, where))

    # Idle circulation (83 W, heating mode): not running; no run has ended yet.
    await _send(ha, broker, (_HVAC, "heat"), *_clamp(83))
    check("idle", active=_OFF, heating=_OFF, last_run=is_state("unknown"))

    # 1. A 7 min heating run (1.8 kW) is reported as 7.0 min when it ends.
    await _send(ha, broker, *_clamp(1800))
    check("heating run starts", active=_ON, heating=_ON)
    await _compressor_run(ha, broker, clock, mode="heat", watts=1800, minutes=7)
    await _send(ha, broker, *_clamp(83))
    check("7 min heating run ends", active=_OFF, heating=_OFF, last_run=near(7.0))

    # 2. A 30 min hot-water run (3.5 kW, hcmode water) is a compressor run but not a heating
    #    run: last run keeps the 7.0.
    await _send(ha, broker, (_HVAC, "water"), *_clamp(3500))
    check("hot-water run starts", active=_ON, heating=_OFF)
    await _compressor_run(ha, broker, clock, mode="water", watts=3500, minutes=30)
    await _send(ha, broker, *_clamp(83))
    check("30 min hot-water run ends", active=_OFF, heating=_OFF, last_run=near(7.0))

    # 3. The next heating run, 12 min, replaces it.
    await _send(ha, broker, (_HVAC, "heat"), *_clamp(1800))
    await _compressor_run(ha, broker, clock, mode="heat", watts=1800, minutes=12)
    await _send(ha, broker, *_clamp(83))
    check("12 min heating run ends", last_run=near(12.0))

    # 4. New: 5 min of heating, then the mode flips to water with the compressor still on: the
    #    heating segment ends at the flip (5.0), the hot-water tail does not count.
    await _send(ha, broker, *_clamp(1800))
    await _compressor_run(ha, broker, clock, mode="heat", watts=1800, minutes=5)
    await _send(ha, broker, (_HVAC, "water"), *_clamp(3500))
    check("heating rolls into hot water", active=_ON, heating=_OFF, last_run=near(5.0))
    await _compressor_run(ha, broker, clock, mode="water", watts=3500, minutes=10)
    await _send(ha, broker, *_clamp(83))
    check("hot-water tail ends", active=_OFF, last_run=near(5.0))
    assert not failures, f"{len(failures)} last-run check(s) failed:\n" + "\n".join(failures)


async def test_cycling_history_stats(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Runs, runtime, average run and duty cycle from the REAL history_stats (recorder).

    New (item 3 seeded the two history_stats sensors behind the average run). Two heating runs
    of 10 and 20 min and one hot-water run today → 2 runs, 0.5 h, average 15 min; the 24 h duty
    cycle is 0.5 h / 24 h. The recorder is `recorder_mock` (in-memory SQLite); every read
    follows `async_wait_recording_done`, so the states are committed before history_stats
    queries them. Starts at 10:00 tomorrow so all runs fall on one day (`today_at()`).
    """
    ids = {"runs": entity_id(ha, "sensor", "history_stats", "heating_compressor_runs_today"),
           "runtime": entity_id(ha, "sensor", "history_stats",
                                "heating_compressor_runtime_today"),
           "duty": entity_id(ha, "sensor", "history_stats", "heating_compressor_duty_cycle_24h"),
           "average": entity_id(ha, "sensor", "template", "heating_compressor_average_run_today")}
    await clock.move_to(local_at(next_day(), 10))
    await wait_subscribed(ha, broker, _HVAC.topic, _HEAT.topic, _COMP.topic, _PUMP.topic)
    await _send(ha, broker, (_PUMP, "on"))
    failures: list[str] = []

    async def check(where: str, **want: Callable[[str], bool]) -> None:
        """Commit the recorder's queue, then compare (history_stats reads from it)."""
        await async_wait_recording_done(ha)
        failures.extend(check_states(ha, ids, want, where))

    await _send(ha, broker, (_HVAC, "heat"), *_clamp(83))
    await clock.advance(60)
    await check("no run today", runs=near(0), runtime=near(0), average=near(0))
    for minutes, pause in ((10, 5), (20, 5)):
        await _send(ha, broker, *_clamp(1800))
        await _compressor_run(ha, broker, clock, mode="heat", watts=1800, minutes=minutes)
        await _send(ha, broker, *_clamp(83))
        await _compressor_run(ha, broker, clock, mode="heat", watts=83, minutes=pause)
    # A hot-water run is not counted.
    await _send(ha, broker, (_HVAC, "water"), *_clamp(3500))
    await _compressor_run(ha, broker, clock, mode="water", watts=3500, minutes=15)
    await _send(ha, broker, *_clamp(83))
    await clock.advance(60)
    await check("two heating runs, one hot-water run", runs=near(2), runtime=near(0.5),
                average=near(15.0), duty=near(round(0.5 / 24 * 100, 1), 0.05))
    assert not failures, f"{len(failures)} cycling check(s) failed:\n" + "\n".join(failures)


async def test_history_stats_read_back_from_recorder(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """After a reload the history_stats sensors get their value from the RECORDED history only.

    history_stats follows live state events and queries the recorder just once, on its first
    update (`HistoryStats.async_update`, `_has_recorder_data` False). `history_stats.reload`
    (`async_setup_reload_service`) resets the platform: new entities with an empty cache, so
    their first update is a database read. Two heating runs of 10 and 20 min and one hot-water
    run are recorded first (committed by `async_wait_recording_done`), then the platform is
    reloaded; the literal anchors (2 runs, 0.5 h, 0.5/24 duty) can only come from the database,
    so a source missing from the filtered test recorder (`history_sources()` in conftest.py)
    fails here, not only in the structural guards of test_recorder_filter.py.
    """
    ids = {"runs": entity_id(ha, "sensor", "history_stats", "heating_compressor_runs_today"),
           "runtime": entity_id(ha, "sensor", "history_stats",
                                "heating_compressor_runtime_today"),
           "duty": entity_id(ha, "sensor", "history_stats", "heating_compressor_duty_cycle_24h")}
    # Same runs as test_cycling_history_stats (energy-mode driven: ehp/Comp + Hc1Pump + clamp).
    await clock.move_to(local_at(next_day(), 10))
    await wait_subscribed(ha, broker, _HVAC.topic, _HEAT.topic, _COMP.topic, _PUMP.topic)
    await _send(ha, broker, (_PUMP, "on"))
    await _send(ha, broker, (_HVAC, "heat"), *_clamp(83))
    await clock.advance(60)
    for minutes in (10, 20):
        await _send(ha, broker, *_clamp(1800))
        await _compressor_run(ha, broker, clock, mode="heat", watts=1800, minutes=minutes)
        await _send(ha, broker, *_clamp(83))
        await _compressor_run(ha, broker, clock, mode="heat", watts=83, minutes=5)
    # A hot-water run is not counted.
    await _send(ha, broker, (_HVAC, "water"), *_clamp(3500))
    await _compressor_run(ha, broker, clock, mode="water", watts=3500, minutes=15)
    await _send(ha, broker, *_clamp(83))
    await clock.advance(60)
    await async_wait_recording_done(ha)
    live = check_states(ha, ids, {"runs": near(2), "runtime": near(0.5)}, "before reload")
    assert not live, "precondition failed:\n" + "\n".join(live)
    # Reset the platform: the new sensors have no live history, only the database.
    await ha.services.async_call("history_stats", "reload", blocking=True)
    await ha.async_block_till_done()
    failures = check_states(
        ha, ids,
        {"runs": near(2), "runtime": near(0.5), "duty": near(round(0.5 / 24 * 100, 1), 0.05)},
        "after reload (database read)",
    )
    assert not failures, f"{len(failures)} read-back check(s) failed:\n" + "\n".join(failures)


async def test_daily_meters_reset_at_midnight(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """The daily utility meters behind the efficiency reset at local midnight (`cycle: daily`).

    New. The compressor table resets them with `utility_meter.reset`; here the real cycle does
    it: 9 kWh heat / 3 kWh electricity during the day (efficiency 3.0), the clock crosses
    midnight → both meters 0, efficiency 0, then the next increments count from 0. The per-mode
    meters reset the same way: with no energy-mode input the tariffs stay at their first option
    (active_heating), which collects everything here.
    """
    ids = {"yield": entity_id(ha, "sensor", "utility_meter", "heating_yield_daily_single_tariff"),
           "elec": entity_id(ha, "sensor", "utility_meter",
                             "heating_electricity_daily_single_tariff"),
           "efficiency": entity_id(ha, "sensor", "template", "heating_efficiency_today"),
           "yield_active": _tariff_ids(ha, "heating_yield_by_mode")["active_heating"],
           "elec_active": _tariff_ids(ha, "heating_electricity_by_mode")["active_heating"]}
    yield_in = _COMPRESSOR_TABLE.inputs["yield"]
    await clock.move_to(local_at(next_day(), 22))
    await wait_subscribed(ha, broker, yield_in.topic, _HEAT_ENERGY.topic)
    failures: list[str] = []

    def check(where: str, **want: Callable[[str], bool]) -> None:
        """Record a failure for every entity (key of `ids`) not matching its predicate."""
        failures.extend(check_states(ha, ids, want, where))

    # First readings only set the meters' start; then +9 kWh heat, +3 kWh electricity.
    await _send(ha, broker, (yield_in, 60000), (_HEAT_ENERGY, 1_000_000.0))
    await _send(ha, broker, (yield_in, 60009), (_HEAT_ENERGY, 1_003_000.0))
    check("evening", **{"yield": near(9), "elec": near(3), "efficiency": near(3.0),
                        "yield_active": near(9), "elec_active": near(3)})
    # Cross local midnight (22:00 → 00:00:30); the Shelly counter expires (120 s), so it is
    # republished afterwards with an unchanged value.
    await clock.move_to(local_at(next_day(after=next_day()), 0, 0, 30))
    await _send(ha, broker, (_HEAT_ENERGY, 1_003_000.0))
    check("after midnight", **{"yield": near(0), "elec": near(0), "efficiency": near(0),
                               "yield_active": near(0), "elec_active": near(0)})
    await _send(ha, broker, (yield_in, 60013), (_HEAT_ENERGY, 1_005_000.0))
    check("next day", **{"yield": near(4), "elec": near(2), "efficiency": near(2.0),
                         "yield_active": near(4), "elec_active": near(2)})
    assert not failures, f"{len(failures)} meter check(s) failed:\n" + "\n".join(failures)
