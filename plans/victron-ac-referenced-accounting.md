# Victron: AC-referenced Solar & Battery for the HA Energy Dashboard

**Status:** IMPLEMENTED — repo-side changes complete, CI green (see "CI fix" section below); deploy
(with entity-registry reclaim) pending.
**Target files:** `packages/victron.yaml`, `packages/pergola.yaml`, `tests/test_victron.py`,
`tests/conftest.py`, `tests/test_pergola.py`
**Branch:** `fix-victron-ac-dc-mixup` (PR #101)

---

## Context

### The problem

`sensor.victron_battery_ac_power` (victron.yaml:274-284) currently computes:

```
batt_ac = ac_load - grid_net - dc_pv - ac_pv
```

`ac_load`, `grid_net` and `ac_pv` are **AC** watts. `dc_pv` is **DC** watts. Subtracting a DC
quantity from an AC quantity silently charges the entire MultiPlus DC→AC conversion loss to the
battery, and reports MPPT solar at its DC value — more than the house actually received as AC.

Consequences today:
- Solar (MPPT) overstated by the inverter loss (~6 %).
- Battery In/Out absorb a loss that is not the battery's (error scales as
  `(1-η) × E_mppt / E_batt`, exceeding 30 % on high-sun, low-cycling days).
- The loss is invisible — not graphable, not attributable.

### What the investigation established

Victron publishes **no** AC-side battery or AC-side DC-PV topic. `system/0/Dc/Vebus/Power` is always
DC (systemcalc computes it as `/Dc/0/Voltage × /Dc/0/Current` off the vebus service — one code path,
no ESS/mode branch). The AC-referencing must therefore be derived.

Tracing `Ac/Consumption` in `dbus-systemcalc-py` gives
`(grid − vebus ActiveIn + pv_on_grid) + vebus Ac/Out + pv_on_output`. This system has **no separate
grid meter** (grid is read at the Multi's AC-in, victron.yaml:149-150), so that collapses to a proven
identity:

```
mp_ac_net := ac_load - grid_net - ac_pv   ==   (vebus Ac/Out) - (vebus Ac/ActiveIn)
```

`mp_ac_net` is the **measured** net AC power of the Multi's conversion stage.

**Key consequence:** the existing formula already computes the correct measured AC quantity. Its only
defect is the `dc_pv` term. **No new MQTT topics are required** — subscribing to
`vebus/276/Ac/ActiveIn/P` and `Ac/Out/P` would yield an algebraically identical value, so they are
deliberately omitted.

### Sign conventions (the easiest thing to get wrong here)

| Quantity | Entity | Positive means |
|---|---|---|
| `grid_net` | `victron_grid_total_power` | import |
| `ac_load` | `victron_ac_load_total_power` | consumption |
| `ac_pv` | `victron_ac_inverter_power` | AC PV production |
| `dc_pv` | `victron_dc_pv_total_power` | MPPT DC production |
| `vebus_dc` | `victron_vebus_dc_power` | **charging** (AC→DC) |
| `mp_ac_net` | **new** `victron_multiplus_ac_net_power` | **inverting** (DC→AC) |
| `batt_ac` | `victron_battery_ac_power` (kept) | **discharging** |

`mp_ac_net` and `vebus_dc` carry **opposite** conventions. Every consumer must account for that.

### Intended outcome

Solar and Battery become AC-referenced, so the Energy Dashboard describes what the house actually
received; conversion loss becomes explicit and graphable; and **both the power and the energy domain
close exactly**.

---

## Decisions taken (agreed with user — do not re-litigate)

1. **AC-referenced model + loss diagnostics.** Losses are subtracted from Solar/Battery, not shown as
   a dashboard consumption device. AC-accurate headline numbers and a visible loss bar are mutually
   exclusive by construction: if Solar/Battery are already AC-accurate, the loss has been subtracted
   from them and no residual remains to draw.
2. **η = long-run accumulated ratio** `E_ac_inv / E_dc_inv`, clamped 50–100 %, bootstrapping at
   100 %. Chosen because it is always defined — including during charge-only spells when no
   inverting is happening to measure η from.
3. **Solar AC kWh accumulates from the delta of the MPPT lifetime counter**, not per-minute power, so
   HA downtime does not lose energy.
4. **The two domains are kept separate and each is made internally exact.** HA never bridges them:
   the Energy Dashboard, utility meters and period charts read *energy* entities; live cards and W
   graphs read *power* entities. `victron_battery_ac_power` is **not** consumed by the Energy
   Dashboard — HA's battery config takes `victron_battery_energy_in/out`.
5. **AC-coupled PV keeps its own device counter.** `pvinverter/20/Ac/Energy/Forward` is an
   independent measurement from a physically separate device that never touches the MultiPlus. It
   needs no η and must not be degraded to an integration.

---

## The maths

### Power domain

```
mp_ac_net = ac_load - grid_net - ac_pv          (measured, + = inverting)
solar_ac  = dc_pv * eta                          (AC-equivalent MPPT power)
batt_ac   = mp_ac_net - solar_ac                 (+ = discharging)
```

Battery is a **residual**, which is what makes simultaneous flows work without per-watt attribution:
every DC↔AC watt crosses one converter with one η.

Worked cases at η = 0.94:

| Scenario | Inputs | `solar_ac` | `mp_ac_net` | `batt_ac` | Check |
|---|---|---|---|---|---|
| PV + battery both inverting | `dc_pv`=1000, batt −500 DC | 940 | 1410 | 470 | `500×0.94 = 470` |
| PV feeds load **and** charges | `dc_pv`=3000, 2000 AC to load | 2820 | 2000 | −820 | `872 DC × 0.94 = 819` |
| MPPT **and** grid both charging | `dc_pv`=1000, grid 2000 AC | 940 | −2000 | −2940 | `2000 + 940` |

Stated assumption: applying the *inverter* η to PV charging into the battery presumes that PV will
eventually leave via the inverter. Guaranteed here — the Multi is the only DC-bus→AC path.

**The identity holds for _any_ η**, which is what makes the 100 % bootstrap safe:
`solar_ac + ac_pv + grid + (mp_ac_net - solar_ac) = ac_load` — the `solar_ac` term cancels. η only
shifts the split between the Solar and Battery buckets, never the total.

### Energy domain

The Energy Dashboard mixes **device counters** (MPPT `Yield/System`, AC-PV `Ac/Energy/Forward`) with
**per-minute integration** (grid). Today the battery accumulators integrate the `batt_ac` *power*
sensor, so they are reconciled against `∫dc_pv` and `∫ac_pv` — not against the counter series the
dashboard actually displays. The gap (minute-sampling error, `expire_after: 120` dropouts, HA
downtime — the last two strictly one-sided) leaks into untracked energy.

Fix: compute the battery accumulators as an **energy-domain residual against exactly the series the
dashboard displays**:

```
per minute:
  solar_inc = max(mppt_counter_delta, 0) * eta     # what the dashboard shows for MPPT
  ac_pv_inc = max(acpv_counter_delta, 0)           # what the dashboard shows for AC PV
  grid_inc  = grid_net / 60000                     # what the dashboard shows for grid
  load_inc  = ac_load / 60000

  batt_inc  = load_inc - grid_inc - ac_pv_inc - solar_inc
  energy_in  += max(-batt_inc, 0)
  energy_out += max( batt_inc, 0)
```

By construction `solar_inc + ac_pv_inc + grid_inc + (out - in) = load_inc` **exactly**. Every source
keeps its best available measurement — no counter is degraded to an integration.

### Accepted, deliberate divergence between the domains

`∫battery_ac_power ≠ battery_energy_out − battery_energy_in` exactly. Each is exact in its own
domain, and HA never compares them: nothing integrates power sensors to fill energy charts, and
nothing differentiates energy to produce power. (The one component that *would* bridge them is the
Riemann-sum `integration` platform, which this repo deliberately does not use.) Document this in the
file so a future reader does not "fix" it.

### Conversion loss — needs no η, measured directly

Because `mp_ac_net` and `vebus_dc` carry opposite conventions, both directions collapse to one
branchless formula:

```
inverting  (mp_ac_net > 0, vebus_dc < 0):  loss = (-vebus_dc) - mp_ac_net
charging   (mp_ac_net < 0, vebus_dc > 0):  loss = (-mp_ac_net) - vebus_dc
                            both equal ->  loss = -(mp_ac_net + vebus_dc)   clamped >= 0
```

Inverting: `-(940 + -1000) = 60`. Charging: `-(-2000 + 1900) = 100`.

**No double counting.** `victron_system_losses_power` is a *DC-bus* balance
(`dc_pv + vebus_dc - batt_dc`); this is the *conversion-stage* balance. `vebus_dc` appears in both
with opposite sign, so they sum to `dc_pv - batt_dc - mp_ac_net` — total system loss, nothing twice.
Both are kept, unchanged.

---

## Expected accuracy impact

| Figure | Today | After | Change |
|---|---|---|---|
| Solar (MPPT) kWh | ~6 % overstated | ±1 % (η estimation) | **~85 % error reduction** |
| Battery In/Out kWh | `(1-η)·E_mppt/E_batt`, often 15-30 % | ±3 % | **~85 % error reduction** |
| Untracked **power** (kW) | exact | exact | **0 % — already exact** |
| Untracked **energy** (kWh) | inflated by counter-vs-integration gap | exact by construction | **gap eliminated** |

Worked example (η = 0.94, MPPT 20 kWh DC, AC-PV 10, grid 5, house 28): Solar 20.0 → 18.8 kWh;
battery net charge 7.0 → 5.8 kWh; home consumption 28.0 both. The two errors are equal and opposite
— exactly `(1-η) × MPPT_production` — which is why they cancel in the total, and why the total looks
right today while the parts are wrong.

**This system's actual current-month figures**, read live via `ha-mcp` (not hypothetical):

| Meter | Value |
|---|---|
| `victron_solar_mppt_monthly` (DC) | 202.11 kWh |
| `victron_battery_in_monthly` | 140.247 kWh |
| `victron_battery_out_monthly` | 93.620 kWh |
| Net battery charge (in − out) | 46.627 kWh |

At an assumed η = 0.94 (η itself is not yet measurable — no sensor exists pre-deploy), today's Solar
figure is overstated by ≈ 12.1 kWh (6 %), and that same 12.1 kWh is misattributed into the battery
net-charge figure, which is a **≈ 26 %** error on its own 46.6 kWh (`0.06 × 202.11 / 46.627`) — this
system sits at the high end of the predicted range precisely because MPPT production is large
relative to battery throughput. Re-run this comparison after a week on the real
`victron_multiplus_conversion_efficiency` reading to replace the assumed η with a measured one.

---

## Implementation

### Dependency graph (verified acyclic)

```
mqtt ──► grid_total ──┐
mqtt ──► ac_load_total ┼──► mp_ac_net ──┬──► [trig] inverter_energy_ac_out ─┐
mqtt ──► ac_pv ───────┘                 │                                   ├──► efficiency ──┐
mqtt ──► vebus_dc ──────────────────────┼──► [trig] inverter_energy_dc_in ──┘                 │
                                        ├──► conversion_loss_power ──► [trig] conv_loss_energy│
                                        │                                                     │
                                        ├──────────────────────────► batt_ac ◄── solar_ac ◄───┤
                                        └──► [trig] battery_energy_in/out ◄───────────────────┘
                                                          (energy-domain residual)
```

`mp_ac_net` never reads η, so the apparent loop `mp_ac_net → accumulators → η → solar_ac → batt_ac`
is a strict DAG.

**Ordering hazards — benign, do not "fix":**
1. *Same-tick staleness.* All sensors in one `- trigger:` block render in a single pass. When the
   minute tick updates the η accumulators, the plain `inverter_efficiency` sensor re-renders only
   after that tick, so same-block consumers use the **previous minute's** η. η moves <0.01 %/min past
   bootstrap — far below measurement noise. Do not inline the η computation to fix this; it would
   duplicate the clamping logic in four places.
2. *First-evaluation NaN — impossible.* `inverter_efficiency` is built so it can never be unavailable
   and never divide by zero: it returns literal `100.0` whenever either accumulator is
   `unknown`/`unavailable` or `E_dc_in < 1.0 kWh`.
3. *Cold start.* MQTT sensors arrive before the first minute tick; accumulators are `unknown` for up
   to 60 s → η = 100 % → exactly today's behaviour. No window where `batt_ac` is wrong in a new way.

### Step 0 — add `availability:` to `victron_ac_load_total_power` (victron.yaml:258-266)

Currently unguarded, in violation of the CLAUDE.md rule, and it now feeds `mp_ac_net` — a silently
zero phase would corrupt `mp_ac_net`, `batt_ac` and both η accumulators. Add the three-phase guard
and drop the `| float(0)` defaults, matching `victron_grid_total_power` directly above it.

### Step 1 — new plain sensor `victron_multiplus_ac_net_power`

`ac_load - grid_net - ac_pv`, with availability over all three. Extracting this shared subexpression
means `batt_ac`, the accumulators and `conversion_loss` read one entity instead of repeating a
seven-sensor sum. Comment must record the systemcalc derivation and the opposite sign convention.

### Step 2 — η accumulators (append to the existing `- trigger: time_pattern /1` block)

```
victron_multiplus_ac_out_energy += max( mp_ac_net, 0) / 60000
victron_multiplus_dc_in_energy  += max(-vebus_dc,  0) / 60000
```

Only the **inverting** direction, both half-waves clamped at 0. Charging is excluded on purpose:
charge efficiency differs from discharge efficiency, and the solar attribution only needs inverting.

### Step 3 — `victron_multiplus_conversion_efficiency` (plain, `%`)

```
if either accumulator unknown/unavailable, or E_dc_in < 1.0 kWh:  100.0
else:  clamp(E_ac / E_dc * 100, 50, 100)
```

The `E_dc_in < 1.0` guard is also the division-by-zero guard — the divisor is provably ≥ 1.0 on the
division path. **No `availability:` template** — this sensor is defined to always return a number so
that `solar_ac`/`batt_ac` can never go unavailable because of it. Omit `device_class` (`power_factor`
is the only `%` class and would mislabel it).

### Step 4 — `victron_solar_yield_ac_watts` (plain, `W`)

`dc_pv * eta/100`, availability over `dc_pv` and the efficiency sensor.

### Step 5 — rewrite `victron_battery_ac_power` (keep entity_id, unique_id, sign)

```
batt_ac = mp_ac_net - solar_ac
```

Entity ID, `unique_id` and the positive=discharging convention are preserved. Add `availability:`.
Comment must state that this is the **power-domain** residual, serving live cards only, and is
deliberately not the integral of the energy sensors.

### Step 6 — `victron_solar_yield_ac_total_kwh` (trigger block, delta-based)

Carries the previous MPPT lifetime reading in an attribute:

```yaml
state: >
  {% set src  = states('sensor.victron_solar_yield_total_kwh') %}
  {% set prev = this.attributes.get('last_dc_total', -1) | float(-1) %}
  ...
  {% if src in ['unavailable','unknown'] or prev < 0 %}
    hold this.state                        # no baseline yet, or source down
  {% else %}
    this.state + max(src - prev, 0) * eta  # max() absorbs a counter reset
  {% endif %}
attributes:
  last_dc_total: >
    ... src if numeric, else hold the previous baseline ...
```

**Use a numeric `-1` sentinel, not `is none`.** A missing/non-numeric attribute passes an `is none`
test but `float()`s to `0`, which would add the entire MPPT *lifetime* total as one minute's delta.
Use `.get()` — bare `this.attributes.last_dc_total` yields a Jinja Undefined on first run.

Verified semantics: `state:` and `attributes:` render in one pass against the *pre-update* `this`, so
`state:` reads the old baseline while `attributes:` writes the new one. Trigger entities with a
`unique_id` restore state **and** custom attributes together. Both templates must be written so they
**cannot raise** — if `state:` throws, HA discards the whole render including attributes, dropping
the baseline.

### Step 7 — rewrite `victron_battery_energy_in/out` as an energy-domain residual

This is the "adjust Battery Energy In/Out if needed" item. Entity IDs, `unique_id`s and the
`utility_meter` bindings all stay put; only the formula changes.

Each sensor carries its **own** `last_mppt_total` and `last_acpv_total` attributes. Both render in
the same pass against the same source states, so they compute identical deltas. The duplication is
deliberate — reading a sibling sensor's delta would reintroduce the same-tick staleness hazard.

Same `-1` sentinel, `max(delta, 0)` reset guard, and hold-on-unavailable behaviour as Step 6.

### Step 8 — loss diagnostics

| Entity | Kind | Definition |
|---|---|---|
| `victron_multiplus_conversion_loss_power` | plain, W | `max(-(mp_ac_net + vebus_dc), 0)` |
| `victron_multiplus_conversion_loss_energy` | trigger, kWh | per-minute accumulation of the above |
| `victron_battery_roundtrip_loss_energy` | plain, kWh | `max(energy_in - energy_out, 0)` |

`victron_battery_roundtrip_loss_energy` caveats, both to be written into the file:
- It **includes the energy currently stored** in the battery, so it is an *upper bound* on true
  round-trip loss. Only meaningful compared at equal SOC (e.g. 07:00 to 07:00 at the same overnight
  floor).
- `state_class: measurement` with **no `device_class`**. It shrinks during discharge, so
  `total_increasing` would generate phantom resets — and HA rejects `device_class: energy` combined
  with `state_class: measurement`.

`victron_system_losses_power/energy` (victron.yaml:291-300, 347-352) are **unchanged**.

### Step 9 — `utility_meter`

Add two, **keep all six existing ones**:

```yaml
victron_multiplus_conversion_loss_monthly:  source: sensor.victron_multiplus_conversion_loss_energy
victron_solar_ac_monthly:         source: sensor.victron_solar_yield_ac_total_kwh
```

`victron_solar_mppt_monthly` stays on the DC counter — the difference between it and
`victron_solar_ac_monthly` *is* the monthly MPPT→AC conversion loss, which is worth having. Not
swapping it also avoids resetting its history.

### Step 10 — audit and report unused sensors (report only, no deletions)

Deliverable: a table of every entity in `packages/victron.yaml` classified by consumer. **Nothing is
deleted without explicit approval** — this step produces the list, a follow-up decides.

Preliminary audit, from a full read of the file plus a repo-wide reference search. To be re-verified
against the final file at implementation time.

**In active use** (dashboard or cross-package):

| Entity | Consumer |
|---|---|
| `victron_grid_energy_import` / `_export` | Energy Dashboard (grid energy) + monthly meters |
| `victron_grid_power_import` / `_export` | Dashboard (grid power) |
| `victron_solar_yield_total_kwh` | Dashboard (PV energy) → to be replaced by the AC total |
| `solar_yield_watts` | Dashboard (PV power) **and** `packages/pergola.yaml` → `pergola_pv_power` |
| `victron_ac_inverter_power` / `_energy_total_kwh` | Dashboard (AC PV power + energy) |
| `victron_battery_energy_in` / `_out` | Dashboard (battery energy) + monthly meters |
| `victron_battery_ac_power` | Dashboard (battery power) |
| `victron_battery_soc` | Dashboard (SOC) |
| `victron_ac_load_total_power` | `packages/pergola.yaml` availability guard + `mp_ac_net` |

**Internal only — required, not directly consumed:**

| Entity | Feeds |
|---|---|
| `victron_grid_l1/l2/l3_power` | `victron_grid_total_power` (kept as per-phase balance diagnostics) |
| `victron_ac_load_l1/l2/l3` | `victron_ac_load_total_power` |
| `victron_grid_total_power` | grid half-waves + `mp_ac_net` |
| `victron_dc_pv_total_power` | `victron_solar_yield_ac_watts` |
| `victron_vebus_dc_power` | η accumulators + `conversion_loss` + `system_losses` |

**Dead branch — nothing consumes it, on or off the dashboard:**

| Entity | Note |
|---|---|
| `victron_battery_power` | only feeds `system_losses_power` |
| `victron_system_losses_power` | only feeds `system_losses_energy` |
| `victron_system_losses_energy` | **terminal** — no dashboard use, no `utility_meter`, no package |

The whole `battery_power → system_losses_power → system_losses_energy` chain terminates in an entity
nothing reads. It is retained by this plan (it measures the DC-bus balance, complementary to the new
conversion loss) but it is the clearest removal candidate. Adding a
`victron_system_losses_monthly` utility_meter would instead give it a purpose.

**No config consumer** (intended for manual invoice comparison, not referenced by any dashboard,
automation or test): all six existing `utility_meter` entities.

Note the current branch is `remove-unused-victron-sensors`, so this audit is on-theme; commit
`b98803f` already removed six such sensors.

### Step 11 — project-rule compliance pass

`availability:` on every new sensor reading a non-guaranteed source; no `| float(default)` where a
guard already applies; no `device:` key in `template:` (unsupported — assign via UI, see Deploy); a
comment describing each part, matching the file's existing density.

---

## Test impact

**All 13 existing assertions still pass unchanged.** η only leaves the 100 % bootstrap once
`E_dc_in` exceeds 1.0 kWh, which requires `vebus_dc < 0` **during a time jump**. Auditing every seed
that coincides with a clock jump:

| Test that jumps time | `vebus_dc` | `E_dc_in` gain |
|---|---|---|
| `test_grid_import_energy_accumulates` | 0 | 0 |
| `test_grid_export_energy_accumulates` | 0 | 0 |
| `test_battery_discharge_energy_accumulates` | 0 (unseeded) | 0 |
| `test_night_no_grid_energy_accumulates` | 0 (unseeded) | 0 |
| `test_system_losses_energy_accumulates` | **+2878** (charging) | 0 |

`test_night_solar_off_battery_discharge` seeds `vebus_dc=-600` but performs **no** jump, and
`conftest.baseline_states` re-seeds it to 0 before the next test. So `E_dc_in` stays ≈ 0, η stays at
100 %, and `solar_ac = dc_pv` — reducing `batt_ac` to today's formula exactly.

At η = 100 % with both lifetime counters seeded at `0.0` and never advancing, the new energy-domain
residual also reproduces the old values:

| Assertion | Recomputed | Verdict |
|---|---|---|
| `battery_ac_power == 92` (:100) | `mp_ac_net 92 − solar_ac 0` | **unchanged** |
| `battery_ac_power == -600` (:109) | `600 − 1200` | **unchanged** |
| `battery_ac_power == 0.0` (:118) | `800 − 800` | **unchanged** |
| `battery_ac_power == 1200` (:193) | `1200 − 0` | **unchanged** |
| `battery_energy_out ≈ 0.02` (:196) | `load_inc 0.02 − 0 − 0 − 0` | **unchanged** |
| `battery_energy_in == "0.0"` (:200) | `max(-0.02, 0)` | **unchanged** |
| `system_losses_power` ×4 (:231,237,243,253) | formula untouched | **unchanged** |

**This is incidental, not robust.** A future test that seeds a negative `vebus_dc` and jumps 20+
minutes would silently flip assertions :109 and :118. The conftest seeds below make it deterministic.

### Required test changes

1. **`tests/conftest.py` — `baseline_states`**: seed the new accumulators to `"0.0"` so η is
   deterministically at bootstrap in every test —
   `victron_multiplus_ac_out_energy`, `victron_multiplus_dc_in_energy`,
   `victron_multiplus_conversion_loss_energy`, `victron_solar_yield_ac_total_kwh`.
   Passing an attrs dict also clears `last_dc_total`, so every test starts un-baselined.
2. **`tests/test_victron.py` — `_reset_energy()`** (line 58 loop): add the same four entity IDs. The
   `home_assistant` fixture is **session-scoped**, so accumulator state bleeds across tests
   otherwise.
3. **New helper** `_seed_eta(ha, *, ac_out, dc_in)` — `set_state` on the two accumulators makes η
   directly controllable, since `inverter_efficiency` is a plain template sensor that recomputes when
   they change.

### New tests

| Area | Cases |
|---|---|
| `mp_ac_net` | inverting (`ac_l1=1000, grid=200, ac_pv=100` → `700`); charging (`ac_l1=200, grid=1000` → `-800`) |
| η | bootstrap at 0 accumulators → `100.0`; below 1.0 kWh threshold → `100.0`; `_seed_eta(9,10)` → `90.0`; clamp low `(1,10)` → `50.0`; clamp high `(12,10)` → `100.0` |
| `solar_ac_watts` | bootstrap `dc_pv=1000` → `1000`; `_seed_eta(9,10)` → `900` |
| `batt_ac` | `_seed_eta(9,10)`, `dc_pv=1200, ac_l1=600` → `-480` (regression guard proving η reaches `batt_ac`) |
| power identity | mixed scenario: assert `solar_ac + ac_pv + grid + batt_ac == ac_load` |
| energy identity | after a jump: assert `solar_inc + ac_pv_inc + grid_inc + (out-in) == load_inc` |
| conversion loss | inverting (`ac_l1=950, vebus_dc=-1000` → `50`); charging (`grid=1000, vebus_dc=950` → `50`); clamped → `0.0`; energy accumulates |
| solar AC total | first run baselines only (state stays `0.0`, `last_dc_total` set); delta applied; delta scaled by η; counter reset holds; source unavailable holds baseline |
| battery energy residual | counter advance produces the right in/out split; AC-PV counter advance is subtracted correctly |
| roundtrip loss | `in=10, out=8` → `2.0`; `out=12` → `0.0` (clamped) |

Chained-attribute tests (solar AC total) must run as one test with sequential jumps, or reset
explicitly at the top of each — `_reset_energy` clearing the attribute is what makes them
independent.

---

## Verification

1. `pytest tests/ -v` — all 13 existing assertions still green (if any moves, η left the bootstrap
   and the conftest seeds were not applied correctly), new tests green.
2. HA config check via the existing `.github/workflows/ha_check.yaml` path.
3. On the live system, sanity-check by regime:
   - **Night, discharging:** `solar_yield_ac_watts` = 0; `battery_ac_power` > 0 and slightly below
     `|victron_battery_power|`; `conversion_loss_power` > 0.
   - **Midday, exporting:** `solar_yield_ac_watts` < `victron_dc_pv_total_power`.
   - **Charging from grid + MPPT** (the case that motivated this): `battery_ac_power` negative and
     larger in magnitude than the grid draw alone.
   - **Power identity, continuously:** `solar_yield_ac_watts + victron_ac_inverter_power +
     victron_grid_total_power + victron_battery_ac_power` == `victron_ac_load_total_power`.
4. After ~24 h of inverting, `victron_multiplus_conversion_efficiency` should leave the bootstrap once
   `victron_multiplus_dc_in_energy` passes 1.0 kWh and settle in a plausible 92–95 % band. If it pins
   at exactly 50 % or 100 % for days, the clamp is hiding a sign or topology error — cross-check
   `victron_multiplus_ac_net_power` against VRM's "MultiPlus AC out".
5. After ~1 week: the Energy Dashboard "Home consumption" for a day should match the integral of
   `victron_ac_load_total_power` to within rounding. A residual gap now means an AC-side input is
   going unavailable, not a formula error.

---

## Revision: repoint instead of duplicate (post-implementation)

The plan as first implemented created NEW entities (`victron_solar_yield_ac_watts`,
`victron_solar_yield_ac_total_kwh`) and left the original `solar_yield_watts` /
`victron_solar_yield_total_kwh` on their raw DC values, requiring a manual Energy Dashboard source
swap and accepting a permanent history discontinuity at the swap date.

**User caught a better approach**: since `solar_yield_watts` and `victron_solar_yield_total_kwh` are
the entity IDs the Energy Dashboard *already* points at, REPOINT those same IDs to the AC-referenced
formulas instead, and give the raw DC readings NEW entity IDs
(`victron_solar_yield_dc_watts` / `_dc_total_kwh`). Implemented as such. Consequences:

- **No Energy Dashboard reconfiguration** for the solar source — it already points at these IDs.
- **`victron_battery_ac_power`, `victron_battery_energy_in/out`** now read the repointed
  `sensor.solar_yield_watts` / feed off `sensor.victron_solar_yield_dc_total_kwh` respectively —
  see the code comments in `packages/victron.yaml` for the exact wiring.
- **`packages/pergola.yaml`** repointed to `sensor.victron_solar_yield_dc_watts` (it wants true panel
  output, not an AC-discounted figure) — done, see that file's `pergola_pv_power` sensor.
- **`victron_solar_mppt_monthly`** repointed to the new DC entity (preserves its original DC-tracking
  purpose); **`victron_solar_ac_monthly`** repointed to the now-AC `victron_solar_yield_total_kwh`.
  Their difference still *is* the monthly conversion loss.

### The entity-registry catch — this is NOT a zero-touch restart

Initial assumption (told to the user, and **wrong**) was that keeping the same `unique_id` across the
platform change (`mqtt:` → `template:`) would be enough for HA to treat it as the same entity and
inherit history automatically. Verified against HA's own documentation and a matching core GitHub
issue that this is false: **the entity registry key includes the platform that registers the entity**,
not just `unique_id`. An `mqtt:`-platform entity and a `template:`-platform entity with an identical
`unique_id` string are two *different* registry rows. Home Assistant will NOT silently merge them —
requesting the old entity_id from the new entity conflicts with the old (now-orphaned) registry row
still holding it, and HA falls back to a suffixed id (`sensor.solar_yield_watts_2`), which is exactly
the discontinuity this revision exists to avoid.

The correct, still-lossless mechanism requires one manual step per repointed entity:

1. Deploy the YAML (old `mqtt:` blocks removed, new `template:` blocks added with
   `default_entity_id:` set to the desired old id — already done in `packages/victron.yaml`).
2. Restart. The old `mqtt:` entities disappear from their platform; their entity_ids become orphaned
   registry rows (state `unavailable`, no config providing them) — NOT automatically deleted.
3. **Settings → Devices & Services → Entities → find each orphaned entity → delete it.** This frees
   the entity_id string. (Two entities: `sensor.solar_yield_watts`, `sensor.victron_solar_yield_total_kwh`.)
4. **Find the new template entity** (it will have landed on a fallback id, e.g.
   `sensor.victron_solar_yield_watts_2` or similar) **→ rename its Entity ID** in the UI to the freed
   string (`sensor.solar_yield_watts` / `sensor.victron_solar_yield_total_kwh`). A user-initiated
   rename in the UI is always conflict-free once the old id is free, regardless of platform/unique_id.
5. Once the entity_id string matches, the recorder/statistics tables — which key by entity_id string,
   not by the abstract registry identity — continue the SAME timeline: old history stays, new values
   append with zero gap, zero reset artifact.

This is genuinely more manual work than "just restart," but it is comparable in effort to the
original plan's Energy Dashboard dropdown swap, and it buys real continuity: no dashboard bar goes
dark, no lifetime total resets to zero.

---

## Deploy steps (user actions — not deployable by `git pull` alone)

1. `git pull` on the HA host → Developer Tools → YAML → *Check configuration* → **full restart**
   (new `utility_meter` entities need a restart; a template reload is not enough).
2. **Entity-registry reclaim** (see "The entity-registry catch" above) — for BOTH
   `sensor.solar_yield_watts` and `sensor.victron_solar_yield_total_kwh`:
   a. Delete the orphaned old entity in Settings → Devices & Services → Entities.
   b. Find the new template entity (likely landed on a fallback/suffixed id) and rename its Entity ID
      to the freed string.
3. **Wait ≥ 2 minutes** so the `/1` trigger fires twice: tick 1 baselines the counter-delta logic,
   tick 2 applies the first real delta. Verify `sensor.victron_solar_yield_total_kwh`'s `last_dc_total`
   attribute equals the current `sensor.victron_solar_yield_dc_total_kwh`.
4. **No Energy Dashboard reconfiguration needed** — it already points at `solar_yield_watts` /
   `victron_solar_yield_total_kwh`, which now carry the AC-referenced values directly. Confirm the
   Solar production chart continues its existing line with no gap.
5. **Attach every NEW template entity to the Victron device** (`device:` is unsupported in template
   YAML, so this is lost automatically the moment an entity moves from `mqtt:` to `template:`):
   Settings → Devices & Services → Entities → assign each of the entities listed under "Final audit"
   below to "Victron Energy System", including the two repointed ones. Optionally mark the η
   accumulators and the roundtrip loss as *Diagnostic*.

---

## Known risks

1. **η bootstrap window.** For the first hours after deploy η = 100 % and the sensors behave exactly
   as today. Intentional and self-correcting, but do not read day one as the final result.
2. **Battery remains the residual** in both domains, so all measurement error still lands there
   rather than being spread. Unchanged from today's design and not made worse — but the battery
   figure stays the least trustworthy of the set.
3. **Attribute-carrying trigger sensors are the most fragile part** (Steps 6 and 7). A raising
   template silently drops the baseline. Every read has an explicit state-string check or a default
   for that reason; the tests for counter-reset and source-unavailable exist to lock it in.
4. **The entity-registry reclaim is a manual, one-time UI step** (see "Revision" above) for exactly
   two entities. Skipping it does not break the new sensors — they work correctly under whatever
   fallback id HA assigns them (e.g. `sensor.victron_solar_yield_total_kwh_2`) — but since the old
   `mqtt:` blocks are removed from YAML, the entity_id the Energy Dashboard is configured against
   (`sensor.solar_yield_watts` / `sensor.victron_solar_yield_total_kwh`) goes orphaned and
   permanently frozen: the dashboard would show a flat line / gap from deploy day onward until the
   dashboard source is manually re-pointed at the new fallback id — reintroducing the exact
   discontinuity this revision exists to avoid. Doing the reclaim is what makes it unnecessary.

---

## Status

- [x] Step 0 — `availability:` on `victron_ac_load_total_power`
- [x] Step 1 — `victron_multiplus_ac_net_power`
- [x] Step 2 — η accumulators (`victron_multiplus_ac_out_energy` / `_dc_in_energy` — renamed from
      the original `victron_inverter_*` names to avoid colliding with the pre-existing AC-coupled
      PV inverter sensors; see "Naming" below)
- [x] Step 3 — `victron_multiplus_conversion_efficiency`
- [x] Step 4 — solar AC watts (REPOINTED into `sensor.solar_yield_watts`, `unique_id:
      victron_solar_yield`, `default_entity_id: sensor.solar_yield_watts` — see "Revision:
      repoint instead of duplicate" below; raw DC moved to new `victron_solar_yield_dc_watts`)
- [x] Step 5 — rewrite `victron_battery_ac_power` (now reads the repointed `sensor.solar_yield_watts`)
- [x] Step 6 — solar AC total kWh (REPOINTED into `sensor.victron_solar_yield_total_kwh`, same
      `unique_id`/`default_entity_id` pattern; raw DC moved to new `victron_solar_yield_dc_total_kwh`)
- [x] Step 7 — rewrite `victron_battery_energy_in/out` (energy-domain residual)
- [x] Step 8 — loss diagnostics (`victron_multiplus_conversion_loss_power/_energy`,
      `victron_battery_roundtrip_loss_energy`)
- [x] Step 9 — utility meters (`victron_solar_ac_monthly`, `victron_multiplus_conversion_loss_monthly`)
- [x] Step 10 — unused-sensor audit (report only) — see "Final audit" below
- [x] Step 11 — comments / project-rule pass
- [x] `tests/conftest.py` seeds + `_reset_energy` + `_seed_eta`
- [x] New tests written (21 new test functions in `tests/test_victron.py`)
- [ ] **Tests executed** — NOT run locally. `ha_integration_test_harness` requires a full Home
      Assistant core install; none exists in this dev environment and installing one was judged
      out of scope for this session. Verified instead by: (1) `yaml.safe_load` parse of the whole
      file — no syntax errors, 34 unique `unique_id`s, zero duplicates, all `device_class`/
      `state_class` combinations valid; (2) every non-trivial Jinja branch evaluated against the
      **live production HA instance** via `ha_eval_template` (read-only) — bootstrap branch,
      counter-delta branch, bootstrap-fallback branch, unavailable-hold branch, conversion-loss
      both directions, roundtrip-loss clamp all confirmed numerically correct; (3) full manual
      trace of all 13 pre-existing assertions plus all new test scenarios against the final
      formulas (see "Test impact" above). **Run `pytest tests/ -v` for real before merging.**
- [x] `packages/pergola.yaml` repointed to `sensor.victron_solar_yield_dc_watts`
- [ ] Deployed by user via `git pull` + entity-registry reclaim for the 2 repointed entities
      (see "Revision: repoint instead of duplicate" — NOT a plain Energy Dashboard dropdown swap)

## Naming (post-implementation correction)

While implementing, the new conversion-stage sensors were initially named with a bare "Inverter"
(`victron_inverter_efficiency`, `victron_inverter_energy_ac_out/dc_in`,
`victron_conversion_loss_power/energy`), which collides with the **pre-existing** AC-coupled PV
inverter sensors (`victron_ac_inverter_power`, `_energy_total_kwh` — a physically different device,
`pvinverter/20`). Caught and renamed before anything was deployed, per the user's explicit choice of
the "MultiPlus prefix" scheme:

| Final name | Was named (never deployed) |
|---|---|
| `victron_multiplus_ac_net_power` | (unchanged, correct from the start) |
| `victron_multiplus_conversion_efficiency` | `victron_inverter_efficiency` |
| `victron_multiplus_ac_out_energy` | `victron_inverter_energy_ac_out` |
| `victron_multiplus_dc_in_energy` | `victron_inverter_energy_dc_in` |
| `victron_multiplus_conversion_loss_power` | `victron_conversion_loss_power` |
| `victron_multiplus_conversion_loss_energy` | `victron_conversion_loss_energy` |
| `victron_multiplus_conversion_loss_monthly` | `victron_conversion_loss_monthly` |

Full disambiguated scheme now in the file: **AC Inverter** = pvinverter/20 (3rd-party AC-coupled PV,
unchanged) · **Solar Yield** = solarcharger/279 MPPT, DC and AC variants (unchanged prefix) ·
**MultiPlus** = vebus/276 conversion stage (new sensors) · **VEBus** = the pre-existing
`victron_vebus_dc_power`, kept as-is as an already-deployed entity · **Battery** / **Grid** as before.
`VEBus` and `MultiPlus` remaining two different prefixes for the same physical device is a known,
accepted wart — the user chose not to rename the pre-existing `victron_vebus_dc_power` to avoid
touching a deployed entity.

## Final audit (re-verified against the implemented file)

Confirms the Step 10 preliminary audit — no changes to the classification, plus the new entities:

**In active use, entity IDs UNCHANGED, formulas repointed to AC-referenced (feeds the Energy
Dashboard automatically — see "Revision: repoint instead of duplicate"):**
`solar_yield_watts` (unique_id `victron_solar_yield`), `victron_solar_yield_total_kwh`,
`victron_battery_ac_power`, `victron_battery_energy_in/out`.

**New, raw-DC-only, no history (replace the OLD meaning of the two IDs above, now consumed
internally and by `pergola.yaml`):** `victron_solar_yield_dc_watts`, `victron_solar_yield_dc_total_kwh`.

**New, diagnostic-only (worth a dashboard card, not an Energy Dashboard *device*):**
`victron_multiplus_ac_net_power`, `victron_multiplus_conversion_efficiency`,
`victron_multiplus_conversion_loss_power/_energy`.

**New, internal only:** `victron_multiplus_ac_out_energy`, `victron_multiplus_dc_in_energy` (feed
`victron_multiplus_conversion_efficiency` only).

### Removed (user-requested cleanup, post-implementation)

Two groups deleted after a full re-audit against the final file, `pergola.yaml`, and your confirmed
dashboard entity list:

1. **The dead chain**: `victron_battery_power` (mqtt) → `victron_system_losses_power` (template) →
   `victron_system_losses_energy` (trigger). No dashboard, no package, no `utility_meter`, no other
   sensor read any of the three — the chain existed solely to feed itself. Also removed
   `victron_battery_roundtrip_loss_energy`, same class of problem (terminal, zero consumers).
2. **All `utility_meter` entities removed — the entire `utility_meter:` key is gone.** Started as
   "just the 2 unrequested new ones" (`victron_solar_ac_monthly`,
   `victron_multiplus_conversion_loss_monthly`), on the assumption the original 6 predating this
   session were in active manual use for Austrian invoice comparison (per the file's own header
   comment). User confirmed that assumption was wrong — none of the 6 are actually checked either.
   Same "no in-repo consumer" test the dead chain failed, applied consistently: all 8 gone. The
   underlying energy sensors (`victron_grid_energy_import/export`, `victron_battery_energy_in/out`,
   `victron_solar_yield_dc_total_kwh`, `victron_ac_inverter_energy_total_kwh`) are untouched — only
   the monthly-reset wrapper is gone. No other package defined `utility_meter:`, so the integration
   simply isn't configured anymore; this is valid, not an error.

`victron_multiplus_conversion_loss_power/_energy` (the sensors, not the monthly meter) are
DELIBERATELY KEPT even though their only consumer (the monthly meter) is now gone — they remain
useful as standalone live/history diagnostics, and removing them was not requested.

Corresponding test removals in `tests/test_victron.py`: `test_system_losses_daytime`,
`test_system_losses_night`, `test_system_losses_clamped_to_zero`,
`test_system_losses_energy_accumulates`, `test_battery_roundtrip_loss`. The `battery_power` parameter
was dropped from `_seed()` and its conftest.py baseline seed removed — nothing else read it.

Final entity count: 30 sensors (was 34), 0 `utility_meter`s (was 8) — the `utility_meter:` key is
removed from the file entirely.

## CI fix: custom `attributes:` on trigger sensors don't survive across ticks (post-implementation)

PR #101's CI (`ha_check.yaml`, real HA container at this repo's pinned `.HA_VERSION`, 2026.8.1) failed
2 of the new tests: `test_solar_yield_ac_total_baselines_then_applies_delta` and
`test_battery_energy_residual_uses_counter_delta_once_baselined`. Config check itself was clean —
only the live-container pytest run failed.

**Root cause.** Steps 6/7 as originally implemented (see "Implementation" above) stashed each
accumulator's previous-tick lifetime-counter reading in a custom `attributes:` key
(`last_dc_total`, `last_mppt_total`, `last_acpv_total`), read back via `this.attributes.get(...)`.
On real HA 2026.8.1 this does not reliably round-trip: every tick reads back the "no baseline"
sentinel, so the counter-delta branch never leaves bootstrap (confirmed via the CI traceback —
tick 2 of the battery test computed `batt_inc == 0` instead of the expected `-1.2`, the exact
signature of `mppt_prev`/`acpv_prev` still reading `-1`).

Traced against HA core source at the `2026.8.1` tag (not guessed, not generic knowledge — see the
new CLAUDE.md "HA version gate" rule this incident is why it was added):
- `TriggerEntity._render_templates` (in `homeassistant/components/template/trigger_entity.py`)
  stores custom attributes into `self._attr_extra_state_attributes`, exposed via an overridden
  `extra_state_attributes` property.
- That override and the whole restore-attribute wiring landed in
  **home-assistant/core#172847** ("Add restore state framework for template entities"), merged
  **2026-06-24** — about 6 weeks before this repo's pinned `.HA_VERSION`.
- 2026.7 also shipped #173974 ("Call state change listeners immediately instead of deferring them
  to the event loop"), touching the same dispatch path.
- Open upstream issue **home-assistant/core#178145** (filed against 2026.8.0b3) independently
  reports `CoordinatorEntity`-based entities losing reliable state writes after a few update
  cycles on this same version range — `TriggerEntity` is itself a `CoordinatorEntity`.

No sensor anywhere in this repo used custom `attributes:` on a trigger sensor before this PR, so
there was no working precedent to check it against — this landed squarely on a code path HA
reworked weeks before the pinned version.

**Fix.** Dropped the `attributes:` blocks entirely. Replaced with two dedicated, state-only
sensors that hold the previous counter reading as their own `state:` (never a custom attribute):
- `victron_solar_yield_dc_baseline_kwh` — previous `victron_solar_yield_dc_total_kwh` reading.
  Consumed by `victron_solar_yield_total_kwh` and both `victron_battery_energy_in/out`.
- `victron_ac_pv_energy_baseline_kwh` — previous `victron_ac_inverter_energy_total_kwh` reading.
  Consumed by both `victron_battery_energy_in/out`.

`this.state` self-reference (not `this.attributes`) is the proven-reliable pattern already used by
the Grid Energy Import/Export accumulators — those tests pass and always have. The two baseline
sensors reuse exactly that.

Both baseline sensors are declared *after* their consumers in the same `- trigger:` block:
entities in one trigger pass render in declaration order, and an earlier entity's fresh write IS
visible to a later entity's `states()` read within that same pass (the same mechanism already
documented for the η one-tick lag). Declaring the baselines last means the consumers read last
tick's value, not one the baseline has already advanced to this tick.

`victron_battery_energy_in` and `_out` now share one baseline pair instead of each carrying its
own copy — the original per-sensor duplication existed specifically to dodge same-tick staleness
from reading a *sibling's* freshly-written attribute; a dedicated external sensor read via
`states()` doesn't have that hazard (both consumers read the same not-yet-updated baseline in the
same pass), so the duplication was no longer needed and was dropped.

Test changes: `_reset_energy()` and `conftest.py`'s `baseline_states` now reset the two new
baseline sensors to the literal string `"unknown"` (same "no baseline yet" sentinel semantics the
empty attribute used to provide) instead of clearing an attribute dict.
`test_solar_yield_ac_total_baselines_then_applies_delta`'s `expected_attributes` checks became
separate `assert_entity_state` calls against `sensor.victron_solar_yield_dc_baseline_kwh`.

Entity count after this fix: 32 sensors (30 + the 2 new baseline sensors).

**Follow-up (same CI fix round):** the first push of the baseline sensors still failed —
different symptom this time: the baseline sensor's own state stayed the literal string
`"unknown"` forever (`ValueError: could not convert string to float: 'unknown'`), meaning even a
plain `this.state` self-reference didn't reliably commit for these two entities. The two new
sensors were the only self-referencing trigger sensors in this file defined with just a bare
`unit_of_measurement` and no `device_class`/`state_class` — every other one that relies on
`this.state` (Grid Energy Import/Export, the η accumulators, Solar Yield AC Total, Battery Energy
In/Out) pairs `device_class: energy` + `state_class: total_increasing`. Added that same pairing to
both baseline sensors to match the only pattern actually proven reliable in this repo's CI, rather
than being the one exception without it.
