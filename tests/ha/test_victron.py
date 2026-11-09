"""Victron power-domain formulas and accumulators (packages/victron.yaml), in-process.

plans/test-execution.md, Step 2, migration items 3 and 4. Replaces every test of the former
Docker tests/test_victron.py: item 3 the 31 instant-power tests (one case each; the one
two-step test is split into two cases) and the battery/grid accumulator spike ports; item 4
the 11 accumulator tests left (η gate, export, night, conversion loss, solar-yield counter
delta incl. the skipped first-tick test, battery residual), now on real minute ticks.

`test_instant_power_table`: ONE test on one fresh HA loops over the cases (tier 1 in the plan:
stateless formulas). Every case first publishes a reset vector and checks that the derived
sensors show it, then publishes the case's inputs and checks its expectations; all failures are
collected into one assert that names each failing case.

The accumulator tests (section "Accumulators driven by real minute ticks"): ONE fresh HA each
(tier 3), real ticks on the frozen clock, nothing seeded.

How the inputs get in:
- Every Victron MQTT sensor is driven over the real broker with Venus OS payloads
  (`{"value": x}`), so the real value_templates, rounding and `expire_after` run.
- "Unavailable" is what production sees: the MQTT sensor's `expire_after` elapsed (Clock), or
  the sensor never received a message (expire_after sensors start unavailable, see
  `test_instant_power_table`'s startup phase). The Docker suite wrote "unavailable" over REST.
- In the instant-power table the two η accumulators (`victron_multiplus_ac_out_energy` /
  `_dc_in_energy`) are seeded to set η per case; their self-reference (`this.state`) makes the
  seed what the next tick builds on. The clock is frozen for the whole table (`clock`
  fixture), so no minute tick can change them mid-case; it moves only for an expiry case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from datetime import timedelta

from homeassistant.core import HomeAssistant

from conftest import (
    Broker,
    Clock,
    at_least,
    check_states,
    entity_id,
    is_state,
    mqtt_sync,
    near,
    publish,
    seed,
    wait_state,
    wait_subscribed,
)

_GX = "N/c0619ab4c19e"

# Victron MQTT inputs: key → (topic under the GX prefix, expire_after in s from victron.yaml).
_INPUTS = {
    "grid_l1": ("system/0/Ac/Grid/L1/Power", 120),
    "grid_l2": ("system/0/Ac/Grid/L2/Power", 120),
    "grid_l3": ("system/0/Ac/Grid/L3/Power", 120),
    "ac_l1": ("system/0/Ac/Consumption/L1/Power", 120),
    "ac_l2": ("system/0/Ac/Consumption/L2/Power", 120),
    "ac_l3": ("system/0/Ac/Consumption/L3/Power", 120),
    "dc_pv": ("system/0/Dc/Pv/Power", 120),
    "ac_pv": ("pvinverter/20/Ac/Power", 120),
    "vebus_i": ("system/0/Dc/Vebus/Current", 600),
    "batt_v": ("system/0/Dc/Battery/Voltage", 86400),
}

# Defaults of every case, as the Docker `_seed()` set them: all power 0 W, 50 V, 0 A, and the η
# accumulators at the conftest baseline 0.0 kWh (η 100 % bootstrap).
_DEFAULTS = {k: 0.0 for k in _INPUTS} | {"batt_v": 50.0}
_ETA_DEFAULT = (0.0, 0.0)

# Reset vector, applied before every case. Every derived value it produces differs from every
# case's expectation of that sensor, except where an output is pinned by physics (export is 0
# whenever the grid imports): there, another output of the same case proves the re-render.
#   ac_net = 37 - 13 - 3 = 21;  solar = 100 × 0.70 = 70;  pv_net = 70 + 3 - 37 = 36;
#   battery = 21 - 70 = -49;    dc = 51 × -1 = -51;       loss = max(-(21 - 51), 0) = 30
_RESET = {"grid_l1": 13.0, "grid_l2": 0.0, "grid_l3": 0.0, "ac_l1": 37.0, "ac_l2": 0.0,
          "ac_l3": 0.0, "dc_pv": 100.0, "ac_pv": 3.0, "vebus_i": -1.0, "batt_v": 51.0}
_ETA_RESET = (7.0, 10.0)  # η 70 %, a value no case expects
_RESET_EXPECT = {
    "grid_total": near(13), "grid_import": near(13), "grid_export": near(0),
    "load_total": near(37), "ac_net": near(21), "dc_power": near(-51), "eta": near(70),
    "solar": near(70), "pv_net": near(36), "pv_surplus": near(36), "battery": near(-49),
    "loss": near(30),
}

# Checked sensors: key → (domain, platform, unique_id); ids are looked up in the registry.
_OUTPUTS = {
    "grid_total": ("sensor", "template", "victron_grid_total_power"),
    "grid_import": ("sensor", "template", "victron_grid_power_import"),
    "grid_export": ("sensor", "template", "victron_grid_power_export"),
    "load_total": ("sensor", "template", "victron_ac_load_total_power"),
    "ac_net": ("sensor", "template", "victron_multiplus_ac_net_power"),
    "dc_power": ("sensor", "template", "victron_multiplus_dc_power"),
    "eta": ("sensor", "template", "victron_multiplus_conversion_efficiency"),
    "solar": ("sensor", "template", "victron_solar_yield"),
    "pv_net": ("sensor", "template", "victron_pv_net_power"),
    "pv_surplus": ("sensor", "template", "victron_pv_surplus_power"),
    "battery": ("sensor", "template", "victron_battery_ac_power"),
    "loss": ("sensor", "template", "victron_multiplus_conversion_loss_power"),
    "ac_out_energy": ("sensor", "template", "victron_multiplus_ac_out_energy"),
    "dc_in_energy": ("sensor", "template", "victron_multiplus_dc_in_energy"),
    # The AC PV inverter's own MQTT sensor (the identity case reads it, as the Docker test did).
    "ac_inverter": ("sensor", "mqtt", "victron_ac_inverter_power"),
}

_KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}


def _vebus_current(watts: float, volts: float = 50.0) -> float:
    """Multi DC current for a wanted Multi DC power at the case voltage (Docker `_seed` rule)."""
    return watts / volts


@dataclass
class Case:
    """One instant-power case.

    inputs: overrides of _DEFAULTS (W, A, V); `vebus_dc` is a convenience for a Multi DC power
      in W at 50 V (converted to `vebus_i`, as the Docker `_seed(vebus_dc=…)`).
    eta: (ac_out, dc_in) kWh seeded into the η accumulators.
    expire: input keys whose MQTT sensor must be expired (unavailable) for this case.
    raw: extra raw payloads published after the inputs (key, payload), e.g. an empty message.
    expect: output key → predicate.
    """

    name: str
    inputs: dict[str, float] = field(default_factory=dict)
    expect: dict[str, Callable[[str], bool]] = field(default_factory=dict)
    eta: tuple[float, float] = _ETA_DEFAULT
    expire: frozenset[str] = frozenset()
    raw: list[tuple[str, str]] = field(default_factory=list)


_PHASES = frozenset({"ac_l1", "ac_l2", "ac_l3"})
_PV = frozenset({"dc_pv", "ac_pv"})
_UNAV = is_state("unavailable")

# One case per former Docker test (same names, same values); the one two-step test
# (`pv_net_treats_unavailable_pv_as_zero_but_load_outage_as_unavailable`) is two cases.
CASES = [
    Case("grid_import_half_wave", {"grid_l1": 200, "grid_l2": 200, "grid_l3": 100},
         {"grid_total": near(500), "grid_import": near(500), "grid_export": near(0)}),
    Case("grid_export_half_wave", {"grid_l1": -300, "grid_l2": -200, "grid_l3": -200},
         {"grid_total": near(-700), "grid_export": near(700), "grid_import": near(0)}),
    Case("ac_load_total", {"ac_l1": 500, "ac_l2": 400, "ac_l3": 300},
         {"load_total": near(1200)}),
    # Night: battery_ac = ac_net - solar = (102 - 10) - 0 = +92 W (discharging).
    Case("battery_ac_power_night", {"grid_l1": 10, "ac_l1": 102}, {"battery": near(92)}),
    Case("battery_ac_power_solar_charging", {"dc_pv": 1200, "ac_l1": 600},
         {"battery": near(-600)}),
    Case("battery_ac_power_grid_exporting", {"dc_pv": 800, "grid_l1": -200, "ac_l1": 600},
         {"battery": near(0)}),
    # MPPT 4000 W DC at η 90 % → 3600 W AC; + AC PV 1000 - load 2500 = 2100.
    Case("pv_net_and_surplus_are_ac_referenced",
         {"dc_pv": 4000, "ac_pv": 1000, "ac_l1": 2500},
         {"pv_net": near(2100), "pv_surplus": near(2100)}, eta=(9.0, 10.0)),
    Case("pv_surplus_clamps_at_zero_but_net_stays_signed", {"dc_pv": 500, "ac_l1": 1200},
         {"pv_net": near(-700), "pv_surplus": near(0)}),
    # Inverter asleep (expired) → PV 0 W, net = -load.
    Case("pv_net_treats_unavailable_pv_as_zero", {"ac_l1": 500},
         {"pv_net": near(-500), "pv_surplus": near(0)}, expire=frozenset({"ac_pv"})),
    # GX outage (load phases expired too) → unavailable, not a false number.
    Case("pv_net_load_outage_is_unavailable", {"ac_l1": 500},
         {"pv_net": _UNAV, "pv_surplus": _UNAV}, expire=frozenset({"ac_pv"}) | _PHASES),
    # Regression: the chain must survive expired PV at night (load 351, grid 12 → 339).
    Case("battery_power_chain_survives_expired_pv_at_night", {"grid_l1": 12, "ac_l1": 351},
         {"ac_net": near(339), "solar": near(0), "battery": near(339), "loss": at_least(0)},
         expire=_PV),
    Case("battery_power_chain_still_unavailable_on_gx_outage", {"grid_l1": 12, "ac_l1": 351},
         {"ac_net": _UNAV, "battery": _UNAV}, expire=_PV | _PHASES),
    Case("night_solar_off_battery_discharge",
         {"grid_l1": 400, "grid_l2": 350, "grid_l3": 250, "vebus_dc": -600},
         {"grid_import": near(1000), "grid_export": near(0)}),
    Case("multiplus_ac_net_inverting", {"ac_l1": 1000, "grid_l1": 200, "ac_pv": 100},
         {"ac_net": near(700)}),
    Case("multiplus_ac_net_charging", {"ac_l1": 200, "grid_l1": 1000}, {"ac_net": near(-800)}),
    Case("inverter_efficiency_bootstrap", {}, {"eta": near(100)}, eta=(0.0, 0.0)),
    Case("inverter_efficiency_below_threshold_still_bootstraps", {}, {"eta": near(100)},
         eta=(0.8, 0.9)),
    Case("inverter_efficiency_accumulated", {}, {"eta": near(90)}, eta=(9.0, 10.0)),
    Case("inverter_efficiency_clamped_low", {}, {"eta": near(50)}, eta=(1.0, 10.0)),
    Case("inverter_efficiency_clamped_high", {}, {"eta": near(100)}, eta=(12.0, 10.0)),
    Case("solar_yield_ac_watts_bootstrap", {"dc_pv": 1000}, {"solar": near(1000)},
         eta=(0.0, 0.0)),
    Case("solar_yield_ac_watts_discounted_by_eta", {"dc_pv": 1000}, {"solar": near(900)},
         eta=(9.0, 10.0)),
    # η reaches battery_ac_power too: 600 - 1200 × 0.9 = -480.
    Case("battery_ac_power_with_eta", {"dc_pv": 1200, "ac_l1": 600}, {"battery": near(-480)},
         eta=(9.0, 10.0)),
    # Identity solar_ac + ac_pv + grid + batt_ac == ac_load: 1800 + 500 - 300 - 800 = 1200.
    Case("power_domain_identity_holds_with_eta",
         {"dc_pv": 2000, "ac_pv": 500, "grid_l1": -300, "ac_l1": 1000, "ac_l2": 200},
         {"load_total": near(1200), "grid_total": near(-300), "ac_inverter": near(500),
          "solar": near(1800), "battery": near(-800)}, eta=(9.0, 10.0)),
    Case("conversion_loss_inverting", {"ac_l1": 950, "vebus_dc": -1000}, {"loss": near(50)}),
    Case("conversion_loss_charging", {"grid_l1": 1000, "vebus_dc": 950}, {"loss": near(50)}),
    Case("conversion_loss_clamped_to_zero", {}, {"loss": near(0)}),
    # Real snapshot 2026-10-17: 52.5 V × -8.1 A = -425 W.
    Case("multiplus_dc_power_inverting_is_negative", {"batt_v": 52.5, "vebus_i": -8.1},
         {"dc_power": near(-425)}),
    Case("multiplus_dc_power_charging_is_positive", {"batt_v": 52.5, "vebus_i": 20},
         {"dc_power": near(1050)}),
    # An expired current (expire_after 600 s) reads 0 W, not unavailable.
    Case("multiplus_dc_power_expired_current_reads_zero", {"batt_v": 52.5, "vebus_i": -8.1},
         {"dc_power": near(0)}, expire=frozenset({"vebus_i"})),
    # Real snapshot: load 351, grid 12 → ac_net 339; 52.5 V × -8.1 A = -425 → loss 86 W.
    Case("conversion_loss_realistic_from_true_dc",
         {"ac_l1": 351, "grid_l1": 12, "batt_v": 52.5, "vebus_i": -8.1}, {"loss": near(86)}),
    # New (value_template guard `value_json is defined`): a service that disappears sends an
    # empty payload, and a null value may arrive; both keep the last value, without a template
    # error (the log guard would fail the test on one).
    Case("empty_or_null_payload_keeps_last_value", {"grid_l1": 300},
         {"grid_total": near(300), "grid_import": near(300)},
         raw=[("grid_l1", ""), ("grid_l1", '{"value": null}')]),
]
# `multiplus_dc_power_unavailable_without_voltage` is the startup phase of the test below.


async def _publish_inputs(
    hass: HomeAssistant, broker: Broker, values: dict[str, float], skip: frozenset[str] = frozenset()
) -> None:
    """Publish a Venus OS payload for every input not in `skip`."""
    for key, (topic, _) in _INPUTS.items():
        if key not in skip:
            await publish(hass, broker, f"{_GX}/{topic}", {"value": values[key]})


async def _seed_eta(hass: HomeAssistant, ids: dict[str, str], eta: tuple[float, float]) -> None:
    """Seed the two η accumulators (no real path without minute ticks, see the docstring)."""
    await seed(hass, {ids["ac_out_energy"]: (str(eta[0]), _KWH),
                      ids["dc_in_energy"]: (str(eta[1]), _KWH)})


def _case_values(case: Case) -> dict[str, float]:
    """The full input vector of a case: defaults, the case's overrides, vebus_dc converted."""
    values = dict(_DEFAULTS)
    for key, value in case.inputs.items():
        if key == "vebus_dc":
            values["vebus_i"] = _vebus_current(value)
        else:
            values[key] = float(value)
    return values


async def test_instant_power_table(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """All instant-power cases on one HA; every failing case is listed in the one assert."""
    ids = {key: entity_id(ha, *spec) for key, spec in _OUTPUTS.items()}
    await wait_subscribed(ha, broker, *(f"{_GX}/{t}" for t, _ in _INPUTS.values()))
    failures: list[str] = []

    # Startup phase (Docker `multiplus_dc_power_unavailable_without_voltage`): the battery
    # voltage has never been published, so its expire_after sensor is still unavailable, as
    # after a restart before the GX sends it. Every other input is published (current -8.1 A),
    # so ac_net is available and the loss is unavailable BECAUSE of the DC side.
    await _publish_inputs(ha, broker, _DEFAULTS | {"vebus_i": -8.1}, skip=frozenset({"batt_v"}))
    await mqtt_sync(ha, broker)
    failures += check_states(
        ha, ids, {"dc_power": _UNAV, "loss": _UNAV, "ac_net": near(0)},
        "multiplus_dc_power_unavailable_without_voltage",
    )

    for case in CASES:
        # Reset: every input and the η accumulators to the reset vector, then prove the
        # derived sensors re-rendered from it. A failed reset is reported and the case runs.
        await _publish_inputs(ha, broker, _RESET)
        await _seed_eta(ha, ids, _ETA_RESET)
        await mqtt_sync(ha, broker)
        failures += check_states(ha, ids, _RESET_EXPECT, f"{case.name} (reset)")

        # The case's inputs: every input published (defaults + overrides), η seeded.
        values = _case_values(case)
        await _publish_inputs(ha, broker, values)
        if case.expire:
            # Let the named sensors expire for real: move past the longest expire_after among
            # them (every input expires, since all were published at the same frozen instant),
            # then republish the inputs that must stay live. The move also fires the minute
            # ticks, so the η accumulators are seeded after it. Sync first: a message that
            # arrives after the move would re-arm its expiry on the moved clock.
            await mqtt_sync(ha, broker)
            await clock.advance(max(_INPUTS[k][1] for k in case.expire) + 1)
            await _publish_inputs(ha, broker, values, skip=case.expire)
        for key, payload in case.raw:
            await publish(ha, broker, f"{_GX}/{_INPUTS[key][0]}", payload)
        await _seed_eta(ha, ids, case.eta)
        await mqtt_sync(ha, broker)
        failures += check_states(ha, ids, case.expect, case.name)
    assert not failures, f"{len(failures)} Victron check(s) failed:\n" + "\n".join(failures)


# ── Accumulators: real broker + moved clock (moved unchanged from the Step 0 spike) ────────
# These are item-4-type tests (time_pattern, platform: integration), already proven in Step 0
# (plans/test-execution.md, "Step 0 results"). They replace the Docker
# `test_battery_discharge_energy_accumulates` and `test_grid_import_energy_accumulates`.
_TOPICS = {
    "grid_l1": "system/0/Ac/Grid/L1/Power",
    "grid_l2": "system/0/Ac/Grid/L2/Power",
    "grid_l3": "system/0/Ac/Grid/L3/Power",
    "ac_l1": "system/0/Ac/Consumption/L1/Power",
    "ac_l2": "system/0/Ac/Consumption/L2/Power",
    "ac_l3": "system/0/Ac/Consumption/L3/Power",
    "dc_pv": "system/0/Dc/Pv/Power",
    "ac_pv": "pvinverter/20/Ac/Power",
    "vebus_i": "system/0/Dc/Vebus/Current",
    "batt_v": "system/0/Dc/Battery/Voltage",
}


async def _publish_gx(ha: HomeAssistant, broker: Broker, **values: float) -> None:
    """Publish Venus OS payloads ({"value": x}) for every power topic (defaults 0, 50 V)."""
    vals = {k: 0.0 for k in _TOPICS} | {"batt_v": 50.0} | values
    for key, topic in _TOPICS.items():
        await ha.async_add_executor_job(broker.wait_subscribed, f"{_GX}/{topic}")
        await ha.async_add_executor_job(broker.publish, f"{_GX}/{topic}", {"value": vals[key]})


async def test_battery_discharge_energy_accumulates(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """Port: 1200 W battery discharge × one time_pattern minute = 0.02 kWh (fed over MQTT)."""
    await _publish_gx(ha, broker, ac_l1=1200)
    await wait_state(ha, "sensor.victron_battery_ac_power", lambda s: s not in ("unknown", "unavailable") and float(s) == 1200)
    # Trigger-based accumulator: `unknown` until its first time_pattern tick (this.state → 0).
    # A real minute boundary during HA start (before the freeze) may already have ticked it.
    st = ha.states.get("sensor.victron_battery_energy_out").state
    before = 0.0 if st == "unknown" else float(st)
    await clock.advance(timedelta(minutes=1))
    out = float(ha.states.get("sensor.victron_battery_energy_out").state)
    assert abs((out - before) - 0.02) < 0.001
    assert float(ha.states.get("sensor.victron_battery_energy_in").state) == 0.0


async def test_grid_import_energy_accumulates(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """0→3000→1000 W import; the 3000→1000 step is EXACTLY 60 s (frozen clock) → exact kWh.

    Stronger than the Docker port (3000→3001 W, tolerance 2 Wh, which `method: left` also
    passed). The 0→3000 step spans HA start → freeze (real time, load dependent), so its area is
    computed from HA's own timestamps rather than assumed zero; the displayed total rounds to
    1 Wh (`round: 3`), hence the 0.6 Wh tolerance.
    """
    src = "sensor.victron_grid_power_import"
    prev = ha.states.get(src)
    assert prev.state == "0"
    await _publish_gx(ha, broker, grid_l1=3000)
    await wait_state(ha, src, "3000.0")
    first_s = ha.states.get(src).last_updated_timestamp - prev.last_reported_timestamp
    await clock.advance(timedelta(minutes=1))
    await _publish_gx(ha, broker, grid_l1=1000)
    await wait_state(ha, src, "1000.0")
    expected = ((0 + 3000) / 2 * first_s + (3000 + 1000) / 2 * 60) / 3_600_000
    total = float(ha.states.get("sensor.victron_grid_energy_import").state)
    assert abs(total - expected) < 0.0006, (total, expected, first_s)
    assert ha.states.get("sensor.victron_grid_energy_export").state in ("0.0", "0.000", "unknown")


async def test_victron_keepalive_published(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """Automations really publish: empty keep-alive on HA start, suppress-republish every 30 s."""
    topic = f"R/{_GX[2:]}/keepalive"
    await ha.async_add_executor_job(broker.wait_received, topic, "")
    mark = len(broker.received)
    await clock.advance(30)
    await ha.async_add_executor_job(
        broker.wait_received, topic, '{"keepalive-options":["suppress-republish"]}', mark
    )


# ── Accumulators driven by real minute ticks (plans/test-execution.md, Step 2, item 4) ──────
# Replace the Docker η, export, night, conversion-loss, solar-yield counter-delta and battery
# residual tests. ONE fresh HA per test (tier 3: the accumulators' `this.state` and the
# `integration` totals cannot be reset), no seeded accumulator or baseline: every value is what
# the real trigger block (`time_pattern: minutes: "/1"`) built from the published inputs.
#
# A tick: publish every input (the GX pushes continuously; power expires after 120 s), sync,
# advance 60 s on the frozen clock, aligned to half past a minute (`Clock.align`). That crosses
# exactly one minute boundary, so the block renders exactly once. The expected value of an accumulator is computed from its state read
# right before the tick with the template's own arithmetic (`round(x + w / 60000, 3)`), so the
# check is exact. The Docker suite allowed one tick per test ("the harness's time_pattern
# trigger only reliably re-fires on the FIRST clock advance"); in-process any number of ticks
# chain, which is what makes the skipped `captures_baseline_on_first_tick` deterministic.
_COUNTERS = {  # lifetime counters (kWh), expire_after 7 days
    "mppt_total": "solarcharger/279/Yield/System",
    "acpv_total": "pvinverter/20/Ac/Energy/Forward",
}
_WEEK = 604800  # the counters' expire_after
_ACC = {key: ("sensor", "template", uid) for key, uid in {
    "ac_out_energy": "victron_multiplus_ac_out_energy",
    "dc_in_energy": "victron_multiplus_dc_in_energy",
    "batt_in": "victron_battery_energy_in",
    "batt_out": "victron_battery_energy_out",
    "loss_energy": "victron_multiplus_conversion_loss_energy",
    "solar_total": "victron_solar_yield_total_kwh",
    "mppt_baseline": "victron_solar_yield_dc_baseline_kwh",
    "acpv_baseline": "victron_ac_pv_energy_baseline_kwh",
}.items()} | {
    "ac_net": ("sensor", "template", "victron_multiplus_ac_net_power"),
    "dc_power": ("sensor", "template", "victron_multiplus_dc_power"),
    "loss": ("sensor", "template", "victron_multiplus_conversion_loss_power"),
    "eta": ("sensor", "template", "victron_multiplus_conversion_efficiency"),
    "grid_import_power": ("sensor", "template", "victron_grid_power_import"),
    "grid_export_power": ("sensor", "template", "victron_grid_power_export"),
    "grid_import": ("sensor", "integration", "victron_grid_energy_import"),
    "grid_export": ("sensor", "integration", "victron_grid_energy_export"),
    "mppt_counter": ("sensor", "mqtt", "victron_solar_yield_dc_total_kwh"),
}


class _Ticker:
    """Publishes a Victron input vector, ticks the minute block and checks accumulator deltas."""

    def __init__(self, hass: HomeAssistant, broker: Broker, clock: Clock) -> None:
        self.hass, self.broker, self.clock = hass, broker, clock
        self.ids = {key: entity_id(hass, *spec) for key, spec in _ACC.items()}
        self.failures: list[str] = []

    async def start(self) -> None:
        """Align the clock to half past a minute (`Clock.align`: one tick per 60 s move), then
        wait until HA subscribed to every topic a test publishes."""
        await self.clock.align()
        topics = [t for t, _ in _INPUTS.values()] + list(_COUNTERS.values())
        await wait_subscribed(self.hass, self.broker, *(f"{_GX}/{t}" for t in topics))

    async def publish(
        self, *, skip: frozenset[str] = frozenset(), counters: dict[str, float] | None = None,
        **values: float,
    ) -> None:
        """Publish every power input (defaults 0 W / 0 A / 50 V; `vebus_dc` = Multi DC power in
        W at 50 V) except `skip`, and the given lifetime counters; then sync."""
        vals = dict(_DEFAULTS)
        for key, value in values.items():
            if key == "vebus_dc":
                vals["vebus_i"] = _vebus_current(value)
            else:
                vals[key] = float(value)
        await _publish_inputs(self.hass, self.broker, vals, skip)
        for key, value in (counters or {}).items():
            await publish(self.hass, self.broker, f"{_GX}/{_COUNTERS[key]}", {"value": value})
        await mqtt_sync(self.hass, self.broker)

    def value(self, key: str) -> float:
        """An accumulator's current value; a trigger sensor that never ticked counts as 0."""
        state = self.hass.states.get(self.ids[key]).state
        return 0.0 if state in ("unknown", "unavailable") else float(state)

    async def tick(self, **publish_kwargs: Any) -> dict[str, float]:
        """Publish (`publish` arguments), read every accumulator, advance one minute.

        Returns the values read BEFORE the tick, for the expectations of `check`.
        """
        await self.publish(**publish_kwargs)
        before = {k: self.value(k) for k in _ACC if self._numeric_or_unknown(k)}
        await self.clock.advance(60)
        return before

    def _numeric_or_unknown(self, key: str) -> bool:
        state = self.hass.states.get(self.ids[key]).state
        return state in ("unknown", "unavailable") or _is_float(state)

    def check(self, where: str, expect: dict[str, Callable[[str], bool]]) -> None:
        """Collect a failure for every entity (key of _ACC) not matching its predicate."""
        self.failures += check_states(self.hass, self.ids, expect, where)

    def done(self) -> None:
        """One assert listing every failed check."""
        assert not self.failures, (
            f"{len(self.failures)} accumulator check(s) failed:\n" + "\n".join(self.failures)
        )


def _is_float(state: str) -> bool:
    """True when the state parses as a number."""
    try:
        float(state)
    except ValueError:
        return False
    return True


def _plus(before: float, watts: float) -> Callable[[str], bool]:
    """Predicate: one tick of `watts` added with the template's arithmetic and rounding."""
    return near(round(before + watts / 60000, 3))


async def test_eta_accumulators_keep_pace_when_ac_pv_expired(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """AC PV asleep: ac_out must integrate alongside dc_in, or η drifts down every night.

    Docker case: load 351, grid 12 → ac_net 339 W (ac_out +339/60000); Multi DC −345 W
    (dc_in +345/60000). Both PV sensors never got a message (expire_after: unavailable), as a
    sleeping inverter. Two ticks in a row, each checked.
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    night = {"grid_l1": 12, "ac_l1": 351, "vebus_dc": -345, "skip": _PV}
    await t.publish(**night)
    t.check("inputs", {"ac_net": near(339), "dc_power": near(-345)})
    for n in (1, 2):
        before = await t.tick(**night)
        t.check(f"tick {n}", {"ac_out_energy": _plus(before["ac_out_energy"], 339),
                              "dc_in_energy": _plus(before["dc_in_energy"], 345)})
    t.done()


async def test_eta_accumulators_gate_on_both_signs(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """Both η accumulators need ac_net > 0 AND dc < 0; a mismatched tick adds to NEITHER.

    Docker: three ticks, only the total after the third was checked. Here each tick is
    checked on its own: (1) ac_net +600 / dc +660 adds nothing, (2) ac_net −600 / dc −660 adds
    nothing, (3) ac_net +600 / dc −660 adds 0.010 / 0.011.
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    steps = [
        ("charging current while AC inverts", {"ac_l1": 600, "vebus_dc": 660}, (600, 660), False),
        ("inverting current while AC charges", {"grid_l1": 600, "vebus_dc": -660}, (-600, -660),
         False),
        ("both inverting (control)", {"ac_l1": 600, "vebus_dc": -660}, (600, -660), True),
    ]
    for where, inputs, (ac_net, dc), adds in steps:
        await t.publish(**inputs)
        t.check(f"{where}: inputs", {"ac_net": near(ac_net), "dc_power": near(dc)})
        before = await t.tick(**inputs)
        t.check(where, {
            "ac_out_energy": _plus(before["ac_out_energy"], 600 if adds else 0),
            "dc_in_energy": _plus(before["dc_in_energy"], 660 if adds else 0),
        })
    t.done()


async def test_grid_export_energy_accumulates(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """1800 → 1000 W export; the second step is EXACTLY 60 s (frozen clock) → exact kWh.

    Replaces the Docker test (1800 → 1801 W, a relative delta from a session-long total with
    a 2 Wh tolerance). Same construction as `test_grid_import_energy_accumulates`: the first
    step (0 → 1800 W) spans HA start → the publish, so its area comes from HA's timestamps;
    the total rounds to 1 Wh (`round: 3`). The import total does not move.
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    src = t.ids["grid_export_power"]
    prev = ha.states.get(src)
    import_before = ha.states.get(t.ids["grid_import"]).state
    await t.publish(grid_l1=-1800)
    t.check("1800 W export", {"grid_export_power": near(1800)})
    first_s = ha.states.get(src).last_updated_timestamp - prev.last_reported_timestamp
    await clock.advance(60)
    await t.publish(grid_l1=-1000)
    expected = (float(prev.state) + 1800) / 2 * first_s / 3_600_000 + (1800 + 1000) / 2 * 60 / 3_600_000
    t.check("after 60 s at 1800 W, now 1000 W", {"grid_export": near(expected, 0.0006),
                                                  "grid_import": is_state(import_before)})
    t.done()


async def test_night_no_grid_energy_accumulates(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """Night: no grid flow, 1500 W load from the battery → grid totals stay, batt_out grows.

    Docker: batt_out "> 0" and the grid totals equal to a session baseline. Here exact: the
    residual falls back to the power domain (no lifetime counters: never published), so
    batt_out += 1500/60000 = 0.025 and batt_in += 0 per tick; a zero-power `integration` step
    has zero area.
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    night = {"ac_l1": 1500, "skip": _PV}
    await t.publish(**night)
    t.check("inputs", {"grid_import_power": near(0), "grid_export_power": near(0)})
    grid = {k: ha.states.get(t.ids[k]).state for k in ("grid_import", "grid_export")}
    for n in (1, 2):
        before = await t.tick(**night)
        t.check(f"tick {n}", {"batt_out": _plus(before["batt_out"], 1500),
                              "batt_in": _plus(before["batt_in"], 0),
                              "grid_import": is_state(grid["grid_import"]),
                              "grid_export": is_state(grid["grid_export"])})
    t.done()


async def test_conversion_loss_energy_accumulates(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """600 W loss (load 600 W, Multi DC −1200 W) adds 0.010 kWh per tick (two ticks)."""
    t = _Ticker(ha, broker, clock)
    await t.start()
    inputs = {"ac_l1": 600, "vebus_dc": -1200}
    await t.publish(**inputs)
    t.check("inputs", {"loss": near(600)})
    for n in (1, 2):
        before = await t.tick(**inputs)
        t.check(f"tick {n}", {"loss_energy": _plus(before["loss_energy"], 600)})
    t.done()


async def test_solar_yield_ac_total_counter_delta(
    ha: HomeAssistant, broker: Broker, clock: Clock
) -> None:
    """The AC solar total follows the MPPT lifetime counter through its baseline, tick by tick.

    Replaces the four Docker counter-delta tests, which each seeded the "already baselined"
    precondition and allowed one tick; `captures_baseline_on_first_tick` was skipped as a
    harness ordering flake. Here it is the first step of one chain on real ticks:
      1. no baseline yet: the tick holds the total and captures the baseline (100.0);
      2. +0.5 kWh: added 1:1 (η 100 % bootstrap), baseline 100.5;
      3. counter reset to 10.0: delta clamped to 0, baseline re-anchors to 10.0;
      4. counter expires (expire_after 7 days): total and baseline hold;
      5. new: the counter returns at 12.0: the next tick takes the whole gap (+2.0).
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    start = t.value("solar_total")
    t.check("start: no baseline", {"mppt_baseline": is_state("unknown")})
    await t.tick(counters={"mppt_total": 100.0})
    t.check("1. first tick captures the baseline", {"solar_total": near(start),
                                                    "mppt_baseline": near(100.0)})
    await t.tick(counters={"mppt_total": 100.5})
    t.check("2. delta applied", {"solar_total": near(round(start + 0.5, 3)),
                                 "mppt_baseline": near(100.5)})
    await t.tick(counters={"mppt_total": 10.0})
    t.check("3. counter reset clamped", {"solar_total": near(round(start + 0.5, 3)),
                                         "mppt_baseline": near(10.0)})
    # 4. Let the counter expire for real, then one more tick with it unavailable. (The tick
    #    inside the long move may run before or after the expiry; both give the same result,
    #    since the counter still equals the baseline.)
    await clock.advance(_WEEK + 1)
    await t.tick()
    t.check("4. counter unavailable holds", {"mppt_counter": _UNAV,
                                             "solar_total": near(round(start + 0.5, 3)),
                                             "mppt_baseline": near(10.0)})
    await t.tick(counters={"mppt_total": 12.0})
    t.check("5. next tick takes the whole gap", {"solar_total": near(round(start + 2.5, 3)),
                                                 "mppt_baseline": near(12.0)})
    t.done()


async def test_battery_energy_residual(ha: HomeAssistant, broker: Broker, clock: Clock) -> None:
    """Battery accumulators: power-domain bootstrap, then the energy-domain counter delta.

    Replaces the Docker `…_bootstrap_before_baseline` and `…_uses_counter_delta_once_baselined`
    (the second seeded both baselines). Chain on real ticks, all power 0 W:
      1. both counters arrive (50.0 / 20.0), no baseline yet: the power fallback adds nothing,
         the tick captures both baselines;
      2. MPPT +1.0, AC PV +0.2 kWh, no load or grid: the whole 1.2 kWh charged the battery
         (batt_in += 1.0 × η 1.0 + 0.2), batt_out += 0.
    """
    t = _Ticker(ha, broker, clock)
    await t.start()
    before = await t.tick(skip=_PV, counters={"mppt_total": 50.0, "acpv_total": 20.0})
    t.check("1. bootstrap tick", {"batt_in": _plus(before["batt_in"], 0),
                                  "batt_out": _plus(before["batt_out"], 0),
                                  "mppt_baseline": near(50.0), "acpv_baseline": near(20.0)})
    before = await t.tick(skip=_PV, counters={"mppt_total": 51.0, "acpv_total": 20.2})
    t.check("2. counter delta", {"batt_in": near(round(before["batt_in"] + 1.2, 3)),
                                 "batt_out": near(before["batt_out"]),
                                 "mppt_baseline": near(51.0), "acpv_baseline": near(20.2),
                                 "eta": near(100)})
    t.done()
