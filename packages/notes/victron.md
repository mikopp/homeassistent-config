---
paths:
  - "packages/victron.yaml"
  - "tests/test_victron.py"
  - "doc/victron/design.md"
---
# Victron package notes (`packages/victron.yaml`)

Current facts of the Victron package. Loads with `packages/victron.yaml`, `tests/test_victron.py`
and `doc/victron/design.md`. Accounting model, formulas, sign table and identities:
`doc/victron/design.md` (`VIC-n`).

## Invariants
- Power identity, any η: `solar_ac + ac_pv + grid + batt_ac == ac_load` (VIC-5). Energy identity
  per minute for the battery residual (VIC-6). η only moves the Solar/Battery split.
- Power and energy domains are each exact and deliberately NOT reconciled with each other (VIC-6).
- `victron_multiplus_ac_net_power` (+ = inverting) and `victron_multiplus_dc_power`
  (+ = charging) have opposite signs; conversion loss = `max(-(ac_net + dc), 0)` (VIC-8). The
  Multi current's sign was observed only while inverting (negative); positive while charging is
  test-covered, not yet seen live.
- `victron_multiplus_conversion_efficiency` always renders a number (no `availability:`;
  100 % bootstrap until `dc_in_energy` ≥ 1 kWh, clamp 50-100) (VIC-7).
- Expired PV sensors and an expired Multi current mean 0, not an outage; the "GX alive" signals
  are AC load and grid (VIC-10).

## Hardware / integration quirks
Hardware: GX `c0619ab4c19e`, MPPT 279 (DC solar), pvinverter 20 (AC-coupled PV), vebus 276
(MultiPlus-II, 3-phase, 3 devices), BMS battery. No separate grid meter (grid = Multi AC-in).

### `Dc/Vebus/Power` is NOT the Multi's DC power
Observed 2026-10-17 (MQTT listen + VRM, snapshots not perfectly synced):

| Quantity | Value |
|---|---|
| `system/0/Dc/Vebus/Current` × `Dc/Battery/Voltage` | −8.1 A × 52.5 V = **425 W** |
| `system/0/Dc/Vebus/Power` | **−337 W** |
| `system/0/Dc/Battery/Power` (BMS) | −435 W (= 52.5 V × −8.3 A) |
| VRM "Inverter AC/DC" | 52.48 V × −7.7 A = 404 W, displays **−302 W** |

Over 26 h of hourly means `Dc/Vebus/Power` equalled the AC net (`ac_load − grid − ac_pv`) within
~1 W at 2.5 kW inverting and 1.9 kW charging, i.e. it behaves like an AC-side value. Why Victron
publishes it that way is **not established**, only the observation is.

Use `sensor.victron_multiplus_dc_power` (= battery voltage × `system/0/Dc/Vebus/Current`) for any
"DC side of the Multi" figure. `Dc/Battery/Power` also includes other DC loads (~10 W in the
snapshot), so it is not the Multi's own DC power.

### Efficiency is load dependent
At ~350 W the Multi loses ~15 % (≈ 80 % efficient; three devices idle-draw), measured from one
snapshot; better efficiency at kW loads is expected but not measured. The long-run ratio η is
dominated by low-load night inverting but is applied to daytime PV: if efficiency rises with load,
daytime Solar is under-credited and Battery over-credited. Totals still close exactly. A
load-dependent η would be a separate change.

### Venus OS MQTT publishes on CHANGE only (proven from source)
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

### Keep-alive (dbus-flashmq, Venus OS 3.x+)
The GX publishes `N/<portal>/…` only while it gets `R/<portal>/keepalive` at least every 60 s.
A keep-alive without `{"keepalive-options":["suppress-republish"]}` (and any topic-list payload,
which flashmq ignores) forces a full dump of ALL topics. So: `suppress-republish` every 30 s, and one
empty-payload keep-alive on HA `start` for the initial snapshot. A YAML reload does not fire `start`;
to force one snapshot after a reload, publish an empty payload to `R/c0619ab4c19e/keepalive`.

### expire_after policy
- MQTT sensors restore their last value after a restart only when `expire_after > 0` and
  `last_changed + expire_after` is still in the future (source, `components/mqtt/sensor.py` at
  2026.10.1; restore on a *reload* not verified). A missing `expire_after` is NOT harmless: the
  sensor is `unknown` until the GX publishes a changed value.
- Fluctuating power sensors (grid / AC load phases, DC PV, AC PV, MPPT W): 120 s. They never
  falsely expire, and an outage makes them unavailable.
- Slow values: SOC and battery voltage 24 h, MPPT and AC PV lifetime counters 7 d (constant
  overnight). Long enough not to falsely expire, present so the value survives a restart.
- `sensor.victron_vebus_dc_current`: 600 s. `victron_multiplus_dc_power` reads an expired current
  as 0 A, which would book the whole AC load as conversion loss while charging. A non-zero current
  changes about every second (no constant non-zero reading for 2+ min in ~5 days of history), so it
  never falsely expires within 600 s. It DOES expire, several times a day, after more than 10 min of
  real 0 A (idle). That is harmless: `ac_net_power` is then about -40..-50 W (Multi idle draw from
  AC), `dc_power` reads 0 W, `conversion_loss_power` shows the idle draw (same as a published
  0 A), and the η gate is closed.
- Every `value_template` checks `value_json is defined`: the GX publishes an EMPTY (non-JSON)
  payload when a service disappears, and then `value_json.value` alone raises.

## Entity map (IDs from YAML `default_entity_id` / as consumed)
| Entity | What |
|---|---|
| `sensor.victron_solar_yield_dc_watts`, `_dc_total_kwh` | raw MPPT W / lifetime kWh (pergola reads the W) |
| `sensor.victron_ac_inverter_power`, `_energy_total_kwh` | AC-coupled PV W / lifetime kWh (Energy Dashboard PV source 2) |
| `sensor.victron_vebus_dc_current`, `sensor.victron_battery_voltage` | inputs of `victron_multiplus_dc_power` |
| `sensor.victron_dc_pv_total_power` | MPPT DC W feeding `solar_yield_watts` |
| `sensor.victron_battery_soc` | SOC (Energy Dashboard, heating_pv_boost, heating dashboard) |
| `sensor.victron_grid_l1..l3_power`, `victron_ac_load_l1..l3` | per-phase MQTT, diagnostics + sums |
| `sensor.victron_grid_total_power`, `_power_import`, `_power_export` | signed grid sum, half-waves |
| `sensor.victron_grid_energy_import`, `_export` | `platform: integration`, Energy Dashboard grid |
| `sensor.victron_ac_load_total_power` | AC load sum (also pergola availability guard) |
| `sensor.victron_multiplus_ac_net_power`, `_dc_power`, `_conversion_loss_power`, `_conversion_loss_energy` | conversion stage |
| `sensor.victron_multiplus_ac_out_energy`, `_dc_in_energy`, `_conversion_efficiency` | η |
| `sensor.solar_yield_watts` | AC-referenced MPPT W (Energy Dashboard solar power) |
| `sensor.victron_solar_yield_total_kwh` | AC-referenced MPPT kWh accumulator (Energy Dashboard solar energy) |
| `sensor.victron_battery_ac_power` | power-domain battery residual (live / power graph; the dashboard's battery energy slot uses `battery_energy_in/out`) |
| `sensor.victron_battery_energy_in`, `_out` | energy-domain battery residual (Energy Dashboard battery) |
| `sensor.victron_solar_yield_dc_baseline_kwh`, `victron_ac_pv_energy_baseline_kwh` | previous counter readings |
| `sensor.victron_pv_net_power`, `_pv_surplus_power` | whole-house PV balance (heating_pv_boost, heating dashboard) |

## Decisions in force
- AC-referenced accounting, η as long-run ratio, counter-delta solar, two exact domains, AC PV on
  its own counter, repointed dashboard IDs, true DC = V × I, grid on `integration`: VIC-3.
- Baselines are separate state-only sensors declared AFTER their consumers, intending that the
  consumers read the previous tick's value. UNPROVEN: render order within one trigger pass was
  never demonstrated, so whether the order matters is unknown; reordering ⇒ re-run the
  counter-delta tests (VIC-9).
- η accumulators share one gate, duplicated inline; keep both copies identical (VIC-7).
- No `utility_meter:`; monthly figures, if wanted, go back as YAML (VIC-12).

## `sensor.victron_solar_yield_total_kwh` is not the MPPT counter
Template accumulator since #121: MPPT counter delta × η, starting from `this.state | float(0)`. It
did not inherit the old MQTT sensor's value (5644.65 kWh → 0.61 kWh on 2026-10-16); the statistics `sum`
stayed continuous, so the Energy Dashboard is fine. Never compare its state with the raw counter.

## Known small biases (documented, not fixed)
- Conversion loss is clamped per sample (`max(-(ac_net+dc), 0)`), so negative excursions are
  dropped and the loss reads a few W high (live 86 W vs ~93 W expected). Diagnostic only;
  unclamped, the `total_increasing` loss energy would not be monotonic.
- `conversion_efficiency` can render twice per minute tick (two accumulator entities) and briefly
  show a value from one fresh and one stale accumulator; cosmetic.
- UNPROVEN: η may lag its accumulators by one tick (a former comment attributed this to in-pass
  render order; never demonstrated). Do not rely on same-tick consistency between η and the
  accumulators.
- η is about 85 % in normal operation (85.1 % in 2026-11); use that as the sanity value.
- Existing η accumulator totals are not re-seeded; old data only dilutes.
- Battery is the residual in both domains, so all measurement error lands there.

## Open issue (not fixed)
`battery_energy_in` / `battery_energy_out` read grid/load with `float(0)` and no availability guard,
so an unavailable grid or load is booked as 0 W for that tick. A "hold the tick" fix is NOT a small
change: both sensors share a long template with counter-delta branches, and the solar/AC-PV baseline
sensors advance on their own, so a held tick would drop that tick's delta. Needs its own tests
(none cover an unavailable grid today).

## Tests (`tests/test_victron.py`)
- `_seed(vebus_dc=…)` means Multi DC power in W: it seeds 50 V and current `vebus_dc / 50`.
- `_seed_eta(ac_out=, dc_in=)` sets the two accumulators to control η directly. `_reset_energy`
  and conftest `baseline_states` reset accumulators to `0.0` and the baselines to `unknown`.
- Grid energy tests assert a before/after delta (`_grid_energy_baseline`): REST `set_state` cannot
  reset an `integration` sensor (VIC-11). The second seed is nudged by 1 W so the template chain
  re-renders. The expected kWh comes from the source sensor's `last_updated` span, not a fixed
  60 s: the step also contains real wall-clock time.
- Each test uses at most one `fast_forward(timedelta(minutes=1))` (one trigger render);
  preconditions like "already baselined" are seeded with `set_state`. The module docstring says
  why `jump_to_next(hour=...)` is avoided.
- `test_solar_yield_ac_total_captures_baseline_on_first_tick` is skipped (harness ordering flake;
  reason in the decorator).

## Related
- `doc/victron/design.md` (current design).
- `ha-energy-metering` skill (platform moves, registry reclaim), `ha-mqtt` skill.
- Consumers: `packages/pergola.yaml` (DC W, load total), `packages/heating_pv_boost.yaml`
  (PV net, AC PV, SOC), `dashboards/heating-dashboard.yaml`.
