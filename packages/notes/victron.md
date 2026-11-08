---
paths:
  - "packages/victron.yaml"
  - "tests/test_victron.py"
  - "plans/victron-*.md"
  - "plans/knowledge-dedup-victron.md"
---
# Victron package notes (`packages/victron.yaml`)

Read before touching `packages/victron.yaml`. Hardware: GX `c0619ab4c19e`, MPPT 279 (DC solar),
pvinverter 20 (AC-coupled PV), vebus 276 (MultiPlus-II, 3-phase, 3 devices), BMS battery.

## `Dc/Vebus/Power` is NOT the Multi's DC power
Observed 2026-10-17 (MQTT listen + VRM, snapshots not perfectly synced):

| Quantity | Value |
|---|---|
| `system/0/Dc/Vebus/Current` × `Dc/Battery/Voltage` | −8.1 A × 52.5 V = **425 W** |
| `system/0/Dc/Vebus/Power` | **−337 W** |
| `system/0/Dc/Battery/Power` (BMS) | −435 W (= 52.5 V × −8.3 A) |
| VRM "Inverter AC/DC" | 52.48 V × −7.7 A = 404 W, displays **−302 W** |

Over 26 h of hourly means `Dc/Vebus/Power` equalled the AC net (`ac_load − grid − ac_pv`) within
~1 W at 2.5 kW inverting and 1.9 kW charging, i.e. it behaves like an AC-side value. Why Victron
publishes it that way is **not established** — only the observation is.

Use `sensor.victron_multiplus_dc_power` (= battery voltage × `system/0/Dc/Vebus/Current`) for any
"DC side of the Multi" figure. Sign: positive = charging, negative = inverting; opposite to
`victron_multiplus_ac_net_power`, so conversion loss = `-(ac_net + dc)` in both directions.
`Dc/Battery/Power` also includes other DC loads (~10 W in the snapshot), so it is not the Multi's
own DC power.

## Efficiency is load dependent
At ~350 W the Multi loses ~15 % (≈ 80 % efficient; three devices idle-draw); at kW loads it is
better. The long-run ratio `victron_multiplus_conversion_efficiency` is dominated by low-load night
inverting but is applied to daytime PV. Totals still close exactly; only the Solar/Battery split
shifts. A load-dependent η would be a separate change.

## Venus OS MQTT publishes on CHANGE only (proven from source)
Python Venus services write values through velib `vedbus.py` `_local_set_value`
(`if self._value == newvalue: return None`), so an unchanged value sends no D-Bus signal.
dbus-flashmq relays every signal it gets, has no de-dup and no periodic value re-publish, and the
`suppress-republish` keep-alive skips the full dump. A value that stays constant (e.g.
`/Dc/Vebus/Current` = 0.0 A while idle) is sent ONCE, so any `expire_after` shorter than "how long it
can stay constant" WILL expire it. Size `expire_after` per topic and read an expired value as
"unchanged", not "outage". Chain: dbus-systemcalc-py `delegates/multi.py` -> velib `vedbus.py` ->
dbus-flashmq `src/state.cpp`; every key line dates from 2014-2024 (`git log -S`), so any current
Venus OS has it. Only Python/vedbus producers were checked; C services (vecan, mk2) were not.

Checking it live: ha-mcp only offers long-term statistics (no raw state history), so an expiry shows
only as missing 5-min rows. MQTT sensors do not expose `expire_after` as an attribute. For exact
timing use the HA History panel or `mosquitto_sub -v -t 'N/c0619ab4c19e/<path>'`.

## expire_after policy
See the comment at the top of `packages/victron.yaml`. A missing `expire_after` on an MQTT sensor
means it is not restored after a restart.

`sensor.victron_vebus_dc_current` uses `expire_after: 600` (not 120). `victron_multiplus_dc_power`
reads an expired current as 0 A, which would book the whole AC load as conversion loss while
charging. A non-zero current changes about every second (no constant non-zero reading for 2+ min
was seen in ~5 days of history), so it never falsely expires within 600 s. It DOES expire, several
times a day, after more than 10 min of real 0 A (idle, see the change-only section above). That is
harmless: `ac_net_power` is then about -40..-50 W (Multi idle draw from AC), `dc_power` reads 0 W,
`conversion_loss_power` shows the idle draw (same as a published 0 A), and the η gate is closed.

## η accumulators share one gate
`ac_out_energy` and `dc_in_energy` both advance only when `ac_net > 0` AND `dc < 0` and both inputs
are available (condition duplicated inline in each template; keep identical). Mismatched signs add
to neither, so skew ticks cannot bias η. Existing totals are not re-seeded; the old ones dilute.
UNPROVEN: η may lag its accumulators by one tick (a former comment attributed this to in-pass render order; never demonstrated). Do not rely on same-tick consistency between η and the accumulators.

## Known small biases (documented, not fixed)
- Conversion loss is clamped per sample (`max(-(ac_net+dc), 0)`), so negative excursions are
  dropped and the loss reads a few W high (live 86 W vs ~93 W expected). Diagnostic only.
- `conversion_efficiency` can render twice per minute tick (two accumulator entities); cosmetic.
- η is about 85 % in normal operation (85.1 % in 2026-11); use that as the sanity value.

## Open issue (not fixed)
`battery_energy_in` / `battery_energy_out` read grid/load with `float(0)` and no availability guard,
so an unavailable grid or load is booked as 0 W for that tick. A "hold the tick" fix is NOT a small
change: both sensors share a long template with counter-delta branches, and the solar/AC-PV baseline
sensors advance on their own, so a held tick would drop that tick's delta. Needs its own tests
(none cover an unavailable grid today).

## `sensor.victron_solar_yield_total_kwh` is not the MPPT counter
Template sensor since #121 (merged 2026-10-16): accumulates the MPPT counter delta x η, starting
from `this.state | float(0)`. It did not restore the old MQTT sensor's value: long-term statistics
go from 5644.65 kWh (2026-10-15) to 0.61 kWh (2026-10-16). The statistics `sum` stayed continuous
(1606 -> 1609 -> 1612), so the Energy Dashboard is unaffected apart from ~2.7 kWh counted that day
instead of ~10. Do not compare its state with the raw counter. Whether it was also reset by hand
is unknown.

## Related plans
`plans/victron-ac-referenced-accounting.md`, `plans/victron-multiplus-true-dc-power.md`.
