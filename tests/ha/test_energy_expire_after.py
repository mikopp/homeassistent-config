"""`expire_after` of the MQTT inputs, in-process on a frozen clock: #159.

The Shelly entities (pool pump, rain water pump, Heizung Pro 3EM) have `expire_after: 120`: they
go `unavailable` once their device stops publishing. The Loxone appliance meters, the Loxone
comfort flag and every ebusd register have NONE, on purpose: Loxone publishes only on change and
has no heartbeat, ebusd does not re-report an unchanged register, and a run must never be split
by a measurement dropout (doc/energy/notes.md, doc/heating_pv_boost/notes.md). Neither half is
checked anywhere else for the pump plugs, and nothing fails if an expiry is added to an entity
that must hold its value.

ONE test on one fresh HA: every input gets its live payload, then the clock moves in three steps
(just before the expiry, just after it, a week) and the states are read each time. A payload after
the expiry brings an expired entity back.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    Clock,
    entity_id,
    mqtt_sync,
    publish,
    wait_subscribed,
)

# Live payloads (MQTT Explorer, 2026-11-12). The pool pump has the rain water pump's payload shape.
_PLUG = (
    '{"id":0, "source":"init", "output":false, "apower":0.0, "voltage":0.0, "current":0.000, '
    '"aenergy":{"total":1519.000,"by_minute":[0.000,0.000,0.000],"minute_ts":1794499560},'
    '"temperature":{"tC":25.0, "tF":77.0}}'
)
_EM = '{"id":0,"total_current":13.462,"total_act_power":2759.613,"total_aprt_power":3112.551}'
_EMDATA = '{"id":0,"total_act":3706743.04, "total_act_ret":61.37}'

# Inputs WITH expire_after: topic → payload, then (domain, unique_id) of each entity it feeds.
_EXPIRING_TOPICS = {
    "shelly/shellyplusplugs-pool-pump/status/switch:0": _PLUG,
    "shelly/shellyplusplugs-rainwaterpump/status/switch:0": _PLUG,
    "shelly/shellypro3em-heizung/status/em:0": _EM,
    "shelly/shellypro3em-heizung/status/emdata:0": _EMDATA,
}
_EXPIRING = [
    *[("sensor", f"shelly_{pump}_{field}")
      for pump in ("pool_pump", "rainwater_pump")
      for field in ("power", "energy", "voltage", "current")],
    ("binary_sensor", "shelly_pool_pump_switch"),
    ("binary_sensor", "shelly_rainwater_pump_switch"),
    ("sensor", "shelly_pro3em_heizung_power"),
    ("sensor", "shelly_pro3em_heizung_energy"),
]

# Inputs WITHOUT expire_after. ehp/Integral is left out: the harness's `mqtt_sync` publishes to it.
_HOLDING_TOPICS = {
    "loxone/washer/power": "0.000", "loxone/washer/energy": "277.606",
    "loxone/tumble-dry/power": "0.000", "loxone/tumble-dry/energy": "419.756",
    "loxone/dishwasher/power": "0.000", "loxone/dishwasher/energy": "603.574",
    "loxone/heating/warm_enough": "On",
    "ebusd/ehp/Status": "23.88;1.540;1.513;heat;08", "ebusd/ehp/HcReturnTemp": "24.12;ok",
    "ebusd/mc/TempDesiredLow": "21.0", "ebusd/mc/TempDesired": "22.0",
    "ebusd/mc/OperatingMode": "on", "ebusd/mc/Status0a": "24.19;off;on;off;24",
    "ebusd/ehp/CompIntegral": "-180", "ebusd/ehp/CompHysteresis": "7.00",
    "ebusd/ehp/CompStartsHc": "13501", "ebusd/ehp/CompStartsHwc": "9420",
    "ebusd/ehp/CompHoursHc": "13316", "ebusd/ehp/YieldTotal": "127975",
    "ebusd/global/scan": "finished", "ebusd/global/running": "true",
    "ebusd/uih/CoolingDemand": "off", "ebusd/mc/CoolingRequestHc2": "no",
    "ebusd/uih/CoolingActive": "off", "ebusd/hwc/Status": "0;off;23.88;0",
    "ebusd/ehp/Comp": "off", "ebusd/ehp/Hc1Pump": "on", "ebusd/ehp/CompDemand": "no",
}
_HOLDING = [
    *[("sensor", f"loxone_{d}_{f}") for d in ("washer", "tumble_dry", "dishwasher")
      for f in ("power", "energy")],
    ("binary_sensor", "heating_loxone_warm_enough"),
    *[("sensor", u) for u in (
        "heating_hvac_action", "heating_circuit_flow_temp", "heating_circuit_return_temp",
        "heating_temp_desired_low", "heating_temp_desired", "heating_hvac_mode",
        "heating_circuit_flow_temp_desired", "heating_compressor_start_integral",
        "heating_compressor_hysteresis", "heating_compressor_starts",
        "hot_water_compressor_starts", "heating_compressor_hours", "heating_yield_total",
        "heating_ebusd_scan_status")],
    *[("binary_sensor", u) for u in (
        "heating_cooling_demand", "heating_cooling_request", "heating_cooling_active_uih",
        "heating_hwc_active", "heating_compressor_running", "heating_circuit_pump",
        "heating_compressor_demand", "heating_ebusd_running")],
]

_EXPIRY = 120  # expire_after of every Shelly entity, seconds


def _states(hass: HomeAssistant, ids: dict[str, str]) -> dict[str, str | None]:
    """Current state of every entity, by unique_id."""
    return {uid: (s.state if (s := hass.states.get(eid)) else None) for uid, eid in ids.items()}


# The comfort flag and the ebusd registers are heating_pv_boost entities: also runs under
# `--package heating_pv_boost`.
@pytest.mark.package("heating_pv_boost")
async def test_expire_after(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Shelly entities expire after 120 s and come back; Loxone and ebusd entities never expire."""
    ids = {uid: entity_id(ha, domain, "mqtt", uid) for domain, uid in _EXPIRING + _HOLDING}
    topics = _EXPIRING_TOPICS | _HOLDING_TOPICS
    await wait_subscribed(ha, broker, *topics)
    failures: list[str] = []

    def check(where: str, expiring_unavailable: bool, holding_before: dict[str, str | None]) -> None:
        """Expiring entities unavailable (or not); holding entities unchanged and never unavailable."""
        now = _states(ha, ids)
        for _, uid in _EXPIRING:
            if (now[uid] == "unavailable") != expiring_unavailable:
                failures.append(f"{where}: {uid} = {now[uid]!r}, "
                                f"want {'unavailable' if expiring_unavailable else 'a value'}")
        for _, uid in _HOLDING:
            if now[uid] != holding_before[uid]:
                failures.append(f"{where}: {uid} = {now[uid]!r}, held {holding_before[uid]!r}")

    for topic, payload in topics.items():
        await publish(ha, broker, topic, payload)
    await mqtt_sync(ha, broker)
    holding = {uid: v for uid, v in _states(ha, ids).items() if uid in {u for _, u in _HOLDING}}
    # Every holding entity has a real value to hold, else "unchanged" proves nothing.
    failures += [f"live payload: {uid} = {v!r}, no value yet" for uid, v in holding.items()
                 if v in (None, "unknown", "unavailable")]
    check("live payload", False, holding)

    await clock.advance(_EXPIRY - 1)   # one second before the expiry
    check(f"{_EXPIRY - 1} s", False, holding)
    await clock.advance(2)             # past it
    check(f"{_EXPIRY + 1} s", True, holding)
    await clock.advance(timedelta(days=7))
    check("7 days", True, holding)

    # A new message brings an expired entity back (the rain water pump; the others stay out).
    await publish(ha, broker, "shelly/shellyplusplugs-rainwaterpump/status/switch:0", _PLUG)
    await mqtt_sync(ha, broker)
    back = {uid: _states(ha, ids)[uid] for _, uid in _EXPIRING if "rainwater" in uid}
    failures += [f"after a new message: {uid} still unavailable" for uid, s in back.items()
                 if s == "unavailable"]
    assert not failures, f"{len(failures)} expire_after check(s) failed:\n" + "\n".join(failures)
