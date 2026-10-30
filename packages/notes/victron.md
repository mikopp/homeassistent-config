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

## expire_after policy
See the comment at the top of `packages/victron.yaml`. A missing `expire_after` on an MQTT sensor
means it is not restored after a restart.

`sensor.victron_vebus_dc_current` uses `expire_after: 600` (not 120). `victron_multiplus_dc_power`
reads an expired current as 0 A, which would book the whole AC load as conversion loss while
charging. Recorder history (2026-10-30): the current changes about every second at non-zero loads
(e.g. -22.7 A in 119 separate spells totalling 139 s in a 2 h window) and a constant non-zero
reading for 2+ min was not seen in ~5 days (judged from per-state totals). Real 0.0 A readings are
correct. The sensor was also unavailable in 8 spells of ~11 min on 2026-10-30 00:00-12:00 (likely
Multi standby / service gone); what the AC side did during them was NOT verified.

## η accumulators share one gate
`ac_out_energy` and `dc_in_energy` both advance only when `ac_net > 0` AND `dc < 0` and both inputs
are available (condition duplicated inline in each template; keep identical). Mismatched signs add
to neither, so skew ticks cannot bias η. Existing totals are not re-seeded; the old ones dilute.

## Known small biases (documented, not fixed)
- Conversion loss is clamped per sample (`max(-(ac_net+dc), 0)`), so negative excursions are
  dropped and the loss reads a few W high (live 86 W vs ~93 W expected). Diagnostic only.
- `conversion_efficiency` can render twice per minute tick (two accumulator entities); cosmetic.

## `sensor.victron_solar_yield_total_kwh` is not the MPPT counter
Template sensor since #121 (merged 2026-10-16): accumulates the MPPT counter delta x η, starting
from `this.state | float(0)`. It did not restore the old MQTT sensor's value: long-term statistics
go from 5644.65 kWh (2026-10-15) to 0.61 kWh (2026-10-16). The statistics `sum` stayed continuous
(1606 -> 1609 -> 1612), so the Energy Dashboard is unaffected apart from ~2.7 kWh counted that day
instead of ~10. Do not compare its state with the raw counter. Whether it was also reset by hand
is unknown.

## Related plans
`plans/victron-ac-referenced-accounting.md`, `plans/victron-multiplus-true-dc-power.md`.
