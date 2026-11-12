"""Pergola roof (packages/pergola.yaml, the Loxone blueprint uses in automations.yaml), in-process.

How the tests drive the package (everything through real triggers, never `automation.trigger`):
- The sun is the REAL `sun` integration at the production location (tests/ha/conftest.py sets
  Europe/Vienna and the Linz coordinates and loads `sun`); the frozen clock is moved to real
  dates and times, so sun.sun's elevation and azimuth are what astral computes there. Nothing
  seeds sun.sun.
- The weather station, the Somfy covers and their lock sensors have no integration in the test
  HA: they are seeded (`_Env.seed`), as real state changes, so the state-change and
  numeric_state triggers fire. The covers echo a tilt command like the Somfy does (their
  `current_tilt_position` follows), so the deadband sees what production sees.
- The Victron PV and house load are MQTT sensors: published over the real broker (Venus OS
  `{"value": x}`), republished on every clock step (`expire_after: 120`), as the GX does.
- The season is the REAL heating/cooling indicator, driven through its seeded 48h mean (as in
  the item-2 tests), and the REAL sync automation sets `input_boolean.pergola_heating` from it.
- Effects are the recorded calls of the stubbed actions (cover tilt / stop, Loxone REST),
  attributed to the automation that made them by the context of its `automation_triggered`
  event.

The cover response waits 500 ms (template-cascade settle delay) before every sun-tracking
move. On the frozen clock that timer never comes due by itself, and HA's
`async_block_till_done` waits for the run forever (the airflow tests therefore turn
the pergola automations off). `_settle` therefore runs HA until idle and moves the frozen clock
to a pending timer when it is at most 0.6 s away; every wait in this module goes through it
(`_PergolaClock`, `_Env.seed`, `_Env.act`, `_Env.sync`).

Expected cover angles come from `_Ref`, an independent Python port of the formulas in
doc/pergola/design.md (PG-4), checked against that document's verification table (PG-4.8) and
the old anchors in `test_reference_model`; the HA tests compare HA's sensors and the sent tilt
with `_Ref` evaluated on the sun position HA itself reports.
"""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import freezegun.api
import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import cancelling
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from conftest import (
    REPO,
    Broker,
    Clock,
    apply_baseline,
    entity_id,
    local_at,
    publish,
    wait_subscribed,
)

# ── Entities ──────────────────────────────────────────────────────────────────
# Helper ids come from their YAML keys (fixed); template entities are looked up by unique_id
# (repo rule: never derive an id), see `_Env.__init__`.
_STATE = "input_select.pergola_automation_state"
_HEATING = "input_boolean.pergola_heating"
_AUTOMATIC = "input_boolean.pergola_automatic_enabled"
_OPTIMIZED = "input_boolean.pergola_cooling_optimized"
_DEADBAND = "input_number.pergola_deadband_angle"
_LINKS, _RECHTS = "cover.dach_links", "cover.dach_rechts"
_TEMP = "sensor.wheatherstation_outdoor_temperature"
_RADIATION = "sensor.wheatherstation_solar_radiation"
_UV = "sensor.wheatherstation_uv_index"
_RAIN_RATE = "sensor.wheatherstation_rain_rate"
_HOURLY_RAIN = "sensor.wheatherstation_hourly_rain"
_MEAN = "sensor.wheatherstation_outdoor_temperature_48h_mean"
_ORIGIN = {"links": "sensor.dach_links_priority_lock_originator",
           "rechts": "sensor.dach_rechts_priority_lock_originator"}
_TIMER = {"links": "sensor.dach_links_priority_lock_timer",
          "rechts": "sensor.dach_rechts_priority_lock_timer"}
_T = {"unit_of_measurement": "°C", "device_class": "temperature"}

# Template entities by unique_id (all platform `template`).
_TEMPLATE_UIDS = {
    "a_eff": ("sensor", "pergola_effective_sun_angle"),
    "slat": ("sensor", "pergola_slat_angle"),
    "effective": ("sensor", "pergola_effective_slat_angle"),
    "tilt": ("sensor", "pergola_tilt_position"),
    "pv": ("sensor", "pergola_pv_power"),
    "step": ("sensor", "pergola_rain_recovery_step"),
    "shining": ("binary_sensor", "pergola_sun_shining"),
    "indicator": ("sensor", "heating_cooling_indicator"),
}

# The season through the REAL indicator: one 48h mean per season (thresholds 12 / 16 / 20 from
# the baseline helpers, hysteresis 1 °C; as `_SEASON_MEAN` in test_airflow_cooling.py).
_COOLING_MEAN, _HEATING_MEAN = "17.0", "11.0"  # passive_cooling (heating off) / active_heating

# Venus OS topics of the two Victron inputs the pergola reads (packages/victron.yaml).
_GX = "N/c0619ab4c19e"
_PV_TOPIC = f"{_GX}/solarcharger/279/Yield/Power"
_LOAD_TOPICS = tuple(f"{_GX}/system/0/Ac/Consumption/L{n}/Power" for n in (1, 2, 3))

# Every automation this module keeps on, by its YAML `id` (= registry unique_id) → short name
# used in the recorded calls. `test_automation_set_is_complete` checks this is every automation
# in packages/pergola.yaml and automations.yaml. Everything else is turned off (`pergola_env`).
_AUTOMATIONS = {
    "1771360145720": "watchdog_links",
    "1771361016291": "watchdog_rechts",
    "1771748333394": "responder_links",
    "1771748414999": "responder_rechts",
    "pergola_state_manager": "state_manager",
    "pergola_not_enough_sun_entry": "entry",
    "pergola_not_enough_sun_exit": "exit",
    "pergola_cover_response": "cover_response",
    "pergola_sync_heating_from_indicator": "sync",
    "1770990019738": "loxone_originator",
    "1771331444049": "loxone_timer",
    "1771534982149": "loxone_tilt",
    "1776801083533": "loxone_automatic",
}

# The shading threshold of binary_sensor.pergola_sun_shining (PG-8), with the baseline helpers.
_SENSITIVITY, _PV_FACTOR, _MIN_ELEVATION = 0.9, 3.2, 10.0


def _threshold(elevation: float) -> float:
    """512 W/m² × sin(elevation) × sensitivity (doc/pergola/design.md, PG-8)."""
    return 512 * math.sin(math.radians(elevation)) * _SENSITIVITY


# ── Reference model: doc/pergola/design.md PG-4, ported independently of the YAML ──────────
class _Ref:
    """The PG-4 formulas at the baseline geometry (wall 204°, max tilt 122°, DB 5°, w/d/t 22/20/3).

    Every value is rounded where the YAML sensor rounds it (A_eff, moe, mow to 0.1°; LB to 1°),
    because the next formula reads the rounded sensor state.
    """

    WALL, MT, DB, W, D, T = 204.0, 122.0, 5.0, 22.0, 20.0, 3.0
    R = math.hypot(D, T) / W  # overlap ratio
    PHI = math.degrees(math.atan(T / D))  # thickness angle offset

    @classmethod
    def a_eff(cls, elevation: float, azimuth: float) -> float:
        """PG-4.1: sun height in the slat-perpendicular plane on the 0-180° east-west line."""
        s = abs(math.sin(math.radians(azimuth - cls.WALL)))
        height = 90.0 if s < 0.001 else math.degrees(
            math.atan(math.tan(math.radians(elevation)) / s))
        return round(height, 1) if azimuth < cls.WALL else round(180 - height, 1)

    @classmethod
    def moe(cls, a: float) -> float:
        """PG-4.2 MaxOpenEast: minimum back-face angle for full shade."""
        return round(a + cls.PHI + math.degrees(math.asin(cls.R * math.sin(math.radians(a)))), 1)

    @classmethod
    def mow(cls, a: float) -> float:
        """PG-4.2 MaxOpenWest: maximum front-face angle for full shade."""
        return round(a + cls.PHI - math.degrees(math.asin(cls.R * math.sin(math.radians(a)))), 1)

    @classmethod
    def lower_bound(cls) -> float:
        """PG-4.2 LB: mow at the largest integer A_eff (1..90) whose raw moe ≤ max_tilt − 5."""
        flip = max(a for a in range(1, 91) if a + cls.PHI + math.degrees(
            math.asin(cls.R * math.sin(math.radians(a)))) <= cls.MT - 5)
        return round(flip + cls.PHI - math.degrees(
            math.asin(cls.R * math.sin(math.radians(flip)))), 0)

    @classmethod
    def min_heat(cls) -> float:
        """PG-4.4 break-the-seal angle: acos(d / √(w² + t²)) + atan(t / w)."""
        return round(math.degrees(math.acos(cls.D / math.hypot(cls.W, cls.T)))
                     + math.degrees(math.atan(cls.T / cls.W)), 1)

    @classmethod
    def slat(cls, mode: str, a: float) -> tuple[float, str]:
        """PG-4.3/4.4: (slat angle, branch) for mode `opt`, `std` (cooling) or `heat`."""
        if mode == "opt":
            if a < 90 and cls.moe(a) <= cls.MT - cls.DB:
                s = min(max(90.0, cls.moe(a) + cls.DB), cls.MT)
                branch = "floor_90" if s == 90 else "max_tilt" if s == cls.MT else "moe_plus_db"
            elif a <= 90:
                s, branch = cls.mow(a) - 5, "flip_mow_minus_5"
            else:
                s = min(cls.mow(a) - 5, 90.0)
                branch = "cap_90" if s == 90 else "mow_minus_5"
            return round(min(max(s, 0.0), cls.MT), 1), branch
        if mode == "std":
            lb = cls.lower_bound()
            if a < 90 and cls.moe(a) <= cls.MT - 5:
                s = a + 90 if a + 90 <= cls.MT else cls.MT
                branch = "a_plus_90" if s < cls.MT else "max_tilt"
            else:
                s = max(a - 90, lb)
                branch = "lower_bound" if s == lb else "a_minus_90"
            return round(min(max(s, lb), cls.MT), 1), branch
        if a > cls.MT:
            return round(cls.MT, 1), "max_tilt"
        s = min(max(a, cls.min_heat()), cls.MT)
        return round(s, 1), "floor" if s == cls.min_heat() else "follow"

    @classmethod
    def tilt(cls, slat: float) -> int:
        """PG-4.6: INT(slat / max_tilt × 100 + correction), clamped to 0..100."""
        corr = 6 if slat < 20 else 5.5 if slat < 69 else 0.5
        return min(max(int(slat / cls.MT * 100 + corr), 0), 100)


# doc/pergola/design.md PG-4.8, literally: (azimuth, elevation, A_eff, moe, mow,
# standard slat, standard tilt, optimized slat, optimized tilt, heating slat, heating tilt).
_PG48 = [
    (115, 20, 20.0, 46.9, 10.2, 110.0, 90, 90.0, 74, 33.5, 32),
    (150, 30, 35.5, 76.3, 11.8, 122, 100, 90.0, 74, 35.5, 34),
    (140, 40, 43.0, 90.4, 12.7, 122, 100, 95.4, 78, 43.0, 40),
    (165, 50, 62.2, 125.1, 16.3, 15, 18, 11.3, 15, 62.2, 56),
    (180, 40, 64.1, 128.4, 16.8, 15, 18, 11.8, 15, 64.1, 58),
    (180, 55, 74.1, 144.8, 20.5, 15, 18, 15.5, 18, 74.1, 61),
    (204, 57, 90.0, 165.3, 31.7, 15, 18, 26.7, 27, 90.0, 74),
    (220, 45, 105.4, 176.3, 51.5, 15.4, 18, 46.5, 43, 105.4, 86),
    (240, 40, 125.0, 182.4, 84.7, 35.0, 34, 79.7, 65, 122, 100),
    (260, 30, 145.1, 185.4, 121.9, 55.1, 50, 90.0, 74, 122, 100),
]


def test_reference_model() -> None:
    """`_Ref` reproduces the design's verification table, LB, θ_min and the old anchors.

    No HA: this anchors the reference to the design document, so the HA tests below compare
    the YAML with the design and not with a copy of the YAML.
    """
    failures = []
    for az, el, a, moe, mow, s_std, t_std, s_opt, t_opt, s_heat, t_heat in _PG48:
        got_a = _Ref.a_eff(el, az)
        got = (got_a, _Ref.moe(got_a), _Ref.mow(got_a),
               _Ref.slat("std", got_a)[0], _Ref.tilt(_Ref.slat("std", got_a)[0]),
               _Ref.slat("opt", got_a)[0], _Ref.tilt(_Ref.slat("opt", got_a)[0]),
               _Ref.slat("heat", got_a)[0], _Ref.tilt(_Ref.slat("heat", got_a)[0]))
        want = (a, moe, mow, s_std, t_std, s_opt, t_opt, s_heat, t_heat)
        if got != want:
            failures.append(f"PG-4.8 az {az} el {el}: got {got}, want {want}")
    # PG-4.2 / PG-4.4 baseline constants; PG-4.6 baseline tilt values (8° → 12, 15° → 18, ...).
    for got, want, what in [(_Ref.lower_bound(), 15.0, "LB"), (_Ref.min_heat(), 33.5, "θ_min")] + [
        (_Ref.tilt(s), t, f"tilt({s})") for s, t in ((8, 12), (15, 18), (90, 74), (122, 100))
    ]:
        if got != want:
            failures.append(f"{what}: {got}, want {want}")
    # The Docker suite's seeded anchor A_eff = 67.9° (optimized 13.0, standard 15.0, heating 67.9).
    for mode, want in (("opt", 13.0), ("std", 15.0), ("heat", 67.9)):
        if (got := _Ref.slat(mode, 67.9)[0]) != want:
            failures.append(f"anchor 67.9 {mode}: {got}, want {want}")
    assert not failures, "\n".join(failures)


def test_automation_set_is_complete() -> None:
    """`_AUTOMATIONS` lists exactly the automations of the pergola package and automations.yaml.

    Those are the ones `pergola_env` keeps on; a new automation there must be added (and
    tested), not silently left off.
    """

    class _Loader(yaml.SafeLoader):
        """SafeLoader that ignores HA tags (!input, !secret, ...)."""

    _Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    pergola = yaml.load((REPO / "packages/pergola.yaml").read_text(), Loader=_Loader)
    global_ = yaml.load((REPO / "automations.yaml").read_text(), Loader=_Loader)
    ids = {str(a["id"]) for a in pergola["automation"] + global_}
    assert ids == set(_AUTOMATIONS), (ids ^ set(_AUTOMATIONS))


# ── Running HA until idle on the frozen clock ─────────────────────────────────
def _real_monotonic() -> float:
    """Real monotonic time (freezer replaces time.monotonic; looked up at call time)."""
    return freezegun.api.real_monotonic()


# Script delays up to this long are reached by moving the frozen clock while settling: the
# cover response's 500 ms settle delay. Everything else (delays of seconds or minutes, the /5
# ticks, sun updates, MQTT's 1 s misc loop) only moves with an explicit clock move.
# Just above 500 ms: a drain delay with 1 s left (hold(29) of 30 s) must not be reached.
_SHORT_DELAY = 0.6
# Real time without progress after which the pending tasks count as waiting on the clock (a
# running drain script's 30 s delay, ...): MQTT round trips here take a few ms.
_IDLE = 0.05


async def _wait_real(hass: HomeAssistant, tasks: list[asyncio.Future], seconds: float) -> bool:
    """Wait up to `seconds` of REAL time for any of `tasks`; True if one finished.

    asyncio's own timeouts run on loop.time(), which is frozen, so a thread timer wakes the
    loop instead.
    """
    wake = hass.loop.create_future()

    def _wake() -> None:
        if not wake.done():
            wake.set_result(None)

    timer = threading.Timer(seconds, hass.loop.call_soon_threadsafe, (_wake,))
    timer.start()
    try:
        await asyncio.wait([*tasks, wake], return_when=asyncio.FIRST_COMPLETED)
    finally:
        timer.cancel()
        if not wake.done():
            wake.cancel()
    return any(t.done() for t in tasks)


def _short_script_delay(hass: HomeAssistant) -> float | None:
    """Seconds until the next pending script `delay` that ends within `_SHORT_DELAY`, or None.

    A script delay is a `loop.call_later(delay, _set_result_unless_done, future)`
    (helpers/script.py `_async_futures_with_timeout`), recognised by that callback.
    """
    now = hass.loop.time()
    ahead = [h.when() - now for h in hass.loop._scheduled
             if not h.cancelled() and getattr(h._callback, "__name__", "")
             == "_set_result_unless_done" and h.when() - now <= _SHORT_DELAY]
    return max(min(ahead), 0.0) if ahead else None


async def _settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run HA until idle, like `async_block_till_done` but never stuck on a timer.

    A pending script delay of at most `_SHORT_DELAY` (the cover response's 500 ms) is reached
    by moving the frozen clock to it. Tasks waiting on real I/O (MQTT) get real time. Tasks
    still pending after `_IDLE` real seconds without progress wait on the clock (a delay of
    seconds or minutes): they run on a later clock move, so settling returns.
    """
    me = asyncio.current_task()
    idle_since = _real_monotonic()
    while True:
        await asyncio.sleep(0)
        pending = [t for t in hass._tasks if t is not me and not t.done() and not cancelling(t)]
        if not pending:
            return
        if await _wait_real(hass, pending, 0.002):
            idle_since = _real_monotonic()
            continue
        if (ahead := _short_script_delay(hass)) is not None:
            freezer.tick(timedelta(seconds=ahead + 0.001))
            async_fire_time_changed(hass)
            idle_since = _real_monotonic()
            continue
        if _real_monotonic() - idle_since > _IDLE:
            return


class _PergolaClock(Clock):
    """The conftest Clock, settling with `_settle` instead of `async_block_till_done`."""

    async def _fire(self, background: bool) -> None:
        # Time listeners first, then run HA until idle (short timers included), then make sure
        # HA's MQTT keep-alive ping was answered (see Clock._settle_mqtt_ping).
        async_fire_time_changed(self.hass)
        await _settle(self.hass, self._freezer)
        await self._settle_mqtt_ping()

    async def settle(self) -> None:
        """Run HA until idle without moving the clock past short timers."""
        await _settle(self.hass, self._freezer)


def _next_date(month: int, day: int, after: date) -> date:
    """The first `month`/`day` strictly after `after` (forward-only clock moves)."""
    for year in (after.year, after.year + 1):
        candidate = date(year, month, day)
        if candidate > after:
            return candidate
    raise AssertionError("unreachable")


# ── Test environment ─────────────────────────────────────────────────────────
class _Env:
    """One test's HA, broker and clock, the live Victron inputs, and the recorded calls."""

    def __init__(self, hass: HomeAssistant, broker: Broker, clock: _PergolaClock) -> None:
        self.hass, self.broker, self.clock = hass, broker, clock
        self.ids = {key: entity_id(hass, domain, "template", uid)
                    for key, (domain, uid) in _TEMPLATE_UIDS.items()}
        # Live Victron values, republished on every clock step (None: not published, so the
        # sensor expires 120 s after its last message, as when the MQTT topic goes quiet).
        self.pv: float | None = 200.0
        self.load: float | None = 500.0  # per phase
        self._sync_count = 1000  # values on the sync topic, never repeated within a test

    # ── states ──
    def state(self, key_or_id: str) -> str | None:
        """State of an entity, by `_TEMPLATE_UIDS` key, `heating` (the season boolean) or entity
        id (None if missing)."""
        eid = {"heating": _HEATING}.get(key_or_id) or self.ids.get(key_or_id, key_or_id)
        s = self.hass.states.get(eid)
        return s.state if s else None

    def sun(self) -> tuple[float, float]:
        """sun.sun (elevation, azimuth), as the real integration reports them now."""
        s = self.hass.states.get("sun.sun")
        assert s is not None, "sun.sun missing"
        return float(s.attributes["elevation"]), float(s.attributes["azimuth"])

    # ── inputs ──
    async def seed(self, states: Mapping[str, Any]) -> None:
        """Set states of entities without an integration here (real state changes), then settle.

        A value is a state string or (state, attributes); a cover takes its tilt as an int.
        """
        for eid, value in states.items():
            if eid.startswith("cover."):
                old = self.hass.states.get(eid)
                attrs = dict(old.attributes) if old else {}
                attrs["current_tilt_position"] = int(value)
                self.hass.states.async_set(eid, "open", attrs)
                continue
            state, attrs = (value, {}) if isinstance(value, str) else value
            self.hass.states.async_set(eid, state, dict(attrs))
        await self.clock.settle()

    async def act(self, domain: str, service: str, data: Mapping[str, Any]) -> None:
        """Call a real action (helpers), then settle (the automations it triggers run)."""
        await self.hass.services.async_call(domain, service, dict(data), blocking=True)
        await self.clock.settle()

    async def select(self, option: str) -> None:
        """Set the state machine directly (the user's way to break a deadlock)."""
        await self.act("input_select", "select_option", {"entity_id": _STATE, "option": option})

    async def turn(self, entity: str, on: bool) -> None:
        """Turn an input_boolean on or off through its action."""
        await self.act("input_boolean", "turn_on" if on else "turn_off", {"entity_id": entity})

    async def number(self, entity: str, value: float) -> None:
        """Set an input_number through its action."""
        await self.act("input_number", "set_value", {"entity_id": entity, "value": value})

    async def sync(self) -> None:
        """Republish the live Victron inputs, then wait until HA handled every message.

        Same idea as conftest `mqtt_sync` (one fresh value on the ebusd integral topic, read by
        nothing, proves every earlier message was handled), but it waits with `_settle`.
        """
        if self.pv is not None:
            await publish(self.hass, self.broker, _PV_TOPIC, {"value": self.pv})
        if self.load is not None:
            for topic in _LOAD_TOPICS:
                await publish(self.hass, self.broker, topic, {"value": self.load})
        self._sync_count += 1
        await publish(self.hass, self.broker, "ebusd/ehp/Integral", str(self._sync_count))
        await self.hass.async_add_executor_job(self.broker.flush)
        sync_id = entity_id(self.hass, "sensor", "mqtt", "heating_energy_integral")
        deadline = _real_monotonic() + 5
        while True:
            await self.clock.settle()
            if self.state(sync_id) == f"{self._sync_count}":
                return
            assert _real_monotonic() < deadline, f"MQTT sync {self._sync_count} not seen"
            await self.hass.async_add_executor_job(threading.Event().wait, 0.002)

    # ── clock ──
    async def hold(self, seconds: float) -> None:
        """Move the clock forward in ≤ 60 s steps, republishing the Victron inputs before each."""
        await self.clock.hold(seconds, self.sync)

    async def move_to(self, when: datetime) -> None:
        """Jump forward to `when` (fires every overdue timer: sun update, /5 ticks, expiries),
        then republish the Victron inputs (the jump expired them, as a GX outage would)."""
        await self.clock.move_to(when)
        await self.sync()

    async def hold_until(self, when: datetime) -> None:
        """Move forward to `when` in ≤ 60 s steps (`hold`)."""
        await self.hold((when - dt_util.now()).total_seconds())

    # ── recorded calls ──
    def calls(self, *kinds: str) -> list[str]:
        """Recorded calls since `clear` as 'owner: call', sorted; `kinds` filters by call kind
        (`tilt`, `stop`, `loxone`). The owner is the automation whose run made the call."""
        owners = self.hass.data["pergola_call_owner"]
        out = []
        for action, calls in self.hass.data["service_calls"].items():
            for call in calls:
                kind, text = _fmt_call(action, call.data)
                if not kinds or kind in kinds:
                    out.append(f"{owners.get(call.context.id, '?')}: {text}")
        return sorted(out)

    def clear(self) -> None:
        """Forget every recorded call."""
        for calls in self.hass.data["service_calls"].values():
            calls.clear()


def _fmt_call(action: str, data: Mapping[str, Any]) -> tuple[str, str]:
    """(kind, short text) of one recorded call."""
    eids = data.get("entity_id") or []
    eids = [eids] if isinstance(eids, str) else list(eids)
    if action == "cover.set_cover_tilt_position":
        # One call moves both covers (PG-4.6); anything else is shown in full.
        both = sorted(eids) == sorted([_LINKS, _RECHTS])
        return "tilt", f"tilt={data['tilt_position']}" + ("" if both else f" {eids}")
    if action == "cover.stop_cover_tilt":
        return "stop", "stop " + ",".join(e.split(".")[1] for e in eids)
    if action == "rest_command.send_to_loxone":
        return "loxone", f"loxone {data['input_name']}={data['value']}"
    return "other", f"{action} {dict(data)}"


@pytest.fixture
async def pergola_ha(ha: HomeAssistant) -> HomeAssistant:
    """The repo HA prepared for the pergola, still on the real clock (so the cover response's
    settle delay passes by itself; request it BEFORE `freezer`, as `pergola_env` does):
    - the shared baseline, without the MQTT states (driven over the broker), the REAL sun
      shining and indicator sensors (computed), and the Somfy "no lock" written as production
      shows it (`unknown`, PG-2.4; the shared baseline says `none`);
    - the sync automation back on (the shared baseline turns it off for other packages);
    - every automation outside `_AUTOMATIONS` off: the other packages' runs wait on timers
      longer than any clock move here (as in test_airflow_cooling.py, the other way round);
    - the cover echo and the call-owner listener.
    """
    await apply_baseline(ha, mqtt=False, skip={entity_id(ha, d, "template", u)
                                               for d, u in (_TEMPLATE_UIDS["shining"],
                                                            _TEMPLATE_UIDS["indicator"])})
    for eid in [*_ORIGIN.values(), *_TIMER.values()]:
        ha.states.async_set(eid, "unknown", {})
    keep = {entity_id(ha, "automation", "automation", uid) for uid in _AUTOMATIONS}
    others = [e for e in ha.states.async_entity_ids("automation") if e not in keep]
    await ha.services.async_call("automation", "turn_off", {"entity_id": others}, blocking=True)
    await ha.services.async_call("automation", "turn_on", {"entity_id": sorted(keep)},
                                 blocking=True)
    names = {entity_id(ha, "automation", "automation", uid): name
             for uid, name in _AUTOMATIONS.items()}
    owners: dict[str, str] = ha.data.setdefault("pergola_call_owner", {})

    @callback
    def _triggered(event: Event) -> None:
        # Every run's actions (and the scripts it starts) carry this event's context.
        owners[event.context.id] = names.get(event.data["entity_id"], event.data["entity_id"])

    ha.bus.async_listen("automation_triggered", _triggered)
    _install_cover_echo(ha)
    await ha.async_block_till_done()
    return ha


@pytest.fixture
async def pergola_env(
    pergola_ha: HomeAssistant, broker: Broker, freezer: FrozenDateTimeFactory
) -> AsyncIterator[_Env]:
    """`pergola_ha` on a frozen clock (`freezer` after it): every boot-time timer fired, the
    Victron inputs published, the recorded calls cleared."""
    ha = pergola_ha
    clock = _PergolaClock(ha, freezer)
    await clock.advance(0)
    env = _Env(ha, broker, clock)
    await wait_subscribed(ha, broker, _PV_TOPIC, *_LOAD_TOPICS)
    await env.sync()
    env.clear()
    yield env
    # A scenario that fails midway leaves the post-rain drain waiting on its delay; on the
    # frozen clock that delay never ends and HA's shutdown would wait for it. Stop it.
    await ha.services.async_call(
        "script", "turn_off", {"entity_id": "script.pergola_post_rain_recovery"}, blocking=True)


def _install_cover_echo(hass: HomeAssistant) -> None:
    """Record tilt commands AND report the new tilt on both covers, as the Somfy does."""
    calls = hass.data["service_calls"]["cover.set_cover_tilt_position"]

    async def handler(call: ServiceCall) -> None:
        calls.append(call)
        eids = call.data.get("entity_id")
        for eid in [eids] if isinstance(eids, str) else eids or []:
            old = hass.states.get(eid)
            attrs = dict(old.attributes) if old else {}
            attrs["current_tilt_position"] = int(call.data["tilt_position"])
            hass.states.async_set(eid, "open", attrs)

    hass.services.async_register("cover", "set_cover_tilt_position", handler)


def _same(got: Any, want: Any) -> bool:
    """Equal; a numeric `want` compares with the state string as a number ("90" == 90.0)."""
    if isinstance(want, (int, float)) and isinstance(got, str):
        try:
            return float(got) == want
        except ValueError:
            return False
    return got == want


def _at(day: date, hour: int, minute: int, second: int = 30) -> datetime:
    """Local wall-clock time on `day` (Europe/Vienna); half past the minute by default, so a
    /5 tick (at hh:mm:00 + < 1 s) is never inside the same second as a check."""
    return local_at(day, hour, minute, second)


async def _sunny(env: _Env, day: date, hour: int = 11, minute: int = 52) -> None:
    """Put the pergola into sun tracking: a cooling-season March day around noon, bright sun.

    Jump to `day` hour:minute:30, radiation 800 W/m² (far above any threshold), then hold
    8 min (crosses two /5 ticks; sun shining's 1 min delay_on passes).
    """
    await env.move_to(_at(day, hour, minute))
    await env.seed({_RADIATION: ("800", {"unit_of_measurement": "W/m²"}), _UV: "0",
                    _MEAN: (_COOLING_MEAN, _T)})
    await env.hold(8 * 60)


# ── Cover formulas: the move made on the not_enough_sun → sun-tracking edge ────────────
@dataclass
class Formula:
    """One sun position and mode: the move the cover response makes when the sun comes out."""

    name: str
    day: tuple[int, int]  # month, day (early March: CET, sun inside the azimuth window)
    at: tuple[int, int]  # hour, minute of the trigger (minute ≡ 2 mod 5: no /5 tick nearby)
    mode: str  # opt / std (cooling, optimized on/off) or heat
    branch: str  # the _Ref branch this sun position exercises (checked)


# Each branch of PG-4.3/4.4 once; times chosen so the branch holds in every year (checked
# for 2026-2039; `branch` is asserted, so a drift fails by name rather than silently).
FORMULAS = [
    Formula("optimized_morning_floor_90", (3, 2), (9, 32), "opt", "floor_90"),
    Formula("optimized_morning_moe_plus_deadband", (3, 4), (11, 52), "opt", "moe_plus_db"),
    Formula("optimized_flip_range_mow_minus_5", (3, 5), (13, 22), "opt", "flip_mow_minus_5"),
    Formula("optimized_afternoon_mow_minus_5", (3, 6), (14, 22), "opt", "mow_minus_5"),
    Formula("optimized_afternoon_cap_90", (3, 7), (16, 2), "opt", "cap_90"),
    Formula("standard_morning_a_plus_90", (3, 8), (9, 32), "std", "a_plus_90"),
    Formula("standard_morning_dead_zone_max_tilt", (3, 9), (10, 32), "std", "max_tilt"),
    Formula("standard_flip_lower_bound", (3, 10), (12, 32), "std", "lower_bound"),
    Formula("standard_afternoon_a_minus_90", (3, 11), (15, 2), "std", "a_minus_90"),
    Formula("heating_floor_min_heating_angle", (3, 12), (9, 32), "heat", "floor"),
    Formula("heating_follows_the_sun", (3, 13), (12, 32), "heat", "follow"),
    Formula("heating_dead_zone_max_tilt", (3, 14), (16, 2), "heat", "max_tilt"),
]


async def _run_formulas(env: _Env, cases: list[Formula]) -> list[str]:
    """Run formula cases in order on one HA; one message per failed check.

    Per case: jump to the case day 6 min before the trigger (the sun is recomputed at the jump
    and next 4 min later, so it holds still from 2 min before the trigger until 2 min after);
    reset: radiation 5 W/m², UV 0 (sun shining turns off after its 5 min delay_off and the
    entry automation sets not_enough_sun), the case's season (48h mean → indicator → sync →
    pergola_heating) and cooling mode; the reset is CHECKED. Then both covers are put far from
    the expected tilt, the recorded calls cleared, and the radiation raised to 800 W/m²: after
    sun shining's 1 min delay_on the exit automation sets the sun state and the cover response
    moves. Checked against `_Ref` on the sun position HA reports.
    """
    failures: list[str] = []
    day = dt_util.now().date()
    for case in cases:
        day = _next_date(*case.day, after=day)
        trigger = _at(day, *case.at)
        await env.move_to(trigger - timedelta(minutes=6))
        heating = case.mode == "heat"
        await env.seed({_RADIATION: ("5", {"unit_of_measurement": "W/m²"}), _UV: "0",
                        _MEAN: (_HEATING_MEAN if heating else _COOLING_MEAN, _T)})
        await env.turn(_OPTIMIZED, case.mode == "opt")
        await env.hold_until(trigger)
        reset = {"state": env.state(_STATE), "shining": env.state("shining"),
                 "heating": env.state(_HEATING)}
        want_reset = {"state": "not_enough_sun", "shining": "off",
                      "heating": "on" if heating else "off"}
        if reset != want_reset:
            failures.append(f"{case.name} (reset): {reset}, want {want_reset}")
        elevation, azimuth = env.sun()
        a = _Ref.a_eff(elevation, azimuth)
        slat, branch = _Ref.slat(case.mode, a)
        tilt = _Ref.tilt(slat)
        if branch != case.branch:
            failures.append(f"{case.name}: sun el {elevation} az {azimuth} → A_eff {a} is in "
                            f"branch {branch}, not {case.branch} (pick another time)")
        far = 0 if tilt >= 50 else 100  # outside every deadband
        await env.seed({_LINKS: far, _RECHTS: far})
        env.clear()
        await env.seed({_RADIATION: ("800", {"unit_of_measurement": "W/m²"})})
        await env.hold(61)
        want_state = "sun_automatik_heating" if heating else "sun_automatik_cooling"
        got = {"state": env.state(_STATE), "a_eff": env.state("a_eff"),
               "slat": env.state("slat"), "effective": env.state("effective"),
               "tilt": env.state("tilt"), "calls": env.calls("tilt")}
        want = {"state": want_state, "a_eff": a, "slat": slat, "effective": slat,
                "tilt": tilt, "calls": [f"cover_response: tilt={tilt}"]}
        for key in want:
            if not _same(got[key], want[key]):
                failures.append(f"{case.name} (sun el {elevation} az {azimuth}): {key} "
                                f"{got[key]!r}, want {want[key]!r}")
    return failures


# The season comes from the REAL heating_cooling_indicator (seeded 48h mean → sync automation):
# a change to its YAML can fail this test, so it also runs under `--package heating_cooling_indicator`.
@pytest.mark.package("heating_cooling_indicator")
async def test_cover_formulas(pergola_env: _Env) -> None:
    """Every slat-angle branch (PG-4.3/4.4) on a real sun position; one HA, one assert."""
    failures = await _run_formulas(pergola_env, FORMULAS)
    assert not failures, f"{len(failures)} formula check(s) failed:\n" + "\n".join(failures)



# ── Deadbands: what a /5 tick does with the covers near the target ───────────────────────
@dataclass
class Deadband:
    """Covers put near the target, then one /5 tick: does the cover response move them?"""

    name: str
    day: tuple[int, int]
    at: tuple[int, int]  # minute ≡ 3 mod 5: the next tick is 90 s later, the sun holds still
    mode: str  # opt / std: cooling, sun shining; nes: not_enough_sun (no sun)
    covers: tuple[int, int]  # links, rechts: offset from the target tilt
    moves: bool


# PG-5.1: DB_tilt = round(5 / 122 × 100) = 4; move when max(|links − target|, |rechts −
# target|) >= 4, or target >= 100. PG-5.2: not_enough_sun moves to 90° (tilt 74) only when the
# deviation is > round(30 / 122 × 100) = 25.
DEADBANDS = [
    Deadband("tracking_3_below_holds", (3, 2), (11, 23), "opt", (-3, -3), False),
    Deadband("tracking_3_above_holds", (3, 3), (11, 23), "opt", (3, 3), False),
    Deadband("tracking_rechts_4_above_moves_both", (3, 4), (11, 23), "opt", (0, 4), True),
    Deadband("tracking_links_4_below_moves_both", (3, 5), (11, 23), "opt", (-4, 0), True),
    Deadband("tracking_dead_zone_target_100_is_always_resent", (3, 6), (10, 33), "std", (0, 0),
             True),
    Deadband("not_enough_sun_25_off_holds", (3, 7), (11, 23), "nes", (-25, -25), False),
    Deadband("not_enough_sun_26_off_moves", (3, 8), (11, 23), "nes", (0, -26), True),
]


# The season comes from the REAL heating_cooling_indicator (seeded 48h mean → sync automation):
# a change to its YAML can fail this test, so it also runs under `--package heating_cooling_indicator`.
@pytest.mark.package("heating_cooling_indicator")
async def test_deadbands(pergola_env: _Env) -> None:
    """Sun-tracking and not_enough_sun deadbands (PG-5) on real ticks; one HA, one assert.

    Per case (each on its own day): 10:00 the inputs are set and settle for 8 min (state
    checked); then the clock jumps to the case time, where the sun is recomputed and the
    overdue /5 tick makes the cover response move to the target (the covers echo it). The
    covers are then put at target + offset, and the next tick (90 s later, same sun) decides.
    """
    env = pergola_env
    failures: list[str] = []
    day = dt_util.now().date()
    for case in DEADBANDS:
        day = _next_date(*case.day, after=day)
        await env.move_to(_at(day, 10, 0))
        radiation = "5" if case.mode == "nes" else "800"
        await env.seed({_RADIATION: (radiation, {"unit_of_measurement": "W/m²"}), _UV: "0",
                        _MEAN: (_COOLING_MEAN, _T)})
        await env.turn(_OPTIMIZED, case.mode == "opt")
        await env.hold(8 * 60)
        await env.move_to(_at(day, *case.at))
        want_state = "not_enough_sun" if case.mode == "nes" else "sun_automatik_cooling"
        if (got := env.state(_STATE)) != want_state:
            failures.append(f"{case.name} (reset): state {got}, want {want_state}")
        target = int(float(env.state("tilt") or "nan"))
        positions = [min(max(target + off, 0), 100) for off in case.covers]
        await env.seed({_LINKS: positions[0], _RECHTS: positions[1]})
        env.clear()
        await env.hold(91)
        want = [f"cover_response: tilt={target}"] if case.moves else []
        if (got_calls := env.calls("tilt")) != want:
            failures.append(f"{case.name} (target {target}, covers {positions}): calls "
                            f"{got_calls}, want {want}")
    assert not failures, f"{len(failures)} deadband check(s) failed:\n" + "\n".join(failures)


# ── Sun rules: rules 5-9 of script.pergola_evaluate_state on real sun positions ─────────
@dataclass
class SunCase:
    """Inputs at a real time; the state the state machine settles in, and a steady tick."""

    name: str
    day: tuple[int, int]
    at: tuple[int, int]  # minute ≡ 2 mod 5: ticks 2.5 and 7.5 min later
    radiation: float | str  # W/m², or "below"/"above": 30 W/m² off the shading threshold
    expect: str
    shining: str
    uv: float = 0
    pv: float | str | None = 200.0  # W; None: MPPT topic quiet (expires); "above": PV path
    mean: str = _COOLING_MEAN
    start: str = "not_enough_sun"
    steady: list[str] | None = None  # tilt calls of the next /5 tick; None: not checked


_NO_SUN_STEADY = ["cover_response: tilt=74"]  # 90° re-sent on every tick, no deadband

SUN_CASES = [
    # Night: radiation 0 and the MPPT topic quiet (expired) while the house load reports →
    # pergola PV 0 → sun_down; the cover response never moves in sun_down. Docker:
    # test_sun_down_state, test_pv_power_zero_at_night_when_mppt_stale (state part).
    SunCase("sun_down_at_night_with_the_mppt_topic_quiet", (3, 2), (22, 2), 0, "sun_down",
            "off", pv=None, start="sun_automatik_cooling", steady=[]),
    # Shading threshold 512 × sin(el) × 0.9, radiation 30 W/m² below / above it (new).
    SunCase("not_enough_sun_below_the_shading_threshold", (3, 3), (11, 2), "below",
            "not_enough_sun", "off", pv=0, start="sun_automatik_cooling", steady=[]),
    SunCase("shining_above_the_shading_threshold", (3, 4), (11, 2), "above",
            "sun_automatik_cooling", "on", pv=0),
    # UV ≥ 3 alone, and PV / conversion factor alone, count as shining (new).
    SunCase("uv_index_3_counts_as_shining", (3, 5), (11, 2), 20, "sun_automatik_cooling", "on",
            uv=3, pv=0),
    SunCase("pv_alone_counts_as_shining", (3, 6), (11, 2), 20, "sun_automatik_cooling", "on",
            pv="above"),
    # Heating season (indicator active_heating → pergola_heating on) → heating state (new).
    SunCase("heating_season_gives_sun_automatik_heating", (3, 7), (11, 2), 800,
            "sun_automatik_heating", "on", mean=_HEATING_MEAN),
    # Azimuth window wall ± 90° = 114°-294°: a June morning just east of it (az ≈ 108°,
    # elevation ≈ 46°: bright sun) → no_sun_behind_house; an hour later (az ≈ 124°) inside.
    # Docker: test_no_sun_behind_house (seeded sun.sun az 350).
    SunCase("no_sun_behind_house_east_of_the_azimuth_window", (6, 21), (10, 2), 800,
            "no_sun_behind_house", "on", start="sun_automatik_cooling", steady=_NO_SUN_STEADY),
    SunCase("sun_inside_the_azimuth_window", (6, 22), (11, 2), 800, "sun_automatik_cooling",
            "on"),
    # Min elevation 10°: a December morning at ≈ 8-9° (azimuth ≈ 140°, inside the window) →
    # no_sun_behind_house, and sun shining is off by its own elevation guard; an hour later
    # (≈ 13°) the sun counts. Docker: test_not_enough_sun (June 04:00 UTC, elevation ≈ 3°).
    SunCase("no_sun_behind_house_below_min_elevation", (12, 21), (9, 2), 300,
            "no_sun_behind_house", "off", start="sun_automatik_cooling",
            steady=_NO_SUN_STEADY),
    SunCase("sun_just_above_min_elevation", (12, 22), (10, 2), 300, "sun_automatik_cooling",
            "on"),
]


# Two other packages: the season comes from the REAL heating_cooling_indicator, and the
# "PV alone counts as shining" cases are fed by the real Victron MQTT sensors (victron.yaml).
@pytest.mark.package("heating_cooling_indicator", "victron")
async def test_sun_rules(pergola_env: _Env) -> None:
    """Rules 5-9 and sun shining (PG-2.2, PG-8) on real sun positions; one HA, one assert.

    Per case (each on its own day): the case's start state is set, the clock jumps to the case
    time, the inputs are set, then 8 min pass (two /5 ticks; sun shining's delays). Checked:
    the state, sun shining, and sun shining against PG-8 on the final elevation; then the
    calls of one more tick where given. The start state differs from the expected one, so
    each case is a real transition.
    """
    env = pergola_env
    failures: list[str] = []
    day = dt_util.now().date()
    for case in SUN_CASES:
        day = _next_date(*case.day, after=day)
        await env.select(case.start)
        await env.move_to(_at(day, *case.at))
        elevation, _ = env.sun()
        threshold = _threshold(elevation)
        radiation = {"below": threshold - 30, "above": threshold + 30}.get(
            case.radiation, case.radiation)  # type: ignore[call-overload]
        env.pv = (threshold + 30) * _PV_FACTOR if case.pv == "above" else case.pv  # type: ignore[assignment]
        await env.sync()
        await env.seed({_RADIATION: (f"{radiation:.0f}", {"unit_of_measurement": "W/m²"}),
                        _UV: f"{case.uv}", _MEAN: (case.mean, _T)})
        await env.hold(8 * 60)
        elevation, azimuth = env.sun()
        pv = float(env.state("pv") or 0)
        formula = elevation > _MIN_ELEVATION and (
            max(float(f"{radiation:.0f}"), pv / _PV_FACTOR) > _threshold(elevation)
            or case.uv >= 3)
        got = {"state": env.state(_STATE), "shining": env.state("shining")}
        want = {"state": case.expect, "shining": case.shining}
        if got != want:
            failures.append(f"{case.name} (sun el {elevation} az {azimuth}): {got}, want {want}")
        if (case.shining == "on") != formula:
            failures.append(f"{case.name}: PG-8 on el {elevation} gives shining {formula}")
        if case.steady is not None:
            env.clear()
            await env.hold(5 * 60)
            if (calls := env.calls("tilt")) != case.steady:
                failures.append(f"{case.name}: steady tick calls {calls}, want {case.steady}")
        env.pv = 200.0
    assert not failures, f"{len(failures)} sun rule check(s) failed:\n" + "\n".join(failures)


# ── Protected states: frost, rain, rain_stopped, user_override; the master switch ──────────
# Each scenario is a forward sequence on ONE fresh HA (parametrized: the protected states hold
# a running drain script and leave only through their own exit rule, so no clean per-case
# reset exists). Each starts in sun tracking on a sunny March noon (`_start`).
Check = Callable[..., None]


async def _start(env: _Env) -> Check:
    """Sunny March day, cooling season, optimized cooling: sun_automatik_cooling at 12:00:30.

    Returns `check(where, **want)`: each key of `want` is `state`, a `_TEMPLATE_UIDS` key or
    `tilt_calls`/`stop_calls` (the recorded calls of that kind since the last `env.clear()`);
    every mismatch is collected in `env.hass.data["pergola_failures"]`.
    """
    await _sunny(env, _next_date(3, 10, after=dt_util.now().date()))
    failures: list[str] = env.hass.data.setdefault("pergola_failures", [])

    def check(where: str, **want: Any) -> None:
        for key, value in want.items():
            if key == "state":
                got: Any = env.state(_STATE)
            elif key.endswith("_calls"):
                got = env.calls(key.removesuffix("_calls"))
            else:
                got = env.state(key)
            if not _same(got, value):
                failures.append(f"{where}: {key} {got!r}, want {value!r}")

    check("start", state="sun_automatik_cooling", shining="on")
    return check


def _move(env: _Env, mode: str = "opt") -> list[str]:
    """The cover response's tilt call for `mode` at the sun position HA reports now (`_Ref`)."""
    slat, _ = _Ref.slat(mode, _Ref.a_eff(*env.sun()))
    return [f"cover_response: tilt={_Ref.tilt(slat)}"]


async def _far(env: _Env, mode: str = "opt") -> None:
    """Put both covers outside every deadband of the current target (a following sun-tracking
    move is then certain)."""
    slat, _ = _Ref.slat(mode, _Ref.a_eff(*env.sun()))
    far = 0 if _Ref.tilt(slat) >= 50 else 100
    await env.seed({_LINKS: far, _RECHTS: far})


async def _frost(env: _Env, check: Check) -> None:
    """Frost entry below 2.5 °C (tested at 2.0, so a lower threshold fails), hold, 0.5 °C
    hysteresis, exit above 3.0 °C to sun tracking.

    Docker: test_frost_entry (state + slat 90), test_frost_recovery (state leaves frost).
    """
    env.clear()
    await env.seed({_TEMP: ("2.0", _T)})  # numeric_state below 2.5 fires at once
    check("frost entry", state="frost", slat=90, tilt_calls=[])
    await env.hold(5 * 60)  # a /5 tick: protected guard and the cover response no-op
    check("frost, one tick later", state="frost", tilt_calls=[])
    await env.seed({_TEMP: ("2.8", _T)})
    check("2.8 °C: inside the hysteresis", state="frost", tilt_calls=[])
    await _far(env)
    env.clear()
    await env.seed({_TEMP: ("3.5", _T)})  # exit → exit_to_normal → evaluate_state
    check("3.5 °C: frost exit, no hourly rain", state="sun_automatik_cooling",
          tilt_calls=_move(env))


async def _frost_exit_drains(env: _Env, check: Check) -> None:
    """Frost exit with rain in the last hour: rain_stopped and the full drain (PG-6.1).

    Exact delays: 30 s settle, 8° (tilt 12) for 5 min, 15° (tilt 18) for 5 min, 30 min more
    while the hourly rain stays > 0, then evaluate_state. The watchdogs stay silent the whole
    time (suppressed in rain_stopped). Docker: test_post_rain_recovery (step sensor only).
    """
    await env.seed({_TEMP: ("-1.5", _T)})
    await env.seed({_HOURLY_RAIN: ("0.4", {"unit_of_measurement": "mm"})})
    env.clear()
    await env.seed({_TEMP: ("3.5", _T)})
    check("exit with hourly rain", state="rain_stopped", step=1, tilt_calls=[])
    await env.hold(29)
    check("drain: 29 s", step=1, tilt_calls=[])
    await env.hold(1)
    check("drain: 30 s → 8°", step=2, tilt_calls=["state_manager: tilt=12"], effective=8)
    env.clear()
    await env.hold(299)
    check("drain: 8° held 299 s", step=2, tilt_calls=[])
    await env.hold(1)
    check("drain: 5 min → 15°", step=3, tilt_calls=["state_manager: tilt=18"], effective=15)
    env.clear()
    await env.hold(300)
    check("drain: 15° held 5 min → drying", state="rain_stopped", step=4, tilt_calls=[])
    await env.hold(1799)
    check("drain: drying 1799 s", state="rain_stopped", step=4, tilt_calls=[], stop_calls=[])
    await _far(env)
    env.clear()
    await env.hold(1)
    check("drain: 30 min dried → evaluate", state="sun_automatik_cooling", step=0,
          tilt_calls=_move(env))


async def _rain_rate(env: _Env, check: Check) -> None:
    """Weather-station rain: rain, hold, rain_stopped when it ends, the short drain (no hourly
    rain: the 8° step and the 30 min drying are skipped). Docker: test_rain_starts."""
    env.clear()
    await env.seed({_RAIN_RATE: ("2.5", {"unit_of_measurement": "mm/h"})})
    check("rain rate 2.5", state="rain", slat=90, tilt_calls=[])
    await env.hold(5 * 60)
    check("rain, one tick later", state="rain", tilt_calls=[])
    await env.seed({_RAIN_RATE: ("0", {"unit_of_measurement": "mm/h"})})
    check("rain ends, locks clear", state="rain_stopped", step=1, tilt_calls=[])
    await env.hold(30)
    check("drain: 30 s → 15° (8° skipped)", step=3, tilt_calls=["state_manager: tilt=18"])
    env.clear()
    await env.hold(299)
    check("drain: 15° held 299 s", state="rain_stopped", tilt_calls=[])
    await _far(env)
    env.clear()
    await env.hold(1)
    check("drain: 5 min → evaluate (no drying wait)", state="sun_automatik_cooling", step=0,
          tilt_calls=_move(env))


async def _cover_lock(env: _Env, check: Check) -> None:
    """Somfy rain lock → rain; the user operates a cover during rain → user_override; both
    locks clear → sun tracking. The lock responders force a report on every originator change.
    Docker: test_rain_lock_from_cover (both = rain), test_rain_with_user_originator."""
    env.clear()
    await env.seed({_ORIGIN["links"]: "rain"})
    check("links rain lock", state="rain", slat=90, tilt_calls=[],
          stop_calls=["responder_links: stop dach_links"])
    env.clear()
    await env.seed({_ORIGIN["rechts"]: "rain"})
    check("rechts rain lock too", state="rain", stop_calls=["responder_rechts: stop dach_rechts"])
    await env.seed({_ORIGIN["links"]: "user"})
    check("user operates links during rain", state="user_override")
    env.clear()
    await env.hold(5 * 60)
    check("user_override, one tick later", state="user_override", tilt_calls=[])
    # rechts first: links still 'user' blocks rain entry (rule 2 guard), override holds.
    await env.seed({_ORIGIN["rechts"]: "unknown"})
    check("rechts lock clears", state="user_override")
    await _far(env)
    env.clear()
    await env.seed({_ORIGIN["links"]: "unknown"})
    check("both locks clear → exit_to_normal", state="sun_automatik_cooling",
          tilt_calls=_move(env))


async def _user_override(env: _Env, check: Check) -> None:
    """User lock from sun tracking → user_override, which rain cannot take over (guard on the
    user lock); the lock clears while it still rains → the state manager's rain entry (rule 2,
    ahead of the user_override exit rule) goes straight to rain, without a sun state in
    between. (The YAML comment at rule 2 → user_override says the exit path runs first and rain
    follows on the next trigger; the code does not do that: reported as a finding.)
    Docker: test_user_override_left (user_override left, driven through dach_links: the first
    two steps restore that side; the new scenario below uses dach_rechts)."""
    env.clear()
    # Rule 4 has one `or` over the two covers; each half needs its own entry check (a mutant
    # that drops the links half survived the rechts-only scenario).
    await env.seed({_ORIGIN["links"]: "user", _TIMER["links"]: "300"})
    check("links user lock", state="user_override", tilt_calls=[])
    await env.seed({_ORIGIN["links"]: "unknown", _TIMER["links"]: "unknown"})
    check("links lock clears (dry) → exit_to_normal", state="sun_automatik_cooling")
    env.clear()
    await env.seed({_ORIGIN["rechts"]: "user", _TIMER["rechts"]: "300"})
    check("rechts user lock", state="user_override", tilt_calls=[],
          stop_calls=["responder_rechts: stop dach_rechts"])
    await env.seed({_RAIN_RATE: ("2.5", {"unit_of_measurement": "mm/h"})})
    check("rain while the user lock holds", state="user_override")
    await env.hold(5 * 60)
    check("user_override, one tick later", state="user_override")
    await env.seed({_ORIGIN["rechts"]: "unknown", _TIMER["rechts"]: "unknown"})
    check("lock clears while raining → rain at once", state="rain")
    await env.hold(5 * 60)
    check("rain, one tick later", state="rain")


async def _master_switch(env: _Env, check: Check) -> None:
    """Master switch off: the state machine and the sensors keep running, the covers do not
    move and the last commanded angle stays (PG-6.3); on again, the next transition moves.
    Docker: test_automation_disabled."""
    before = env.state("effective")
    await env.turn(_AUTOMATIC, False)
    await _far(env, "heat")
    env.clear()
    await env.seed({_MEAN: (_HEATING_MEAN, _T)})  # indicator → sync → heating → evaluate
    slat, _ = _Ref.slat("heat", _Ref.a_eff(*env.sun()))
    check("master off, season → heating", state="sun_automatik_heating", heating="on",
          slat=slat, effective=before, tilt_calls=[])
    await env.turn(_AUTOMATIC, True)
    check("master on: no trigger yet", tilt_calls=[])
    await _far(env)
    await env.seed({_MEAN: (_COOLING_MEAN, _T)})  # season back → cooling → cover response
    check("master on, season → cooling", state="sun_automatik_cooling", heating="off",
          tilt_calls=_move(env))


PROTECTED = {
    "frost": _frost,
    "frost_exit_with_hourly_rain_drains": _frost_exit_drains,
    "rain_rate": _rain_rate,
    "cover_rain_lock_then_user": _cover_lock,
    "user_override": _user_override,
    "master_switch": _master_switch,
}


# Only the master-switch scenario drives the REAL heating_cooling_indicator (season flip), so only
# that parameter also runs under `--package heating_cooling_indicator`.
@pytest.mark.parametrize(
    "scenario",
    [pytest.param(k, marks=pytest.mark.package("heating_cooling_indicator")) if k == "master_switch" else k
     for k in PROTECTED],
)
async def test_protected_states(pergola_env: _Env, scenario: str) -> None:
    """Protected states and the master switch: one forward scenario per fresh HA."""
    check = await _start(pergola_env)
    await PROTECTED[scenario](pergola_env, check)
    failures = pergola_env.hass.data["pergola_failures"]
    assert not failures, f"{len(failures)} {scenario} check(s) failed:\n" + "\n".join(failures)


# ── PV wrapper over the real broker ───────────────────────────────────────────
# sensor.pergola_pv_power wraps the REAL Victron MQTT sensors (solar yield DC, AC load total):
# a change to victron.yaml can fail this test, so it also runs under `--package victron`.
@pytest.mark.package("victron")
async def test_pv_power_wrapper(pergola_env: _Env) -> None:
    """sensor.pergola_pv_power (PG-8): MPPT value; 0 when the MPPT topic is quiet but the GX
    reports (house load); unavailable when both are quiet; sun shining stays available while
    the weather station reports. Expiry is the real `expire_after: 120`.

    Docker: test_pv_power_zero_at_night_when_mppt_stale (wrapper part; it seeded
    `unavailable`). New: both quiet, the MPPT coming back alone, sun shining's availability.
    """
    env = pergola_env
    failures: list[str] = []
    dc = "sensor.victron_solar_yield_dc_watts"  # default_entity_id in packages/victron.yaml

    def check(where: str, **want: str) -> None:
        for key, value in want.items():
            if (got := env.state(dc if key == "dc" else key)) != value:
                failures.append(f"{where}: {key} {got!r}, want {value!r}")

    await env.move_to(_at(_next_date(3, 10, after=dt_util.now().date()), 12, 2))
    env.pv = 1500.0
    await env.sync()
    check("MPPT 1500 W", dc="1500", pv="1500.0")
    env.pv = None
    await env.hold(121)
    check("MPPT topic quiet 121 s, GX reports", dc="unavailable", pv="0")
    env.load = None
    await env.hold(121)
    check("GX quiet too", pv="unavailable")
    await env.seed({_RADIATION: ("unavailable", {})})
    check("weather station gone as well", shining="unavailable")
    env.pv = 800.0
    await env.sync()
    check("MPPT back alone", dc="800", pv="800.0")
    if env.state("shining") == "unavailable":
        failures.append("MPPT back: sun shining still unavailable")
    assert not failures, f"{len(failures)} PV check(s) failed:\n" + "\n".join(failures)


# ── Season sync: sensor.heating_cooling_indicator → input_boolean.pergola_heating ───────
# The indicator is driven through its real input (the 48h mean, thresholds 12 / 16 / 20,
# hysteresis 1 °C, at most 3 steps per mean change), never pinned (it reads `this.state`).
_SYNC_STEPS = [  # (48h mean, indicator reached, pergola_heating)
    ("22.0", "active_cooling", "off"),  # neutral → active_cooling (2 steps)
    ("14.0", "neutral", "on"),  # active_cooling → neutral (2 steps)
    ("17.0", "passive_cooling", "off"),  # neutral → passive_cooling
    ("8.0", "active_heating", "on"),  # passive_cooling → active_heating (2 steps)
    ("17.0", "passive_cooling", "off"),  # active_heating → passive_cooling (2 steps)
    ("22.0", "active_cooling", "off"),  # passive_cooling → active_cooling
    ("8.0", "active_heating", "on"),  # active_cooling → active_heating (3 steps)
]


# The season comes from the REAL heating_cooling_indicator (seeded 48h mean → sync automation):
# a change to its YAML can fail this test, so it also runs under `--package heating_cooling_indicator`.
@pytest.mark.package("heating_cooling_indicator")
async def test_season_sync(pergola_env: _Env) -> None:
    """The sync automation follows every real indicator change; an unavailable indicator
    leaves pergola_heating as it is.

    Docker: test_indicator_heating_season_turns_pergola_heating_on,
    …_cooling_season_turns_pergola_heating_off, …_unavailable_keeps_pergola_heating_unchanged
    (they fired the automation with automation.trigger; here only the indicator's own state
    change triggers it).
    """
    env = pergola_env
    failures: list[str] = []
    for mean, indicator, heating in _SYNC_STEPS:
        await env.seed({_MEAN: (mean, _T)})
        got = (env.state("indicator"), env.state(_HEATING))
        if got != (indicator, heating):
            failures.append(f"mean {mean}: (indicator, heating) {got}, want "
                            f"{(indicator, heating)}")
    await env.seed({_MEAN: ("unavailable", {})})
    got = (env.state("indicator"), env.state(_HEATING))
    if got != ("unavailable", "on"):
        failures.append(f"mean unavailable: {got}, want ('unavailable', 'on')")
    assert not failures, f"{len(failures)} sync check(s) failed:\n" + "\n".join(failures)


# ── Watchdogs, lock responders and the Loxone mirror (blueprint mine/loxone_inputs.yaml) ───
async def test_watchdogs_responders_loxone(pergola_env: _Env) -> None:
    """New (no Docker test): the forced state reports (PG-2.4) and the Loxone mirror.

    - Watchdogs: on a /5 tick, `stop_cover_tilt` per cover when neither the cover nor its lock
      sensors updated in 5 min, unless the state is a moving one (suppressed in sun tracking).
    - Lock responders: `stop_cover_tilt` at once on an originator change.
    - Loxone (automations.yaml, three through the blueprint): originator, timer (`unknown`
      → 0), cover tilt attribute (`<cover>.current_tilt_position`) and the master switch
      (0/1), each as `rest_command.send_to_loxone`.
    """
    env = pergola_env
    failures: list[str] = []

    def expect(where: str, kinds: tuple[str, ...], want: list[str]) -> None:
        if (got := env.calls(*kinds)) != sorted(want):
            failures.append(f"{where}: {got}, want {sorted(want)}")

    day = _next_date(3, 10, after=dt_util.now().date())
    # not_enough_sun (no moving state).
    await env.move_to(_at(day, 12, 2))
    await env.seed({_RADIATION: ("5", {"unit_of_measurement": "W/m²"}), _UV: "0",
                    _LINKS: 74, _RECHTS: 74})
    await env.hold_until(_at(day, 12, 10))
    if env.state(_STATE) != "not_enough_sun":
        failures.append(f"setup: state {env.state(_STATE)}, want not_enough_sun")
    # The covers report a tilt near the 90° target (74; not_enough_sun moves only when more than
    # 30° off, so nothing moves) at a known time. Before not_enough_sun is reached, the cover
    # response may or may not have moved them (the 12:05/12:10 ticks race the state change), so
    # their last update is only known from here on. 73, not 74: an unchanged state and
    # attributes would not refresh `last_updated`.
    await env.hold_until(_at(day, 12, 11))
    await env.seed({_LINKS: 73, _RECHTS: 73})
    env.clear()
    await env.hold_until(_at(day, 12, 15))
    expect("12:15 tick, covers updated 3.5 min ago", ("stop", "tilt"), [])
    env.clear()
    await env.hold_until(_at(day, 12, 20))
    expect("12:20 tick, nothing updated for 8.5 min", ("stop", "tilt"),
           ["watchdog_links: stop dach_links", "watchdog_rechts: stop dach_rechts"])
    env.clear()
    await env.hold_until(_at(day, 12, 22))
    await env.seed({_LINKS: 72})  # a cover report (tilt changed): links fresh, mirrored
    expect("links reports tilt 72", ("loxone", "stop", "tilt"),
           ["loxone_tilt: loxone dach_links.current_tilt_position=72"])
    env.clear()
    await env.hold_until(_at(day, 12, 25))
    expect("12:25 tick, links updated 2.5 min ago", ("stop", "tilt"),
           ["watchdog_rechts: stop dach_rechts"])
    # Sun tracking with a deadband no sun move exceeds: covers still for > 5 min, yet the
    # watchdogs stay silent (moving-state suppression).
    await env.number(_DEADBAND, 20)
    await env.seed({_RADIATION: ("800", {"unit_of_measurement": "W/m²"})})
    await env.hold_until(_at(day, 12, 35))
    if env.state(_STATE) != "sun_automatik_cooling":
        failures.append(f"sun tracking: state {env.state(_STATE)}")
    env.clear()
    await env.hold_until(_at(day, 12, 40))
    covers_idle = all(dt_util.utcnow() - env.hass.states.get(c).last_updated
                      > timedelta(minutes=5) for c in (_LINKS, _RECHTS))
    if not covers_idle:
        failures.append("sun tracking: a cover updated within 5 min (watchdog check void)")
    expect("12:40 tick in sun tracking", ("stop", "tilt"), [])
    # Lock responders and the Loxone mirror of the lock sensors.
    env.clear()
    await env.seed({_ORIGIN["links"]: "user"})
    expect("links originator → user", ("stop", "loxone"),
           ["responder_links: stop dach_links",
            "loxone_originator: loxone dach_links_priority_lock_originator=user"])
    env.clear()
    await env.seed({_TIMER["links"]: "300"})
    expect("links timer 300", ("loxone",),
           ["loxone_timer: loxone dach_links_priority_lock_timer=300"])
    env.clear()
    await env.seed({_TIMER["links"]: "unknown"})
    expect("links timer unknown → 0", ("loxone",),
           ["loxone_timer: loxone dach_links_priority_lock_timer=0"])
    # The master switch, mirrored as 0 / 1.
    env.clear()
    await env.turn(_AUTOMATIC, False)
    expect("master off", ("loxone",), ["loxone_automatic: loxone pergola_automatic_enabled=0"])
    env.clear()
    await env.turn(_AUTOMATIC, True)
    expect("master on", ("loxone",), ["loxone_automatic: loxone pergola_automatic_enabled=1"])
    assert not failures, f"{len(failures)} check(s) failed:\n" + "\n".join(failures)
