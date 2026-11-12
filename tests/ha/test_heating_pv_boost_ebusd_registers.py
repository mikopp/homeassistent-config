"""ebusd register ingest (packages/heating_pv_boost.yaml), in-process: #159.

Every MQTT entity fed from an `ebusd/...` register gets real payloads over the real broker and
its resulting state is asserted, so a broken `value_template` fails a test. The FIRST payload of
every topic is the exact string seen on the live broker (MQTT Explorer, 2026-11-12, geoTHERM
EHP00 SW 0383); the following ones are variants derived from the templates and from
doc/heating_pv_boost/registers.md (every enum in both forms, case, whitespace, unmapped values,
short or empty payloads, garbage numbers).

One looping test on ONE fresh HA (stateless templates): per topic the payloads are published in
order WITHOUT a reset, so "ignored payload keeps the last value" is checked against the value the
previous step produced. Failures are collected; one assert names every failing step.

`ehp/Integral` is the `mqtt_sync` channel of the harness (tests/ha/conftest.py), so it has its own
test below. The `loxone/...` topics are not here (no live payloads supplied yet).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    wait_state,
    check_states,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    wait_subscribed,
)

# unique_id → domain of every entity this table reads (ids are looked up, never derived: #146).
_ENTITIES = {
    "heating_hvac_action": "sensor",
    "heating_circuit_flow_temp": "sensor",
    "heating_circuit_return_temp": "sensor",
    "heating_temp_desired_low": "sensor",
    "heating_temp_desired": "sensor",
    "heating_hvac_mode": "sensor",
    "heating_circuit_flow_temp_desired": "sensor",
    "heating_compressor_start_integral": "sensor",
    "heating_compressor_hysteresis": "sensor",
    "heating_compressor_starts": "sensor",
    "hot_water_compressor_starts": "sensor",
    "heating_compressor_hours": "sensor",
    "heating_yield_total": "sensor",
    "heating_ebusd_scan_status": "sensor",
    "heating_cooling_demand": "binary_sensor",
    "heating_cooling_request": "binary_sensor",
    "heating_cooling_active_uih": "binary_sensor",
    "heating_hwc_active": "binary_sensor",
    "heating_compressor_running": "binary_sensor",
    "heating_circuit_pump": "binary_sensor",
    "heating_compressor_demand": "binary_sensor",
    "heating_ebusd_running": "binary_sensor",
}

_Check = Callable[[str], bool]


@dataclass
class Msg:
    """One published payload and the state every entity of that topic must show afterwards."""

    payload: str
    expect: dict[str, _Check]
    why: str = ""


@dataclass
class Topic:
    """An ebusd topic with its ordered payloads (no reset in between)."""

    topic: str
    msgs: list[Msg] = field(default_factory=list)


_ON, _OFF = is_state("on"), is_state("off")
_ACTION, _FLOW = "heating_hvac_action", "heating_circuit_flow_temp"


def _status(flow: str, mode: str, tail: str = "00") -> str:
    """ehp/Status: HcFlowTemp;HcPress;SourcePress;hcmode;raw hex (registers.md)."""
    return f"{flow};1.540;1.513;{mode};{tail}"


def _mode_msgs(topic_key: str, values: dict[str, str], unmapped: str) -> list[Msg]:
    """One message per (payload → state) pair of a single-entity enum register."""
    msgs = [Msg(raw, {topic_key: is_state(state)}) for raw, state in values.items()]
    return msgs + [Msg(unmapped, {topic_key: is_state("unknown")}, "unmapped enum → unknown")]


def _onoff_msgs(key: str, *, guarded: bool) -> list[Msg]:
    """Cases of a plain on/off register: names, raw numbers, case/space, garbage.

    guarded=True: the template renders '' for an unrecognised payload (last value kept).
    guarded=False: anything not recognised as "on" is OFF (the binary_sensors without a guard).
    """
    garbage = _ON if guarded else _OFF
    return [
        Msg("on", {key: _ON}),
        Msg("off", {key: _OFF}),
        Msg("1", {key: _ON}, "raw number"),
        Msg("0", {key: _OFF}, "raw number"),
        Msg(" YES ", {key: _ON}, "case and whitespace"),
        Msg("no", {key: _OFF}),
        Msg("true", {key: _ON}),
        Msg("false", {key: _OFF}),
        Msg("on", {key: _ON}),
        Msg("n/a", {key: garbage},
            "garbage keeps the last value" if guarded else "garbage is OFF"),
    ]


def _counter_msgs(key: str, first: str, second: str) -> list[Msg]:
    """Cases of an integer counter register: live value, a bump, garbage, empty (ignored)."""
    return [
        Msg(first, {key: near(float(first))}, "live value"),
        Msg(second, {key: near(float(second))}),
        Msg("n/a", {key: near(float(second))}, "garbage ignored"),
        Msg("", {key: near(float(second))}, "empty ignored"),
        Msg(f"{second}.0", {key: near(float(second))}, "float form of the same integer"),
    ]


TOPICS = [
    # ── ehp/Status → hvac_action (field 3, the enum) and circuit flow temp (field 0) ──────────
    Topic("ebusd/ehp/Status", [
        Msg("23.88;1.540;1.513;heat;08", {_ACTION: is_state("heat"), _FLOW: near(23.88)},
            "live payload"),
        Msg(_status("25.19", "off"), {_ACTION: is_state("off"), _FLOW: near(25.19)}),
        Msg(_status("26.0", "cooling", "0a"), {_ACTION: is_state("cooling"), _FLOW: near(26.0)}),
        Msg(_status("26.5", "cool"), {_ACTION: is_state("cooling"), _FLOW: near(26.5)},
            "older config generation name"),
        Msg(_status("27.0", "water"), {_ACTION: is_state("water"), _FLOW: near(27.0)}),
        Msg(_status("28.0", "heat"), {_ACTION: is_state("heat"), _FLOW: near(28.0)}),
        # The same enum as raw numbers: 0=off 1=cooling 3=heat 4=water.
        Msg(_status("29.0", "0"), {_ACTION: is_state("off"), _FLOW: near(29.0)}, "raw 0"),
        Msg(_status("30.0", "1"), {_ACTION: is_state("cooling"), _FLOW: near(30.0)}, "raw 1"),
        Msg(_status("31.0", "3"), {_ACTION: is_state("heat"), _FLOW: near(31.0)}, "raw 3"),
        Msg(_status("32.0", "4"), {_ACTION: is_state("water"), _FLOW: near(32.0)}, "raw 4"),
        Msg(_status("33.0", " HEAT "), {_ACTION: is_state("heat"), _FLOW: near(33.0)},
            "case and whitespace"),
        Msg(_status("34.0", "2"), {_ACTION: is_state("unknown"), _FLOW: near(34.0)},
            "2 is not in the hcmode enum"),
        Msg(_status("35.0", "defrost"), {_ACTION: is_state("unknown"), _FLOW: near(35.0)}),
        # A flow temp that is not a number keeps the last flow; the mode is still decoded.
        Msg(_status("-", "off"), {_ACTION: is_state("off"), _FLOW: near(35.0)},
            "ebusd '-' for no value"),
        Msg(_status("n/a", "water"), {_ACTION: is_state("water"), _FLOW: near(35.0)}),
        # A payload without field 3 (short or empty) is not a mode: hvac_action is unknown, the
        # flow temp (field 0) is still read, and an empty payload leaves it as it was.
        Msg("36.5;1.5", {_FLOW: near(36.5), _ACTION: is_state("unknown")},
            "too few fields for the mode"),
        Msg(_status("37.0", "heat"), {_ACTION: is_state("heat"), _FLOW: near(37.0)}),
        Msg("", {_FLOW: near(37.0), _ACTION: is_state("unknown")}, "empty payload"),
    ]),
    # ── ehp/HcReturnTemp: temp;sensor-status, only "ok" readings are used ─────────────────────
    Topic("ebusd/ehp/HcReturnTemp", [
        Msg("24.12;ok", {"heating_circuit_return_temp": near(24.12)}, "live payload"),
        Msg("25.5;OK", {"heating_circuit_return_temp": near(25.5)}, "status is case-insensitive"),
        Msg("99.0;circuit", {"heating_circuit_return_temp": near(25.5)}, "short-circuit probe"),
        Msg("-50.0;cutoff", {"heating_circuit_return_temp": near(25.5)}, "open-circuit probe"),
        Msg("26.0;ok", {"heating_circuit_return_temp": near(26.0)}),
        Msg("26.0", {"heating_circuit_return_temp": near(26.0)}, "no status field → ignored"),
        Msg("", {"heating_circuit_return_temp": near(26.0)}, "empty ignored"),
    ]),
    # ── mc/TempDesiredLow and mc/TempDesired: plain °C, one decimal ───────────────────────────
    Topic("ebusd/mc/TempDesiredLow", [
        Msg("21.0", {"heating_temp_desired_low": near(21.0)}, "live payload"),
        Msg("19.5", {"heating_temp_desired_low": near(19.5)}),
        Msg("19.54", {"heating_temp_desired_low": near(19.5)}, "rounded to one decimal"),
        Msg("n/a", {"heating_temp_desired_low": near(19.5)}, "garbage ignored"),
        Msg("", {"heating_temp_desired_low": near(19.5)}, "empty ignored"),
    ]),
    Topic("ebusd/mc/TempDesired", [
        Msg("22.0", {"heating_temp_desired": near(22.0)}, "live payload"),
        Msg("24.5", {"heating_temp_desired": near(24.5)}),
        Msg("-", {"heating_temp_desired": near(24.5)}, "ebusd '-' ignored"),
        Msg("", {"heating_temp_desired": near(24.5)}, "empty ignored"),
    ]),
    # ── mc/OperatingMode → hvac_mode (the configured SETTING): 0..5 as name or number ────────
    Topic("ebusd/mc/OperatingMode", _mode_msgs(
        "heating_hvac_mode",
        {"on": "on",  # live payload
         "auto": "auto", "low": "low", "off": "off", "eco": "eco", "disabled": "disabled",
         "0": "disabled", "1": "on", "2": "off", "3": "auto", "4": "eco", "5": "low",
         " AUTO ": "auto", "Off": "off"},
        "6") + [
        Msg("", {"heating_hvac_mode": is_state("unknown")}, "empty payload is not a mode"),
        Msg("auto", {"heating_hvac_mode": is_state("auto")}),
    ]),
    # ── mc/Status0a: flowtemp;mixer;pump;onoff;flowtempdesired → field 4 ──────────────────────
    Topic("ebusd/mc/Status0a", [
        Msg("24.19;off;on;off;24", {"heating_circuit_flow_temp_desired": near(24.0)},
            "live payload"),
        Msg("30.0;off;on;on;28.5", {"heating_circuit_flow_temp_desired": near(28.5)}),
        Msg("30.0;off;on;on;n/a", {"heating_circuit_flow_temp_desired": near(28.5)},
            "garbage field 4 ignored"),
        Msg("30.0;off;on;on", {"heating_circuit_flow_temp_desired": near(28.5)},
            "too few fields ignored"),
        Msg("", {"heating_circuit_flow_temp_desired": near(28.5)}, "empty ignored"),
    ]),
    # ── Installer tuning registers (single numbers) ───────────────────────────────────────────
    Topic("ebusd/ehp/CompIntegral", [
        Msg("-180", {"heating_compressor_start_integral": near(-180)}, "live payload"),
        Msg("-150", {"heating_compressor_start_integral": near(-150)}),
        Msg("-150.4", {"heating_compressor_start_integral": near(-150)}, "rounded to integer"),
        Msg("n/a", {"heating_compressor_start_integral": near(-150)}, "garbage ignored"),
        Msg("", {"heating_compressor_start_integral": near(-150)}, "empty ignored"),
    ]),
    Topic("ebusd/ehp/CompHysteresis", [
        Msg("7.00", {"heating_compressor_hysteresis": near(7.0)}, "live payload"),
        Msg("9.5", {"heating_compressor_hysteresis": near(9.5)}),
        Msg("n/a", {"heating_compressor_hysteresis": near(9.5)}, "garbage ignored"),
        Msg("", {"heating_compressor_hysteresis": near(9.5)}, "empty ignored"),
    ]),
    # ── Lifetime counters ─────────────────────────────────────────────────────────────────────
    Topic("ebusd/ehp/CompStartsHc",
          _counter_msgs("heating_compressor_starts", "13501", "13502")),
    Topic("ebusd/ehp/CompStartsHwc",
          _counter_msgs("hot_water_compressor_starts", "9420", "9421")),
    Topic("ebusd/ehp/CompHoursHc",
          _counter_msgs("heating_compressor_hours", "13316", "13317")),
    Topic("ebusd/ehp/YieldTotal",
          _counter_msgs("heating_yield_total", "127975", "127980")),
    # ── ebusd's own status topics (retained, `in` only on the bridge) ─────────────────────────
    Topic("ebusd/global/scan", [
        Msg("OK", {"heating_ebusd_scan_status": is_state("OK")}),
        Msg("running", {"heating_ebusd_scan_status": is_state("running")}),
        Msg("finished", {"heating_ebusd_scan_status": is_state("finished")}),
        Msg("scan finished", {"heating_ebusd_scan_status": is_state("scan finished")},
            "no template: the payload is the state"),
    ]),
    Topic("ebusd/global/running", _onoff_msgs("heating_ebusd_running", guarded=False) + [
        Msg("true", {"heating_ebusd_running": _ON}, "ebusd online (retained)"),
        Msg("false", {"heating_ebusd_running": _OFF}, "last will on disconnect"),
    ]),
    # ── Cooling signals: the live values are off / 0 / no; names and numbers both arrive ──────
    Topic("ebusd/uih/CoolingDemand",
          [Msg("off", {"heating_cooling_demand": _OFF}, "live payload")]
          + _onoff_msgs("heating_cooling_demand", guarded=False)),
    Topic("ebusd/mc/CoolingRequestHc2",
          [Msg("no", {"heating_cooling_request": _OFF}, "live payload")]
          + _onoff_msgs("heating_cooling_request", guarded=False)),
    Topic("ebusd/uih/CoolingActive",
          [Msg("off", {"heating_cooling_active_uih": _OFF}, "live payload")]
          + _onoff_msgs("heating_cooling_active_uih", guarded=False)),
    # ── hwc/Status: desired;onoff;actual;desired → field 1 ────────────────────────────────────
    Topic("ebusd/hwc/Status", [
        Msg("0;off;23.88;0", {"heating_hwc_active": _OFF}, "live payload"),
        Msg("50;on;31.5;50", {"heating_hwc_active": _ON}),
        Msg("50;1;31.5;50", {"heating_hwc_active": _ON}, "raw number"),
        Msg("50;0;31.5;50", {"heating_hwc_active": _OFF}, "raw number"),
        Msg("50;yes;31.5;50", {"heating_hwc_active": _ON}),
        Msg("50;n/a;31.5;50", {"heating_hwc_active": _OFF}, "unrecognised → OFF"),
        Msg("50;on;31.5;50", {"heating_hwc_active": _ON}),
        Msg("50", {"heating_hwc_active": _ON}, "too few fields: ignored, last value kept"),
    ]),
    # ── Compressor and pump: guarded on/off, an unrecognised payload keeps the last value ─────
    Topic("ebusd/ehp/Comp",
          [Msg("off", {"heating_compressor_running": _OFF}, "live payload")]
          + _onoff_msgs("heating_compressor_running", guarded=True)),
    Topic("ebusd/ehp/Hc1Pump",
          [Msg("on", {"heating_circuit_pump": _ON}, "live payload")]
          + _onoff_msgs("heating_circuit_pump", guarded=True)),
    Topic("ebusd/ehp/CompDemand",
          [Msg("no", {"heating_compressor_demand": _OFF}, "live payload")]
          + _onoff_msgs("heating_compressor_demand", guarded=False)),
]


class _MqttWarnings(logging.Handler):
    """Collects WARNING+ records of the mqtt integration, tagged with the step being published."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.step = ""
        self.hits: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("homeassistant.components.mqtt"):
            self.hits.append(f"{self.step}: {record.getMessage()}")


async def test_ebusd_registers(ha: HomeAssistant, broker: Broker) -> None:
    """Every ebusd payload of the table, one HA; every failing step is named in the one assert."""
    ids = {uid: entity_id(ha, domain, "mqtt", uid) for uid, domain in _ENTITIES.items()}
    await wait_subscribed(ha, broker, *(t.topic for t in TOPICS))
    failures: list[str] = []
    # A template that raises on a payload keeps the last state, so the state check alone cannot
    # see a missing empty/garbage guard; the warning the mqtt integration logs for it does.
    warnings = _MqttWarnings()
    logging.getLogger("homeassistant.components.mqtt").addHandler(warnings)
    try:
        for topic in TOPICS:
            for n, msg in enumerate(topic.msgs, start=1):
                where = f"{topic.topic} #{n} {msg.payload!r}"
                where += f" ({msg.why})" if msg.why else ""
                warnings.step = where
                await publish(ha, broker, topic.topic, msg.payload)
                await mqtt_sync(ha, broker)
                failures += check_states(ha, ids, msg.expect, where)
    finally:
        logging.getLogger("homeassistant.components.mqtt").removeHandler(warnings)
    failures += [f"mqtt warning at {hit}" for hit in warnings.hits]
    assert not failures, f"{len(failures)} ebusd register check(s) failed:\n" + "\n".join(failures)


async def test_ebusd_integral(ha: HomeAssistant, broker: Broker) -> None:
    """ehp/Integral (live: 66): the sensor behind `mqtt_sync`, so it is checked without it.

    Order is the sync: an ignored payload is followed by a `TempDesired` message that DOES change
    its sensor, and once that shows, the earlier Integral message was handled too.
    """
    integral = entity_id(ha, "sensor", "mqtt", "heating_energy_integral")
    marker = entity_id(ha, "sensor", "mqtt", "heating_temp_desired")
    await wait_subscribed(ha, broker, "ebusd/ehp/Integral", "ebusd/mc/TempDesired")
    failures: list[str] = []
    # (payload, state of the Integral sensor afterwards): live value, negative, rounding, ignored.
    steps = [("66", 66), ("-600", -600), ("-12.6", -13), ("n/a", -13), ("", -13), ("0", 0)]
    for n, (payload, want) in enumerate(steps, start=1):
        await publish(ha, broker, "ebusd/ehp/Integral", payload)
        await publish(ha, broker, "ebusd/mc/TempDesired", f"{20 + n}.0")
        await wait_state(ha, marker, near(20.0 + n))
        state = ha.states.get(integral)
        got = state.state if state else None
        if got is None or not near(want)(got):
            failures.append(f"Integral #{n} {payload!r}: {integral} = {got!r}, want {want}")
    assert not failures, "\n".join(failures)
