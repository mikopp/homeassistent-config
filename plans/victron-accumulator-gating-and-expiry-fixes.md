# Victron: efficiency-accumulator gating, vebus-current expiry, comment corrections

**Status:** IMPLEMENTED on branch `fix/victron-expiry-and-accumulator-gating` (PR open); awaiting user
deployment. `pytest` is CI-only (no HA core / docker locally).
**Target files:** `packages/victron.yaml`, `tests/test_victron.py`, `packages/notes/victron.md`.
**Pinned HA:** `ghcr.io/home-assistant/home-assistant:2026.10.1` (`FROM` in `.github/ha-versions/ha/Dockerfile`, read 2026-10-30).
**Base:** master `0a4cab0`. Independent of the airflow and heating plans — touches Victron files only.
**Follows from:** `plans/victron-multiplus-true-dc-power.md`, `plans/victron-ac-referenced-accounting.md`.

The first draft of this plan proposed a "dc_power unavailable when current stale" guard (option B,
30 W threshold). The user decided against it (D1 below); this version reflects the settled decisions.

---

## 0. Status

| # | Step | Status |
|---|---|---|
| 1 | Investigation of `sensor.victron_solar_yield_total_kwh` (F7 / D6) | [x] DONE (ha-mcp long-term statistics; comment-only outcome) |
| 2 | Branch + decisions D1-D6 settled by user | [x] DONE |
| 3 | `victron.yaml`: `expire_after` 120 -> 600 on `victron_vebus_dc_current`; policy/dc_power comments | [x] DONE |
| 4 | `victron.yaml`: same-condition gate on both η accumulators (inline) | [x] DONE |
| 5 | Tests (`tests/test_victron.py`): gate on both signs; expired-current docstring | [x] DONE (written, CI-only run) |
| 6 | Documentation only: loss-clamp bias (F3), double η render (F4), solar-yield comment correction (D6) | [x] DONE |
| 7 | Fix 6c (battery in/out hold on unavailable grid/load) | [x] DECIDED: left out (see D4) |
| 8 | Notes (`packages/notes/victron.md`) + `git ls-files --eol` | [x] DONE |
| 9 | User: merge, `git pull` + check config + full restart (never me) | [ ] TODO |
| 10 | Live verification (read-only ha-mcp) | [ ] TODO |
| 11 | Learning entry — ONLY if step 10 proves a mechanism | [ ] TODO |

Local checks run: yamllint, `fix_yaml_style.py`, `resolve_ha_yaml.py`, YAML parse, the two new
accumulator templates rendered with plain Jinja. NOT run locally: pytest / HA config check (no
harness or docker); CI is the only real run.

---

## 1. Context

`packages/victron.yaml` builds an AC-referenced Solar/Battery split from an inverter efficiency η,
the ratio of two minute-tick accumulators (`ac_out_energy`, `dc_in_energy`). Conversion loss is
`-(ac_net + dc)`. No MQTT topic, entity ID or `unique_id` changes.

### Findings (master `0a4cab0`) and outcome

| # | Finding | Outcome |
|---|---|---|
| F1 | `victron_vebus_dc_current` `expire_after: 120`; an expired current reads 0 A in `victron_multiplus_dc_power`, which while charging would book the whole AC load as loss (while inverting it only biases η, via F2). | Fixed by D1: `expire_after: 600`. |
| F2 | The accumulators were gated on independent signs (`ac_out += max(ac_net,0)`, `dc_in += max(-dc,0)`), so skew ticks advanced only one side and biased η. | Fixed: one shared gate in both. |
| F3 | Loss clamp `max(-(ac_net+dc),0)` is biased a few W high. | Comment + note only (D4). |
| F4 | `conversion_efficiency` can render twice per tick (cosmetic). | Comment + note only (D4). |
| F5 | One η applied to DC solar. | No change (already documented). |
| F6c | `battery_energy_in/out` `float(0)` on grid/load without availability guard. | Left out (D4). |
| F7 | `sensor.victron_solar_yield_total_kwh` far below the raw MPPT counter. | Resolved, no code (D6). |

Sign note: `ac_net` positive = inverting, `dc` negative = inverting.

---

## 2. Settled decisions

- **D1 (replaces option B / threshold D2): raise `expire_after` of `victron_vebus_dc_current` from 120 to
  600 s.** No "dc_power unavailable when current stale" logic. Evidence (ha-mcp history,
  2026-10-30): the current changes about every second at non-zero loads (e.g. -22.7 A in 119 separate
  spells totalling 139 s in a 2 h window); a constant non-zero reading for 2+ min was not seen in
  ~5 days of history (judged from per-state totals, not the single longest run). Real 0.0 A readings
  are correct. Limits: the sensor was unavailable in 8 spells of ~11 min on 2026-10-30 00:00-12:00
  (likely Multi standby / service gone). **KNOWN UNVERIFIED POINT: what the AC side did during those
  spells was NOT verified.** A real GX outage is now detected after 10 min for this one sensor
  (other consumers still pair it with `ac_net_power`, which needs load and grid).
- **Fix 2 / D3: gate BOTH accumulators on the same condition** (`ac_net > 0` AND `dc < 0`, both inputs
  available), duplicated inline in each template; no new entity. Mismatched signs add to neither.
- **D4:** findings 3 and 4 documentation only (comments + `victron.md`); finding 5 no change. Fix 6c
  (hold on unavailable grid/load): follow the plan only if small and safe. Judged NOT small/safe here:
  both sensors share a long template with counter-delta branches and baseline sensors that advance
  independently of a hold (a held tick would drop that tick's solar/AC-PV delta), existing battery
  tests were not written with an unavailable-grid case, and pytest cannot be run locally. Left out;
  can be a follow-up with its own tests.
- **D5:** accumulators are NOT re-seeded; old totals dilute. η therefore converges slowly to the
  unbiased value; the old bias stays in the totals.
- **D6 (no code, comment only):** `sensor.victron_solar_yield_total_kwh` is a template sensor (since
  #121, merged 2026-10-16 14:56) that accumulates the MPPT counter delta x η. Long-term statistics
  show it going from 5644.65 kWh (2026-10-15) to 0.61 kWh (2026-10-16): the new template did not
  restore the old MQTT sensor's state (`this.state | float(0)` start), although the file comment
  promised continuity. The statistics `sum` stayed continuous (1606 -> 1609 -> 1612), so the Energy
  Dashboard is unaffected apart from ~2.7 kWh counted that day instead of ~10. Whether the owner
  also reset it by hand is unknown. The misleading comment was corrected.

---

## 3. Implementation summary

1. `victron_vebus_dc_current`: `expire_after: 600`, with reason comment; policy block and
   `victron_multiplus_dc_power` comment updated.
2. `victron_multiplus_ac_out_energy` / `victron_multiplus_dc_in_energy`: shared gate
   `ok = both available and ac_net > 0 and dc < 0`; increments `ac_net/60000` and `-dc/60000` only
   when `ok`. `float` without default after the availability test; `this.state | float(0)` kept as the
   standard accumulator seed.
3. Comments: F3 bias at the loss sensor, F4 at η, D6 correction at the solar-yield template.
4. Tests: `test_eta_accumulators_gate_on_both_signs` (one test, three ticks: ac+/dc+ skip, ac-/dc-
   skip, control inverting adds exactly one tick's worth to each). Single tick-firing test on purpose
   (known adjacent-real-tick harness flake, see `plans/victron-ac-referenced-accounting.md`).
   Existing `test_eta_accumulators_keep_pace_when_ac_pv_expired` and
   `test_conversion_loss_energy_accumulates` are inverting-on-both-sides and unaffected.
5. `packages/notes/victron.md`: 600 s expiry and evidence, shared gate, small biases, solar-yield total.

---

## 4. Risks

1. **Accumulator meaning changes:** skew ticks are excluded from now on; old totals keep the old
   bias and dilute slowly (D5).
2. **Slower outage detection** for the vebus current (10 min instead of 2 min).
3. **Unverified:** AC-side behaviour during the ~11 min unavailable spells (D1).
4. **Harness flake / CI-only test run:** the new test could not be run locally.

---

## 5. Post-deploy verification (step 10, read-only ha-mcp)

- `conversion_efficiency` stays ~84 %.
- `ac_out_energy` and `dc_in_energy` still advance together while inverting.
- No unavailable victron sensors; `sensor.victron_vebus_dc_current` has `expiry` attribute / behaves
  with 600 s.
- No new ERROR from `victron` in the system log.
