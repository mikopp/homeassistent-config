# Victron energy accounting: design

Current design of `packages/victron.yaml`. Where this doc and the YAML disagree, the YAML wins:
fix this doc. Section IDs (`VIC-1` …) are stable; never renumber, mark retired IDs as gone.
Hardware quirks, entity map, biases and open issues: `packages/notes/victron.md`. History,
investigations and superseded designs: `background.md` (not design-relevant).

## VIC-1 Topology and goal

- Hardware: GX `c0619ab4c19e` (Cerbo GX); MPPT `solarcharger/279` (DC-coupled panels); AC-coupled
  third-party PV inverter `pvinverter/20` (measured on the AC side); MultiPlus-II `vebus/276`
  (3-phase, three devices); Smart BMS battery.
- DC bus: MPPT → MultiPlus ↔ battery. AC bus: MultiPlus AC out ↔ grid ↔ AC PV inverter ↔ loads.
- **No separate grid meter**: grid is measured at the Multi's own AC-in (`system/0/Ac/Grid/L1..3`).
- Austrian grid operator bills the 15-min SUM of all three phases (no per-phase billing), so every
  grid calculation uses the signed L1+L2+L3 total. Per-phase sensors are diagnostics only.
- Goal: the HA Energy Dashboard shows Solar and Battery **AC-referenced** (what the house actually
  received after the MultiPlus conversion), the conversion loss is explicit and graphable, and both
  the power and the energy domain close exactly.

## VIC-2 Sign conventions (the easiest thing to get wrong)

| Symbol | Entity | Positive means |
|---|---|---|
| `grid_net` | `sensor.victron_grid_total_power` | import |
| `ac_load` | `sensor.victron_ac_load_total_power` | consumption |
| `ac_pv` | `sensor.victron_ac_inverter_power` | AC PV production |
| `dc_pv` | `sensor.victron_dc_pv_total_power` | MPPT DC production |
| `mp_dc` | `sensor.victron_multiplus_dc_power` | **charging** (AC→DC) |
| `mp_ac_net` | `sensor.victron_multiplus_ac_net_power` | **inverting** (DC→AC) |
| `solar_ac` | `sensor.solar_yield_watts` | AC-equivalent MPPT production |
| `batt_ac` | `sensor.victron_battery_ac_power` | **discharging** (HA house-centric) |

`mp_ac_net` and `mp_dc` carry **opposite** conventions; every consumer accounts for that.

## VIC-3 Decisions in force (agreed with the user; do not re-litigate)

1. **AC-referenced model + loss diagnostics.** The loss is subtracted from Solar/Battery, not shown
   as an Energy Dashboard consumption device. AC-accurate headline numbers and a visible loss bar
   are mutually exclusive by construction.
2. **η = long-run accumulated ratio** `E_ac_out / E_dc_in` (inverting only), clamped 50–100 %,
   bootstrapping at 100 %. Always defined, including charge-only spells (VIC-7).
3. **Solar AC kWh accumulates from the delta of the MPPT lifetime counter**, not from per-minute
   power, so HA downtime loses no energy (VIC-9).
4. **The two domains are separate and each is internally exact** (VIC-5, VIC-6). The Energy
   Dashboard reads *energy* entities; live cards and W graphs read *power* entities. The battery
   *energy* slot of the Energy Dashboard uses `victron_battery_energy_in/out`;
   `victron_battery_ac_power` only feeds its power graph.
5. **AC-coupled PV keeps its own device counter** (`pvinverter/20/Ac/Energy/Forward`): an
   independent measurement that never touches the MultiPlus, needs no η and must not be degraded
   to an integration.
6. **Repoint, don't duplicate.** The Energy Dashboard's original IDs `sensor.solar_yield_watts` and
   `sensor.victron_solar_yield_total_kwh` carry the AC-referenced values; the raw MPPT readings
   live on `sensor.victron_solar_yield_dc_watts` / `_dc_total_kwh` (VIC-12).
7. **True Multi DC power = battery voltage × `system/0/Dc/Vebus/Current`** (VIC-8), never
   `system/0/Dc/Vebus/Power`.
8. **Grid energy uses `sensor: platform: integration`** (VIC-11); the other accumulators stay
   per-minute trigger sensors. Scope choice: the η/loss accumulators need the shared gate (VIC-7),
   so `integration` would need an extra gating template sensor each.

## VIC-4 Dependency graph (acyclic)

```
mqtt grid L1-3 ─► grid_total ─┬─► grid_power_import/export ─► [integration] grid_energy_import/export
mqtt load L1-3 ─► ac_load ────┼─► mp_ac_net ─┬─► [trig] ac_out_energy ─┐
mqtt ac_pv ───────────────────┘              │                         ├─► efficiency (η) ─┐
mqtt V_batt × mqtt I_vebus ─► mp_dc ─────────┼─► [trig] dc_in_energy ──┘                   │
                                             ├─► conversion_loss_power ─► [trig] loss_energy│
mqtt dc_pv ─────────────────────────────────────────────► solar_yield_watts ◄──────────────┤
                                             └─► batt_ac = mp_ac_net − solar_ac             │
mqtt MPPT counter, AC PV counter ─► [trig] solar_yield_total_kwh, battery_energy_in/out ◄──┘
                                    [trig] baselines (previous counter readings)
solar_yield_watts + ac_pv − ac_load ─► pv_net_power ─► pv_surplus_power
```

`mp_ac_net` never reads η, so the apparent loop accumulators → η → `solar_ac` → `batt_ac` is a DAG.
`[trig]` = sensors in the single `time_pattern: /1` trigger block.

## VIC-5 Power domain

```
mp_ac_net = ac_load − grid_net − ac_pv     (measured, + = inverting)
solar_ac  = dc_pv × η                      (AC-equivalent MPPT power)
batt_ac   = mp_ac_net − solar_ac           (+ = discharging)
```

- **Why `mp_ac_net` is measured, not modelled:** dbus-systemcalc-py defines
  `Ac/Consumption = (grid − vebus ActiveIn + pv_on_grid) + vebus Ac/Out + pv_on_output`. With no
  separate grid meter this collapses to `mp_ac_net == vebus Ac/Out − vebus Ac/ActiveIn`, so the
  raw `vebus/276/Ac/ActiveIn/P` and `Ac/Out/P` topics would be algebraically identical and are
  deliberately not subscribed.
- Battery is a **residual**, which handles simultaneous flows without per-watt attribution: every
  DC↔AC watt crosses one converter with one η. Applying the inverter η to PV that charges the
  battery assumes it eventually leaves via the inverter; guaranteed here (the Multi is the only
  DC-bus→AC path).
- **Identity, for any η:** `solar_ac + ac_pv + grid_net + batt_ac == ac_load` (the `solar_ac` term
  cancels). η only shifts the Solar/Battery split, never the total; this is what makes the 100 %
  bootstrap safe. At η = 100 % `batt_ac` equals the pre-#121 formula `ac_load − grid − dc_pv − ac_pv`.
- Worked cases at η = 0.94: PV 1000 DC + battery 500 DC inverting → `solar_ac` 940, `mp_ac_net`
  1410, `batt_ac` 470. PV 3000 DC, 2000 AC to load → `batt_ac` −820. MPPT 1000 DC and grid
  2000 AC both charging → `mp_ac_net` −2000, `batt_ac` −2940.
- `victron_pv_net_power = solar_ac + ac_pv − ac_load` (signed, negative = PV short of load);
  `victron_pv_surplus_power = max(net, 0)`. Consumers that add a load back
  (`packages/heating_pv_boost.yaml`) must use the signed net: clamping first loses the deficit.
  `packages/pergola.yaml` reads the raw `sensor.victron_solar_yield_dc_watts` (true panel output).

## VIC-6 Energy domain

The battery accumulators are an **energy-domain residual against the dashboard's own sources**,
every minute (MPPT and AC PV as counter deltas, grid as the minute sample, see the last bullet):

```
solar_inc = max(mppt_counter − mppt_baseline, 0) × η    # dashboard MPPT (= solar_yield_total_kwh step)
acpv_inc  = max(acpv_counter − acpv_baseline, 0)        # dashboard AC PV
grid_inc  = grid_net / 60000
load_inc  = ac_load  / 60000
batt_inc  = load_inc − grid_inc − acpv_inc − solar_inc
energy_in  += max(−batt_inc, 0);   energy_out += max(batt_inc, 0)
```

- By construction `solar_inc + acpv_inc + grid_inc + (out − in) == load_inc` exactly each minute;
  every source keeps its best measurement (no counter degraded to an integration).
- **Bootstrap fallback:** when a counter has no baseline yet (new sensor, manual reset) or its
  source is unavailable, that term falls back to the power estimate (`dc_pv × η / 60000`,
  `ac_pv / 60000`) instead of zero, so there is no dead first minute.
- **Accepted divergence:** `∫batt_ac ≠ energy_out − energy_in`. Each is exact in its own domain and
  HA never compares them (nothing integrates the power sensors into energy charts; the Riemann
  `integration` platform is used only for grid energy). Do not "fix" this.
- Note: `grid_inc` here is the per-minute sample of `grid_net`, while the dashboard's grid series is
  the `integration` sensor (VIC-11), so the residual is exact against the minute samples, not
  against the integration sensor.

## VIC-7 η (conversion efficiency)

- Accumulators (`[trig]`, kWh, `total_increasing`) share **one gate**, duplicated inline in both
  templates (keep identical; a helper entity would add a render-order dependency in the block):
  ```
  ok      = ac_net and mp_dc both available AND ac_net > 0 AND mp_dc < 0
  ac_out += ac_net  / 60000  if ok
  dc_in  += (−mp_dc) / 60000 if ok
  ```
  Only inverting is accumulated: charge efficiency differs, and the solar attribution only needs the
  inverting figure. With independent half-wave clamps, a tick where only one side looked inverting
  (mode transition, sampling skew, expired current) would advance one side and bias η; the shared
  gate drops such ticks from both.
- `victron_multiplus_conversion_efficiency` (plain, `%`, no `device_class`: `power_factor` is the
  only `%` class and would mislabel it) has **no `availability:`** and always returns a number, so
  `solar_ac` / `batt_ac` never go unavailable because of it:
  - either accumulator `unknown`/`unavailable`, or `E_dc_in < 1.0 kWh` → `100.0` (the 1.0 guard is
    also the division-by-zero guard);
  - else `clamp(E_ac / E_dc × 100, 50, 100)`, rounded to 0.1.
- Consumers read η with `| float(100)` in the trigger block, `| float` in `solar_yield_watts`.
- A clamp pinned at exactly 50 or 100 % for days means a sign or topology error; cross-check
  `mp_ac_net` against VRM "MultiPlus AC out".
- Normal value ≈ 85 % (note). One ratio for all loads is a known simplification; load dependence
  is only partly measured (note).
- Accumulator history is never re-seeded automatically; after a fix to the η inputs the user resets
  both accumulators to 0 together (Developer Tools → States), else old data only dilutes.

## VIC-8 MultiPlus DC power and conversion loss

- `mp_dc = V_batt × I_vebus` from `system/0/Dc/Battery/Voltage` (BMS) and
  `system/0/Dc/Vebus/Current`. `system/0/Dc/Vebus/Power` follows the AC side on this system and is
  not used (evidence in the note). The Multi current is negative while inverting (observed,
  −8.1 A); positive while charging follows the convention and is test-covered, but no live
  charging reading has been recorded. Re-check at a live charge. BMS vs Multi terminal voltage differs by ~0.02 V (≈ 0.04 %), negligible.
- Why the Multi current and not `Dc/Battery/Power`: the battery monitor also sees other DC loads
  (MPPT self-consumption, GX, ~10 W), which would be booked as Multi loss. The Multi's net DC
  current already includes MPPT flow, so no `dc_pv` term is needed.
- Conversion loss, one branchless formula for both directions:
  ```
  inverting (mp_ac_net > 0, mp_dc < 0): loss = (−mp_dc) − mp_ac_net
  charging  (mp_ac_net < 0, mp_dc > 0): loss = (−mp_ac_net) − mp_dc
  both:                                 loss = max(−(mp_ac_net + mp_dc), 0)
  ```
  Example: inverting `ac_net` 339, `mp_dc` −425 → 86 W. The ≥ 0 clamp exists because AC and DC are
  sampled independently; its bias is in the note. `victron_multiplus_conversion_loss_energy`
  integrates it per minute (monotonic because the source is clamped).

## VIC-9 Counter-delta accumulators and baselines

Used by `victron_solar_yield_total_kwh` (`state + max(Δ, 0) × η`) and the battery residual (VIC-6).

- The previous counter reading is the **state** of a dedicated trigger sensor,
  `victron_solar_yield_dc_baseline_kwh` / `victron_ac_pv_energy_baseline_kwh`
  (`src if available else this.state`), read with `states()`. No custom `attributes:` on trigger
  sensors: state-only is simpler and matches the `this.state` pattern every accumulator here uses
  (the attributes mechanism is UNPROVEN, `ha-templates` skill).
- Baselines carry `device_class: energy` + `state_class: total_increasing` like every other
  self-referencing trigger sensor in the file (harmless; keeps them consistent).
- **Sentinel:** `'unknown' | float(-1)` → `prev < 0` means "no baseline": the tick only re-baselines
  and adds nothing (solar total) or uses the power fallback (battery), so a lifetime total is never
  taken as a one-minute delta. Use a numeric `-1` sentinel, never `is none`.
- Counter reset / backwards jump: `max(Δ, 0)` adds nothing; the baseline re-anchors.
- Source unavailable: the total holds and the baseline holds, so the next good tick picks up the
  whole gap in one delta (no energy lost).
- **Declaration order:** the baselines are declared AFTER their consumers, intending that the
  consumers read the previous tick's value. Whether order matters is UNPROVEN (note, "Decisions in
  force"); reordering ⇒ re-run the counter-delta tests.

## VIC-10 Availability policy for derived sensors

- "GX alive" signals are `ac_load_total_power` (all three load phases) and `grid_total_power` (all
  three grid phases). `mp_ac_net` gates on load + grid (and everything downstream inherits it);
  `pv_net_power` gates on the load side only.
- An expired PV sensor (`dc_pv`, `ac_pv`, both `expire_after: 120`) means "not generating" = 0 W,
  not an outage: they are read with `| float(0)` and kept out of `availability:` in `mp_ac_net`,
  `solar_yield_watts`, `pv_net_power` and the battery residual. Putting them in `availability:`
  once blanked the battery chain and the dashboard at night and biased η (background).
- `mp_dc` reads the Multi current with `| float(0)` (expired current = 0 A = nothing flowing) and
  gates only on the voltage; a real GX outage is still caught because every consumer pairs it with
  `mp_ac_net`.
- These are deliberate deviations from the "no `float(default)`" rule; each has an inline comment.
- MQTT `expire_after` sizing and the change-only publish behaviour: note.

## VIC-11 Grid energy (`sensor: platform: integration`)

- `victron_grid_energy_import/export` integrate `victron_grid_power_import/export` (non-negative
  half-waves of `grid_total_power`) with `method: trapezoidal`, `unit_prefix: k`, `round: 3`, on
  every source state change (~1-2 s MQTT cadence) instead of one sample per minute.
- No `device_class` / `state_class` keys (the platform rejects them and sets its own).
- Platform semantics (running total in memory, not resettable by `set_state`; missing source at
  startup; statistics step when replacing a `total_increasing` sensor) and why a same-value
  re-post does not reach it through the template chain: `ha-energy-metering` and `ha-templates`
  skills.

## VIC-12 Entity identity rules for this package

- Entities whose platform changed but which keep the Energy Dashboard's IDs (same `unique_id`):
  `sensor.solar_yield_watts` (`victron_solar_yield`, mqtt → template),
  `sensor.victron_solar_yield_total_kwh` (mqtt → template trigger),
  `sensor.victron_grid_energy_import` / `_export` (template trigger → integration). A platform
  move needs a manual registry reclaim (delete orphan, rename new entity within ~5 min); procedure
  in the `ha-energy-metering` skill.
- `sensor.victron_solar_yield_total_kwh`'s state is an accumulator since #121, not the MPPT
  counter (note).
- MQTT sensors carrying `device:` must pin `default_entity_id`, else HA derives
  `sensor.technikraum_victron_energy_system_…` and consumers read a missing ID (#126).
- Template entities cannot carry `device:`; device assignment is a UI step.
- Naming scheme: **AC Inverter** = `pvinverter/20`; **Solar Yield** = MPPT `solarcharger/279`
  (DC and AC variants); **MultiPlus** = `vebus/276` conversion stage. `victron_vebus_dc_current`
  keeps the VEBus prefix (MQTT topic name).
- No `utility_meter:` in this package; if monthly figures are wanted again, add a YAML
  `utility_meter:` block (not UI helpers).

## VIC-13 Live sanity checks

- Power identity, continuously: `solar_yield_watts + victron_ac_inverter_power +
  victron_grid_total_power + victron_battery_ac_power == victron_ac_load_total_power`.
- Energy identity over a day: AC solar + AC PV + net grid + (battery out − in) ≈ ∫`ac_load`
  (within ~1 %; a residual gap means an AC-side input went unavailable, not a formula error).
- Night, inverting: `solar_yield_watts` = 0 but available; `battery_ac_power` > 0;
  `conversion_loss_power` clearly > 0 (tens of W at ~350 W, hundreds at kW loads).
- Midday: `solar_yield_watts` < `victron_dc_pv_total_power`.
- `mp_dc` ≈ `system/0/Dc/Battery/Power` within the other DC loads, same sign; never ≈ `mp_ac_net`.
- η ≈ 85 % (VIC-7).
