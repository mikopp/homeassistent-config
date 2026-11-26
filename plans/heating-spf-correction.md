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
- The owner's BA (Bedienungsanleitung geoTHERM exclusiv VWS, 0020025604_00), p.16
  "Energieertragsdisplay": "Zeigt … die aus der Umwelt gewonnene Energie an … Rechts oben ist die
  Gesamtsumme"; p.9 Abb. 4.2: 1/4 electricity + 3/4 environment = 4/4 heat. Recorded in device VWS-29.
- The ebusd catalog `vaillant/08.ehp.csv` calls `YieldTotal` "Gesamtsumme Energieertrag", which is that
  display's total. The link is by name only (`[ASSUMED]` in VWS-29).
- The same wording is in the English *Operating Manual geoTHERM VWS* 0020045200_00, p.16–17.

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
1. [DONE] **Device fact** (`device-knowledge` skill): VWS-29 in
   `doc/devices/vaillant-vws-83-2/registers-ehp.md` now reads environmental yield `[BA p.16] [BA p.9]`,
   with the register = panel total link marked `[ASSUMED]`; BA's References `Covers` extended. No T row
   (no test). Copies: `design.md` HPB-2 is rewritten in step 5, the YAML comment in step 2.
2. [DONE] **YAML**: the 6 efficiency templates are `((heat + elec) / elec)`; names "… SPF …";
   `sensor.heating_efficiency_today` got `default_entity_id` so its name change cannot move its id on
   a fresh install. `utility_meter`/`sql` names were NOT renamed: their entity ids come from `name:`
   on first registration (fresh installs, tests); comments say environmental yield instead.
3. [DONE] **Dashboard**: SPF H4 section/title, "Environmental yield (ground heat)" labels.
4. [DONE] **Tests**: daily, per-mode, midnight-reset and 30 d expectations +1; mutation (`heat / elec`)
   fails 5 tests; 20× stable.
5. [DONE] **Knowledge:** design HPB-2 Efficiency bullet (SPF H4, boundary, ±10 %); notes entity map
   and "Energy modes"; README feature line.
6. [DONE] **PR #201** with the post-deploy note: the SPF sensors step up ≈ +1 at deploy (formula change, not
   the machine). No bridge or broker change. Expect the 30 d space-heating SPF ≈ 4–4.5 in mild weather.
   The PR states that the owner check (step 7) is still open.
7. [TODO] **Owner check:** read the panel's "Energy input display" total (top right, kWh) and
   `sensor.geotherm_heating_yield_total` at the same moment. Equal (± a few kWh) → add T row
   `T54` to `evidence.md`, replace VWS-29's `[ASSUMED]` with `[T54]` (CONFIRMED) and record the
   learning via `record-learning`. Different → revert the formula change
   (follow-up PR) and re-plan.
8. [TODO] Close: waits on step 7 (the plan stays open after the PR merges). Per `doc/KNOWLEDGE.md#K-6`,
   update the design doc (K-4.1 gate), check sizes, delete this plan.

## Knowledge homes touched
`doc/devices/vaillant-vws-83-2/` (VWS-29, evidence), `doc/heating_pv_boost/design.md` (HPB-2),
`doc/heating_pv_boost/notes.md`, YAML comments.

## Status
- 2026-11-26: plan created; owner check moved to step 7, implementation proceeds on the
  assumption.
- 2026-11-26: steps 1–6 done (PR #201). Next: the owner check (step 7), then Close.
