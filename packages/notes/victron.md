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

## Related plans
`plans/victron-ac-referenced-accounting.md`, `plans/victron-multiplus-true-dc-power.md`.
