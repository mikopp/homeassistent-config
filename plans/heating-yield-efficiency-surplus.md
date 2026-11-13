# Heating: single space-heating yield, rolling 30-day efficiency, PV surplus fix

## Overview

Three owner-reported issues in `packages/heating_pv_boost.yaml` and `dashboards/heating-dashboard.yaml`:

1. **Passive heating yield is not 0.** The heat pump has two heating cycles: the **active**
   cycle (compressor running) and the **passive** cycle (circulation pump only, no compressor).
   The yield (`ehp/YieldTotal`, whole kWh, slowest poll) of an active cycle often arrives only
   after the switch to the passive cycle, so it is counted as passive yield.
   Owner decision: one combined space-heating yield; no active/passive yield split.
2. **Rolling efficiency.** Add 30-day efficiency sensors (overall, space heating, hot water)
   next to the existing "today" ones.
3. **PV surplus reads too high** (`sensor.heating_pv_surplus`). Definition still to be decided
   by the owner (see Phase C).

Wording rule (owner): in notes, comments, dashboard and test names say **active / passive
heating cycle** and **per-mode meter / mode bucket**, never "tariff". `tariffs:` survives only
as the literal HA `utility_meter` config key (and in HA-generated ids such as
`*_single_tariff`), which we cannot rename.

## Design

### A. Single space-heating yield (investigated, mechanism confirmed in source)

- Mechanism (`utility_meter` `sensor.py` at 2026.10.1): when the meter's mode select changes,
  the next source change is counted entirely to the NEW mode (`_last_valid_state` is cleared;
  the delta is computed from the last value seen before the switch). A late whole-kWh step of
  an active cycle therefore lands in passive.
- The per-mode **yield** meter gets its own mode list: `space_heating`, `water_heating`,
  `cooling`, `off` (`cooling`/`off` stay as misbooking checks). Active and passive heating
  cycles both select `space_heating`; selecting the option that is already set fires no state
  change, so the active→passive switch can no longer misbook.
- The per-mode **electricity** meter keeps all five modes (Shelly reports in Wh every ~60 s,
  no timing problem; passive-cycle electricity, the circulation pump, stays visible).
- `sensor.heating_energy_mode` keeps its five states (run statistics read `active_heating`).
- Space heating efficiency = space-heating yield ÷ (active + passive electricity).
- Migration: new entity for `space_heating` (unique_id `heating_yield_by_mode_space_heating`);
  the old active/passive yield entities become orphans, deleted by the owner after deploy.
  Their history is ~1 week and wrong anyway. Full HA restart needed (`utility_meter` has no reload).
- Leftover, accepted: late steps at active→water, water→passive and →off boundaries still
  misbook; the `off`/`cooling` buckets show it.

### B. Rolling 30-day efficiency (owner-approved approach)

- Ratio of 30-day sums (heat ÷ electricity), never a mean of daily ratios.
- Sums come from the recorder's **long-term statistics** via `sql:` sensors: they are never
  purged (raw history is only 14 days, `configuration.yaml`) and their `sum` ignores daily and
  device meter resets. A `statistics` sensor would shrink to 14 days after every restart.
  Up to ~1 h lag (hourly compilation): fine for this slow metric (owner).
- Six `sql:` kWh sums: overall, space heating, hot water × (yield, electricity). The space-heating
  yield query lists the new `space_heating` id plus the old active/passive yield ids, so the
  window carries across the merge. A `days` attribute shows the covered window (per-mode figures
  are partial until ~2026-12-12).
- Three template efficiencies: `Heating Efficiency 30d`, `Space Heating Efficiency 30d`,
  `Hot Water Efficiency 30d`.
- **Floor (owner):** below 10 kWh the result is not meaningful → the sensor renders **unknown**
  (template returns `none`), never `unavailable` (that stays reserved for "inputs missing").
  Open: floor on yield (owner's wording) or on electricity (agent's proposal; at COP ~4,
  10 kWh electricity ≈ 40 kWh heat, so a 1 kWh yield step is ≤ 2.5 % instead of ≤ 10 %).
- Verified at 2026.10.1: `sql:` YAML supported; no `default_entity_id` (ids come from `name:`,
  look up after deploy); a NULL result warns every poll → `COALESCE`; the word `entity_id` must
  not appear in the query. UNVERIFIED: the 30 s poll interval (platform default).

### C. PV surplus (OPEN — owner decision needed)

- Investigation: no sign error or double count; the match with VRM "AC Loads" (338 W) is a
  coincidence. Sensor = battery charging (AC side ~183) + grid export 66 + whole heating-circuit
  draw (~81-89, idle circulation) ≈ 330-338 W.
- Confirmed flaw: the idle circulation pump (~83 W) is added back although it runs whether or
  not a slab charge happens.
- Options:
  - **A** keep battery charging as surplus; add back only the draw above idle (compressor).
    Snapshot: ~250 W. Battery protected only by `input_number.heating_pv_min_battery_soc`.
  - **B** surplus = grid export + compressor draw only. Snapshot: ~66 W.
  - **C** battery charging counts only above an SOC threshold, else B.
- Regression case from the VRM snapshot (MPPT 161, AC PV 450, loads 338, grid −66, idle 89 W),
  plus a balance cross-check in `tests/ha/test_victron.py` (`pv_net == −(grid + battery_ac)`).

## Steps

### Phase A — single space-heating yield
1. [TODO] Yield meter: own mode list (`space_heating`, `water_heating`, `cooling`, `off`);
   automation maps active/passive heating → `space_heating`; Space Heating Efficiency Today
   reads the combined yield; `group.heating_pv_boost` members; dashboard row
   "Space heating (active + passive cycle)". Depends on: nothing.
2. [TODO] Wording: drop "tariff" from comments, notes, dashboard and test names/docstrings.
   Rename the automation alias/id `heating_energy_tariff_follows_mode` →
   `heating_energy_meters_follow_mode` (new automation entity; dashboard ref at line 228 updated;
   old entity is an orphan to delete after deploy). Depends on: 1.
3. [TODO] Tests: separate electricity/yield mode lists in `tests/ha/test_heating_pv_boost.py`;
   `test_energy_split_by_mode` asserts the combined bucket and a regression step (active cycle,
   switch to passive, THEN YieldTotal +1 → counted to `space_heating`); midnight-reset test and
   `tests/baseline.py` seeds updated. Depends on: 1.

### Phase B — rolling 30-day efficiency
4. [TODO] `sql:` block with the six 30-day kWh sums (with `days` attribute); three 30d efficiency
   templates (unknown below the floor); group members. Depends on: 1 (space-heating yield id).
5. [TODO] Dashboard: new card "Efficiency (rolling 30 days)" after "Energy by Mode (today)".
   Depends on: 4.
6. [TODO] Tests — pure unit tests, no HA long-term statistics (owner):
   - efficiency templates: seed the six 30d kWh inputs; check sum ratio, the floor → `unknown`
     (not `unavailable`), missing input → `unavailable`;
   - the SQL query: render the query template and run it against a standalone in-memory SQLite
     with a minimal `statistics`/`statistics_meta` table of fabricated rows (window edge, daily
     reset pattern in `sum`, old + new space-heating ids added, empty table → 0, no NULL);
   - config loads with `sql:` (dependency `sqlparse` pinned in `requirements_test.txt`, guarded in
     `tests/ha/test_versions.py`; classify `sql` in `tests/ha/conftest.py` if the recorder filter
     test requires it). Mutation checks: 30 → 31 days, MIN/MAX swapped.
   Depends on: 4.

### Phase C — PV surplus (blocked on owner decision A/B/C)
7. [TODO] Implement the chosen definition in `sensor.heating_pv_surplus`; update the comment.
   Depends on: owner decision.
8. [TODO] Tests: VRM snapshot regression case, idle-draw case, compressor case; Victron balance
   cross-check. Depends on: 7.

### Phase D — verify, deploy notes
9. [TODO] Full `.github/scripts/ci-local.sh` (and `--e2e`); `git ls-files --eol` clean.
   Deploy notes from `git diff origin/master...HEAD`: restart HA; check the yield mode select;
   look up new ids (space-heating yield, six `sql` sensors, renamed automation) by unique_id;
   delete orphans (old active/passive yield sensors + statistics, old automation); check the
   Energy Dashboard / UI cards outside git for the old yield ids. Deploy day is partial.

### Close
10. [TODO] Close per `doc/KNOWLEDGE.md#K-6`:
    - `doc/heating_pv_boost/notes.md`: entity map, "Energy modes" (active/passive heating cycle,
      combined yield, no "tariff"), 30d efficiency, surplus definition, Tests section.
    - `ha-energy-metering` skill via `record-learning`: "a mode-select change counts the next
      source change entirely to the new mode" (confirmed in source) and the `sql:`-on-long-term-
      statistics pattern for rolling sums.
    - `doc/victron/notes.md` only if the surplus change touches Victron facts.
    - `plans/heating-cycling-from-ehp.md`: its YieldTotal-misbooking hypothesis is now observed;
      point it here / remove.
    - Delete this plan.

## Knowledge homes updated
`doc/heating_pv_boost/notes.md`, `.claude/skills/ha-energy-metering/` (via `record-learning`),
possibly `doc/victron/notes.md`, `plans/heating-cycling-from-ehp.md`.

## Status

- Investigation done (three read-only subagents). Nothing implemented.
- Owner decisions: combined space-heating yield, electricity keeps five modes (yes); 30-day via
  `sql:` on long-term statistics (yes); 1 h lag fine; below floor → `unknown`; tests must not use
  HA long-term statistics; no "tariff" wording.
- Open: surplus definition (A/B/C); 30d floor on yield or electricity; whether the "today"
  efficiencies should also go `unknown` below their 1 kWh floor instead of 0.
- Next: owner answers the open points and approves the plan; then Phase A step 1.
