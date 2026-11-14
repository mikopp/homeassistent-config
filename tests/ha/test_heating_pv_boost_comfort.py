"""Phase 2 comfort control (packages/heating_pv_boost.yaml), in-process.

`automation.heating_comfort_control` writes `ebusd/mc/OperatingMode/set` (names `on`/`off`) and
`ebusd/mc/TempDesired/set` (absolute, one decimal) from `sensor.heating_wanted_operating_mode`
and `sensor.heating_target_temp`; the plan's "Control law" rows 1-7 are the spec.

How the inputs get in (real broker; the assertions read what HA published to it):
- the read-backs (`mc/OperatingMode`, `mc/TempDesired`, `mc/TempDesiredLow`), `ehp/Status`
  (ebusd online) and `loxone/heating/warm_enough` go over the broker;
- the season is the REAL indicator, driven by the seeded 48h outdoor mean (as in
  test_heating_pv_boost.py); the slab decision `binary_sensor.heating_slab_mode_wanted` is seeded
  (its own gates are covered by `test_slab_mode_wanted_delays`).

The table arms the master switch LAST in each case, so the automation sees only the final inputs
and the writes of that one evaluation are asserted. A fence message published by HA itself after
the arming proves "no write" (one client publishes in order).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    Clock,
    SeedValue,
    mqtt_sync,
    publish,
    seed,
    wait_subscribed,
)

_C = {"unit_of_measurement": "°C", "device_class": "temperature"}
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_INDICATOR = "sensor.heating_cooling_indicator"
_SLAB = "binary_sensor.heating_slab_mode_wanted"
_WARM = "binary_sensor.loxone_heating_heating_loxone_warm_enough"
_MASTER = "input_boolean.heating_comfort_control_enabled"
_STAMP = "input_datetime.heating_mode_last_written"
_TEMP_STAMP = "input_datetime.heating_temp_desired_last_written"
_WANTED = "sensor.heating_wanted_operating_mode"
_MODE_SET = "ebusd/mc/OperatingMode/set"
_TEMP_SET = "ebusd/mc/TempDesired/set"
_STATUS = "ebusd/ehp/Status"
_INPUT_TOPICS = (_STATUS, "ebusd/mc/TempDesiredLow", "ebusd/mc/OperatingMode",
                 "ebusd/mc/TempDesired", "loxone/heating/warm_enough")

# 48h mean → season (thresholds 12 / 16 / 20 from the baseline); `None` makes the indicator unknown.
_SEASON = {"neutral": 14.0, "active_heating": 8.0, "active_cooling": 22.0,
           "passive_cooling": 18.0}


def _mean(value: float | None) -> dict[str, SeedValue]:
    """Seed of the 48h mean; None seeds `unavailable` (indicator unavailable: row 1)."""
    return {_MEAN: ("unavailable", {}) if value is None else (str(value), _C)}


async def _season(hass: HomeAssistant, season: str | None) -> None:
    """Drive the real indicator to `season` (via neutral first, as its hysteresis needs)."""
    await seed(hass, _mean(14.0))
    if season is None:
        await seed(hass, _mean(None))
        return
    await seed(hass, _mean(_SEASON[season]))
    assert hass.states.get(_INDICATOR).state == season, (
        f"indicator is {hass.states.get(_INDICATOR).state}, wanted {season}")


# Helper values the decision needs (production values; no baseline, see `_helpers`).
_HELPERS = {
    "input_number.heating_boost_offset": 1.5,
    "input_number.heating_indicator_heating_below": 12,
    "input_number.heating_indicator_passive_cooling_above": 16,
    "input_number.heating_indicator_active_cooling_above": 20,
}


async def _helpers(hass: HomeAssistant) -> None:
    """Set the helpers the season and the setpoint read, like test_slab_mode_wanted_delays."""
    for eid, value in _HELPERS.items():
        await _call(hass, "input_number", "set_value", entity_id=eid, value=value)


async def _call(hass: HomeAssistant, domain: str, action: str, **data: Any) -> None:
    await hass.services.async_call(domain, action, data, blocking=True)


async def _master(hass: HomeAssistant, on: bool) -> None:
    await _call(hass, "input_boolean", "turn_on" if on else "turn_off", entity_id=_MASTER)


async def _end_hold(hass: HomeAssistant) -> None:
    """Make both holds over (stamps back to 1970): the mode hold and the setpoint re-send guard."""
    for stamp in (_STAMP, _TEMP_STAMP):
        await _call(hass, "input_datetime", "set_datetime", entity_id=stamp, timestamp=0)


async def _inputs(hass: HomeAssistant, broker: Broker, *, status: bool = True, tdl: str = "21.0",
                  mode: str = "low", temp: str = "21.0", warm: str | None = "OFF") -> None:
    """Publish the ebusd read-backs, ebusd liveness and the Loxone flag; wait until handled."""
    if status:
        await publish(hass, broker, _STATUS, "25.2;1.5;1.2;heat;0a01")
    await publish(hass, broker, "ebusd/mc/TempDesiredLow", tdl)
    await publish(hass, broker, "ebusd/mc/OperatingMode", mode)
    await publish(hass, broker, "ebusd/mc/TempDesired", temp)
    if warm is not None:
        await publish(hass, broker, "loxone/heating/warm_enough", warm)
    await mqtt_sync(hass, broker)


async def _fence(hass: HomeAssistant, broker: Broker, index: int) -> list[tuple[str, str]]:
    """Every `/set` HA published since `index`, after a fence from the same MQTT client."""
    n = hass.data["fence"] = hass.data.get("fence", 0) + 1
    await hass.async_block_till_done()
    await _call(hass, "mqtt", "publish", topic="test/fence", payload=str(n))
    await hass.async_add_executor_job(broker.wait_received, "test/fence", str(n), index)
    return [(t, p) for t, p in broker.received[index:] if t.endswith("/set")]


@dataclass
class Case:
    """One control-law case: inputs, expected wanted mode, expected `/set` writes in order."""

    name: str
    season: str | None
    wanted: str
    writes: list[tuple[str, str]]
    slab: str = "off"
    warm: str | None = "OFF"
    mode: str = "low"
    temp: str = "21.0"
    tdl: str = "21.0"
    armed: bool = True


# TDL 21, boost offset 1.5 (baseline). Read-backs are chosen so every case differs from wanted
# unless it is the idempotence case.
_CASES = [
    Case("row1_indicator_unknown_writes_nothing", None, "unavailable", [],
         mode="low", temp="30.0"),
    Case("row2_passive_cooling_off_and_tdl", "passive_cooling", "off",
         [(_MODE_SET, "off"), (_TEMP_SET, "21.0")], mode="on", temp="22.0", warm="ON"),
    Case("row2_active_cooling_off_and_tdl", "active_cooling", "off",
         [(_MODE_SET, "off"), (_TEMP_SET, "21.0")], mode="on", temp="22.0", slab="on"),
    Case("row3_boost_overrides_warm_enough", "active_heating", "on",
         [(_MODE_SET, "on"), (_TEMP_SET, "23.5")], slab="on", warm="ON", mode="off"),
    Case("row4_warm_enough_after_boost_off", "active_heating", "off",
         [(_MODE_SET, "off"), (_TEMP_SET, "22.0")], slab="off", warm="ON", mode="on", temp="23.5"),
    Case("row4_slab_unknown_counts_as_off", "active_heating", "off",
         [(_MODE_SET, "off"), (_TEMP_SET, "22.0")], slab="unknown", warm="ON", mode="on"),
    Case("row5_not_warm_enough_heats", "active_heating", "on",
         [(_MODE_SET, "on"), (_TEMP_SET, "22.0")], warm="OFF", mode="off"),
    Case("row6_neutral_warm_enough_stops", "neutral", "off",
         [(_MODE_SET, "off")], warm="ON", mode="on", temp="22.0"),
    Case("row6_neutral_never_boosts", "neutral", "off",
         [(_MODE_SET, "off"), (_TEMP_SET, "22.0")], warm="ON", slab="on", mode="on"),
    Case("row7_neutral_not_warm_enough_heats", "neutral", "on",
         [(_MODE_SET, "on"), (_TEMP_SET, "22.0")], warm="OFF", mode="off"),
    Case("temp_only_change_writes_temp_only", "neutral", "on",
         [(_TEMP_SET, "22.0")], warm="OFF", mode="on", temp="23.5"),
    Case("idempotent_raw_enum_read_back_writes_nothing", "neutral", "on",
         [], warm="OFF", mode="1", temp="22.0"),
    Case("idempotent_off_writes_nothing", "neutral", "off",
         [], warm="ON", mode="off", temp="22.04"),
    Case("master_switch_off_writes_nothing", "neutral", "on", [], warm="OFF", mode="off",
         temp="30.0", armed=False),
    # Last: the seeded unknown state of an MQTT entity hides the next same-value message.
    Case("tdl_unknown_writes_nothing", "neutral", "on", [], warm="OFF", mode="off", temp="30.0",
         tdl=""),
]


async def test_comfort_control_table(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Rows 1-7 of the control law, the master switch and idempotence, one HA, one assert."""
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    failures: list[str] = []
    for case in _CASES:
        await _master(ha, False)
        await _end_hold(ha)
        await _season(ha, case.season)
        await _inputs(ha, broker, mode=case.mode, temp=case.temp, warm=case.warm,
                      tdl=case.tdl or "21.0")
        if case.tdl == "":
            await seed(ha, {"sensor.geotherm_heating_temp_desired_low": ("unknown", {})})
        await seed(ha, {_SLAB: (case.slab, {})})
        got_wanted = ha.states.get(_WANTED).state
        if got_wanted != case.wanted:
            failures.append(f"{case.name}: wanted mode {got_wanted!r}, want {case.wanted!r}")
        index = len(broker.received)
        if case.armed:
            await _master(ha, True)
        else:
            # Disarmed: poke every trigger input that moves; still nothing may be written.
            await _inputs(ha, broker, mode=case.mode, temp="30.5", warm=case.warm)
        got = await _fence(ha, broker, index)
        if got != case.writes:
            failures.append(f"{case.name}: wrote {got}, want {case.writes}")
    assert not failures, f"{len(failures)} comfort check(s) failed:\n" + "\n".join(failures)


async def test_no_write_while_ebusd_offline(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Armed and different from wanted, but ebusd is offline: nothing; back online: it writes."""
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _season(ha, "neutral")
    await _inputs(ha, broker, mode="off", temp="21.0", warm="OFF")  # wanted on, TDL + 1 = 22.0
    await seed(ha, {_SLAB: ("off", {})})
    # ehp/Status is not republished: online = last update < 900 s ago.
    await clock.advance(timedelta(minutes=16))
    assert ha.states.get("binary_sensor.heating_ebusd_online").state == "off"
    await _end_hold(ha)
    index = len(broker.received)
    await _master(ha, True)
    assert await _fence(ha, broker, index) == [], "wrote while ebusd was offline"
    # ebusd is back (a fresh status): the online trigger evaluates again and the writes follow.
    await _inputs(ha, broker, mode="off", temp="21.0", warm=None)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "on"), (_TEMP_SET, "22.0")]


async def test_mode_hold_defers_change_but_not_setpoint(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """One mode change per 30 min: a change inside the hold waits for its end; TempDesired does not.

    Neutral, not warm enough: on. Loxone says warm enough: off is wanted, but the write of `on`
    just happened. A new TDL moves the setpoint at once, the mode follows when the hold ends.
    """
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _season(ha, "neutral")
    await seed(ha, {_SLAB: ("off", {})})
    await _inputs(ha, broker, mode="off", temp="21.0", warm="OFF")
    await _end_hold(ha)
    await clock.align()

    async def refresh() -> None:
        """ebusd keeps publishing its status (online window 900 s)."""
        await publish(ha, broker, _STATUS, "25.2;1.5;1.2;heat;0a01")
        await mqtt_sync(ha, broker)

    index = len(broker.received)
    await _master(ha, True)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "on"), (_TEMP_SET, "22.0")]
    # The machine echoes the write; Loxone then reports warm enough (off wanted) and TDL moves.
    await _inputs(ha, broker, mode="on", temp="22.0", warm="ON")
    index = len(broker.received)
    await _inputs(ha, broker, tdl="22.0", mode="on", temp="22.0", warm="ON")
    assert await _fence(ha, broker, index) == [(_TEMP_SET, "23.0")], \
        "setpoint must follow at once and the mode must wait"
    await _inputs(ha, broker, tdl="22.0", mode="on", temp="23.0", warm="ON")
    assert ha.states.get(_WANTED).state == "off"

    index = len(broker.received)
    await clock.hold(29 * 60, refresh)
    assert await _fence(ha, broker, index) == [], "mode written inside the hold"
    await clock.hold(2 * 60, refresh)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "off")], "deferred change not applied"
    # A fresh hold started: the next change waits again.
    await _inputs(ha, broker, tdl="22.0", mode="off", temp="23.0", warm="OFF")
    index = len(broker.received)
    await clock.hold(5 * 60, refresh)
    assert await _fence(ha, broker, index) == [], "second mode change inside the new hold"


async def test_loxone_silent_24h_counts_as_not_warm_enough(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """Warm enough sets `off`; 24 h without any Loxone message (even identical) gives `on`.

    An identical re-sent payload moves `last_reported` only; it must keep Loxone online.
    """
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _call(ha, "automation", "turn_off", entity_id="automation.heating_comfort_control")
    await _season(ha, "neutral")
    await seed(ha, {_SLAB: ("off", {})})
    online = "binary_sensor.heating_loxone_online"
    await _inputs(ha, broker, warm="ON")
    assert ha.states.get(_WANTED).state == "off"
    await clock.advance(timedelta(hours=23, minutes=58))
    assert ha.states.get(online).state == "on"
    # The same payload again (a heartbeat): the state does not change, the report does.
    await _inputs(ha, broker, warm="ON", status=False)
    await clock.advance(timedelta(minutes=3))
    assert ha.states.get(online).state == "on", "an identical re-sent payload must keep Loxone online"
    assert ha.states.get(_WANTED).state == "off"
    # Then silence: 24 h after the last (identical) message.
    await clock.advance(timedelta(hours=23, minutes=56))
    assert ha.states.get(online).state == "on"
    await clock.advance(timedelta(minutes=3))
    assert ha.states.get(online).state == "off"
    assert ha.states.get(_WANTED).state == "on"
    # Loxone speaks again with a different payload: warm enough is honoured again.
    await _inputs(ha, broker, warm="OFF", status=False)
    await _inputs(ha, broker, warm="ON", status=False)
    assert ha.states.get(_WANTED).state == "off"


async def test_warm_enough_unknown_or_unavailable_heats(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """A `warm_enough` that is unknown or unavailable is "not warm enough": wanted `on`, written."""
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _season(ha, "neutral")
    await seed(ha, {_SLAB: ("off", {})})
    failures: list[str] = []
    for state in ("unknown", "unavailable"):
        await _master(ha, False)
        await _end_hold(ha)
        # A real warm-enough first (wanted off), then the entity loses its value.
        await _inputs(ha, broker, mode="off", temp="22.0", warm="OFF")
        await _inputs(ha, broker, mode="off", temp="22.0", warm="ON")
        if ha.states.get(_WANTED).state != "off":
            failures.append(f"{state}: warm enough did not give off")
        await seed(ha, {_WARM: (state, {})})
        if ha.states.get(_WANTED).state != "on":
            failures.append(f"{state}: wanted {ha.states.get(_WANTED).state!r}, want 'on'")
        index = len(broker.received)
        await _master(ha, True)
        got = await _fence(ha, broker, index)
        if got != [(_MODE_SET, "on")]:
            failures.append(f"{state}: wrote {got}, want the mode on")
    assert not failures, "\n".join(failures)


async def test_hold_ends_while_disarmed_then_arming_applies_it(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """A change deferred by the hold is not lost when the hold ends with the switch off."""
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _season(ha, "neutral")
    await seed(ha, {_SLAB: ("off", {})})
    await _master(ha, False)
    await _end_hold(ha)
    await _inputs(ha, broker, mode="off", temp="22.0", warm="OFF")
    index = len(broker.received)
    await _master(ha, True)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "on")]
    # The machine echoes; the operator disarms; Loxone then says warm enough.
    await _inputs(ha, broker, mode="on", temp="22.0", warm="OFF")
    await _master(ha, False)
    await _inputs(ha, broker, mode="on", temp="22.0", warm="ON")

    async def refresh() -> None:
        await publish(ha, broker, _STATUS, "25.2;1.5;1.2;heat;0a01")
        await mqtt_sync(ha, broker)

    index = len(broker.received)
    await clock.hold(32 * 60, refresh)
    assert await _fence(ha, broker, index) == [], "wrote while disarmed"
    await _master(ha, True)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "off")]


async def test_stale_read_back_does_not_repeat_writes(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """ebusd never echoes: the mode is not re-sent inside the 30 min hold, the setpoint not in 5 min.

    Other triggers (switch toggles, read-back flips) fire meanwhile; each is re-evaluated against the
    unchanged read-back and must not publish again until its guard has run out.
    """
    await _helpers(ha)
    await wait_subscribed(ha, broker, *_INPUT_TOPICS)
    await _season(ha, "neutral")
    await seed(ha, {_SLAB: ("off", {})})
    await _master(ha, False)
    await _end_hold(ha)
    await clock.align()
    # Wanted: on, 22.0. Read-back stays off / 21.0 whatever HA writes.
    await _inputs(ha, broker, mode="off", temp="21.0", warm="OFF")

    async def refresh() -> None:
        await publish(ha, broker, _STATUS, "25.2;1.5;1.2;heat;0a01")
        await mqtt_sync(ha, broker)

    async def toggle() -> None:
        await _master(ha, False)
        await _master(ha, True)

    index = len(broker.received)
    await _master(ha, True)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "on"), (_TEMP_SET, "22.0")]
    index = len(broker.received)
    await toggle()
    await _inputs(ha, broker, mode="low", temp="21.0", warm="OFF", status=False)
    await _inputs(ha, broker, mode="off", temp="21.0", warm="OFF", status=False)
    assert await _fence(ha, broker, index) == [], "re-published straight away"
    await clock.hold(4 * 60, refresh)
    await toggle()
    assert await _fence(ha, broker, index) == [], "setpoint re-sent inside 5 min / mode inside the hold"
    await clock.hold(2 * 60, refresh)
    await toggle()
    assert await _fence(ha, broker, index) == [(_TEMP_SET, "22.0")], "setpoint not re-sent after 5 min"
    index = len(broker.received)
    await clock.hold(26 * 60, refresh)
    assert await _fence(ha, broker, index) == [(_MODE_SET, "on"), (_TEMP_SET, "22.0")], \
        "mode not re-sent when the hold ended"
