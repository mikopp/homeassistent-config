"""Shelly inputs of packages/energy.yaml fed with live payloads, in-process: #159.

Rain water pump (Plus Plug S, `switch:0`: power, energy, voltage, current, relay) and the Heizung
Pro 3EM (`em:0` power, `emdata:0` energy). The FIRST payload of every topic is the exact text seen
on the live broker (MQTT Explorer, 2026-11-12), verbatim (its odd spacing, `null` fields and the
phase data nothing reads included); the following ones are variants of the same shape: a running
pump with non-zero values, firmware decimals that the templates round, the relay on and off, a
null energy block (the templates' `is not none` branch), export (negative power).

One looping test on ONE fresh HA (stateless templates, no clock); each topic's payloads in order
WITHOUT a reset, so "null keeps the last value" is checked against the previous step's value.
Failures are collected; one assert names every failing step; any mqtt WARNING fails it too (a
template that raises keeps the last state and only logs). The pool pump's own cases are in
test_energy_pool_pump.py; the Pro 3EM's expiry and its use in the heating package are in
test_heating_pv_boost.py.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    MqttWarnings,
    check_states,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    wait_subscribed,
)

_PUMP = "shelly/shellyplusplugs-rainwaterpump/status/switch:0"
_EM = "shelly/shellypro3em-heizung/status/em:0"
_EMDATA = "shelly/shellypro3em-heizung/status/emdata:0"

# unique_id → domain of every entity read here (ids are looked up, never derived: #146).
_ENTITIES = {
    "shelly_rainwater_pump_power": "sensor",
    "shelly_rainwater_pump_energy": "sensor",
    "shelly_rainwater_pump_voltage": "sensor",
    "shelly_rainwater_pump_current": "sensor",
    "shelly_rainwater_pump_switch": "binary_sensor",
    "shelly_pro3em_heizung_power": "sensor",
    "shelly_pro3em_heizung_energy": "sensor",
}

# The live payloads, verbatim (do not reformat: the spacing is what the device sends).
_PUMP_LIVE = (
    '{"id":0, "source":"init", "output":false, "apower":0.0, "voltage":0.0, "current":0.000, '
    '"aenergy":{"total":1519.000,"by_minute":[0.000,0.000,0.000],"minute_ts":1794499560},'
    '"temperature":{"tC":25.0, "tF":77.0}}'
)
_EM_LIVE = (
    '{"id":0,"a_current":4.158,"a_voltage":233.4,"a_act_power":864.3,"a_aprt_power":971.8,'
    '"a_pf":0.89,"a_freq":50.0,"b_current":4.682,"b_voltage":230.1,"b_act_power":968.6,'
    '"b_aprt_power":1079.9,"b_pf":0.90,"b_freq":50.0,"c_current":4.622,"c_voltage":229.2,'
    '"c_act_power":926.7,"c_aprt_power":1060.8,"c_pf":0.87,"c_freq":50.0,"n_current":null,'
    '"total_current":13.462,"total_act_power":2759.613,"total_aprt_power":3112.551, '
    '"user_calibrated_phase":[]}'
)
_EMDATA_LIVE = (
    '{"id":0,"a_total_act_energy":905729.66,"a_total_act_ret_energy":61.28,'
    '"b_total_act_energy":1279203.97,"b_total_act_ret_energy":0.00,'
    '"c_total_act_energy":1521809.41,"c_total_act_ret_energy":0.09,'
    '"total_act":3706743.04, "total_act_ret":61.37}'
)

_ON, _OFF = is_state("on"), is_state("off")
_Expect = dict[str, Callable[[str], bool]]


def _pump(*, source: str = "timer", output: bool = False, apower: float = 0.0,
          voltage: float = 230.0, current: float = 0.0, energy_wh: float | None = 1519.0) -> str:
    """The live payload's shape with other values (`energy_wh=None`: a null energy block)."""
    data = json.loads(_PUMP_LIVE)
    data.update(source=source, output=output, apower=apower, voltage=voltage, current=current)
    data["aenergy"] = None if energy_wh is None else {**data["aenergy"], "total": energy_wh}
    return json.dumps(data)


def _em(watts: float) -> str:
    """The live `em:0` payload with another all-phase power."""
    return json.dumps(json.loads(_EM_LIVE) | {"total_act_power": watts})


def _emdata(total_wh: float | None) -> str:
    """The live `emdata:0` payload with another cumulative energy (None: null)."""
    return json.dumps(json.loads(_EMDATA_LIVE) | {"total_act": total_wh})


@dataclass
class Step:
    """One published payload and the state of each affected entity afterwards."""

    payload: str
    expect: _Expect
    why: str = ""


_P = "shelly_rainwater_pump_"
_H = "shelly_pro3em_heizung_"
# (topic, steps). Energy is Wh in the payload, kWh as a state; the templates round to 1 / 3 decimals.
TABLE: list[tuple[str, list[Step]]] = [
    (_PUMP, [
        Step(_PUMP_LIVE, {_P + "power": near(0.0), _P + "energy": near(1.519),
                          _P + "voltage": near(0.0), _P + "current": near(0.0),
                          _P + "switch": _OFF}, "live payload (relay off, nothing flowing)"),
        # A pump running: every value non-zero, relay on.
        Step(_pump(source="button", output=True, apower=412.3, voltage=231.7, current=1.795,
                   energy_wh=1523.4),
             {_P + "power": near(412.3), _P + "energy": near(1.523), _P + "voltage": near(231.7),
              _P + "current": near(1.795), _P + "switch": _ON}, "running"),
        # Firmware decimals the templates round: 1 decimal W/V, 3 for A and kWh.
        Step(_pump(output=True, apower=412.34, voltage=231.76, current=1.7956,
                   energy_wh=1523.4567),
             {_P + "power": near(412.3), _P + "energy": near(1.523), _P + "voltage": near(231.8),
              _P + "current": near(1.796), _P + "switch": _ON}, "rounding"),
        # A null energy block is ignored (last energy kept); the other values still move.
        Step(_pump(output=True, apower=398.0, voltage=230.0, current=1.73, energy_wh=None),
             {_P + "power": near(398.0), _P + "energy": near(1.523), _P + "voltage": near(230.0),
              _P + "current": near(1.73), _P + "switch": _ON}, "null energy block"),
        # The pump stops: relay off, no power, energy has grown.
        Step(_pump(output=False, apower=0.0, voltage=230.5, current=0.0, energy_wh=1530.25),
             {_P + "power": near(0.0), _P + "energy": near(1.53), _P + "voltage": near(230.5),
              _P + "current": near(0.0), _P + "switch": _OFF}, "stopped"),
        Step(_PUMP_LIVE, {_P + "power": near(0.0), _P + "energy": near(1.519),
                          _P + "voltage": near(0.0), _P + "switch": _OFF}, "live payload again"),
    ]),
    (_EM, [
        Step(_EM_LIVE, {_H + "power": near(2759.6)}, "live payload (heating, ~2.8 kW)"),
        Step(_em(0.0), {_H + "power": near(0.0)}, "idle"),
        Step(_em(1812.449), {_H + "power": near(1812.4)}, "rounded to one decimal"),
        Step(_em(-1234.56), {_H + "power": near(-1234.6)}, "export (negative)"),
        Step(_EM_LIVE, {_H + "power": near(2759.6)}, "live payload again"),
    ]),
    (_EMDATA, [
        Step(_EMDATA_LIVE, {_H + "energy": near(3706.743)}, "live payload (Wh → kWh)"),
        Step(_emdata(3706800.7), {_H + "energy": near(3706.801)}, "rounded to three decimals"),
        Step(_emdata(None), {_H + "energy": near(3706.801)}, "null total ignored"),
        Step(_emdata(3706950.0), {_H + "energy": near(3706.95)}),
        Step(_EMDATA_LIVE, {_H + "energy": near(3706.743)}, "live payload again"),
    ]),
]


async def test_shelly_live_payloads(ha: HomeAssistant, broker: Broker) -> None:
    """Every payload of the table, one HA; every failing step is named in the one assert."""
    ids = {uid: entity_id(ha, domain, "mqtt", uid) for uid, domain in _ENTITIES.items()}
    await wait_subscribed(ha, broker, _PUMP, _EM, _EMDATA)
    failures: list[str] = []
    warnings = MqttWarnings()
    logging.getLogger("homeassistant.components.mqtt").addHandler(warnings)
    try:
        for topic, steps in TABLE:
            for n, step in enumerate(steps, start=1):
                warnings.step = where = f"{topic} #{n}" + (f" ({step.why})" if step.why else "")
                await publish(ha, broker, topic, step.payload)
                await mqtt_sync(ha, broker)
                failures += check_states(ha, ids, step.expect, where)
    finally:
        logging.getLogger("homeassistant.components.mqtt").removeHandler(warnings)
    failures += [f"mqtt warning at {hit}" for hit in warnings.hits]
    assert not failures, f"{len(failures)} Shelly check(s) failed:\n" + "\n".join(failures)
