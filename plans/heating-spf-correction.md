# Heat-pump efficiency → SPF H4 (YieldTotal is environmental yield)

## Overview
`ehp/YieldTotal` is very likely the **environmental yield** (heat taken from the ground), not delivered
heat. If so, every efficiency sensor in `packages/heating_pv_boost.yaml` reads COP − 1 (≈ 3.5 instead of
≈ 4.5). Fix: SPF = (environmental yield + electricity) ÷ electricity, in every existing efficiency
sensor, per bucket (space heating, hot water, combined). This is SPF **H4**: the Shelly "Heizung" clamp
measures everything the geoTHERM draws (compressor, brine pump, internal heating pump, controls,
standby, hot water) and nothing else (owner, 2026-11-26).

**HYPOTHESIS, assumed correct for implementation (owner, 2026-11-26), verified in step 7:** that the
`YieldTotal` register is the panel's "total environmental yield". Evidence so far:
- Vaillant *Operating Manual geoTHERM VWS* 0020045200_00 (VWS 63/83/103 /2), p. 16–17, "Energy input
  display": "Top right the total of the environmental yield since commissioning is displayed".
  Graphics display: "The output of the heat source must not be equated with the heating output. The
  heating output corresponds to approx. the output of the heat source + compressor output."
- The ebusd catalog `vaillant/08.ehp.csv` calls `YieldTotal` "Gesamtsumme Energieertrag". The link to
  the display total is inferred from that name only.

Accuracy: no brine flow meter, so the yield is estimated by the unit (±~10 %). Env + E slightly
overstates delivered heat: standby and controls power and compressor case losses never reach the
heating water.

## Design
- Changes design HPB-2, "Efficiency" bullet (formula and its basis VWS-29). Invariants unchanged:
  same buckets, same misbooking acceptance, ratio of sums for 30 d, floors 1 kWh / 10 kWh → `none`.
- Owner decisions: no live COP (`ActualEnvironmentPower` is whole-kW display data, and the Fine
  variant needs SW ≥ 414); keep entity IDs and accept the +1 step in history at deploy; keep the
  combined sensor that includes hot water.
- Already in place, nothing to build: ratio of sums, division and floor guards, counter resets
  (`utility_meter`, `''` value_template).

## Steps
1. [TODO] **Device fact** (`device-knowledge` skill): correct VWS-29 in
   `doc/devices/vaillant-vws-83-2/registers-ehp.md` to environmental yield, tagged with the manual as
   documentary evidence (new evidence row); not CONFIRMED until step 7.
2. [TODO] **YAML** `packages/heating_pv_boost.yaml`: the 6 efficiency templates become
   `((heat + elec) / elec) | round(2) if elec >= floor else none`; `name:` becomes "… SPF …" (IDs
   unchanged); yield display names and comments say environmental yield; comments point to
   design/notes. Check per platform that a `name:` change keeps the ID (`ha-energy-metering`).
3. [TODO] **Dashboard** `dashboards/heating-dashboard.yaml`: labels "Environmental yield", "SPF (H4)".
4. [TODO] **Tests** (`ha-test-harness` first): `tests/ha/test_heating_pv_boost.py` daily and per-mode
   cases, and `tests/ha/test_heating_pv_boost_rolling.py` 30 d cases, each expectation +1 (ratio of
   sums 43/11 = 3.91 vs mean of daily SPF 3.5). Mutation check: `heat / elec` must fail. Targeted run
   while working, full `.github/scripts/ci-local.sh` before push, `git ls-files --eol`.
5. [TODO] **Knowledge:** design HPB-2 Efficiency bullet; `doc/heating_pv_boost/notes.md` entity map and
   "Energy modes" (efficiency → SPF H4, env yield). No `record-learning` yet: it waits for step 7.
6. [TODO] **PR** with the post-deploy note: the SPF sensors step up ≈ +1 at deploy (formula change, not
   the machine). No bridge or broker change. Expect the 30 d space-heating SPF ≈ 4–4.5 in mild weather.
   The PR states that the owner check (step 7) is still open.
7. [TODO] **Owner check:** read the panel's "Energy input display" total (top right, kWh) and
   `sensor.geotherm_heating_yield_total` at the same moment. Equal (± a few kWh) → mark VWS-29
   CONFIRMED and record the learning via `record-learning`. Different → revert the formula change
   (follow-up PR) and re-plan.
8. [TODO] Close: waits on step 7 (the plan stays open after the PR merges). Per `doc/KNOWLEDGE.md#K-6`,
   update the design doc (K-4.1 gate), check sizes, delete this plan.

## Knowledge homes touched
`doc/devices/vaillant-vws-83-2/` (VWS-29, evidence), `doc/heating_pv_boost/design.md` (HPB-2),
`doc/heating_pv_boost/notes.md`, YAML comments.

## Status
- 2026-11-26: plan created; owner check moved to step 7, implementation proceeds on the
  assumption. Next: step 1, on the owner's go-ahead.
