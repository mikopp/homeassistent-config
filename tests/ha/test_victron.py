"""Victron power-domain formulas and accumulators (packages/victron.yaml), in-process.

plans/test-execution.md, Step 2, migration item 3. Replaces the 31 instant-power tests of the
Docker tests/test_victron.py (one case each; the one two-step test is split into two cases)
and holds the three Victron tests moved unchanged from the Step 0 spike (battery accumulator,
grid `integration`, keep-alive publish). The other accumulator tests (η ticks, export, conversion
loss energy, counter-delta baselines, battery residual) stay in the Docker file until item 4.

`test_instant_power_table`: ONE test on one fresh HA loops over the cases (tier 1 in the plan:
stateless formulas). Every case first publishes a reset vector and checks that the derived
sensors show it, then publishes the case's inputs and checks its expectations; all failures are
collected into one assert that names each failing case.

How the inputs get in:
- Every Victron MQTT sensor is driven over the real broker with Venus OS payloads
  (`{"value": x}`), so the real value_templates, rounding and `expire_after` run.
- "Unavailable" is what production sees: the MQTT sensor's `expire_after` elapsed (Clock), or
  the sensor never received a message (expire_after sensors start unavailable, see
  `test_instant_power_table`'s startup phase). The Docker suite wrote "unavailable" over REST.
- The two η accumulators (`victron_multiplus_ac_out_energy` / `_dc_in_energy`) are trigger-based
  time_pattern sensors: a real path needs minute ticks (item 4), so they are seeded, as in the
  Docker suite. Their self-reference (`this.state`) makes the seed what the next tick builds on.
- The clock is frozen for the whole table (`clock` fixture), so no real minute boundary can tick
  the accumulators mid-case; it moves only for an expiry case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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
