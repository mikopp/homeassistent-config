"""Loxone MQTT inputs, in-process: #159.

The six appliance meters of packages/energy.yaml (washer, tumble dryer, dishwasher: power in kW,
lifetime energy in kWh) and the comfort flag `loxone/heating/warm_enough` of
packages/heating_pv_boost.yaml get real payloads over the real broker; their resulting state (and
units) is asserted. The FIRST payload of every topic is the exact string seen on the live broker
(MQTT Explorer, 2026-11-12: bare numbers with 3 decimals, `On` for the flag); the following ones are
variants derived from the templates (rounding, a running load, whitespace, empty, the flag in
every spelling it accepts).

One looping test on ONE fresh HA (stateless templates), each topic's payloads in order WITHOUT a
reset, so "empty keeps the last value" is checked against the value the previous step produced.
Failures are collected; one assert names every failing step. Any mqtt WARNING fails the test too:
a template that raises keeps the last state and only logs.

Not covered, accepted (owner): a non-numeric payload (`n/a`) on the six meters. Their template
guards only the empty payload, so such a payload raises (warning, last value kept); nothing
publishes one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    wait_subscribed,
)


@dataclass
class Meter:
    """One Loxone appliance sensor: its topic, unique_id, unit and the payload → state steps."""

    topic: str
    unique_id: str
    unit: str
    steps: list[tuple[str, float]]


def _steps(live: str, running: list[str]) -> list[tuple[str, float]]:
    """Payload steps shared by every meter: the live value, the `running` values in order
    (a load that changes; a power meter ends with its draw ending), rounding, empty ignored."""
    return [
        (live, float(live)),
        *[(value, float(value)) for value in running],
        ("1.23456", 1.235),       # rounded to three decimals
        ("", 1.235),              # empty payload: ignored, last value kept
        ("  ", 1.235),            # whitespace only: the same
        (" 2.5 ", 2.5),           # surrounding whitespace is trimmed
        ("0", 0.0),               # integer form of zero
        (live, float(live)),      # back to the live value
    ]


# Live payloads are the idle values on the broker (power 0.000, lifetime energy). The non-zero
# power values are REPRESENTATIVE kW readings, not captured ones (every appliance was idle when
# the live values were read): a small standby draw, a typical load and a heater peak, then the 0
# Loxone publishes when a draw ends. Energy rises monotonically (total_increasing).
METERS = [
    Meter("loxone/washer/power", "loxone_washer_power", "kW",
          _steps("0.000", ["0.004", "0.134", "1.987", "2.049", "0.000"])),
    Meter("loxone/washer/energy", "loxone_washer_energy", "kWh",
          _steps("277.606", ["277.610", "278.113", "279.5"])),
    Meter("loxone/tumble-dry/power", "loxone_tumble_dry_power", "kW",
          _steps("0.000", ["0.007", "0.812", "2.436", "0.000"])),
    Meter("loxone/tumble-dry/energy", "loxone_tumble_dry_energy", "kWh",
          _steps("419.756", ["419.760", "420.001", "421.2"])),
    Meter("loxone/dishwasher/power", "loxone_dishwasher_power", "kW",
          _steps("0.000", ["0.003", "0.087", "2.041", "1.998", "0.000"])),
    Meter("loxone/dishwasher/energy", "loxone_dishwasher_energy", "kWh",
          _steps("603.574", ["603.580", "604.002", "605.1"])),
]

_ON, _OFF = is_state("on"), is_state("off")
# loxone/heating/warm_enough: ON for 1/on/yes/true (any case, trimmed), anything else is OFF.
# The template has no empty-payload guard on purpose (owner): an empty or garbage payload is OFF,
# i.e. "not warm enough".
_FLAG: list[tuple[str, Callable[[str], bool], str]] = [
    ("On", _ON, "live payload"),
    ("Off", _OFF, ""),
    ("1", _ON, "raw number"),
    ("0", _OFF, "raw number"),
    ("true", _ON, ""),
    ("false", _OFF, ""),
    (" YES ", _ON, "case and whitespace"),
    ("no", _OFF, ""),
    ("on", _ON, ""),
    ("", _OFF, "empty payload is OFF (by design)"),
    ("on", _ON, ""),
    ("n/a", _OFF, "garbage is OFF"),
    ("On", _ON, "back to the live payload"),
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


# warm_enough drives the real heating_pv_boost entities: also runs under `--package heating_pv_boost`.
@pytest.mark.package("heating_pv_boost")
async def test_loxone_inputs(ha: HomeAssistant, broker: Broker) -> None:
    """Every Loxone payload of the tables, one HA; every failing step is named in the one assert."""
    ids = {m.unique_id: entity_id(ha, "sensor", "mqtt", m.unique_id) for m in METERS}
    flag = entity_id(ha, "binary_sensor", "mqtt", "heating_loxone_warm_enough")
    await wait_subscribed(ha, broker, "loxone/heating/warm_enough", *(m.topic for m in METERS))
    failures: list[str] = []
    warnings = _MqttWarnings()
    logging.getLogger("homeassistant.components.mqtt").addHandler(warnings)
    try:
        for meter in METERS:
            for n, (payload, want) in enumerate(meter.steps, start=1):
                warnings.step = where = f"{meter.topic} #{n} {payload!r}"
                await publish(ha, broker, meter.topic, payload)
                await mqtt_sync(ha, broker)
                state = ha.states.get(ids[meter.unique_id])
                got = state.state if state else None
                if got is None or not near(want)(got):
                    failures.append(f"{where}: {ids[meter.unique_id]} = {got!r}, want {want}")
            # The Energy Dashboard needs the unit (kW is native, no scaling) on every state.
            unit = ha.states.get(ids[meter.unique_id]).attributes.get("unit_of_measurement")
            if unit != meter.unit:
                failures.append(f"{meter.topic}: unit {unit!r}, want {meter.unit!r}")
        for n, (payload, check, why) in enumerate(_FLAG, start=1):
            warnings.step = where = (f"loxone/heating/warm_enough #{n} {payload!r}"
                                     + (f" ({why})" if why else ""))
            await publish(ha, broker, "loxone/heating/warm_enough", payload)
            await mqtt_sync(ha, broker)
            state = ha.states.get(flag)
            got = state.state if state else None
            if got is None or not check(got):
                failures.append(f"{where}: {flag} = {got!r}, want {check.__doc__}")
    finally:
        logging.getLogger("homeassistant.components.mqtt").removeHandler(warnings)
    failures += [f"mqtt warning at {hit}" for hit in warnings.hits]
    assert not failures, f"{len(failures)} Loxone check(s) failed:\n" + "\n".join(failures)
