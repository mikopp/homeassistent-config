# Victron: true MultiPlus DC power (replace the AC-derived `Dc/Vebus/Power`)

**Status:** IMPLEMENTED on `fix/victron-true-dc-power` (PR open) — phases 1-4 done, `pytest` not run locally (CI only); phase 5 (deploy) and 6 (live verification) are user/follow-up steps.
**Target files:** `packages/victron.yaml`, `tests/test_victron.py`, `tests/conftest.py`,
`packages/notes/victron.md` (new), `packages/CLAUDE.md` (index row),
`plans/victron-ac-referenced-accounting.md` (correct a wrong claim)
**Branch:** user decision 2026-10-17: implement on the current branch. That branch's PR (#128) was already merged, so the work moved to `fix/victron-true-dc-power` off `origin/master`.
**Follows from:** `plans/victron-ac-referenced-accounting.md`, status updates 2026-10-17.

---

## 1. Overview

### The problem

The AC-referenced accounting (PR #121) assumes `sensor.victron_vebus_dc_power`
(MQTT `system/0/Dc/Vebus/Power`) is the **true DC power** of the MultiPlus. It is not. It follows the
**AC side**, so every quantity built on "DC in vs AC out" is wrong:

| Evidence (user MQTT listen + VRM screenshots, 2026-10-17, snapshots not perfectly synced) | |
|---|---|
| `Dc/Vebus/Current` × battery voltage | −8.1 A × 52.5 V = **425 W** |
| `Dc/Vebus/Power` | **−337 W** — does not match V×I |
| `Dc/Battery/Power` (BMS, true DC) | −435 W (= 52.5 V × −8.3 A) |
| VRM "Inverter AC/DC" | 52.48 V × −7.7 A = 404 W, but shows **−302 W** |
| 26 h of hourly means | `ac_net_power` ≈ −`vebus_dc_power` within ~1 W at 2.5 kW inverting and 1.9 kW charging |

Consequences live today:
- `victron_multiplus_conversion_loss_power` ≈ 0 W (a real MultiPlus loses ~15 % at ~350 W). Loss
  energy since deploy: 0.139 kWh — wrong.
- `victron_multiplus_dc_in_energy` ≈ `ac_out_energy`, so `victron_multiplus_conversion_efficiency`
  is meaningless (≈ 99–100 %), and with it the AC-referenced solar yield
  (`solar_yield_watts`, `victron_solar_yield_total_kwh`) and the battery in/out split.
- Occasionally `ac_net_power` > −`vebus_dc_power` (physically impossible) — sampling noise on two
  AC-derived numbers.
- Totals (power and energy identities) are **not** affected — they close for any η. Only the
  Solar/Battery split and the loss diagnostics are.

Not a cause, but a wrong claim to correct: the AC-referenced plan states that
`Dc/Vebus/Power` is "always DC (systemcalc computes it as `/Dc/0/Voltage × /Dc/0/Current`)". The
data above contradicts this for this system. Why Victron publishes an AC-like value there is
**not established** and not needed for the fix.

### The fix

Build the Multi's true DC power ourselves from two values that **are** real DC:
`system/0/Dc/Vebus/Current` (the Multi's own DC current) × battery voltage. Expose it as a **new**
entity (user decision: new entity ID, not a reclaim of the old one), repoint the three consumers, and
remove the AC-derived sensor.

Sign convention is deliberately identical to the old sensor — **positive = charging (AC→DC),
negative = inverting (DC→AC)** — because Victron reports the Multi current negative while
discharging (confirmed: −8.1 A). So the existing formulas keep working unchanged:

```
multiplus_dc = V_batt × I_vebus                       (new, W)
loss         = max(-(mp_ac_net + multiplus_dc), 0)    (unchanged formula)
dc_in       += max(-multiplus_dc, 0) / 60000          (unchanged formula)
```

Why `Dc/Vebus/Current` × V and not `Dc/Battery/Power`: the battery monitor also sees every other DC
load (MPPT self-consumption, GX, …) — about 10 W of the 435 W in the snapshot — which would be
booked as Multi loss. The Multi's own current isolates the conversion stage, and its net DC current
already includes MPPT flow when the sun is up (no `dc_pv` term needed).

---

## 2. Design

### New entities

| Entity (`default_entity_id`) | Kind | Source | Notes |
|---|---|---|---|
| `sensor.victron_vebus_dc_current` | MQTT, A | `N/c0619ab4c19e/system/0/Dc/Vebus/Current` | `device_class: current`, `state_class: measurement`, `expire_after: 120` (fluctuating, same policy as the power sensors) |
| `sensor.victron_battery_voltage` | MQTT, V | `N/c0619ab4c19e/system/0/Dc/Battery/Voltage` | `device_class: voltage`, `state_class: measurement`, `expire_after: 86400` (slow diagnostic, same reasoning and value as `victron_battery_soc`: needed so a restart restores it) |
| `sensor.victron_multiplus_dc_power` | template, W | `V × I` of the two above | MultiPlus prefix = conversion-stage naming scheme from the AC-referenced plan. `device_class: power`, `state_class: measurement` |

All three MQTT/template entities pin their ID with `default_entity_id` — the 2026-10-16 bug (#126)
was exactly missing that on a `device:`-carrying MQTT sensor, which made HA prefix the ID with the
area/device name.

### `victron_multiplus_dc_power` details
- `state: round(V × I, 0)`.
- `availability:` on the **voltage** only. The current is read with `| float(0)`: an expired current
  sensor means "no DC current flowing" (the GX does not re-publish an unchanged value), exactly the
  reasoning already used for expired PV sensors (`victron_pv_net_power`, `solar_yield_watts`).
  This deliberately deviates from the repo's "no `float(default)`" rule; an inline comment must say
  why. A real GX outage is still caught — `ac_net_power` (its partner in every consumer) requires
  `ac_load_total_power` and `grid_total_power`.
- Voltage source: the BMS voltage differs from the Multi's terminal voltage by ~0.02 V (52.50 vs
  52.48 in the VRM screenshot) → ≈ 0.04 % error, negligible. If `vebus/276/Dc/0/Voltage` turns
  out to be published, it is a drop-in alternative; not worth a third topic now.

### Consumers to repoint (found by grep, all in `packages/victron.yaml`)
1. `victron_multiplus_conversion_loss_power` — state (l.527) and availability (l.535).
2. `victron_multiplus_dc_in_energy` — state (l.575) and its comment (l.557-559).
3. Comments only: header sign-convention note (l.19), `ac_net_power` comment (l.345), loss comment
   (l.515-519).

### Removed
`sensor.victron_vebus_dc_power` (MQTT block l.131-144) — after the repoint it has no consumer, and
keeping a sensor that looks like DC power but is AC-derived is a trap. Same "no consumer → remove"
rule already applied to the dead chain. Its registry row becomes an orphan the user deletes.

### Known consequence — documented, deliberately NOT fixed here
The Multi's efficiency is load dependent (~80 % at ~350 W from the snapshot, higher at kW loads;
three Multi devices idle-draw add up). The single long-run ratio η is therefore dominated by
low-load night inverting but is applied to **daytime** PV, which flows at higher power: solar AC is
slightly under-credited, the battery residual absorbs the difference. Both domains still close
exactly. A load-dependent η is a separate design change, out of scope.

### What this does not change
Power and energy identities, `solar_yield_watts` / `victron_solar_yield_total_kwh` formulas,
`victron_battery_ac_power`, battery in/out residual, `victron_multiplus_ac_net_power`, the
Energy Dashboard wiring. Only the DC reference feeding η and the loss changes.

---

## 3. Implementation steps

### Phase 0 — Diagnosis (done)
1. [DONE] Establish that `Dc/Vebus/Power` is AC-derived — see evidence table; recorded in
   `plans/victron-ac-referenced-accounting.md` (status updates 2026-10-17).
2. [DONE] Confirm both topics exist and carry real DC values (user MQTT listen:
   `Dc/Vebus/Current` = −8.1, `Dc/Battery/Voltage` = 52.5, both JSON `{"value": …}`).
3. [DONE] This plan — approved by the user 2026-10-17.

### Phase 1 — Branch and notes
4. [DONE] Branch: `fix/victron-restore-slow-sensors` was already merged (#128), so a new branch `fix/victron-true-dc-power` off `origin/master`.
   *Dependency:* approval of this plan.
5. [DONE] Create `packages/notes/victron.md` and flip the `victron.yaml` row in
   `packages/CLAUDE.md` from "— (none yet)" to the note. Content (observations only, no
   unproven cause): `Dc/Vebus/Power` ≠ V×I and tracks AC net (numbers above); the true-DC recipe;
   sign convention; the load-dependent-η caveat; the `expire_after` policy pointer. Read
   `packages/notes/` index rule first (CLAUDE.md of `packages/`).

### Phase 2 — `packages/victron.yaml`
6. [DONE] Add the two MQTT sensors (`victron_vebus_dc_current`, `victron_battery_voltage`) in the
   VEBus/Battery sections, with `default_entity_id`, `device: *victron_device`, the standard
   `value_json is defined and value.value is not none` guard in `value_template`, and a comment for
   each. Current rounded to 2 decimals, voltage to 2.
   *Dependency:* step 4. *Note:* `expire_after` values per the design table; update the policy
   comment at the top of the file to list the two new sensors.
7. [DONE] Add template sensor `victron_multiplus_dc_power` next to
   `victron_multiplus_ac_net_power` (`default_entity_id: sensor.victron_multiplus_dc_power`),
   comment records: why not `Dc/Vebus/Power`, sign convention, the `float(0)` current justification.
   *Dependency:* step 6.
8. [DONE] Repoint `victron_multiplus_conversion_loss_power` (state + availability) and
   `victron_multiplus_dc_in_energy` to `sensor.victron_multiplus_dc_power`; formulas unchanged.
   Update the three comment blocks listed in the design (l.19, l.345, l.515-519, l.557-559).
   *Dependency:* step 7.
9. [DONE] Delete the `victron_vebus_dc_power` MQTT block (l.131-144) and update the header
   comment. Re-grep the repo for `victron_vebus_dc_power` — expect zero hits outside `plans/`.
   *Dependency:* step 8.

### Phase 3 — Tests
10. [DONE] `tests/conftest.py` `baseline_states`: replace the `victron_vebus_dc_power` seed with
    `sensor.victron_vebus_dc_current` = `"0"` (A) and `sensor.victron_battery_voltage` = `"50"` (V),
    so `victron_multiplus_dc_power` starts at 0 W and η stays at its 100 % bootstrap.
11. [DONE] `tests/test_victron.py` `_seed(...)`: keep the `vebus_dc` parameter (it now means
    "true DC power in W") and implement it as `voltage = 50 V`, `current = vebus_dc / 50`, so
    V×I == `vebus_dc` and every existing assertion (l.257-290, 539-567) is unchanged. Docstring
    updated.
    *Dependency:* step 10.
12. [DONE] New tests:
    | Case | Assert |
    |---|---|
    | inverting | V=52.5, I=−8.1 → `victron_multiplus_dc_power` = −425 |
    | charging | V=52.5, I=+20 → +1050 |
    | realistic loss | ac_load 351/grid 12 → ac_net 339, V=52.5, I=−8.1 → loss = 86 |
    | current expired (`unavailable`) | power = 0, **not** unavailable (voltage present) |
    | voltage `unavailable` | power `unavailable`, loss `unavailable` |
    | η leaves bootstrap on real data | seed `dc_in`/`ac_out` via `_seed_eta`-style accumulators, not via the removed sensor |
    | regression | `sensor.victron_vebus_dc_power` is absent from the config / not referenced |
    Also confirm `_reset_energy` needs no change (it resets accumulators, not these inputs).
    *Dependency:* step 11.
13. [IN_PROGRESS] `pytest tests/ -v` NOT run (no HA core / docker here) — CI is the real run. Done instead: whole-file `yaml` parse OK, 43 unique_id/default_entity_id values with no duplicates, zero `victron_vebus_dc_power` references left outside `plans/`, and the new Jinja (V×I, expired current → 0, loss 86 W) evaluated on the live HA with `ha_eval_template` (read-only). Original text: run `pytest tests/ -v`. Not runnable locally (no HA core / docker in this environment,
    see the AC-referenced plan) → CI is the real run. Local substitutes: `yaml.safe_load` parse,
    unique_id / default_entity_id duplicate check, and the new Jinja evaluated against the live HA
    with `ha_eval_template` (read-only).
    *Dependency:* steps 9-12.

### Phase 4 — Docs and hygiene
14. [DONE] `plans/victron-ac-referenced-accounting.md`: strike the "systemcalc computes V×I / always
    DC" claim (Context section) with a pointer to this plan; keep the rest.
15. [DONE] Line endings: `git ls-files --eol` — nothing may show `w/crlf` or `i/crlf`.
16. [TODO] Add a `.claude/learnings.md` entry **only after** step 20 verifies on the live system
    (CLAUDE.md: never log an unconfirmed learning). The MQTT numbers above are direct observations,
    so the note in step 5 is fine now; a learning that claims a *cause* is not.

### Phase 5 — Deploy (user actions; `git pull` is the user's, never mine)
17. [TODO] User: `git pull` on the HA host → Developer Tools → YAML → Check configuration →
    **full restart**, not a reload. A restart fires the "Initial Full Publish" automation, so the two
    new MQTT sensors get a value immediately; a reload does not (suppress-republish never re-sends
    an unchanged voltage). Fallback after a reload: publish an empty payload to
    `R/c0619ab4c19e/keepalive`.
18. [TODO] User: Settings → Devices & Services → Entities → delete the orphaned
    `sensor.victron_vebus_dc_power`. Optional: assign the new template entity
    `sensor.victron_multiplus_dc_power` to the "Victron Energy System" device (`device:` is not
    supported in template YAML).
19. [TODO] User: **re-seed the η accumulators to 0 again**, same Developer Tools → States steps as
    earlier (`victron_multiplus_ac_out_energy`, `victron_multiplus_dc_in_energy`, within a minute of
    each other, at night). Reason: the 2026-10-17 20:17 reset restarted them from 0, but since then
    `dc_in` has been integrating the AC-derived value. Optionally also `victron_multiplus_conversion_loss_energy`
    (0.139 kWh of near-zero-loss history). Compiled statistics are not rewritten.

### Phase 6 — Verification (live, read-only via ha-mcp)
20. [TODO] After ~2 min:
    - `sensor.victron_multiplus_dc_power` ≈ `Dc/Battery/Power` (MQTT) within ~15-25 W of other DC
      load, same sign; **not** ≈ `victron_multiplus_ac_net_power` any more.
    - `victron_multiplus_conversion_loss_power` clearly > 0 (tens of W at ~350 W, hundreds of W at
      kW loads), never stuck at 0.
    - `victron_multiplus_conversion_efficiency` = 100.0 (bootstrap).
    After the first overnight inverting (`dc_in` ≥ 1.0 kWh): η in a plausible 80-95 %, not pinned at
    50 or 100. Power identity still holds (`solar_yield_watts + victron_ac_inverter_power +
    victron_grid_total_power + victron_battery_ac_power == victron_ac_load_total_power`).
    After ~24 h: energy identity (solar AC + AC PV + net grid + battery out−in vs ∫load) still
    within ~1 %; no new ERROR in the system log from `victron`.

---

## 4. Risks and open points

1. **Current sign / availability on other firmware states.** Confirmed negative while discharging;
   not yet seen while charging. Verified by test + the live check after the first charge.
2. **Expired-current-as-0 hides a stale topic.** Accepted (same as PV); GX outages are still caught
   by `ac_net_power`'s availability.
3. **Loss is an upper bound on pure conversion loss** only if the Multi's own DC current includes
   anything but the conversion stage; the snapshots suggest it does not.
4. **η semantic limit** (load dependent) — see Design; separate change if wanted.
5. **Mid-tick sampling:** `ac_net` and `multiplus_dc` are still independently sampled; the ≥ 0
   clamp on the loss stays.

## 5. Decisions

- New entity, not a registry reclaim of `victron_vebus_dc_power` — user, 2026-10-17.
- Entity name `sensor.victron_multiplus_dc_power` (MultiPlus prefix scheme) — **proposed**, change
  on request.
- Voltage from the BMS topic `system/0/Dc/Battery/Voltage` — **proposed**.
